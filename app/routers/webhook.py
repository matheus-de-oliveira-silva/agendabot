from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Tenant, Customer, Conversation
from ..services.ai_service import chat_with_ai
from ..services.scheduler import get_available_slots, format_slots_for_ai
import os
import json
import httpx

router = APIRouter()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "agendabot123")


# ── Verificação do webhook (GET) ──────────────────────────────────────────────
# A Meta chama essa rota para confirmar que o servidor é legítimo
@router.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params.get("hub.challenge", 0))
    
    raise HTTPException(status_code=403, detail="Token inválido")


# ── Recebe mensagens (POST) ───────────────────────────────────────────────────
@router.post("/webhook")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    body = await request.json()

    # Extrai os dados da mensagem do payload do WhatsApp
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]["value"]
        
        # Ignora se não for mensagem (pode ser status de entrega etc)
        if "messages" not in change:
            return {"status": "ignored"}

        message = change["messages"][0]
        phone_number_id = change["metadata"]["phone_number_id"]
        customer_phone = message["from"]
        message_text = message["text"]["body"]

    except (KeyError, IndexError):
        return {"status": "ignored"}

    # Busca o tenant pelo phone_number_id
    tenant = db.query(Tenant).filter(
        Tenant.phone_number_id == phone_number_id
    ).first()

    # Para testes sem WhatsApp configurado, usa tenant padrão
    if not tenant:
        return {"status": "tenant_not_found"}

    # Busca ou cria o cliente
    customer = db.query(Customer).filter(
        Customer.tenant_id == tenant.id,
        Customer.phone == customer_phone
    ).first()

    if not customer:
        customer = Customer(
            tenant_id=tenant.id,
            phone=customer_phone,
            wa_id=customer_phone
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    # Busca ou cria a conversa
    conversation = db.query(Conversation).filter(
        Conversation.tenant_id == tenant.id,
        Conversation.customer_phone == customer_phone
    ).first()

    if not conversation:
        conversation = Conversation(
            tenant_id=tenant.id,
            customer_phone=customer_phone,
            messages="[]"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Carrega histórico de mensagens
    history = json.loads(conversation.messages)

    # Chama a IA
    ai_response = chat_with_ai(history, message_text)

    # Processa a ação retornada pela IA
    reply_text = ""

    if ai_response.get("action") == "check_availability":
        slots = get_available_slots(
            db, tenant.id,
            ai_response.get("date", ""),
            ai_response.get("service", "")
        )
        reply_text = format_slots_for_ai(slots)

    elif ai_response.get("action") == "create_appointment":
        reply_text = f"Perfeito! Agendamento confirmado para {ai_response.get('datetime', '')}. Até lá! 🐾"

    else:
        reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

    # Atualiza histórico
    history.append({"role": "user", "content": message_text})
    history.append({"role": "assistant", "content": reply_text})
    conversation.messages = json.dumps(history[-20:])  # guarda só as últimas 20
    db.commit()

    # Envia resposta pelo WhatsApp
    await send_whatsapp_message(
        phone=customer_phone,
        message=reply_text,
        phone_number_id=phone_number_id,
        token=tenant.wa_access_token
    )

    return {"status": "ok"}


async def send_whatsapp_message(phone: str, message: str, 
                                 phone_number_id: str, token: str):
    """Envia mensagem pelo WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)