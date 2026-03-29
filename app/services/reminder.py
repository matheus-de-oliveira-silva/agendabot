from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Appointment, Customer
import httpx
import os
import asyncio

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


async def send_reminder(chat_id: str, message: str):
    """Envia lembrete via Telegram."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": message}
        )


async def send_daily_reminders():
    """
    Busca agendamentos de amanhã e envia lembretes.
    Deve ser chamado uma vez por dia.
    """
    db = SessionLocal()

    try:
        amanha = datetime.now() + timedelta(days=1)
        inicio = amanha.replace(hour=0, minute=0, second=0, microsecond=0)
        fim = amanha.replace(hour=23, minute=59, second=59, microsecond=0)

        # Busca agendamentos de amanhã confirmados
        appointments = db.query(Appointment).filter(
            Appointment.scheduled_at >= inicio,
            Appointment.scheduled_at <= fim,
            Appointment.status == "confirmed"
        ).all()

        print(f"[Lembretes] Encontrados {len(appointments)} agendamentos para amanhã")

        for appointment in appointments:
            # Busca o cliente
            customer = db.query(Customer).filter(
                Customer.id == appointment.customer_id
            ).first()

            if not customer:
                continue

            # Monta a mensagem
            horario = appointment.scheduled_at.strftime("%d/%m/%Y às %H:%M")
            nome = customer.name or "Cliente"

            mensagem = (
                f"🐾 Olá, {nome}! Lembrando do seu agendamento amanhã:\n\n"
                f"📅 Data: {horario}\n\n"
                f"Até lá! Se precisar cancelar ou reagendar, é só me chamar. 😊"
            )

            # Envia o lembrete
            await send_reminder(customer.phone, mensagem)
            print(f"[Lembretes] Lembrete enviado para {customer.phone}")

    finally:
        db.close()
        