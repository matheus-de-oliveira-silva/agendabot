from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models import Appointment, Pet, Tenant, Service
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


def _get_tenant_hours(db: Session, tenant_id: str) -> tuple:
    """Retorna (open_hour, open_min, close_hour, close_min, open_days) do tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return 9, 0, 18, 0, "0,1,2,3,4,5"
    open_time  = getattr(tenant, 'open_time',  '09:00') or '09:00'
    close_time = getattr(tenant, 'close_time', '18:00') or '18:00'
    open_days  = getattr(tenant, 'open_days',  '0,1,2,3,4,5') or '0,1,2,3,4,5'
    try:
        oh, om = map(int, open_time.split(':'))
        ch, cm = map(int, close_time.split(':'))
    except Exception:
        oh, om, ch, cm = 9, 0, 18, 0
    return oh, om, ch, cm, open_days


def check_business_hours(date_str: str) -> dict:
    """Verificação legada sem tenant — mantida por compatibilidade."""
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


def check_business_hours_for_tenant(db: Session, tenant_id: str, date_str: str) -> dict:
    """Verifica horário de funcionamento usando configuração real do tenant."""
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"open": False, "reason": "INVALIDA"}

    now = agora_brasilia()
    if date.date() < now.date():
        return {"open": False, "reason": "PASSADO"}
    if date_str in FERIADOS:
        return {"open": False, "reason": "FERIADO"}

    _, _, _, _, open_days = _get_tenant_hours(db, tenant_id)
    weekday = str(date.weekday())
    open_days_list = [d.strip() for d in open_days.split(',')]
    if weekday not in open_days_list:
        return {"open": False, "reason": "FECHADO"}

    return {"open": True, "reason": ""}


def get_available_slots(db: Session, tenant_id: str, date_str: str, service_name: str = "") -> list:
    check = check_business_hours_for_tenant(db, tenant_id, date_str)
    if not check["open"]:
        return []

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    oh, om, ch, cm, _ = _get_tenant_hours(db, tenant_id)
    now = agora_brasilia()
    slots = []

    cur = oh * 60 + om
    end = ch * 60 + cm

    while cur < end:
        slot_hour = cur // 60
        slot_min  = cur % 60
        slot_time = date.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)

        if date.date() == now.date() and slot_time <= now + timedelta(minutes=30):
            cur += 30
            continue

        existing = db.query(Appointment).filter(
            Appointment.tenant_id == tenant_id,
            Appointment.scheduled_at == slot_time,
            Appointment.status != "cancelled"
        ).first()

        if not existing:
            slots.append({
                "datetime":  slot_time.isoformat(),
                "time":      slot_time.strftime("%H:%M"),
                "available": True
            })

        cur += 30

    return slots


def format_slots_for_ai(slots: list, date_str: str = "") -> str:
    now = agora_brasilia()

    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date_str in FERIADOS:
                return "🎉 Nesse dia é feriado!\n\nPosso verificar outro dia? 😊"
            if date.date() < now.date():
                return "Essa data já passou! Vamos escolher uma data futura? 😊"
        except ValueError:
            pass

    if not slots:
        return "😕 Não há horários disponíveis para esse dia.\n\nPosso verificar outro dia? 😊"

    header = "📅 Horários disponíveis:\n\n"
    lista  = "\n".join([f"🕐 {s['time']}" for s in slots])
    footer = "\n\nQual horário prefere? 😊"
    return header + lista + footer


def get_next_business_day(db: Session = None, tenant_id: str = None) -> str:
    day = agora_brasilia() + timedelta(days=1)

    if db and tenant_id:
        _, _, _, _, open_days = _get_tenant_hours(db, tenant_id)
        open_days_list = [d.strip() for d in open_days.split(',')]
        while str(day.weekday()) not in open_days_list or day.strftime("%Y-%m-%d") in FERIADOS:
            day += timedelta(days=1)
    else:
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


def create_appointment(
    db: Session,
    tenant_id: str,
    customer_id: str,
    service_id: str,
    datetime_str: str,
    pet_name: str = None,
    pet_breed: str = None,
    pet_weight: float = None,
    pickup_time: str = None,
    pickup_address: str = None,   # ← NOVO: endereço de busca/entrega (Etapa 5)
    notes: str = "",
) -> dict:
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except ValueError:
        return {"success": False, "error": "Data inválida"}

    now = agora_brasilia()
    if scheduled_at <= now:
        return {"success": False, "error": "Horário já passou"}

    date_str = scheduled_at.strftime("%Y-%m-%d")
    if date_str in FERIADOS:
        return {"success": False, "error": "Feriado"}

    oh, om, ch, cm, open_days = _get_tenant_hours(db, tenant_id)
    weekday = str(scheduled_at.weekday())
    open_days_list = [d.strip() for d in open_days.split(',')]

    if weekday not in open_days_list:
        return {"success": False, "error": "Estabelecimento fechado nesse dia"}

    slot_min  = scheduled_at.hour * 60 + scheduled_at.minute
    open_min  = oh * 60 + om
    close_min = ch * 60 + cm

    if slot_min < open_min or slot_min >= close_min:
        return {"success": False, "error": "Fora do horário de atendimento"}

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
        pickup_address=pickup_address,   # ← NOVO
        status="confirmed",
        payment_status="pending",
        notes=notes
    )

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    # LGPD: nunca loga o endereço em texto plano
    print(f"[Agendamento] tenant={tenant_id[:8]} | endereço: {'sim' if pickup_address else 'não'}")

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
            "id":             a.id,
            "scheduled_at":   a.scheduled_at.strftime("%d/%m/%Y às %H:%M"),
            "status":         a.status,
            "service_id":     a.service_id,
            "pet_name":       a.pet_name,
            "pet_breed":      a.pet_breed,
            "pet_weight":     a.pet_weight,
            "pickup_time":    a.pickup_time,
            "pickup_address": a.pickup_address,  # ← NOVO (usado pelo dashboard)
        }
        for a in appointments
    ]