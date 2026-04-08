from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Tenant, Customer, Conversation, Service, Pet, Appointment
from ..services.ai_service import chat_with_ai
from ..services.scheduler import get_available_slots, format_slots_for_ai, create_appointment, cancel_appointment, get_customer_appointments
import os
import json
import httpx

router = APIRouter()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "agendabot123")


def get_tenant_services(db, tenant_id: str) -> list:
    services = db.query(Service).filter(Service.tenant_id == tenant_id, Service.active == True).all()
    result = []
    for s in services:
        key = s.name.lower()
        key = key.replace(" ", "_").replace("ã","a").replace("é","e").replace("ê","e")
        key = key.replace("ç","c").replace("á","a").replace("ó","o").replace("í","i")
        key = "".join(c for c in key if c.isalnum() or c == "_")
        result.append({
            "id": s.id, "key": key, "name": s.name,
            "price": s.price or 0, "duration_min": s.duration_min or 60,
            "description": s.description or "", "color": s.color or "#6C5CE7",
        })
    return result

def get_tenant_config(tenant) -> dict:
    return {
        "bot_attendant_name": getattr(tenant, 'bot_attendant_name', None) or "Mari",
        "bot_business_name": getattr(tenant, 'bot_business_name', None) or tenant.display_name or tenant.name,
        "display_name": tenant.display_name or tenant.name,
        "name": tenant.name,
        "subject_label": getattr(tenant, 'subject_label', None) or "Pet",
        "subject_label_plural": getattr(tenant, 'subject_label_plural', None) or "Pets",
        "open_days": getattr(tenant, 'open_days', None) or "0,1,2,3,4,5",
        "open_time": getattr(tenant, 'open_time', None) or "09:00",
        "close_time": getattr(tenant, 'close_time', None) or "18:00",
    }

def find_service_by_key(services: list, key: str):
    for s in services:
        if s["key"] == key:
            return s
    for s in services:
        if key in s["key"] or s["key"] in key:
            return s
    return services[0] if services else None

def get_customer_context(db, tenant_id, customer_id, customer_name) -> dict:
    pets = db.query(Pet).filter(Pet.tenant_id == tenant_id, Pet.customer_id == customer_id).all()
    total = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.customer_id == customer_id,
        Appointment.status != "cancelled"
    ).count()
    return {
        "name": customer_name or "",
        "pets": [{"name": p.name, "breed": p.breed, "weight": p.weight} for p in pets],
        "total_appointments": total
    }


