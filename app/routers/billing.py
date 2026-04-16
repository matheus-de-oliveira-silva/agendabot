"""
billing.py — Webhook da Kiwify + emails automáticos via Resend.

Fluxo completo:
  compra_aprovada → cria tenant → WhatsApp boas-vindas + email boas-vindas
  subscription_renewed → reativa tenant + email de upgrade se plano mudou
  cancelamento/chargeback → suspende tenant + email de suspensão

LGPD:
  - Emails enviados apenas ao titular da conta (billing_email)
  - Nenhum dado de cliente final é incluído
  - Logs nunca expõem email ou telefone completos
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
EVOLUTION_INSTANCE   = os.getenv("EVOLUTION_INSTANCE", "agendabot")
APP_URL              = os.getenv("APP_URL", "https://web-production-c1b1c.up.railway.app")

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

PLAN_NAMES = {
    "basico":  "Básico",
    "pro":     "Pro",
    "agencia": "Agência",
}

MOTIVO_MAP = {
    "compra_reembolsada": "reembolso",
    "reembolso":          "reembolso",
    "chargeback":         "chargeback",
    "subscription_canceled": "cancelamento",
    "assinatura_cancelada":  "cancelamento",
    "subscription_late":     "inadimplencia",
    "assinatura_atrasada":   "inadimplencia",
}


def _verify_signature(body_bytes: bytes, request: Request) -> bool:
    if not KIWIFY_WEBHOOK_TOKEN:
        print("[Billing] ⚠️ KIWIFY_WEBHOOK_TOKEN não configurado")
        return True
    received_sig = request.query_params.get("signature", "")
    if not received_sig:
        print("[Billing] ⚠️ Sem signature — aceitando (teste manual)")
        return True
    expected_sig = hmac.new(
        KIWIFY_WEBHOOK_TOKEN.encode("utf-8"),
        body_bytes, hashlib.sha1
    ).hexdigest()
    ok = hmac.compare_digest(expected_sig, received_sig)
    if not ok:
        print("[Billing] ❌ Signature inválida")
    return ok


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
    if "agencia" in product_name or "497" in product_name:
        return "agencia"
    elif "pro" in product_name or "197" in product_name:
        return "pro"
    return "basico"


def _criar_tenant(db: Session, email: str, name: str, phone: str, plan: str) -> Tenant:
    biz_name = name or email.split("@")[0]
    temp_pw  = secrets.token_urlsafe(12)
    hashed   = bcrypt.hashpw(temp_pw.encode(), bcrypt.gensalt()).decode()
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
        setup_token=secrets.token_urlsafe(32), setup_done=False,
        dashboard_password=hashed,
        dashboard_token=secrets.token_urlsafe(32),
        bot_active=False,
    )
    db.add(tenant)
    db.flush()
    db.add(Service(
        tenant_id=tenant.id, name="Serviço Padrão",
        duration_min=60, price=10000, color="#6C5CE7",
        description="Configure seus serviços no setup", active=True,
    ))
    db.commit()
    db.refresh(tenant)
    print(f"[Billing] ✅ Tenant criado: {tenant.id[:8]}... | plano={plan}")
    return tenant


async def _enviar_boas_vindas(phone: str, email: str, nome: str, plano: str, dashboard_url: str):
    """Envia WhatsApp + email de boas-vindas em paralelo."""
    # WhatsApp
    if phone:
        phone_clean = "".join(c for c in phone if c.isdigit())
        plan_label  = PLAN_NAMES.get(plano, "AgendaBot")
        msg = (
            f"Olá! 🎉 Sua assinatura do *AgendaBot {plan_label}* foi confirmada!\n\n"
            f"Nossa equipe vai entrar em contato *em até 2 horas* pelo WhatsApp "
            f"para ativar o seu bot. O processo leva apenas 15 minutos! 😊\n\n"
            f"Fique de olho neste número!"
        )
        ok = await send_whatsapp_via_instance(phone_clean, msg, EVOLUTION_INSTANCE)
        print(f"[Billing] WhatsApp boas-vindas: {'✅' if ok else '⚠️ falhou'}")

    # Email
    if email:
        ok = await email_boas_vindas(
            to=email, nome=nome, plano=plano, dashboard_url=dashboard_url
        )
        print(f"[Billing] Email boas-vindas: {'✅' if ok else '⚠️ falhou'}")


def _get_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "https")
    host  = request.headers.get("host", "")
    return f"{proto}://{host}"


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

    print(f"[Billing] evento={event} | email={'sim' if email else 'não'}")

    if os.getenv("ENVIRONMENT") != "production":
        print(f"[Billing][DEBUG] keys: {list(body.keys())}")

    if event not in EVENTOS_ATIVAR and event not in EVENTOS_SUSPENDER:
        print(f"[Billing] evento '{event}' ignorado")
        return {"status": "ignored", "event": event}

    if not email:
        return JSONResponse({"error": "Email não encontrado"}, status_code=422)

    db = SessionLocal()
    try:
        # ── SUSPENDER ────────────────────────────────────────────────────────
        if event in EVENTOS_SUSPENDER:
            tenants = db.query(Tenant).filter(Tenant.billing_email == email).all()
            if not tenants:
                return {"status": "tenant_not_found"}
            for t in tenants:
                t.plan_active = False
                t.bot_active  = False
            db.commit()
            print(f"[Billing] ⏸ {len(tenants)} tenant(s) suspenso(s)")

            # Email de suspensão
            motivo = MOTIVO_MAP.get(event, "cancelamento")
            nome   = tenants[0].display_name or tenants[0].name or ""
            await email_plano_suspenso(to=email, nome=nome, motivo=motivo)

            return {"status": "ok", "action": "suspended", "count": len(tenants)}

        # ── ATIVAR / CRIAR ────────────────────────────────────────────────────
        plan     = _get_plan(body)
        base_url = _get_base_url(request)

        tenants_existentes = db.query(Tenant).filter(Tenant.billing_email == email).all()

        if tenants_existentes:
            plano_anterior = tenants_existentes[0].plan or "basico"
            for t in tenants_existentes:
                t.plan_active = True
                t.plan        = plan
                if getattr(t, 'setup_done', False):
                    t.bot_active = True
            db.commit()
            print(f"[Billing] ✅ {len(tenants_existentes)} tenant(s) reativado(s)")

            # Email de upgrade se plano mudou
            if plan != plano_anterior:
                nome = tenants_existentes[0].display_name or tenants_existentes[0].name or ""
                await email_upgrade_confirmado(to=email, nome=nome, plano_novo=plan)

            return {"status": "ok", "action": "reactivated", "count": len(tenants_existentes)}

        # Novo cliente
        if plan == "agencia":
            count = db.query(Tenant).filter(Tenant.plan_tenant_group == email).count()
            if count >= 3:
                return JSONResponse({"error": "Limite de 3 negócios atingido"}, status_code=422)

        tenant        = _criar_tenant(db, email, customer["name"], customer["phone"], plan)
        dashboard_url = f"{base_url}/dashboard?tid={tenant.id}"

        await _enviar_boas_vindas(
            phone=customer["phone"],
            email=email,
            nome=customer["name"],
            plano=plan,
            dashboard_url=dashboard_url,
        )

        return {"status": "ok", "action": "created", "plan": plan}

    except Exception as e:
        db.rollback()
        print(f"[Billing] ❌ Erro: {e}")
        return JSONResponse({"error": "Erro interno"}, status_code=500)
    finally:
        db.close()


@router.get("/billing/webhook")
async def billing_webhook_verify():
    return {"status": "ok", "service": "AgendaBot Billing"}