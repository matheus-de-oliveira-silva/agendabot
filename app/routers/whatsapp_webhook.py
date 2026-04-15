"""
whatsapp_webhook.py — Recebe mensagens WhatsApp via Evolution API.

LGPD:
  - Mensagens nunca são logadas em texto plano
  - Endereços nunca aparecem em logs
  - Cada tenant é isolado — dados de um tenant nunca acessam outro
  - Histórico de conversa limitado a 20 mensagens e resetado após 24h de inatividade
"""

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
from ..services.evolution_helper import send_whatsapp_message
from ..services.notifier import notify_owner_new_appointment
import os, json
from datetime import datetime, timedelta
import pytz

router   = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_tenant_services(db, tenant_id: str) -> list:
    services = db.query(Service).filter(
        Service.tenant_id == tenant_id,
        Service.active    == True
    ).all()
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
    pets  = db.query(Pet).filter(Pet.tenant_id == tenant_id, Pet.customer_id == customer_id).all()
    total = db.query(Appointment).filter(
        Appointment.tenant_id   == tenant_id,
        Appointment.customer_id == customer_id,
        Appointment.status      != "cancelled"
    ).count()
    return {
        "name": customer_name or "",
        "pets": [{"name": p.name, "breed": p.breed, "weight": p.weight} for p in pets],
        "total_appointments": total,
    }


def check_business_hours_dynamic(tenant_config: dict, date_str: str) -> dict:
    try:
        date      = datetime.strptime(date_str, "%Y-%m-%d")
        weekday   = str(date.weekday())
        open_days = [d.strip() for d in (tenant_config.get("open_days") or "0,1,2,3,4,5").split(",")]
        if weekday not in open_days:
            return {"open": False, "reason": "closed_day"}
        if date_str in FERIADOS:
            return {"open": False, "reason": "holiday"}
        if date.date() < datetime.now().date():
            return {"open": False, "reason": "past"}
        return {"open": True}
    except Exception:
        return {"open": False, "reason": "invalid_date"}


def should_reset_conversation(conversation) -> bool:
    if not conversation.updated_at:
        return False
    agora = datetime.now(BRASILIA).replace(tzinfo=None)
    return (agora - conversation.updated_at) > timedelta(hours=24)


