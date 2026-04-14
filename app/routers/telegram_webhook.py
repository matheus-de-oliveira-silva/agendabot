from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Tenant, Customer, Conversation, Service, Pet, Appointment
from ..services.ai_service import chat_with_ai
from ..services.scheduler import (
    get_available_slots, format_slots_for_ai,
    check_business_hours, create_appointment,
    cancel_appointment, get_customer_appointments, FERIADOS
)
import os, json, httpx
from ..services.notifier import notify_owner_new_appointment
from datetime import datetime, timedelta
import pytz

router = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
COMANDOS_RESET = ["/start", "/reiniciar", "/reset", "/novo"]

TELEGRAM_TENANT_ID = os.getenv("TELEGRAM_TENANT_ID", "")


def get_tenant_services(db, tenant_id: str) -> list:
    services = db.query(Service).filter(
        Service.tenant_id == tenant_id,
        Service.active == True
    ).all()
    result = []
    for s in services:
        key = s.name.lower()
        key = key.replace(" ", "_").replace("ã", "a").replace("é", "e").replace("ê", "e")
        key = key.replace("ç", "c").replace("á", "a").replace("ó", "o").replace("í", "i")
        key = "".join(c for c in key if c.isalnum() or c == "_")
        result.append({
            "id": s.id, "key": key, "name": s.name,
            "price": s.price or 0, "duration_min": s.duration_min or 60,
            "description": s.description or "", "color": s.color or "#6C5CE7",
        })
    return result


