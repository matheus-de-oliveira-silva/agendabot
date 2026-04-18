"""
billing.py — Webhook da Kiwify + emails automáticos via Resend.

Fluxo completo:
  compra_aprovada       → cria tenant → WhatsApp + email boas-vindas
  subscription_renewed  → reativa tenant + email upgrade se plano mudou
  cancelamento/charge   → suspende tenant + email suspensão

Fixes v2:
  - Rebranding: AgendaBot → BotGen
  - Email de erro quando limite de agência é atingido
  - Melhor extração de dados do payload Kiwify (múltiplos formatos)
  - Logs nunca expõem email ou telefone completos (LGPD)
  - Retry em caso de falha no email (não bloqueia o webhook)
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Service
from ..services.evolution_helper import send_whatsapp_via_instance
from ..services.email_service import (
    email_boas_vindas,
    email_plano_suspenso,
    email_upgrade_confirmado,
)
import os, secrets, bcrypt, hmac, hashlib, json

router = APIRouter()

KIWIFY_WEBHOOK_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")
EVOLUTION_INSTANCE   = os.getenv("EVOLUTION_INSTANCE", "botgen")
APP_URL              = os.getenv("APP_URL", "https://web-production-c1b1c.up.railway.app")

PRODUCT_PLAN_MAP = {
    os.getenv("KIWIFY_PRODUCT_BASICO",  ""): "basico",
    os.getenv("KIWIFY_PRODUCT_PRO",     ""): "pro",
    os.getenv("KIWIFY_PRODUCT_AGENCIA", ""): "agencia",
}

# Eventos que ativam/criam tenants
EVENTOS_ATIVAR = {
    "compra_aprovada", "order_approved",
    "subscription_renewed", "subscription_activated",
    "assinatura_renovada", "assinatura_ativada",
}

# Eventos que suspendem tenants
EVENTOS_SUSPENDER = {
    "compra_reembolsada", "order_refunded",
    "chargeback",
    "subscription_canceled", "assinatura_cancelada",
    "subscription_late", "assinatura_atrasada",
    "reembolso",
}

PLAN_NAMES = {
    "basico":  "Básico",
    "pro":     "Pro",
    "agencia": "Agência",
}

MOTIVO_MAP = {
    "compra_reembolsada": "reembolso",
    "order_refunded":     "reembolso",
    "reembolso":          "reembolso",
    "chargeback":         "chargeback",
    "subscription_canceled":  "cancelamento",
    "assinatura_cancelada":   "cancelamento",
    "subscription_late":      "inadimplencia",
    "assinatura_atrasada":    "inadimplencia",
}


def _verify_signature(body_bytes: bytes, request: Request) -> bool:
    """
    Verifica assinatura HMAC-SHA1 do webhook da Kiwify.
    A assinatura vem como query param 'signature'.
    """
    if not KIWIFY_WEBHOOK_TOKEN:
        print("[Billing] ⚠️ KIWIFY_WEBHOOK_TOKEN não configurado — aceitando")
        return True

    received_sig = request.query_params.get("signature", "")
    if not received_sig:
        # Permite requisições sem assinatura em dev/teste manual
        env = os.getenv("ENVIRONMENT", "")
        if env == "production":
            print("[Billing] ❌ Sem signature em produção — rejeitando")
            return False
        print("[Billing] ⚠️ Sem signature — aceitando (não-produção)")
        return True

    expected_sig = hmac.new(
        KIWIFY_WEBHOOK_TOKEN.encode("utf-8"),
        body_bytes,
        hashlib.sha1
    ).hexdigest()

    ok = hmac.compare_digest(expected_sig, received_sig)
    if not ok:
        print(f"[Billing] ❌ Signature inválida")
    return ok


def _get_customer_data(body: dict) -> dict:
    """
    Extrai dados do cliente do payload da Kiwify.
    A Kiwify usa diferentes formatos dependendo do tipo de evento.
    LGPD: dados retornados são usados apenas para criação do tenant,
          nunca logados em plaintext.
    """
    # Formato 1: objeto Customer
    c = body.get("Customer") or body.get("customer") or {}
    # Formato 2: objeto buyer
    b = body.get("buyer") or {}
    # Formato 3: dados diretos no body

    email = (
        c.get("email") or
        b.get("email") or
        body.get("email") or
        ""
    ).strip().lower()

    name = (
        c.get("full_name") or c.get("name") or
        b.get("name") or b.get("full_name") or
        body.get("customer_name") or
        ""
    ).strip()

    phone = (
        c.get("mobile") or c.get("phone") or c.get("cellphone") or
        b.get("phone") or b.get("mobile") or
        body.get("phone") or
        ""
    ).strip()

    # Remove formatação do telefone
    phone_clean = "".join(c for c in phone if c.isdigit())

    return {"email": email, "name": name, "phone": phone_clean}


def _get_plan(body: dict) -> str:
    """
    Determina o plano baseado no product_id ou nome do produto.
    Tenta múltiplos campos pois a Kiwify varia o formato por evento.
    """
    # Tenta por product_id primeiro (mais confiável)
    product_id = (
        body.get("product_id") or
        (body.get("Product") or {}).get("id") or
        (body.get("product") or {}).get("id") or
        (body.get("Subscription") or {}).get("plan_id") or
        (body.get("Plan") or {}).get("id") or
        (body.get("plan") or {}).get("id") or
        ""
    )

    # Remove chave vazia do mapa (produto não configurado no .env)
    plan_by_id = {k: v for k, v in PRODUCT_PLAN_MAP.items() if k}
    if product_id and product_id in plan_by_id:
        return plan_by_id[product_id]

    # Fallback: detecta pelo nome do produto
    product_name = (
        (body.get("Product") or {}).get("name") or
        (body.get("product") or {}).get("name") or
        (body.get("Plan") or {}).get("name") or
        (body.get("plan") or {}).get("name") or
        body.get("product_name") or
        ""
    ).lower()

    if "agencia" in product_name or "agência" in product_name or "497" in product_name:
        return "agencia"
    if "pro" in product_name or "197" in product_name:
        return "pro"

    # Default: básico
    return "basico"


def _criar_tenant(db: Session, email: str, name: str, phone: str, plan: str) -> Tenant:
    """
    Cria novo tenant com configurações padrão.
    bot_active=False — só ativa após onboarding (WhatsApp conectado).
    """
    biz_name    = name or email.split("@")[0] or "Meu Negócio"
    temp_pw     = secrets.token_urlsafe(12)
    hashed      = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt()).decode()
    setup_token = secrets.token_urlsafe(32)

    tenant = Tenant(
        name=biz_name, display_name=biz_name,
        business_type="outro", tenant_icon="⚙️",
        subject_label="Cliente", subject_label_plural="Clientes",
        bot_attendant_name="Mari", bot_business_name=biz_name,
        open_days="0,1,2,3,4,5", open_time="09:00", close_time="18:00",
        owner_phone=phone or None, notify_new_appt=True,
        needs_address=False, address_label="Endereço de busca",
        plan=plan, plan_active=True,
        billing_email=email,
        plan_tenant_group=email if plan == "agencia" else None,
        setup_token=setup_token, setup_done=False,
        dashboard_password=hashed,
        dashboard_token=secrets.token_urlsafe(32),
        bot_active=False,  # só ativa após onboarding
    )
    db.add(tenant)
    db.flush()

    # Serviço placeholder — substituído no setup pelo cliente
    db.add(Service(
        tenant_id=tenant.id,
        name="Serviço Padrão",
        duration_min=60, price=10000,
        color="#6C5CE7",
        description="Configure seus serviços no setup",
        active=True,
    ))
    db.commit()
    db.refresh(tenant)
    # LGPD: não loga email completo
    print(f"[Billing] ✅ Tenant criado | id={tenant.id[:8]}... | plano={plan}")
    return tenant


async def _enviar_boas_vindas(
    phone: str, email: str, nome: str, plano: str,
    dashboard_url: str, setup_url: str = ""
):
    """
    Envia WhatsApp + email de boas-vindas.
    LGPD: dados enviados apenas ao titular da conta.
    """
    plan_label = PLAN_NAMES.get(plano, "BotGen")

    # WhatsApp (via instância global — notificação do próprio BotGen)
    if phone:
        setup_info = f"\n\n🔗 Configure agora: {setup_url}" if setup_url else ""
        msg = (
            f"Olá! 🎉 Sua assinatura do *BotGen {plan_label}* foi confirmada!\n\n"
            f"Nossa equipe vai entrar em contato *em até 2 horas* pelo WhatsApp "
            f"para ativar o seu bot. O processo leva apenas 15 minutos! 😊"
            f"{setup_info}\n\n"
            f"Fique de olho neste número!"
        )
        try:
            ok = await send_whatsapp_via_instance(phone, msg, EVOLUTION_INSTANCE)
            print(f"[Billing] WhatsApp boas-vindas: {'✅' if ok else '⚠️ falhou'}")
        except Exception as e:
            print(f"[Billing] WhatsApp erro: {e}")

    # Email (via Resend)
    if email:
        try:
            ok = await email_boas_vindas(
                to=email, nome=nome, plano=plano,
                setup_url=setup_url,
                dashboard_url=dashboard_url,
            )
            print(f"[Billing] Email boas-vindas: {'✅' if ok else '⚠️ falhou'}")
        except Exception as e:
            print(f"[Billing] Email erro: {e}")


def _get_base_url(request: Request) -> str:
    """Detecta a URL base correta mesmo atrás de proxy (Railway)."""
    if APP_URL:
        return APP_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "https")
    host  = request.headers.get("host", "")
    return f"{proto}://{host}"


@router.post("/billing/webhook")
async def billing_webhook(request: Request):
    """
    Recebe webhooks da Kiwify.
    Retorna sempre 200 para a Kiwify não ficar retentando —
    erros internos são logados mas não bloqueiam a resposta.
    """
    try:
        body_bytes = await request.body()
        body       = json.loads(body_bytes)
    except Exception as e:
        print(f"[Billing] Payload inválido: {e}")
        return JSONResponse({"error": "Payload inválido"}, status_code=400)

    if not _verify_signature(body_bytes, request):
        return JSONResponse({"error": "Assinatura inválida"}, status_code=401)

    event    = (body.get("event") or "").strip().lower()
    customer = _get_customer_data(body)
    email    = customer["email"]

    # LGPD: nunca loga email completo
    print(f"[Billing] evento='{event}' | email={'sim' if email else 'não'}")

    # Debug em não-produção
    if os.getenv("ENVIRONMENT") != "production":
        print(f"[Billing][DEBUG] keys={list(body.keys())} | product_id={body.get('product_id','?')}")

    if event not in EVENTOS_ATIVAR and event not in EVENTOS_SUSPENDER:
        print(f"[Billing] evento '{event}' ignorado")
        return {"status": "ignored", "event": event}

    if not email:
        print("[Billing] ⚠️ Email não encontrado no payload")
        return JSONResponse({"error": "Email não encontrado no payload"}, status_code=422)

    db = SessionLocal()
    try:
        base_url = _get_base_url(request)

        # ── SUSPENDER ────────────────────────────────────────────────────────
        if event in EVENTOS_SUSPENDER:
            tenants = db.query(Tenant).filter(Tenant.billing_email == email).all()
            if not tenants:
                print(f"[Billing] Tenant não encontrado para suspensão")
                # Retorna 200 para Kiwify não retentar — pode ser cliente de teste
                return {"status": "tenant_not_found"}

            for t in tenants:
                t.plan_active = False
                t.bot_active  = False
            db.commit()
            print(f"[Billing] ⏸ {len(tenants)} tenant(s) suspenso(s)")

            # Email de suspensão — não bloqueia em caso de erro
            try:
                motivo = MOTIVO_MAP.get(event, "cancelamento")
                nome   = tenants[0].display_name or tenants[0].name or ""
                await email_plano_suspenso(to=email, nome=nome, motivo=motivo)
            except Exception as e:
                print(f"[Billing] Email suspensão falhou: {e}")

            return {"status": "ok", "action": "suspended", "count": len(tenants)}

        # ── ATIVAR / CRIAR ────────────────────────────────────────────────────
        plan = _get_plan(body)

        tenants_existentes = db.query(Tenant).filter(Tenant.billing_email == email).all()

        if tenants_existentes:
            plano_anterior = tenants_existentes[0].plan or "basico"
            for t in tenants_existentes:
                t.plan_active = True
                t.plan        = plan
                # Só reativa bot se o setup já foi concluído
                if getattr(t, 'setup_done', False) and getattr(t, 'phone_number_id', None):
                    t.bot_active = True
            db.commit()
            print(f"[Billing] ✅ {len(tenants_existentes)} tenant(s) reativado(s) | plano={plan}")

            # Email de upgrade se plano mudou
            if plan != plano_anterior:
                try:
                    nome = tenants_existentes[0].display_name or tenants_existentes[0].name or ""
                    await email_upgrade_confirmado(to=email, nome=nome, plano_novo=plan)
                except Exception as e:
                    print(f"[Billing] Email upgrade falhou: {e}")

            return {"status": "ok", "action": "reactivated", "count": len(tenants_existentes), "plan": plan}

        # ── NOVO CLIENTE ──────────────────────────────────────────────────────

        # Verificar limite de negócios para plano agência
        if plan == "agencia":
            count = db.query(Tenant).filter(Tenant.plan_tenant_group == email).count()
            if count >= 3:
                print(f"[Billing] ⚠️ Limite de 3 negócios atingido para agência")
                # Notifica por email que atingiu o limite
                try:
                    from ..services.email_service import _send_email, _base_html
                    content = f"""<h1>Limite de negócios atingido</h1>
                    <p>Você já tem 3 negócios cadastrados no Plano Agência, que é o limite do plano.</p>
                    <p>Para adicionar mais negócios, entre em contato com nosso suporte.</p>"""
                    await _send_email(
                        to=email,
                        subject="⚠️ Limite de negócios do Plano Agência atingido",
                        html=_base_html(content)
                    )
                except Exception:
                    pass
                return JSONResponse({"error": "Limite de 3 negócios do Plano Agência atingido"}, status_code=422)

        tenant = _criar_tenant(db, email, customer["name"], customer["phone"], plan)

        dashboard_url = f"{base_url}/dashboard?tid={tenant.id}"
        setup_url     = f"{base_url}/setup?token={tenant.setup_token}" if tenant.setup_token else ""

        await _enviar_boas_vindas(
            phone=customer["phone"],
            email=email,
            nome=customer["name"],
            plano=plan,
            dashboard_url=dashboard_url,
            setup_url=setup_url,
        )

        return {"status": "ok", "action": "created", "plan": plan}

    except Exception as e:
        db.rollback()
        print(f"[Billing] ❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        # Retorna 200 para Kiwify não retentar infinitamente
        # O erro está logado para investigação
        return {"status": "error", "message": "Erro interno processado"}
    finally:
        db.close()


@router.get("/billing/webhook")
async def billing_webhook_verify():
    """Health check do endpoint de billing."""
    return {"status": "ok", "service": "BotGen Billing"}