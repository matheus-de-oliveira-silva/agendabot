from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Customer, Conversation, Appointment, Service
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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


async def send_telegram_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        )


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    body = await request.json()

    if "message" not in body:
        return {"status": "ignored"}

    message = body["message"]

    if "text" not in message:
        return {"status": "ignored"}

    chat_id = message["chat"]["id"]
    customer_phone = str(chat_id)
    message_text = message["text"]
    first_name = message["chat"].get("first_name", "")

    db = SessionLocal()

    try:
        # Busca o primeiro tenant ativo (MVP com um único negócio)
        tenant = db.query(Tenant).first()
        if not tenant:
            await send_telegram_message(chat_id, "Erro: configuração não encontrada.")
            return {"status": "error"}

        # Busca ou cria cliente
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

        # Chama a IA
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
                        reply_text = (
                            "😔 Que pena! Hoje é domingo e estamos fechadinhos!\n\n"
                            "Funcionamos de segunda a sábado das 9h às 18h.\n"
                            "Posso verificar horários para amanhã? 😊"
                        )
                    elif date_str in FERIADOS:
                        reply_text = (
                            "🎉 Nesse dia é feriado e vamos estar de folga!\n\n"
                            "Funcionamos de segunda a sábado das 9h às 18h.\n"
                            "Posso verificar outro dia para você? 😊"
                        )
                    elif date.date() < datetime.now().date():
                        reply_text = "Essa data já passou! Vamos escolher uma data futura? 😊"
                    else:
                        reply_text = "Não consigo agendar para essa data. Pode escolher outro dia?"
                except ValueError:
                    reply_text = "Não entendi a data. Pode me informar novamente? 😊"
            else:
                slots = get_available_slots(
                    db, tenant.id,
                    date_str,
                    ai_response.get("service", "")
                )
                reply_text = format_slots_for_ai(slots, date_str)

        # ── Criar agendamento ──────────────────────────────────
        elif action == "create_appointment":
            service = db.query(Service).filter(
                Service.tenant_id == tenant.id,
                Service.active == True
            ).first()

            service_id = service.id if service else "default"
            datetime_str = ai_response.get("datetime", "")
            pet_name = ai_response.get("pet_name", "seu pet")

            result = create_appointment(
                db, tenant.id, customer.id,
                service_id, datetime_str
            )

            if result["success"]:
                reply_text = (
                    f"✅ Agendamento confirmado!\n\n"
                    f"🐾 Pet: {pet_name}\n"
                    f"📅 Data: {result['scheduled_at']}\n\n"
                    f"Até lá! Qualquer dúvida é só chamar. 😊"
                )
            else:
                reply_text = (
                    f"😕 Não consegui confirmar esse horário ({result['error']}). "
                    f"Vamos tentar outro horário?"
                )

        # ── Ver agendamentos do cliente ────────────────────────
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

        await send_telegram_message(chat_id, reply_text)
        return {"status": "ok"}

    finally:
        db.close()
        