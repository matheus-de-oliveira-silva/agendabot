"""
billing.py — Webhook da Kiwify para controle automático de assinatura.

Rota: POST /billing/webhook

Como configurar na Kiwify:
1. Acesse Apps → Webhooks → Criar Webhook
2. URL: https://seu-dominio.com/billing/webhook
3. Token: coloque o mesmo valor de KIWIFY_WEBHOOK_TOKEN no .env
4. Eventos a marcar:
   - compra_aprovada
   - compra_reembolsada
   - chargeback
   - subscription_canceled
   - subscription_late
   - subscription_renewed

Payload real da Kiwify (campos usados aqui):
{
  "event": "compra_aprovada",         # ou subscription_canceled etc.
  "webhook_token": "seu_token",       # token de segurança
  "Customer": {
    "email": "cliente@email.com",
    "full_name": "Nome do Cliente",
    "mobile": "11999999999"
  },
  "Subscription": {                   # presente em eventos de assinatura
    "status": "active",
    "start_date": "2024-01-01",
    "next_payment": "2024-02-01"
  },
  "order_id": "abc123",
  "product_id": "xyz456"
}

Variáveis de ambiente necessárias:
  KIWIFY_WEBHOOK_TOKEN — token configurado no webhook da Kiwify (campo "Token")
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant
import os, json

router = APIRouter()

KIWIFY_WEBHOOK_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")

# Eventos que ATIVAM a assinatura
EVENTOS_ATIVAR = {
    "compra_aprovada",
    "subscription_renewed",
}

# Eventos que SUSPENDEM a assinatura
EVENTOS_SUSPENDER = {
    "compra_reembolsada",
    "chargeback",
    "subscription_canceled",
    "subscription_late",
}


def _verify_token(body: dict) -> bool:
    """
    Verifica o token de segurança enviado pela Kiwify.
    Se KIWIFY_WEBHOOK_TOKEN não estiver configurado, loga um aviso mas aceita.
    """
    if not KIWIFY_WEBHOOK_TOKEN:
        print("[Billing] ⚠️ KIWIFY_WEBHOOK_TOKEN não configurado — aceitando sem verificação")
        return True
    token_recebido = body.get("webhook_token", "")
    return token_recebido == KIWIFY_WEBHOOK_TOKEN


def _get_email(body: dict) -> str:
    """Extrai o email do cliente do payload da Kiwify."""
    customer = body.get("Customer") or body.get("customer") or {}
    email = (
        customer.get("email")
        or body.get("email")
        or ""
    ).strip().lower()
    return email


def _find_tenant_by_email(db: Session, email: str):
    """
    Busca tenant pelo billing_email.
    Retorna None se não encontrado.
    """
    if not email:
        return None
    return db.query(Tenant).filter(
        Tenant.billing_email == email
    ).first()


@router.post("/billing/webhook")
async def billing_webhook(request: Request):
    """
    Recebe eventos da Kiwify e atualiza o status da assinatura do tenant.

    Ativar  → compra_aprovada, subscription_renewed
    Suspender → compra_reembolsada, chargeback, subscription_canceled, subscription_late
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Payload inválido"}, status_code=400)

    # ── Verificação de segurança ───────────────────────────────────────────────
    if not _verify_token(body):
        print(f"[Billing] ❌ Token inválido recebido")
        return JSONResponse({"error": "Token inválido"}, status_code=401)

    event = (body.get("event") or "").strip().lower()
    email = _get_email(body)

    # Log sem dados sensíveis
    print(f"[Billing] evento={event} | email_presente={'sim' if email else 'não'}")

    # ── Ignora eventos irrelevantes ────────────────────────────────────────────
    if event not in EVENTOS_ATIVAR and event not in EVENTOS_SUSPENDER:
        print(f"[Billing] evento '{event}' ignorado")
        return {"status": "ignored", "event": event}

    if not email:
        print(f"[Billing] ⚠️ Email não encontrado no payload do evento '{event}'")
        return JSONResponse({"error": "Email não encontrado no payload"}, status_code=422)

    db = SessionLocal()
    try:
        tenant = _find_tenant_by_email(db, email)

        if not tenant:
            # Loga sem expor o email completo (LGPD)
            dominio = email.split("@")[-1] if "@" in email else "?"
            print(f"[Billing] ⚠️ Tenant não encontrado para domínio @{dominio} | evento={event}")
            # Retorna 200 para a Kiwify não ficar reentando — é um evento legítimo
            # mas para um email que não está cadastrado como billing_email de nenhum tenant
            return {"status": "tenant_not_found", "event": event}

        ativar = event in EVENTOS_ATIVAR

        tenant.plan_active = ativar
        tenant.bot_active  = ativar

        db.commit()

        status_str = "ativado ✅" if ativar else "suspenso ⏸"
        print(f"[Billing] Tenant {tenant.id[:8]}... {status_str} | evento={event}")

        return {
            "status": "ok",
            "event": event,
            "tenant": tenant.name,
            "plan_active": ativar,
            "bot_active": ativar,
        }

    except Exception as e:
        db.rollback()
        print(f"[Billing] ❌ Erro ao processar evento: {e}")
        return JSONResponse({"error": "Erro interno"}, status_code=500)

    finally:
        db.close()


@router.get("/billing/webhook")
async def billing_webhook_verify(request: Request):
    """
    Alguns serviços fazem um GET para verificar se a URL está ativa.
    Retorna 200 simples.
    """
    return {"status": "ok", "service": "AgendaBot Billing"}