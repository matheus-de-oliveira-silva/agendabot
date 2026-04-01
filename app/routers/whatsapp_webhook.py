from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Customer, Conversation, Service
from ..services.ai_service import chat_with_ai
from ..services.scheduler import (
    get_available_slots, format_slots_for_ai,
    check_business_hours, create_appointment,
    cancel_appointment, get_customer_appointments, FERIADOS
)
import os
import json
import httpx
from datetime import datetime

router = APIRouter()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "agendabot")

SERVICE_KEYWORDS = {
    "banho_tosa": ["banho e tosa", "tosa"],
    "banho_simples": ["banho simples", "banho"],
    "tosa_higienica": ["tosa higiênica", "tosa higienica", "higiênica"],
    "consulta": ["consulta", "veterinária", "veterinaria"],
}

def find_service(db, tenant_id: str, service_key: str):
    keywords = SERVICE_KEYWORDS.get(service_key, [])
    for keyword in keywords:
        service = db.query(Service).filter(
            Service.tenant_id == tenant_id,
            Service.active == True,
            Service.name.ilike(f"%{keyword}%")
        ).first()
        if service:
            return service
    return db.query(Service).filter(
        Service.tenant_id == tenant_id,
        Service.active == True
    ).first()


async def send_whatsapp_message(phone: str, text: str):
    """Envia mensagem via Evolution API."""
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": phone,
        "text": text
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.json()

    # Ignora mensagens que não sejam do tipo correto
    if body.get("event") != "messages.upsert":
        return {"status": "ignored"}

    try:
        data = body["data"]
        key = data.get("key", {})

        # Ignora mensagens enviadas pelo próprio bot
        if key.get("fromMe"):
            return {"status": "ignored"}

        # Ignora mensagens de grupos
        remote_jid = key.get("remoteJid", "")
        if "@g.us" in remote_jid:
            return {"status": "ignored"}

        message = data.get("message", {})
        message_text = (
            message.get("conversation") or
            message.get("extendedTextMessage", {}).get("text") or
            ""
        )

        if not message_text:
            return {"status": "ignored"}

        # Pega só o número sem @s.whatsapp.net
        customer_phone = remote_jid.replace("@s.whatsapp.net", "")

    except (KeyError, TypeError):
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        tenant = db.query(Tenant).first()
        if not tenant:
            return {"status": "error", "detail": "tenant not found"}

        # Busca ou cria cliente
        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.phone == customer_phone
        ).first()

        if not customer:
            push_name = data.get("pushName", "")
            customer = Customer(
                tenant_id=tenant.id,
                phone=customer_phone,
                name=push_name,
                wa_id=customer_phone
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

        # Busca ou cria conversa
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

        history = json.loads(conversation.messages)
        ai_response = chat_with_ai(history, message_text)
        action = ai_response.get("action", "reply")
        reply_text = ""

        # ── Verificar disponibilidade ──────────────────────────
        if action == "check_availability":
            date_str = ai_response.get("date", "")
            check = check_business_hours(date_str)

            if not check["open"]:
                try:
                    date = datetime.strptime(date_str, "%Y-%m-%d")
                    if date.weekday() == 6:
                        reply_text = "😔 Domingo estamos fechados!\n\nFuncionamos de segunda a sábado das 9h às 18h.\nPosso verificar horários para amanhã? 😊"
                    elif date_str in FERIADOS:
                        reply_text = "🎉 Nesse dia é feriado e vamos estar de folga!\n\nFuncionamos de segunda a sábado das 9h às 18h.\nPosso verificar outro dia para você? 😊"
                    elif date.date() < datetime.now().date():
                        reply_text = "Essa data já passou! Vamos escolher uma data futura? 😊"
                    else:
                        reply_text = "Não consigo agendar para essa data. Pode escolher outro dia?"
                except ValueError:
                    reply_text = "Não entendi a data. Pode me informar novamente? 😊"
            else:
                slots = get_available_slots(db, tenant.id, date_str, ai_response.get("service", ""))
                reply_text = format_slots_for_ai(slots, date_str)

        # ── Criar agendamento ──────────────────────────────────
        elif action == "create_appointment":
            service_key = ai_response.get("service", "")
            service = find_service(db, tenant.id, service_key)

            if not service:
                reply_text = "Desculpe, não encontrei esse serviço. Pode escolher outro?"
            else:
                datetime_str = ai_response.get("datetime", "")
                pet_name = ai_response.get("pet_name", "seu pet")
                result = create_appointment(db, tenant.id, customer.id, service.id, datetime_str)

                if result["success"]:
                    reply_text = (
                        f"✅ Agendamento confirmado!\n\n"
                        f"🐾 Pet: {pet_name}\n"
                        f"✂️ Serviço: {service.name}\n"
                        f"📅 Data: {result['scheduled_at']}\n\n"
                        f"Até lá! Qualquer dúvida é só chamar. 😊"
                    )
                else:
                    reply_text = f"😕 Não consegui confirmar esse horário ({result['error']}). Vamos tentar outro horário?"

        # ── Ver agendamentos ───────────────────────────────────
        elif action == "list_appointments":
            appointments = get_customer_appointments(db, tenant.id, customer.id)
            if not appointments:
                reply_text = "Você não tem agendamentos futuros no momento. Deseja agendar? 😊"
            else:
                reply_text = "📋 Seus próximos agendamentos:\n\n"
                for i, a in enumerate(appointments, 1):
                    reply_text += f"{i}. 📅 {a['scheduled_at']}\n"
                reply_text += "\nPara cancelar, me diga o número do agendamento."

        # ── Cancelar agendamento ───────────────────────────────
        elif action == "cancel_appointment":
            appointment_index = ai_response.get("appointment_index", 1) - 1
            appointments = get_customer_appointments(db, tenant.id, customer.id)
            if not appointments:
                reply_text = "Você não tem agendamentos para cancelar."
            elif appointment_index < 0 or appointment_index >= len(appointments):
                reply_text = "Não encontrei esse agendamento. Qual número você quer cancelar?"
            else:
                appt = appointments[appointment_index]
                result = cancel_appointment(db, appt["id"], tenant.id)
                if result["success"]:
                    reply_text = f"✅ Agendamento de {appt['scheduled_at']} cancelado com sucesso!"
                else:
                    reply_text = f"Não consegui cancelar: {result['error']}"

        # ── Resposta normal ────────────────────────────────────
        else:
            reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

        # Atualiza histórico
        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": reply_text})
        conversation.messages = json.dumps(history[-20:])
        db.commit()

        await send_whatsapp_message(customer_phone, reply_text)
        return {"status": "ok"}

    finally:
        db.close()
        