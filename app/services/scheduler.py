from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models import Appointment
import pytz

BRASILIA = pytz.timezone("America/Sao_Paulo")

FERIADOS = [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03",
    "2026-04-21", "2026-05-01", "2026-06-04", "2026-09-07",
    "2026-10-12", "2026-11-02", "2026-11-15", "2026-12-25",
    # 2027
    "2027-01-01", "2027-04-02", "2027-04-21", "2027-05-01",
    "2027-09-07", "2027-10-12", "2027-11-02", "2027-11-15", "2027-12-25",
]

def agora_brasilia() -> datetime:
    """Retorna o datetime atual no fuso de Brasília (sem tzinfo para comparações simples)."""
    return datetime.now(BRASILIA).replace(tzinfo=None)


def check_business_hours(date_str: str) -> dict:
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"open": False, "reason": "INVALIDA"}

    now = agora_brasilia()

    if date.weekday() == 6:
        return {"open": False, "reason": "DOMINGO"}

    if date_str in FERIADOS:
        return {"open": False, "reason": "FERIADO"}

    if date.date() < now.date():
        return {"open": False, "reason": "PASSADO"}

    return {"open": True, "reason": ""}


def get_available_slots(db: Session, tenant_id: str, date_str: str, service_name: str) -> list:
    check = check_business_hours(date_str)
    if not check["open"]:
        return []

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    slots = []
    now = agora_brasilia()

    for hour in range(9, 18):
        slot_time = date.replace(hour=hour, minute=0, second=0, microsecond=0)

        # Ignora horários que já passaram (considera margem de 30 min)
        if date.date() == now.date() and slot_time <= now + timedelta(minutes=30):
            continue

        existing = db.query(Appointment).filter(
            Appointment.tenant_id == tenant_id,
            Appointment.scheduled_at == slot_time,
            Appointment.status != "cancelled"
        ).first()

        if not existing:
            slots.append({
                "datetime": slot_time.isoformat(),
                "time": slot_time.strftime("%H:%M"),
                "available": True
            })

    return slots


def format_slots_for_ai(slots: list, date_str: str = "") -> str:
    now = agora_brasilia()

    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")

            if date.weekday() == 6:
                return (
                    "😔 Domingo estamos fechados!\n\n"
                    "Funcionamos de segunda a sábado das 9h às 18h.\n"
                    "Posso verificar horários para amanhã? 😊"
                )

            if date_str in FERIADOS:
                return (
                    "🎉 Nesse dia é feriado e vamos estar de folga!\n\n"
                    "Funcionamos de segunda a sábado das 9h às 18h.\n"
                    "Posso verificar outro dia para você? 😊"
                )

            if date.date() < now.date():
                return "Essa data já passou! Vamos escolher uma data futura? 😊"

        except ValueError:
            pass

    if not slots:
        return (
            "😕 Não há horários disponíveis para esse dia.\n\n"
            "Posso verificar outro dia? Funcionamos de segunda a sábado das 9h às 18h! 🐾"
        )

    header = "📅 Horários disponíveis:\n\n"
    lista = "\n".join([f"🕐 {s['time']}" for s in slots])
    footer = "\n\nQual horário prefere? 😊"

    return header + lista + footer


def get_next_business_day() -> str:
    day = agora_brasilia() + timedelta(days=1)
    while day.weekday() == 6 or day.strftime("%Y-%m-%d") in FERIADOS:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def create_appointment(db: Session, tenant_id: str, customer_id: str,
                       service_id: str, datetime_str: str, notes: str = "") -> dict:
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except ValueError:
        return {"success": False, "error": "Data inválida"}

    now = agora_brasilia()

    # Não permite agendar no passado
    if scheduled_at <= now:
        return {"success": False, "error": "Horário já passou"}

    # Não permite agendar fora do horário comercial
    if scheduled_at.hour < 9 or scheduled_at.hour >= 18:
        return {"success": False, "error": "Fora do horário de atendimento"}

    # Não permite domingo
    if scheduled_at.weekday() == 6:
        return {"success": False, "error": "Não abrimos aos domingos"}

    # Não permite feriado
    date_str = scheduled_at.strftime("%Y-%m-%d")
    if date_str in FERIADOS:
        return {"success": False, "error": "Feriado"}

    # Verifica conflito de horário
    existing = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.scheduled_at == scheduled_at,
        Appointment.status != "cancelled"
    ).first()

    if existing:
        return {"success": False, "error": "Horário já ocupado"}

    appointment = Appointment(
        tenant_id=tenant_id,
        customer_id=customer_id,
        service_id=service_id,
        scheduled_at=scheduled_at,
        status="confirmed",
        notes=notes
    )

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    return {
        "success": True,
        "appointment_id": appointment.id,
        "scheduled_at": scheduled_at.strftime("%d/%m/%Y às %H:%M")
    }


def cancel_appointment(db: Session, appointment_id: str, tenant_id: str) -> dict:
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant_id
    ).first()

    if not appointment:
        return {"success": False, "error": "Agendamento não encontrado"}

    if appointment.status == "cancelled":
        return {"success": False, "error": "Já cancelado"}

    appointment.status = "cancelled"
    db.commit()

    return {"success": True, "message": "Agendamento cancelado com sucesso"}


def get_customer_appointments(db: Session, tenant_id: str, customer_id: str) -> list:
    """Retorna agendamentos futuros do cliente."""
    now = agora_brasilia()

    appointments = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.customer_id == customer_id,
        Appointment.scheduled_at >= now,
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    return [
        {
            "id": a.id,
            "scheduled_at": a.scheduled_at.strftime("%d/%m/%Y às %H:%M"),
            "status": a.status,
            "service_id": a.service_id
        }
        for a in appointments
    ]