def get_tenant_config(tenant) -> dict:
    return {
        "bot_attendant_name":   getattr(tenant, 'bot_attendant_name', None) or "Mari",
        "bot_business_name":    getattr(tenant, 'bot_business_name', None) or tenant.display_name or tenant.name,
        "display_name":         tenant.display_name or tenant.name,
        "name":                 tenant.name,
        "business_type":        getattr(tenant, 'business_type', None) or "outro",
        "subject_label":        getattr(tenant, 'subject_label', None) or "Cliente",
        "subject_label_plural": getattr(tenant, 'subject_label_plural', None) or "Clientes",
        "open_days":            getattr(tenant, 'open_days', None) or "0,1,2,3,4,5",
        "open_time":            getattr(tenant, 'open_time', None) or "09:00",
        "close_time":           getattr(tenant, 'close_time', None) or "18:00",
        # ── Etapa 5: endereço ──────────────────────────────────────────────
        "needs_address":        bool(getattr(tenant, 'needs_address', False)),
        "address_label":        getattr(tenant, 'address_label', None) or "Endereço de busca",
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


def should_reset_conversation(conversation) -> bool:
    if not conversation.updated_at:
        return False
    agora = datetime.now(BRASILIA).replace(tzinfo=None)
    return (agora - conversation.updated_at) > timedelta(hours=24)


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


def _find_tenant_for_telegram(db) -> Tenant:
    if TELEGRAM_TENANT_ID:
        tenant = db.query(Tenant).filter(
            Tenant.id == TELEGRAM_TENANT_ID,
            Tenant.bot_active == True
        ).first()
        if tenant:
            return tenant
        print(f"[Telegram] AVISO: TELEGRAM_TENANT_ID='{TELEGRAM_TENANT_ID}' não encontrado ou bot inativo.")

    tenants_ativos = db.query(Tenant).filter(Tenant.bot_active == True).all()
    if len(tenants_ativos) == 1:
        return tenants_ativos[0]
    elif len(tenants_ativos) > 1:
        print(
            f"[Telegram] AVISO DE PRIVACIDADE: Há {len(tenants_ativos)} tenants ativos e TELEGRAM_TENANT_ID "
            f"não está configurado! Configure TELEGRAM_TENANT_ID no .env para evitar vazamento de dados entre tenants."
        )
        return tenants_ativos[0]
    return None


async def send_telegram_message(chat_id: int, text: str):
    if not TELEGRAM_TOKEN:
        print(f"[Telegram] TELEGRAM_TOKEN não configurado. Msg para {chat_id}: {text[:50]}...")
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as e:
            print(f"[Telegram] Erro ao enviar mensagem: {e}")


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
    message_text = message["text"].strip()
    first_name = message["chat"].get("first_name", "")

    db = SessionLocal()
    try:
        tenant = _find_tenant_for_telegram(db)
        if not tenant:
            await send_telegram_message(chat_id, "Serviço temporariamente indisponível. Tente mais tarde.")
            return {"status": "tenant_not_found"}

        if not getattr(tenant, 'bot_active', True):
            await send_telegram_message(chat_id, "Olá! Estamos temporariamente fora do ar. Por favor, tente mais tarde. 🙏")
            return {"status": "bot_inactive"}

        tenant_config = get_tenant_config(tenant)
        services = get_tenant_services(db, tenant.id)
        business_name = tenant_config["bot_business_name"]

        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.phone == customer_phone
        ).first()
        if not customer:
            customer = Customer(tenant_id=tenant.id, phone=customer_phone, name=first_name, wa_id=customer_phone)
            db.add(customer)
            db.commit()
            db.refresh(customer)
        elif first_name and not customer.name:
            customer.name = first_name
            db.commit()

        conversation = db.query(Conversation).filter(
            Conversation.tenant_id == tenant.id,
            Conversation.customer_phone == customer_phone
        ).first()
        if not conversation:
            conversation = Conversation(tenant_id=tenant.id, customer_phone=customer_phone, messages="[]")
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        if message_text.lower() in COMANDOS_RESET:
            conversation.messages = "[]"
            db.commit()
            nome = f" {customer.name or first_name}" if (customer.name or first_name) else ""
            await send_telegram_message(chat_id, f"Oi{nome}! 😊 Bem-vindo ao {business_name}!\n\nComo posso ajudar você hoje? 🐾")
            return {"status": "ok"}

        if should_reset_conversation(conversation):
            conversation.messages = "[]"
            db.commit()

        history = json.loads(conversation.messages)
        customer_context = get_customer_context(db, tenant.id, customer.id, customer.name or first_name)

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
                open_time  = tenant_config.get("open_time", "09:00")
                close_time = tenant_config.get("close_time", "18:00")
                if reason == "closed_day":
                    reply_text = f"😔 Nesse dia não funcionamos!\n\nFuncionamos {open_time} às {close_time}.\nPosso verificar outro dia? 😊"
                elif reason == "holiday":
                    reply_text = f"🎉 Nesse dia é feriado!\n\nPosso verificar outro dia? 😊"
                elif reason == "past":
                    reply_text = "Essa data já passou! Vamos escolher uma data futura? 😊"
                else:
                    reply_text = "Não consigo agendar para essa data. Pode escolher outro dia?"
            else:
                slots = get_available_slots(db, tenant.id, date_str, ai_response.get("service", ""))
                requested_time = ai_response.get("requested_time", "")
                if requested_time:
                    available_times = [s["time"] for s in slots]
                    if requested_time in available_times:
                        reply_text = f"__SLOT_OK__{requested_time}__{date_str}"
                    else:
                        proximos = available_times[:3] if available_times else []
                        sugestoes = ", ".join(proximos) if proximos else "nenhum"
                        reply_text = f"__SLOT_OCUPADO__{requested_time}__{date_str}__{sugestoes}"
                else:
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
                    nome_final = customer_name_ai or customer.name or first_name or ""
                    if nome_final and not customer.name:
                        customer.name = nome_final
                        db.commit()
                    if not ai_response.get("customer_name") and nome_final:
                        ai_response["customer_name"] = nome_final

                    # ── Etapa 5: captura endereço da resposta da IA ────────
                    pickup_address = ai_response.get("pickup_address") or None

                    result = create_appointment(
                        db=db,
                        tenant_id=tenant.id,
                        customer_id=customer.id,
                        service_id=service_obj.id,
                        datetime_str=ai_response.get("datetime", ""),
                        pet_name=ai_response.get("pet_name"),
                        pet_breed=ai_response.get("pet_breed"),
                        pet_weight=ai_response.get("pet_weight"),
                        pickup_time=ai_response.get("pickup_time"),
                        pickup_address=pickup_address,   # ← NOVO
                    )

                    price_fmt = f"R$ {svc_data['price']/100:.2f}" if svc_data.get('price') else ""
                    subject   = tenant_config.get("subject_label", "Pet")

                    if result["success"]:
                        pet_info = ai_response.get("pet_name", f"seu {subject.lower()}")
                        if ai_response.get("pet_breed"):
                            pet_info += f" ({ai_response['pet_breed']})"
                        pickup = f"\n🏠 Busca: {ai_response['pickup_time']}" if ai_response.get("pickup_time") else ""

                        # ── Linha de endereço condicional ──────────────────
                        if pickup_address:
                            label = tenant_config.get("address_label", "Endereço")
                            address_line = f"\n📍 {label}: {pickup_address}"
                        else:
                            address_line = ""

                        reply_text = (
                            f"✅ Agendamento confirmado!\n\n"
                            f"🐾 {subject}: {pet_info}\n"
                            f"✂️ Serviço: {service_obj.name}{' — ' + price_fmt if price_fmt else ''}\n"
                            f"📅 Data: {result['scheduled_at']}"
                            f"{pickup}"
                            f"{address_line}\n\n"
                            f"Até lá! 😊"
                        )

                        appt_obj = db.query(Appointment).filter(Appointment.id == result["appointment_id"]).first()
                        if appt_obj:
                            await notify_owner_new_appointment(tenant, appt_obj, customer, service_obj)
                    else:
                        reply_text = f"😕 Não consegui confirmar ({result['error']}). Vamos tentar outro horário?"

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
                    reply_text = f"✅ Agendamento de {appt['scheduled_at']} cancelado!"
                else:
                    reply_text = f"Não consegui cancelar: {result['error']}"

        else:
            reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

        # ── Segunda chamada à IA para slots específicos ────────────────────
        if reply_text.startswith("__SLOT_OK__"):
            parts = reply_text.split("__")
            slot_time, slot_date = parts[2], parts[3]
            slot_msg = f"[SISTEMA] O horario {slot_time} do dia {slot_date} esta DISPONIVEL. Confirme esse horario ao cliente e siga para o proximo passo do agendamento."
            history.append({"role": "user", "content": message_text})
            ai2 = chat_with_ai(history, slot_msg, customer_context, tenant_config, services)
            reply_text = ai2.get("message", f"Perfeito! O horario das {slot_time} esta disponivel 😊")

        elif reply_text.startswith("__SLOT_OCUPADO__"):
            parts = reply_text.split("__")
            slot_time = parts[2]
            slot_date = parts[3]
            sugestoes = parts[4] if len(parts) > 4 else "nenhum"
            slot_msg = f"[SISTEMA] O horario {slot_time} do dia {slot_date} esta OCUPADO. Horarios proximos disponiveis: {sugestoes}. Informe o cliente e oferta esses horarios."
            history.append({"role": "user", "content": message_text})
            ai2 = chat_with_ai(history, slot_msg, customer_context, tenant_config, services)
            reply_text = ai2.get("message", f"Ops! O horario das {slot_time} esta ocupado. Temos {sugestoes} disponiveis. Qual prefere?")

        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": reply_text})
        conversation.messages = json.dumps(history[-20:])
        db.commit()

        await send_telegram_message(chat_id, reply_text)
        return {"status": "ok"}

    finally:
        db.close()