def _find_tenant_for_whatsapp(db, body: dict):
    """
    Identifica o tenant pelo nome da instância Evolution no payload.
    Com múltiplos tenants, o phone_number_id é obrigatório para isolamento.
    LGPD: garante que a mensagem só vai para o tenant correto.
    """
    instance_name = (
        body.get("instance")
        or body.get("instanceName")
        or body.get("data", {}).get("instance")
        or ""
    )
    if instance_name:
        tenant = db.query(Tenant).filter(
            Tenant.phone_number_id == instance_name,
            Tenant.bot_active      == True
        ).first()
        if tenant:
            return tenant

    # Fallback: se só há 1 tenant ativo, usa ele (ambiente de desenvolvimento)
    tenants_ativos = db.query(Tenant).filter(Tenant.bot_active == True).all()
    if len(tenants_ativos) == 1:
        return tenants_ativos[0]

    # Múltiplos tenants sem instance identificada — não processa (segurança LGPD)
    if len(tenants_ativos) > 1:
        print(f"[WhatsApp] ⚠️ Múltiplos tenants ativos mas instância não identificada no payload. Ignorando.")
    return None


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.json()

    if body.get("event") != "messages.upsert":
        return {"status": "ignored"}

    try:
        data   = body["data"]
        key    = data.get("key", {})
        if key.get("fromMe"):
            return {"status": "ignored"}
        remote_jid = key.get("remoteJid", "")
        if "@g.us" in remote_jid:
            return {"status": "ignored"}
        message      = data.get("message", {})
        message_text = (
            message.get("conversation") or
            message.get("extendedTextMessage", {}).get("text") or ""
        ).strip()
        if not message_text:
            return {"status": "ignored"}
        customer_phone = remote_jid.replace("@s.whatsapp.net", "")
        push_name      = data.get("pushName", "")
    except (KeyError, TypeError):
        return {"status": "ignored"}

    db = SessionLocal()
    try:
        tenant = _find_tenant_for_whatsapp(db, body)
        if not tenant:
            return {"status": "tenant_not_found"}

        if not getattr(tenant, 'bot_active', True):
            await send_whatsapp_message(
                customer_phone,
                "Olá! Estamos temporariamente fora do ar. Por favor, tente mais tarde. 🙏",
                tenant
            )
            return {"status": "bot_inactive"}

        tenant_config = get_tenant_config(tenant)
        services      = get_tenant_services(db, tenant.id)

        # Busca ou cria cliente (isolado por tenant_id — LGPD)
        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.phone     == customer_phone
        ).first()
        if not customer:
            customer = Customer(
                tenant_id=tenant.id, phone=customer_phone,
                name=push_name, wa_id=customer_phone
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        elif push_name and not customer.name:
            customer.name = push_name
            db.commit()

        # Busca ou cria conversa (isolada por tenant_id — LGPD)
        conversation = db.query(Conversation).filter(
            Conversation.tenant_id      == tenant.id,
            Conversation.customer_phone == customer_phone
        ).first()
        if not conversation:
            conversation = Conversation(
                tenant_id=tenant.id, customer_phone=customer_phone, messages="[]"
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        # Reset após 24h de inatividade
        if should_reset_conversation(conversation):
            conversation.messages = "[]"
            db.commit()

        history          = json.loads(conversation.messages)
        customer_context = get_customer_context(
            db, tenant.id, customer.id, customer.name or push_name
        )
        if not customer_context.get("name") and push_name:
            customer_context["name"] = push_name

        # Chama IA
        ai_response = chat_with_ai(
            history, message_text, customer_context,
            tenant_config=tenant_config,
            services=services
        )
        action     = ai_response.get("action", "reply")
        reply_text = ""

        # ── check_availability ────────────────────────────────────────────────
        if action == "check_availability":
            date_str = ai_response.get("date", "")
            check    = check_business_hours_dynamic(tenant_config, date_str)

            if not check["open"]:
                reason  = check.get("reason", "")
                open_t  = tenant_config.get("open_time", "09:00")
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
                slots          = get_available_slots(db, tenant.id, date_str, ai_response.get("service", ""))
                requested_time = ai_response.get("requested_time", "")
                if requested_time:
                    available_times = [s["time"] for s in slots]
                    if requested_time in available_times:
                        reply_text = f"__SLOT_OK__{requested_time}__{date_str}"
                    else:
                        proximos  = available_times[:3] if available_times else []
                        sugestoes = ", ".join(proximos) if proximos else "nenhum"
                        reply_text = f"__SLOT_OCUPADO__{requested_time}__{date_str}__{sugestoes}"
                else:
                    reply_text = format_slots_for_ai(slots, date_str)

        # ── create_appointment ────────────────────────────────────────────────
        elif action == "create_appointment":
            service_key = ai_response.get("service", "")
            svc_data    = find_service_by_key(services, service_key)

            if not svc_data:
                reply_text = "Desculpe, não encontrei esse serviço. Pode escolher outro?"
            else:
                service_obj = db.query(Service).filter(Service.id == svc_data["id"]).first()
                if not service_obj:
                    reply_text = "Serviço não encontrado. Pode escolher outro?"
                else:
                    # Salva nome do cliente
                    customer_name_ai = ai_response.get("customer_name", "")
                    nome_final = customer_name_ai or customer.name or push_name or ""
                    if nome_final and not customer.name:
                        customer.name = nome_final
                        db.commit()
                    if not ai_response.get("customer_name") and nome_final:
                        ai_response["customer_name"] = nome_final

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
                        pickup_address=pickup_address,
                    )

                    if result["success"]:
                        # Usa mensagem gerada pela IA (tom adaptado ao tipo de negócio)
                        ia_message = ai_response.get("message", "")
                        if ia_message:
                            # Adiciona endereço se necessário (LGPD: só aqui, nunca em log)
                            if pickup_address:
                                label = tenant_config.get("address_label", "Endereço")
                                if label.lower() not in ia_message.lower():
                                    ia_message += f"\n📍 {label}: {pickup_address}"
                            reply_text = ia_message
                        else:
                            # Fallback manual
                            subject   = tenant_config.get("subject_label", "Cliente")
                            price_fmt = f"R$ {svc_data['price']/100:.2f}" if svc_data.get('price') else ""
                            pet_info  = ai_response.get("pet_name", "")
                            if pet_info and ai_response.get("pet_breed"):
                                pet_info += f" ({ai_response['pet_breed']})"
                            pet_ln    = f"\n🐾 {subject}: {pet_info}" if pet_info else ""
                            pickup_ln = f"\n🏠 Busca: {ai_response['pickup_time']}" if ai_response.get("pickup_time") else ""
                            addr_ln   = f"\n📍 {tenant_config.get('address_label','Endereço')}: {pickup_address}" if pickup_address else ""
                            reply_text = (
                                f"✅ Agendamento confirmado!\n\n"
                                f"✂️ Serviço: {service_obj.name}{' — ' + price_fmt if price_fmt else ''}\n"
                                f"📅 {result['scheduled_at']}"
                                f"{pet_ln}{pickup_ln}{addr_ln}\n\n"
                                f"Até lá! 😊"
                            )

                        # Notifica o dono
                        appt_obj = db.query(Appointment).filter(
                            Appointment.id == result["appointment_id"]
                        ).first()
                        if appt_obj:
                            await notify_owner_new_appointment(tenant, appt_obj, customer, service_obj)

                        # LGPD: nunca loga endereço
                        print(f"[Agendamento] criado | endereço: {'sim' if pickup_address else 'não'}")
                    else:
                        reply_text = f"😕 Não consegui confirmar esse horário ({result['error']}). Vamos tentar outro?"

        # ── list_appointments ─────────────────────────────────────────────────
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

        # ── cancel_appointment ────────────────────────────────────────────────
        elif action == "cancel_appointment":
            idx          = ai_response.get("appointment_index", 1) - 1
            appointments = get_customer_appointments(db, tenant.id, customer.id)
            if not appointments:
                reply_text = "Você não tem agendamentos para cancelar."
            elif idx < 0 or idx >= len(appointments):
                reply_text = "Não encontrei esse agendamento."
            else:
                appt   = appointments[idx]
                result = cancel_appointment(db, appt["id"], tenant.id)
                if result["success"]:
                    reply_text = f"✅ Agendamento de {appt['scheduled_at']} cancelado com sucesso!"
                else:
                    reply_text = f"Não consegui cancelar: {result['error']}"

        # ── reply ─────────────────────────────────────────────────────────────
        else:
            reply_text = ai_response.get("message", "Desculpe, não entendi. Pode repetir?")

        # ── Segunda chamada à IA para slots específicos ───────────────────────
        if reply_text.startswith("__SLOT_OK__"):
            parts      = reply_text.split("__")
            slot_time  = parts[2]
            slot_date  = parts[3]
            slot_msg   = (
                f"[SISTEMA] O horario {slot_time} do dia {slot_date} esta DISPONIVEL. "
                f"Confirme esse horario ao cliente e siga para o proximo passo."
            )
            history.append({"role": "user", "content": message_text})
            ai2        = chat_with_ai(history, slot_msg, customer_context, tenant_config, services)
            reply_text = ai2.get("message", f"Perfeito! O horário das {slot_time} está disponível 😊")

        elif reply_text.startswith("__SLOT_OCUPADO__"):
            parts      = reply_text.split("__")
            slot_time  = parts[2]
            slot_date  = parts[3]
            sugestoes  = parts[4] if len(parts) > 4 else "nenhum"
            slot_msg   = (
                f"[SISTEMA] O horario {slot_time} do dia {slot_date} esta OCUPADO. "
                f"Horarios proximos disponiveis: {sugestoes}. "
                f"Informe o cliente e oferta esses horarios."
            )
            history.append({"role": "user", "content": message_text})
            ai2        = chat_with_ai(history, slot_msg, customer_context, tenant_config, services)
            reply_text = ai2.get("message", f"Ops! O horário das {slot_time} está ocupado. Temos {sugestoes} disponíveis. Qual prefere?")

        # Atualiza histórico (limitado a 20 mensagens)
        history.append({"role": "user",      "content": message_text})
        history.append({"role": "assistant", "content": reply_text})
        conversation.messages = json.dumps(history[-20:])
        db.commit()

        await send_whatsapp_message(customer_phone, reply_text, tenant)
        return {"status": "ok"}

    finally:
        db.close()