"""
billing.py — Webhook da Kiwify para controle automático de assinatura.

Fluxo completo:
  compra_aprovada → cria tenant → envia WhatsApp de boas-vindas (onboarding manual)
  subscription_renewed → reativa tenant
  compra_reembolsada / chargeback / cancelado / atrasado → suspende

Modelo de onboarding:
  O cliente compra → recebe WhatsApp avisando que entraremos em contato
  Você (Matheus) entra em contato, faz uma chamada de 15 min via compartilhamento de tela,
  cria a instância na Evolution, escaneia o QR Code junto com o cliente
  → bot ativo, cliente feliz, você no controle

Planos:
  basico  R$97,90  — até 7 serviços, sem CSV, sem lembretes automáticos
  pro     R$197,90 — serviços ilimitados, CSV, lembretes automáticos
  agencia R$497,90 — tudo do pro + até 3 tenants vinculados ao mesmo email

LGPD:
  - Dados do comprador usados apenas para criar o tenant e enviar boas-vindas
  - Email e telefone nunca logados em texto plano
  - Tenant criado com bot_active=False até onboarding completo
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Service
from ..services.evolution_helper import send_whatsapp_via_instance
import os, secrets, bcrypt, hmac, hashlib, json

router = APIRouter()

KIWIFY_WEBHOOK_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")
EVOLUTION_INSTANCE   = os.getenv("EVOLUTION_INSTANCE", "agendabot")

PRODUCT_PLAN_MAP = {
    os.getenv("KIWIFY_PRODUCT_BASICO",  ""): "basico",
    os.getenv("KIWIFY_PRODUCT_PRO",     ""): "pro",
    os.getenv("KIWIFY_PRODUCT_AGENCIA", ""): "agencia",
}

EVENTOS_ATIVAR = {"compra_aprovada", "subscription_renewed"}
EVENTOS_SUSPENDER = {
    "compra_reembolsada", "chargeback", "subscription_canceled",
    "subscription_late", "reembolso", "assinatura_cancelada", "assinatura_atrasada"
}

PLAN_LABELS = {
    "basico":  "Básico",
    "pro":     "Pro",
    "agencia": "Agência",
}


# ── Verificação HMAC ──────────────────────────────────────────────────────────

def _verify_signature(body_bytes: bytes, request: Request) -> bool:
    """
    Kiwify assina o payload com HMAC-SHA1 usando o token como chave.
    A assinatura chega como query param ?signature=xxx
    """
    if not KIWIFY_WEBHOOK_TOKEN:
        print("[Billing] ⚠️ KIWIFY_WEBHOOK_TOKEN não configurado — aceitando sem verificação")
        return True

    received_sig = request.query_params.get("signature", "")
    if not received_sig:
        print("[Billing] ⚠️ Sem signature — aceitando (possível teste manual)")
        return True

    expected_sig = hmac.new(
        KIWIFY_WEBHOOK_TOKEN.encode("utf-8"),
        body_bytes,
        hashlib.sha1
    ).hexdigest()

    resultado = hmac.compare_digest(expected_sig, received_sig)
    if not resultado:
        print(f"[Billing] ❌ Signature inválida")
    return resultado


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_customer_data(body: dict) -> dict:
    c = body.get("Customer") or body.get("customer") or {}
    return {
        "email": (c.get("email") or body.get("email") or "").strip().lower(),
        "name":  (c.get("full_name") or c.get("name") or "").strip(),
        "phone": (c.get("mobile") or c.get("phone") or "").strip(),
    }


def _get_plan(body: dict) -> str:
    product_id = (
        body.get("product_id")
        or (body.get("Product") or {}).get("id")
        or (body.get("Subscription") or {}).get("plan_id")
        or (body.get("Plan") or {}).get("id")
        or ""
    )
    plan = PRODUCT_PLAN_MAP.get(product_id, "")
    if plan:
        return plan

    product_name = (
        (body.get("Product") or {}).get("name")
        or (body.get("Plan") or {}).get("name")
        or ""
    ).lower()

    if "agencia" in product_name or "agência" in product_name or "497" in product_name:
        return "agencia"
    elif "pro" in product_name or "197" in product_name:
        return "pro"
    return "basico"


def _count_group_tenants(db: Session, email: str) -> int:
    return db.query(Tenant).filter(Tenant.plan_tenant_group == email).count()


def _criar_tenant(db: Session, email: str, name: str, phone: str, plan: str) -> Tenant:
    """
    Cria tenant com bot_active=False.
    Bot só ativa após onboarding (você cria instância e configura WhatsApp).
    """
    biz_name = name or email.split("@")[0]
    temp_pw  = secrets.token_urlsafe(12)
    hashed   = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt()).decode()

    tenant = Tenant(
        name=biz_name,
        display_name=biz_name,
        business_type="outro",
        tenant_icon="⚙️",
        subject_label="Cliente",
        subject_label_plural="Clientes",
        bot_attendant_name="Mari",
        bot_business_name=biz_name,
        open_days="0,1,2,3,4,5",
        open_time="09:00",
        close_time="18:00",
        owner_phone=phone or None,
        notify_new_appt=True,
        needs_address=False,
        address_label="Endereço de busca",
        plan=plan,
        plan_active=True,
        billing_email=email,
        plan_tenant_group=email if plan == "agencia" else None,
        setup_token=secrets.token_urlsafe(32),
        setup_done=False,
        dashboard_password=hashed,
        dashboard_token=secrets.token_urlsafe(32),
        bot_active=False,  # ← inativo até onboarding concluído
    )
    db.add(tenant)
    db.flush()

    # Serviço placeholder — atualizado durante onboarding
    db.add(Service(
        tenant_id=tenant.id,
        name="Serviço Padrão",
        duration_min=60,
        price=10000,
        color="#6C5CE7",
        description="Configure seus serviços no setup",
        active=True,
    ))
    db.commit()
    db.refresh(tenant)

    # LGPD: não loga email nem telefone
    print(f"[Billing] ✅ Tenant criado: {tenant.id[:8]}... | plano={plan}")
    return tenant


async def _enviar_boas_vindas(phone: str, plan: str):
    """
    Envia WhatsApp de boas-vindas informando que entraremos em contato.
    Não envia link técnico — o onboarding é feito por você (Matheus).
    """
    if not phone:
        print("[Billing] Sem telefone — boas-vindas não enviada")
        return

    phone_clean = "".join(c for c in phone if c.isdigit())
    if not phone_clean:
        return

    plan_label = PLAN_LABELS.get(plan, "Básico")

    mensagem = (
        f"Olá! 🎉 Sua assinatura do *AgendaBot {plan_label}* foi confirmada!\n\n"
        f"Nossa equipe entrará em contato em breve para ativar o seu bot. "
        f"O processo leva apenas 15 minutos.\n\n"
        f"Fique de olho neste número! 😊"
    )

    success = await send_whatsapp_via_instance(phone_clean, mensagem, EVOLUTION_INSTANCE)
    if success:
        print(f"[Billing] ✅ Boas-vindas enviada | plano={plan}")
    else:
        print(f"[Billing] ⚠️ Boas-vindas não enviada (Evolution pode estar offline)")


def _get_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "https")
    host  = request.headers.get("host", "")
    return f"{proto}://{host}"


# ── Webhook principal ─────────────────────────────────────────────────────────

@router.post("/billing/webhook")
async def billing_webhook(request: Request):
    try:
        body_bytes = await request.body()
        body       = json.loads(body_bytes)
    except Exception:
        return JSONResponse({"error": "Payload inválido"}, status_code=400)

    if not _verify_signature(body_bytes, request):
        return JSONResponse({"error": "Assinatura inválida"}, status_code=401)

    event    = (body.get("event") or "").strip().lower()
    customer = _get_customer_data(body)
    email    = customer["email"]

    # LGPD: só loga se tem email, sem expor o valor
    print(f"[Billing] evento={event} | email_presente={'sim' if email else 'não'}")

    # Log de debug apenas em desenvolvimento
    if os.getenv("ENVIRONMENT") != "production":
        print(f"[Billing][DEBUG] payload keys: {list(body.keys())}")

    if event not in EVENTOS_ATIVAR and event not in EVENTOS_SUSPENDER:
        print(f"[Billing] evento '{event}' ignorado")
        return {"status": "ignored", "event": event}

    if not email:
        return JSONResponse({"error": "Email não encontrado no payload"}, status_code=422)

    db = SessionLocal()
    try:
        # ── SUSPENDER ────────────────────────────────────────────────────────
        if event in EVENTOS_SUSPENDER:
            tenants = db.query(Tenant).filter(Tenant.billing_email == email).all()
            if not tenants:
                return {"status": "tenant_not_found", "event": event}
            for t in tenants:
                t.plan_active = False
                t.bot_active  = False
            db.commit()
            print(f"[Billing] ⏸ {len(tenants)} tenant(s) suspenso(s) | evento={event}")
            return {"status": "ok", "event": event, "action": "suspended", "count": len(tenants)}

        # ── ATIVAR / CRIAR ────────────────────────────────────────────────────
        plan = _get_plan(body)

        tenants_existentes = db.query(Tenant).filter(Tenant.billing_email == email).all()

        if tenants_existentes:
            # Renovação — reativa tenants existentes
            for t in tenants_existentes:
                t.plan_active = True
                t.plan        = plan
                # Só reativa bot se o setup/onboarding foi concluído
                if getattr(t, 'setup_done', False):
                    t.bot_active = True
            db.commit()
            print(f"[Billing] ✅ {len(tenants_existentes)} tenant(s) reativado(s) | evento={event}")
            return {
                "status": "ok",
                "event":  event,
                "action": "reactivated",
                "count":  len(tenants_existentes),
            }

        # Novo cliente
        if plan == "agencia":
            count = _count_group_tenants(db, email)
            if count >= 3:
                print(f"[Billing] ⚠️ Limite de 3 tenants do plano Agência atingido")
                return JSONResponse(
                    {"error": "Limite de 3 negócios do plano Agência atingido."},
                    status_code=422
                )

        tenant = _criar_tenant(db, email, customer["name"], customer["phone"], plan)

        # Envia boas-vindas informando que entraremos em contato
        await _enviar_boas_vindas(customer["phone"], plan)

        return {
            "status":  "ok",
            "event":   event,
            "action":  "created",
            "tenant":  tenant.name,
            "plan":    plan,
        }

    except Exception as e:
        db.rollback()
        print(f"[Billing] ❌ Erro: {e}")
        return JSONResponse({"error": "Erro interno"}, status_code=500)
    finally:
        db.close()


@router.get("/billing/webhook")
async def billing_webhook_verify(request: Request):
    return {"status": "ok", "service": "AgendaBot Billing"}