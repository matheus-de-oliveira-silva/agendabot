"""
billing.py — Webhook da Kiwify para controle automático de assinatura.

Fluxo completo:
  compra_aprovada → cria tenant automaticamente → envia link de setup via WhatsApp
  subscription_renewed → reativa tenant
  compra_reembolsada / chargeback / subscription_canceled / subscription_late → suspende

Planos:
  basico  R$97,90  — até 7 serviços, sem CSV, sem lembretes automáticos
  pro     R$197,90 — serviços ilimitados, CSV, lembretes automáticos
  agencia R$497,90 — tudo do pro + até 3 tenants vinculados ao mesmo email

Variáveis de ambiente necessárias:
  KIWIFY_WEBHOOK_TOKEN     — token gerado pela Kiwify no webhook (campo "Token")
  KIWIFY_PRODUCT_BASICO    — ID do plano básico na Kiwify
  KIWIFY_PRODUCT_PRO       — ID do plano pro na Kiwify
  KIWIFY_PRODUCT_AGENCIA   — ID do plano agência na Kiwify
  EVOLUTION_API_URL        — URL da Evolution API
  EVOLUTION_API_KEY        — chave da Evolution API
  EVOLUTION_INSTANCE       — instância principal (do Matheus) para enviar mensagens
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Service
import os, secrets, bcrypt, httpx

router = APIRouter()

KIWIFY_WEBHOOK_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")
EVOLUTION_API_URL    = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY    = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE   = os.getenv("EVOLUTION_INSTANCE", "agendabot")

# Mapeamento produto_id → plano
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_token(body: dict, request: Request = None) -> bool:
    """
    Verifica o token de segurança da Kiwify.
    A Kiwify manda o token de duas formas:
      1. Como query param ?signature=xxx na URL (forma atual da Kiwify)
      2. Como campo webhook_token no body (fallback)
    """
    if not KIWIFY_WEBHOOK_TOKEN:
        print("[Billing] ⚠️ KIWIFY_WEBHOOK_TOKEN não configurado — aceitando sem verificação")
        return True

    # 1. Query param ?signature=xxx (Kiwify atual)
    if request:
        signature = request.query_params.get("signature", "")
        if signature and signature == KIWIFY_WEBHOOK_TOKEN:
            return True

    # 2. Campo no body (fallback)
    token_body = body.get("webhook_token", "")
    if token_body and token_body == KIWIFY_WEBHOOK_TOKEN:
        return True

    return False


def _get_customer_data(body: dict) -> dict:
    """Extrai dados do cliente do payload da Kiwify."""
    c = body.get("Customer") or body.get("customer") or {}
    return {
        "email": (c.get("email") or body.get("email") or "").strip().lower(),
        "name":  (c.get("full_name") or c.get("name") or "").strip(),
        "phone": (c.get("mobile") or c.get("phone") or "").strip(),
    }


def _get_plan(body: dict) -> str:
    """
    Determina o plano a partir do product_id ou nome do produto.
    Tenta múltiplos campos pois a Kiwify pode variar o payload entre planos.
    """
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

    # Fallback pelo nome do produto/plano
    product_name = (
        (body.get("Product") or {}).get("name")
        or (body.get("Plan") or {}).get("name")
        or ""
    ).lower()

    if "agencia" in product_name or "agência" in product_name or "497" in product_name:
        return "agencia"
    elif "pro" in product_name or "197" in product_name:
        return "pro"
    else:
        return "basico"


def _count_group_tenants(db: Session, email: str) -> int:
    """Conta quantos tenants já existem no grupo de agência."""
    return db.query(Tenant).filter(Tenant.plan_tenant_group == email).count()


def _criar_tenant(db: Session, email: str, name: str, phone: str, plan: str) -> Tenant:
    """
    Cria um novo tenant com configurações padrão.
    O cliente vai personalizar tudo no setup wizard.
    """
    biz_name = name or email.split("@")[0]

    # Senha temporária — cliente troca no passo 5 do setup
    temp_pw = secrets.token_urlsafe(12)
    hashed  = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt()).decode()

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
        bot_active=False,
    )
    db.add(tenant)
    db.flush()

    # Serviço placeholder — cliente troca no setup
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
    print(f"[Billing] ✅ Tenant criado: {tenant.id[:8]}... | plano={plan}")
    return tenant


async def _enviar_whatsapp_setup(phone: str, tenant_name: str, setup_url: str):
    """Envia o link de setup via WhatsApp usando a instância principal (do Matheus)."""
    if not phone or not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        print("[Billing] WhatsApp não configurado — link de setup não enviado")
        return

    phone_clean = "".join(c for c in phone if c.isdigit())
    if not phone_clean:
        print("[Billing] Número inválido para envio de WhatsApp")
        return

    mensagem = (
        f"Olá! 🎉 Sua assinatura do *AgendaBot* foi confirmada!\n\n"
        f"Agora é só configurar o seu bot. Clique no link abaixo e siga os passos — "
        f"leva menos de 10 minutos:\n\n"
        f"👉 {setup_url}\n\n"
        f"Qualquer dúvida é só responder aqui. Boas vendas! 🚀"
    )

    url     = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"number": phone_clean, "text": mensagem},
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                print("[Billing] ✅ WhatsApp de setup enviado com sucesso")
            else:
                print(f"[Billing] ❌ WhatsApp erro {resp.status_code}: {resp.text[:80]}")
        except Exception as e:
            print(f"[Billing] ❌ WhatsApp exceção: {e}")


def _get_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "https")
    host  = request.headers.get("host", "")
    return f"{proto}://{host}"


# ── Webhook principal ─────────────────────────────────────────────────────────

@router.post("/billing/webhook")
async def billing_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Payload inválido"}, status_code=400)

    # Verificação de token — passa o request para checar query param
    if not _verify_token(body, request):
        print("[Billing] ❌ Token inválido recebido")
        return JSONResponse({"error": "Token inválido"}, status_code=401)

    event    = (body.get("event") or "").strip().lower()
    customer = _get_customer_data(body)
    email    = customer["email"]

    print(f"[Billing] evento={event} | email_presente={'sim' if email else 'não'}")

    # Log do payload em desenvolvimento para debug
    if os.getenv("ENVIRONMENT") != "production":
        print(f"[Billing][DEBUG] payload keys: {list(body.keys())}")

    if event not in EVENTOS_ATIVAR and event not in EVENTOS_SUSPENDER:
        print(f"[Billing] evento '{event}' ignorado")
        return {"status": "ignored", "event": event}

    if not email:
        print(f"[Billing] ⚠️ Email não encontrado no payload do evento '{event}'")
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
        plan     = _get_plan(body)
        base_url = _get_base_url(request)

        # Verifica se já existe tenant com esse email
        tenants_existentes = db.query(Tenant).filter(Tenant.billing_email == email).all()

        if tenants_existentes:
            # Reativa todos os tenants desse email (renovação)
            for t in tenants_existentes:
                t.plan_active = True
                t.plan        = plan
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

        # ── Novo cliente ──────────────────────────────────────────────────────

        # Verifica limite do plano agência (máx 3 tenants por grupo)
        if plan == "agencia":
            count = _count_group_tenants(db, email)
            if count >= 3:
                print("[Billing] ⚠️ Limite de 3 tenants do plano Agência atingido")
                return JSONResponse(
                    {"error": "Limite de 3 negócios do plano Agência atingido."},
                    status_code=422
                )

        # Cria o tenant
        tenant    = _criar_tenant(db, email, customer["name"], customer["phone"], plan)
        setup_url = f"{base_url}/setup?token={tenant.setup_token}"

        # Envia WhatsApp com o link de setup
        await _enviar_whatsapp_setup(customer["phone"], tenant.display_name, setup_url)

        return {
            "status":        "ok",
            "event":         event,
            "action":        "created",
            "tenant":        tenant.name,
            "plan":          plan,
            "setup_enviado": bool(customer["phone"]),
        }

    except Exception as e:
        db.rollback()
        print(f"[Billing] ❌ Erro: {e}")
        return JSONResponse({"error": "Erro interno"}, status_code=500)
    finally:
        db.close()


@router.get("/billing/webhook")
async def billing_webhook_verify(request: Request):
    """GET para verificar se a URL está ativa."""
    return {"status": "ok", "service": "AgendaBot Billing"}