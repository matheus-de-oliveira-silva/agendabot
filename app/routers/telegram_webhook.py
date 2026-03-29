from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Customer, Conversation
from ..services.ai_service import chat_with_ai
from ..services.scheduler import get_available_slots, format_slots_for_ai
import os
import json
import httpx

router = APIRouter()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ID do tenant de teste que criamos
TEST_TENANT_ID = "d558102e-7862-4553-a08f-14447d687252"


async def send_telegram_message(chat_id: int, text: str):
    """Envia mensagem para o usuário no Telegram."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
        )


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Recebe mensagens do Telegram e processa com a IA."""
    body = await request.json()

    # Ignora se não for mensagem de texto
    if "message" not in body:
        return {"status": "ignored"}

    message = body["message"]

    # Ignora se não tiver texto
    if "text" not in message:
        return {"status": "ignored"}

    chat_id = message["chat"]["id"]
    customer_phone = str(chat_id)  # usa o chat_id como identificador
    message_text = message["text"]
    
    # Pega o nome do usuário se disponível
    first_name = message["chat"].get("first_name", "")

    # Abre sessão do banco
    db = SessionLocal()

    try:
        # Busca o tenant de teste
        tenant = db.query(Tenant).filter(
            Tenant.id == TEST_TENANT_ID
        ).first()

        if not tenant:
            await send_telegram_message(chat_id, "Erro: tenant não encontrado.")
            return {"status": "error"}

        # Busca ou cria o cliente
        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.phone == customer_phone
        ).first()

        if not customer:
            customer = Customer(
                tenant_id=tenant.id,
                phone=customer_phone,
                name=first_name,
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

        # Carrega histórico
        history = json.loads(conversation.messages)

        # Chama a IA
        ai_response = chat_with_ai(history, message_text)

        # Processa a ação
        action = ai_response.get("action", "reply")
        reply_text = ""

        if action == "check_availability":
            date_str = ai_response.get("date", "")

            # Verifica domingo e feriado ANTES de buscar slots
            from ..services.scheduler import check_business_hours, FERIADOS
            check = check_business_hours(date_str)

            if not check["open"]:
                if check["message"] == "DOMINGO":
                    reply_text = "Hoje é domingo e estamos fechados! 😊 De segunda a sábado funcionamos das 9h às 18h. Posso agendar para amanhã?"
                elif check["message"] == "FERIADO":
                    reply_text = "Nesse dia é feriado e estaremos fechados! 🎉 Funcionamos de segunda a sábado das 9h às 18h. Posso agendar para outro dia?"
                elif check["message"] == "PASSADO":
                    reply_text = "Essa data já passou! Vamos escolher uma data futura? 😊"
                else:
                    reply_text = "Não consigo agendar para essa data. Pode escolher outro dia?"
            else:
                slots = get_available_slots(
                    db, tenant.id,
                    date_str,
                    ai_response.get("service", "")
                )
                reply_text = format_slots_for_ai(slots, date_str)

        elif action == "create_appointment":
            pet_name = ai_response.get("pet_name", "seu pet")
            scheduled = ai_response.get("datetime", "")
            reply_text = (
                f"✅ Agendamento confirmado!\n\n"
                f"🐾 Pet: {pet_name}\n"
                f"📅 Data: {scheduled}\n\n"
                f"Até lá! Qualquer dúvida é só chamar."
            )

        else:
            reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

        # Atualiza histórico
        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": reply_text})
        conversation.messages = json.dumps(history[-20:])
        db.commit()

        # Envia resposta para o Telegram
        await send_telegram_message(chat_id, reply_text)

        return {"status": "ok"}

    finally:
        db.close()