# ── Verificação do webhook (GET) ──────────────────────────────────────────────
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

    try:
        entry = body["entry"][0]
        change = entry["changes"][0]["value"]

        if "messages" not in change:
            return {"status": "ignored"}

        message = change["messages"][0]
        phone_number_id = change["metadata"]["phone_number_id"]
        customer_phone = message["from"]
        message_text = message["text"]["body"]

    except (KeyError, IndexError):
        return {"status": "ignored"}

    # ── Busca tenant pelo phone_number_id (isolamento correto) ──
    tenant = db.query(Tenant).filter(
        Tenant.phone_number_id == phone_number_id
    ).first()

    if not tenant:
        return {"status": "tenant_not_found"}

    # Verifica se bot está ativo
    if not getattr(tenant, 'bot_active', True):
        return {"status": "bot_inactive"}

    tenant_config = get_tenant_config(tenant)
    services = get_tenant_services(db, tenant.id)

    # Busca ou cria cliente (sempre vinculado ao tenant correto)
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

    # Busca ou cria conversa (sempre vinculada ao tenant correto)
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
    customer_context = get_customer_context(db, tenant.id, customer.id, customer.name)

    # Chama IA com contexto completo do tenant correto
    ai_response = chat_with_ai(
        history, message_text,
        customer_context=customer_context,
        tenant_config=tenant_config,
        services=services
    )

    action = ai_response.get("action", "reply")
    reply_text = ""

    if action == "check_availability":
        from datetime import datetime
        date_str = ai_response.get("date", "")
        slots = get_available_slots(db, tenant.id, date_str, ai_response.get("service", ""))
        reply_text = format_slots_for_ai(slots, date_str)

    elif action == "create_appointment":
        service_key = ai_response.get("service", "")
        svc_data = find_service_by_key(services, service_key)
        if not svc_data:
            reply_text = "Desculpe, não encontrei esse serviço. Pode escolher outro?"
        else:
            service_obj = db.query(Service).filter(Service.id == svc_data["id"]).first()
            if not service_obj:
                reply_text = "Serviço não encontrado. Pode escolher outro?"
            else:
                customer_name_ai = ai_response.get("customer_name", "")
                if customer_name_ai and not customer.name:
                    customer.name = customer_name_ai
                    db.commit()

                result = create_appointment(
                    db=db, tenant_id=tenant.id, customer_id=customer.id,
                    service_id=service_obj.id,
                    datetime_str=ai_response.get("datetime", ""),
                    pet_name=ai_response.get("pet_name"),
                    pet_breed=ai_response.get("pet_breed"),
                    pet_weight=ai_response.get("pet_weight"),
                    pickup_time=ai_response.get("pickup_time"),
                )
                price_fmt = f"R$ {svc_data['price']/100:.2f}" if svc_data.get('price') else ""
                subject = tenant_config.get("subject_label", "Pet")
                if result["success"]:
                    pet_info = ai_response.get("pet_name", f"seu {subject.lower()}")
                    if ai_response.get("pet_breed"):
                        pet_info += f" ({ai_response['pet_breed']})"
                    pickup = f"\n🏠 Busca: {ai_response['pickup_time']}" if ai_response.get("pickup_time") else ""
                    reply_text = (
                        f"✅ Agendamento confirmado!\n\n"
                        f"🐾 {subject}: {pet_info}\n"
                        f"✂️ Serviço: {service_obj.name}{' — ' + price_fmt if price_fmt else ''}\n"
                        f"📅 Data: {result['scheduled_at']}"
                        f"{pickup}\n\n"
                        f"Até lá! Qualquer dúvida é só chamar. 😊"
                    )
                else:
                    reply_text = f"😕 Não consegui confirmar esse horário ({result['error']}). Vamos tentar outro?"

    elif action == "list_appointments":
        appointments = get_customer_appointments(db, tenant.id, customer.id)
        if not appointments:
            reply_text = "Você não tem agendamentos futuros. Deseja agendar? 😊"
        else:
            reply_text = "📋 Seus próximos agendamentos:\n\n"
            for i, a in enumerate(appointments, 1):
                reply_text += f"{i}. 📅 {a['scheduled_at']}"
                if a.get("pet_name"):
                    reply_text += f" — {a['pet_name']}"
                reply_text += "\n"
            reply_text += "\nPara cancelar, me diga o número."

    elif action == "cancel_appointment":
        idx = ai_response.get("appointment_index", 1) - 1
        appointments = get_customer_appointments(db, tenant.id, customer.id)
        if not appointments:
            reply_text = "Você não tem agendamentos para cancelar."
        elif idx < 0 or idx >= len(appointments):
            reply_text = "Não encontrei esse agendamento."
        else:
            appt = appointments[idx]
            result = cancel_appointment(db, appt["id"], tenant.id)
            if result["success"]:
                reply_text = f"✅ Agendamento de {appt['scheduled_at']} cancelado com sucesso!"
            else:
                reply_text = f"Não consegui cancelar: {result['error']}"

    else:
        reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

    # Atualiza histórico
    history.append({"role": "user", "content": message_text})
    history.append({"role": "assistant", "content": reply_text})
    conversation.messages = json.dumps(history[-20:])
    db.commit()

    await send_whatsapp_message(
        phone=customer_phone,
        message=reply_text,
        phone_number_id=phone_number_id,
        token=tenant.wa_access_token
    )

    return {"status": "ok"}


async def send_whatsapp_message(phone: str, message: str,
                                 phone_number_id: str, token: str):
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