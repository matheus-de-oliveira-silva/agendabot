from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models import Appointment

FERIADOS = [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03",
    "2026-04-21", "2026-05-01", "2026-06-04", "2026-09-07",
    "2026-10-12", "2026-11-02", "2026-11-15", "2026-12-25",
]

def check_business_hours(date_str: str) -> dict:
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"open": False, "message": "Data inválida."}

    if date.weekday() == 6:
        return {"open": False, "message": "DOMINGO"}

    if date_str in FERIADOS:
        return {"open": False, "message": "FERIADO"}

    if date.date() < datetime.now().date():
        return {"open": False, "message": "PASSADO"}

    return {"open": True, "message": ""}


def get_available_slots(db: Session, tenant_id: str, date_str: str, service_name: str) -> list:
    check = check_business_hours(date_str)
    if not check["open"]:
        return []

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    slots = []
    now = datetime.now()

    for hour in range(9, 18):
        slot_time = date.replace(hour=hour, minute=0, second=0, microsecond=0)

        if date.date() == now.date() and slot_time <= now:
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
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")

            if date.weekday() == 6:
                return "Hoje é domingo e estamos fechados! 😊 De segunda a sábado funcionamos das 9h às 18h. Posso agendar para amanhã?"

            if date_str in FERIADOS:
                return "Nesse dia é feriado e estaremos fechados! 🎉 Funcionamos de segunda a sábado das 9h às 18h. Posso agendar para outro dia?"

            if date.date() < datetime.now().date():
                return "Essa data já passou! Vamos escolher uma data futura? 😊"

        except ValueError:
            pass

    if not slots:
        return (
            "Não há horários disponíveis para esse dia. "
            "Posso verificar outro dia? "
            "Funcionamos de segunda a sábado das 9h às 18h! 🐾"
        )

    times = [s["time"] for s in slots]

    if len(times) == 1:
        return f"Temos apenas o horário das {times[0]} disponível. Deseja confirmar?"

    times_str = ", ".join(times[:-1]) + f" ou {times[-1]}"
    return f"Temos os seguintes horários disponíveis: {times_str}. Qual prefere? 😊"


def get_next_business_day() -> str:
    day = datetime.now() + timedelta(days=1)
    while day.weekday() == 6 or day.strftime("%Y-%m-%d") in FERIADOS:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def create_appointment(db: Session, tenant_id: str, customer_id: str,
                        service_id: str, datetime_str: str, notes: str = "") -> dict:
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except ValueError:
        return {"success": False, "error": "Data inválida"}

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