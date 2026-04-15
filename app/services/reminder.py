"""
reminder.py — Lembretes automáticos de agendamentos.

Envia lembretes por WhatsApp (Evolution API) ou Telegram,
sempre filtrado por tenant para garantir isolamento total.

Regra de plano:
  - basico  → lembretes desativados
  - pro     → lembretes ativos
  - agencia → lembretes ativos
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Appointment, Customer, Tenant, Service
import httpx
import os
import pytz

BRASILIA          = pytz.timezone("America/Sao_Paulo")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


async def _send_telegram(chat_id: str, message: str):
    if not TELEGRAM_TOKEN:
        print(f"[Lembrete] TELEGRAM_TOKEN não configurado — pulando envio para {chat_id}")
        return
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=10
            )
            if resp.status_code != 200:
                print(f"[Lembrete] Telegram erro {resp.status_code} para {chat_id}: {resp.text[:100]}")
        except Exception as e:
            print(f"[Lembrete] Telegram exceção para {chat_id}: {e}")


async def _send_whatsapp(phone: str, message: str, instance: str):
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        print(f"[Lembrete] Evolution API não configurada — pulando envio para {phone}")
        return
    url     = f"{EVOLUTION_API_URL}/message/sendText/{instance}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"number": phone, "text": message},
                headers=headers,
                timeout=10
            )
            if resp.status_code not in (200, 201):
                print(f"[Lembrete] WhatsApp erro {resp.status_code} para {phone}: {resp.text[:100]}")
        except Exception as e:
            print(f"[Lembrete] WhatsApp exceção para {phone}: {e}")


def _build_reminder_message(appointment: Appointment, customer: Customer,
                             service: Service, tenant: Tenant) -> str:
    subject  = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    biz_name = tenant.display_name or tenant.name
    horario  = appointment.scheduled_at.strftime("%d/%m às %H:%M")
    nome     = customer.name or "Cliente"
    svc_nome = service.name if service else "atendimento"

    pet_linha = ""
    if appointment.pet_name:
        pet_linha = f"🐾 {subject}: {appointment.pet_name}"
        if appointment.pet_breed:
            pet_linha += f" ({appointment.pet_breed})"
        pet_linha += "\n"

    pickup_linha = ""
    if appointment.pickup_time:
        pickup_linha = f"🏠 Busca: {appointment.pickup_time}\n"

    return (
        f"Oi, {nome}! 😊 Lembrando do seu agendamento amanhã:\n\n"
        f"📅 {horario}\n"
        f"✂️ {svc_nome}\n"
        f"{pet_linha}"
        f"{pickup_linha}\n"
        f"Qualquer dúvida é só chamar. Até amanhã! 🙏\n"
        f"— {biz_name}"
    )


async def send_daily_reminders():
    """
    Busca agendamentos de amanhã e envia lembretes.
    Itera por tenant para garantir isolamento total.
    Plano básico não recebe lembretes automáticos.
    """
    db = SessionLocal()
    try:
        agora         = agora_brasilia()
        amanha_inicio = (agora + timedelta(days=1)).replace(hour=0,  minute=0,  second=0,  microsecond=0)
        amanha_fim    = (agora + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)

        tenants        = db.query(Tenant).filter(Tenant.bot_active == True).all()
        total_enviados = 0

        for tenant in tenants:
            # ── Plano básico não tem lembretes automáticos ────────────────
            plano = getattr(tenant, 'plan', 'basico') or 'basico'
            if plano == 'basico':
                print(f"[Lembrete] '{tenant.display_name or tenant.name}': plano básico — lembretes desativados")
                continue

            # Agendamentos de amanhã SOMENTE deste tenant
            appointments = db.query(Appointment).filter(
                Appointment.tenant_id    == tenant.id,
                Appointment.scheduled_at >= amanha_inicio,
                Appointment.scheduled_at <= amanha_fim,
                Appointment.status       == "confirmed"
            ).all()

            if not appointments:
                continue

            print(f"[Lembrete] '{tenant.display_name or tenant.name}': {len(appointments)} agendamento(s)")

            wa_instance = getattr(tenant, 'phone_number_id', None) or \
                          os.getenv("EVOLUTION_INSTANCE", "agendabot")

            for appointment in appointments:
                customer = db.query(Customer).filter(
                    Customer.id        == appointment.customer_id,
                    Customer.tenant_id == tenant.id
                ).first()
                if not customer:
                    print(f"[Lembrete] Cliente não encontrado para appointment {appointment.id}")
                    continue

                service = db.query(Service).filter(
                    Service.id        == appointment.service_id,
                    Service.tenant_id == tenant.id
                ).first()

                mensagem = _build_reminder_message(appointment, customer, service, tenant)
                phone    = customer.phone or ""

                if phone.startswith("tg:"):
                    await _send_telegram(phone.replace("tg:", ""), mensagem)
                    canal = "Telegram"
                elif phone.isdigit() and len(phone) > 10:
                    await _send_whatsapp(phone, mensagem, wa_instance)
                    canal = "WhatsApp"
                elif phone.isdigit():
                    await _send_telegram(phone, mensagem)
                    canal = "Telegram"
                else:
                    print(f"[Lembrete] Canal desconhecido para phone='{phone}' — pulando")
                    continue

                print(f"[Lembrete] ✅ {canal} → {customer.name or phone} ({tenant.display_name or tenant.name})")
                total_enviados += 1

        print(f"[Lembrete] Concluído. {total_enviados} lembrete(s) enviado(s) em {len(tenants)} tenant(s).")

    except Exception as e:
        print(f"[Lembrete] ❌ Erro geral: {e}")
    finally:
        db.close()