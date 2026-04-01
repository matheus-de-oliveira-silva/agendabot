from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models import Appointment, Pet
import pytz

BRASILIA = pytz.timezone("America/Sao_Paulo")

FERIADOS = [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03",
    "2026-04-21", "2026-05-01", "2026-06-04", "2026-09-07",
    "2026-10-12", "2026-11-02", "2026-11-15", "2026-12-25",
    "2027-01-01", "2027-04-02", "2027-04-21", "2027-05-01",
    "2027-09-07", "2027-10-12", "2027-11-02", "2027-11-15", "2027-12-25",
]

def agora_brasilia() -> datetime:
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
                return "😔 Domingo estamos fechados!\n\nFuncionamos de segunda a sábado das 9h às 18h.\nPosso verificar horários para amanhã? 😊"
            if date_str in FERIADOS:
                return "🎉 Nesse dia é feriado e vamos estar de folga!\n\nFuncionamos de segunda a sábado das 9h às 18h.\nPosso verificar outro dia para você? 😊"
            if date.date() < now.date():
                return "Essa data já passou! Vamos escolher uma data futura? 😊"
        except ValueError:
            pass

    if not slots:
        return "😕 Não há horários disponíveis para esse dia.\n\nPosso verificar outro dia? Funcionamos de segunda a sábado das 9h às 18h! 🐾"

    header = "📅 Horários disponíveis:\n\n"
    lista = "\n".join([f"🕐 {s['time']}" for s in slots])
    footer = "\n\nQual horário prefere? 😊"

    return header + lista + footer


def get_next_business_day() -> str:
    day = agora_brasilia() + timedelta(days=1)
    while day.weekday() == 6 or day.strftime("%Y-%m-%d") in FERIADOS:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def get_or_create_pet(db: Session, tenant_id: str, customer_id: str,
                       pet_name: str, breed: str = None, weight: float = None) -> Pet:
    pet = db.query(Pet).filter(
        Pet.tenant_id == tenant_id,
        Pet.customer_id == customer_id,
        Pet.name.ilike(pet_name)
    ).first()

    if not pet:
        pet = Pet(
            tenant_id=tenant_id,
            customer_id=customer_id,
            name=pet_name,
            breed=breed,
            weight=weight
        )
        db.add(pet)
        db.commit()
        db.refresh(pet)
    else:
        updated = False
        if breed and not pet.breed:
            pet.breed = breed
            updated = True
        if weight and not pet.weight:
            pet.weight = weight
            updated = True
        if updated:
            db.commit()

    return pet


def create_appointment(db: Session, tenant_id: str, customer_id: str,
                       service_id: str, datetime_str: str,
                       pet_name: str = None, pet_breed: str = None,
                       pet_weight: float = None, pickup_time: str = None,
                       notes: str = "") -> dict:
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except ValueError:
        return {"success": False, "error": "Data inválida"}

    now = agora_brasilia()

    if scheduled_at <= now:
        return {"success": False, "error": "Horário já passou"}
    if scheduled_at.hour < 9 or scheduled_at.hour >= 18:
        return {"success": False, "error": "Fora do horário de atendimento"}
    if scheduled_at.weekday() == 6:
        return {"success": False, "error": "Não abrimos aos domingos"}

    date_str = scheduled_at.strftime("%Y-%m-%d")
    if date_str in FERIADOS:
        return {"success": False, "error": "Feriado"}

    existing = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.scheduled_at == scheduled_at,
        Appointment.status != "cancelled"
    ).first()

    if existing:
        return {"success": False, "error": "Horário já ocupado"}

    pet_id = None
    if pet_name:
        pet = get_or_create_pet(db, tenant_id, customer_id, pet_name, pet_breed, pet_weight)
        pet_id = pet.id

    appointment = Appointment(
        tenant_id=tenant_id,
        customer_id=customer_id,
        service_id=service_id,
        pet_id=pet_id,
        pet_name=pet_name,
        pet_breed=pet_breed,
        pet_weight=pet_weight,
        scheduled_at=scheduled_at,
        pickup_time=pickup_time,
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
            "service_id": a.service_id,
            "pet_name": a.pet_name,
            "pet_breed": a.pet_breed,
            "pet_weight": a.pet_weight,
            "pickup_time": a.pickup_time,
        }
        for a in appointments
    ]