from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Customer, Conversation, Service, Pet, Appointment
from ..services.ai_service import chat_with_ai
from ..services.scheduler import (
    get_available_slots, format_slots_for_ai,
    create_appointment, cancel_appointment,
    get_customer_appointments, FERIADOS
)
import os, json, httpx
from datetime import datetime, timedelta
import pytz

router = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "agendabot")


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

def check_business_hours_dynamic(tenant_config: dict, date_str: str) -> dict:
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = str(date.weekday())
        open_days = [d.strip() for d in (tenant_config.get("open_days") or "0,1,2,3,4,5").split(",")]
        if weekday not in open_days:
            return {"open": False, "reason": "closed_day"}
        if date_str in FERIADOS:
            return {"open": False, "reason": "holiday"}
        if date.date() < datetime.now().date():
            return {"open": False, "reason": "past"}
        return {"open": True}
    except:
        return {"open": False, "reason": "invalid_date"}

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

def should_reset_conversation(conversation) -> bool:
    if not conversation.updated_at:
        return False
    agora = datetime.now(BRASILIA).replace(tzinfo=None)
    return (agora - conversation.updated_at) > timedelta(hours=24)

def _find_tenant_for_whatsapp(db, body: dict):
    """
    Descobre qual tenant deve receber a mensagem.

    Estratégia (em ordem de prioridade):
    1. Tenta achar pelo instance name da Evolution API (campo 'instance')
       mapeado pelo phone_number_id configurado no tenant.
    2. Tenta pelo número de destino da mensagem (campo 'to' ou 'destination').
    3. Fallback: se só existe 1 tenant com bot ativo, usa ele.
       Se houver mais de 1, rejeita (não dá pra adivinhar).
    """

    # Tenta extrair o instance name do payload da Evolution API
    instance_name = (
        body.get("instance")
        or body.get("instanceName")
        or body.get("data", {}).get("instance")
        or ""
    )

    # Tenta achar por phone_number_id = instance_name
    if instance_name:
        tenant = db.query(Tenant).filter(
            Tenant.phone_number_id == instance_name,
            Tenant.bot_active == True
        ).first()
        if tenant:
            return tenant

    # Tenta pelo número de destino (alguns payloads trazem o número do bot)
    destination = (
        body.get("destination")
        or body.get("to")
        or body.get("data", {}).get("key", {}).get("remoteJid", "").split("@")[0]
    )

    # Fallback seguro: só usa .first() se houver exatamente 1 tenant ativo
    tenants_ativos = db.query(Tenant).filter(Tenant.bot_active == True).all()
    if len(tenants_ativos) == 1:
        return tenants_ativos[0]

    # Mais de 1 tenant e não conseguiu identificar — rejeita
    return None

async def send_whatsapp_message(phone: str, text: str):
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        print(f"[WhatsApp] Evolution não configurada. Mensagem para {phone}: {text[:50]}...")
        return
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"number": phone, "text": text}, headers=headers)
        except Exception as e:
            print(f"[WhatsApp] Erro ao enviar mensagem: {e}")

async def send_whatsapp_message_for_tenant(phone: str, text: str, tenant):
    """Envia mensagem usando as credenciais do tenant correto."""
    instance = getattr(tenant, 'phone_number_id', None) or EVOLUTION_INSTANCE
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        print(f"[WhatsApp:{instance}] Sem Evolution configurada. Msg para {phone}: {text[:50]}...")
        return
    url = f"{EVOLUTION_API_URL}/message/sendText/{instance}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"number": phone, "text": text}, headers=headers)
        except Exception as e:
            print(f"[WhatsApp:{instance}] Erro ao enviar: {e}")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.json()

    if body.get("event") != "messages.upsert":
        return {"status": "ignored"}

    try:
        data = body["data"]
        key = data.get("key", {})
        if key.get("fromMe"):
            return {"status": "ignored"}
        remote_jid = key.get("remoteJid", "")
        if "@g.us" in remote_jid:
            return {"status": "ignored"}
        message = data.get("message", {})
        message_text = (
            message.get("conversation") or
            message.get("extendedTextMessage", {}).get("text") or ""
        ).strip()
        if not message_text:
            return {"status": "ignored"}
        customer_phone = remote_jid.replace("@s.whatsapp.net", "")
        push_name = data.get("pushName", "")
    except (KeyError, TypeError):
        return {"status": "ignored"}

    db = SessionLocal()
    try:
        # ── Isolamento por tenant ──────────────────────────────────────────
        tenant = _find_tenant_for_whatsapp(db, body)
        if not tenant:
            print(f"[WhatsApp] Tenant não identificado para mensagem de {customer_phone}. Body keys: {list(body.keys())}")
            return {"status": "tenant_not_found"}

        if not getattr(tenant, 'bot_active', True):
            await send_whatsapp_message_for_tenant(
                customer_phone,
                "Olá! Estamos temporariamente fora do ar. Por favor, tente mais tarde. 🙏",
                tenant
            )
            return {"status": "bot_inactive"}

        tenant_config = get_tenant_config(tenant)
        services = get_tenant_services(db, tenant.id)

        # Cliente sempre vinculado ao tenant correto
        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.phone == customer_phone
        ).first()
        if not customer:
            customer = Customer(tenant_id=tenant.id, phone=customer_phone, name=push_name, wa_id=customer_phone)
            db.add(customer)
            db.commit()
            db.refresh(customer)
        elif push_name and not customer.name:
            customer.name = push_name
            db.commit()

        # Conversa sempre vinculada ao tenant correto
        conversation = db.query(Conversation).filter(
            Conversation.tenant_id == tenant.id,
            Conversation.customer_phone == customer_phone
        ).first()
        if not conversation:
            conversation = Conversation(tenant_id=tenant.id, customer_phone=customer_phone, messages="[]")
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        if should_reset_conversation(conversation):
            conversation.messages = "[]"
            db.commit()

        history = json.loads(conversation.messages)
        customer_context = get_customer_context(db, tenant.id, customer.id, customer.name or push_name)

        ai_response = chat_with_ai(
            history, message_text, customer_context,
            tenant_config=tenant_config,
            services=services
        )
        action = ai_response.get("action", "reply")
        reply_text = ""

        if action == "check_availability":
            date_str = ai_response.get("date", "")
            check = check_business_hours_dynamic(tenant_config, date_str)
            if not check["open"]:
                reason = check.get("reason", "")
                open_t = tenant_config.get("open_time", "09:00")
                close_t = tenant_config.get("close_time", "18:00")
                if reason == "closed_day":
                    reply_text = f"😔 Nesse dia não funcionamos!\n\nFuncionamos {open_t} às {close_t}.\nPosso verificar outro dia? 😊"
                elif reason == "holiday":
                    reply_text = "🎉 Nesse dia é feriado! Posso verificar outro dia? 😊"
                elif reason == "past":
                    reply_text = "Essa data já passou! Vamos escolher uma data futura? 😊"
                else:
                    reply_text = "Não consigo agendar para essa data. Pode escolher outro dia?"
            else:
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

        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": reply_text})
        conversation.messages = json.dumps(history[-20:])
        db.commit()

        await send_whatsapp_message_for_tenant(customer_phone, reply_text, tenant)
        return {"status": "ok"}

    finally:
        db.close()