"""
scheduler.py — Gerenciamento de slots e agendamentos.

Otimizações v2:
- get_available_slots: 1 query por dia (antes eram N queries, uma por slot)
- FERIADOS calculado dinamicamente via função importável (sem lista hardcoded)
- Feriados de 2026/2027+ calculados automaticamente via algoritmo da Páscoa
- get_blocked_slots: carregado junto com agendamentos para evitar queries extras
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models import Appointment, Pet, Tenant, Service, BlockedSlot
import pytz

BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


# ── Feriados dinâmicos ────────────────────────────────────────────────────────

def _calcular_pascoa(year: int) -> datetime:
    """Algoritmo de Butcher para calcular a Páscoa."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day)


def _build_feriados(anos: list) -> set:
    """
    Monta o conjunto de feriados nacionais para os anos solicitados.
    Inclui feriados fixos e móveis (Carnaval, Páscoa, Corpus Christi).
    """
    feriados = set()
    for year in anos:
        pascoa         = _calcular_pascoa(year)
        carnaval_seg   = (pascoa - timedelta(days=48)).strftime("%Y-%m-%d")
        carnaval_ter   = (pascoa - timedelta(days=47)).strftime("%Y-%m-%d")
        sexta_santa    = (pascoa - timedelta(days=2)).strftime("%Y-%m-%d")
        pascoa_str     = pascoa.strftime("%Y-%m-%d")
        corpus_christi = (pascoa + timedelta(days=60)).strftime("%Y-%m-%d")

        feriados.update([
            f"{year}-01-01",  # Confraternização Universal
            f"{year}-04-21",  # Tiradentes
            f"{year}-05-01",  # Dia do Trabalho
            f"{year}-09-07",  # Independência do Brasil
            f"{year}-10-12",  # Nossa Sra. Aparecida
            f"{year}-11-02",  # Finados
            f"{year}-11-15",  # Proclamação da República
            f"{year}-12-25",  # Natal
            carnaval_seg,
            carnaval_ter,
            sexta_santa,
            pascoa_str,
            corpus_christi,
        ])
    return feriados


def _get_feriados_ativos() -> set:
    """Retorna feriados do ano atual e dos próximos 2 anos."""
    ano_atual = datetime.now().year
    return _build_feriados([ano_atual, ano_atual + 1, ano_atual + 2])


# Carregado uma vez ao iniciar — atualiza sozinho com o passar dos anos
FERIADOS = _get_feriados_ativos()


# ── Horários do tenant ────────────────────────────────────────────────────────

def _get_tenant_hours(db: Session, tenant_id: str) -> tuple:
    """
    Retorna (open_hour, open_min, close_hour, close_min, open_days) do tenant.
    Usa valores padrão se o tenant não for encontrado.
    """
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


# ── Verificação de horário de funcionamento ───────────────────────────────────

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
    weekday        = str(date.weekday())
    open_days_list = [d.strip() for d in open_days.split(',')]

    if weekday not in open_days_list:
        return {"open": False, "reason": "FECHADO"}

    return {"open": True, "reason": ""}


# ── Slots disponíveis — otimizado ─────────────────────────────────────────────

def get_available_slots(
    db: Session,
    tenant_id: str,
    date_str: str,
    service_name: str = ""
) -> list:
    """
    Retorna slots disponíveis para o dia.

    OTIMIZAÇÃO: faz apenas 2 queries no banco por chamada:
      1. Agendamentos confirmados do dia
      2. Slots bloqueados do dia
    Antes eram N queries (uma por slot de 30 min).
    """
    check = check_business_hours_for_tenant(db, tenant_id, date_str)
    if not check["open"]:
        return []

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    oh, om, ch, cm, _ = _get_tenant_hours(db, tenant_id)
    now = agora_brasilia()

    # ── Query 1: todos os agendamentos confirmados do dia ─────────────────────
    inicio_dia = date.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    fim_dia    = date.replace(hour=23, minute=59, second=59, microsecond=0)

    agendamentos_do_dia = db.query(Appointment.scheduled_at).filter(
        Appointment.tenant_id    == tenant_id,
        Appointment.scheduled_at >= inicio_dia,
        Appointment.scheduled_at <= fim_dia,
        Appointment.status       != "cancelled"
    ).all()

    # Set de horários ocupados (comparação em memória — muito mais rápido)
    ocupados = {a.scheduled_at.strftime("%H:%M") for a in agendamentos_do_dia}

    # ── Query 2: slots bloqueados manualmente pelo dono ───────────────────────
    bloqueios = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str
    ).all()

    # Dia inteiro bloqueado?
    if any(b.time is None for b in bloqueios):
        return []

    # Horários específicos bloqueados
    for b in bloqueios:
        if b.time:
            ocupados.add(b.time)

    # ── Gera slots disponíveis em memória ─────────────────────────────────────
    slots = []
    cur   = oh * 60 + om
    end   = ch * 60 + cm

    while cur < end:
        slot_hour = cur // 60
        slot_min  = cur % 60
        slot_time = date.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)

        # Pula slots no passado (com margem de 30 min)
        if date.date() == now.date() and slot_time <= now + timedelta(minutes=30):
            cur += 30
            continue

        time_str = slot_time.strftime("%H:%M")
        if time_str not in ocupados:
            slots.append({
                "datetime":  slot_time.isoformat(),
                "time":      time_str,
                "available": True,
            })

        cur += 30

    return slots


def format_slots_for_ai(slots: list, date_str: str = "") -> str:
    """Formata lista de slots para enviar à IA."""
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
    """Retorna o próximo dia útil do tenant."""
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


# ── Pet ───────────────────────────────────────────────────────────────────────

def get_or_create_pet(
    db: Session,
    tenant_id: str,
    customer_id: str,
    pet_name: str,
    breed: str = None,
    weight: float = None
) -> Pet:
    """
    Busca pet existente pelo nome (case-insensitive) ou cria novo.
    Atualiza raça/peso se estavam vazios.
    Salva apenas dados que o cliente forneceu — nunca inventa.
    """
    pet = db.query(Pet).filter(
        Pet.tenant_id   == tenant_id,
        Pet.customer_id == customer_id,
        Pet.name.ilike(pet_name)
    ).first()

    if not pet:
        pet = Pet(
            tenant_id=tenant_id,
            customer_id=customer_id,
            name=pet_name,
            breed=breed   or None,
            weight=weight or None,
        )
        db.add(pet)
        db.commit()
        db.refresh(pet)
    else:
        # Só atualiza campos que ainda não temos e o cliente forneceu agora
        updated = False
        if breed and not pet.breed:
            pet.breed  = breed
            updated    = True
        if weight and not pet.weight:
            pet.weight = weight
            updated    = True
        if updated:
            db.commit()

    return pet


# ── Criar agendamento ─────────────────────────────────────────────────────────

def create_appointment(
    db: Session,
    tenant_id: str,
    customer_id: str,
    service_id: str,
    datetime_str: str,
    pet_name: str      = None,
    pet_breed: str     = None,
    pet_weight: float  = None,
    pickup_time: str   = None,
    pickup_address: str = None,
    notes: str         = "",
) -> dict:
    """
    Cria um agendamento após validar todas as regras de negócio.

    Salva apenas o necessário:
    - pet_name/breed/weight: só quando o tipo de negócio usa (petshop, clínica etc)
    - pickup_time: só quando o negócio faz busca
    - pickup_address: só quando needs_address=True no tenant
    - notes: texto livre, salvo apenas se fornecido

    Retorna dict com success, appointment_id e scheduled_at formatado.
    """

    # ── Valida datetime ───────────────────────────────────────────────────────
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except (ValueError, TypeError):
        return {"success": False, "error": "Data inválida"}

    now = agora_brasilia()
    if scheduled_at <= now:
        return {"success": False, "error": "Horário já passou"}

    date_str = scheduled_at.strftime("%Y-%m-%d")

    # ── Valida feriado ────────────────────────────────────────────────────────
    if date_str in FERIADOS:
        return {"success": False, "error": "Feriado nacional — estabelecimento fechado"}

    # ── Valida dias e horário de funcionamento do tenant ─────────────────────
    oh, om, ch, cm, open_days = _get_tenant_hours(db, tenant_id)
    weekday        = str(scheduled_at.weekday())
    open_days_list = [d.strip() for d in open_days.split(',')]

    if weekday not in open_days_list:
        return {"success": False, "error": "Estabelecimento fechado nesse dia"}

    slot_min  = scheduled_at.hour * 60 + scheduled_at.minute
    open_min  = oh * 60 + om
    close_min = ch * 60 + cm

    if slot_min < open_min or slot_min >= close_min:
        return {"success": False, "error": "Fora do horário de atendimento"}

    # ── Verifica bloqueio manual do dono ──────────────────────────────────────
    bloqueio_dia = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str,
        BlockedSlot.time      == None  # dia inteiro bloqueado
    ).first()
    if bloqueio_dia:
        return {"success": False, "error": "Dia bloqueado pelo estabelecimento"}

    time_str = scheduled_at.strftime("%H:%M")
    bloqueio_hora = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str,
        BlockedSlot.time      == time_str
    ).first()
    if bloqueio_hora:
        return {"success": False, "error": "Horário bloqueado pelo estabelecimento"}

    # ── Verifica conflito de horário ──────────────────────────────────────────
    existing = db.query(Appointment).filter(
        Appointment.tenant_id    == tenant_id,
        Appointment.scheduled_at == scheduled_at,
        Appointment.status       != "cancelled"
    ).first()

    if existing:
        return {"success": False, "error": "Horário já ocupado"}

    # ── Cria pet se necessário ────────────────────────────────────────────────
    # Só cria registro de pet se o nome foi fornecido (petshop, clínica etc)
    # Para barbearia, salão etc, pet_name chega como None — não cria nada
    pet_id = None
    if pet_name and pet_name.strip():
        pet    = get_or_create_pet(db, tenant_id, customer_id, pet_name.strip(), pet_breed, pet_weight)
        pet_id = pet.id

    # ── Cria agendamento ──────────────────────────────────────────────────────
    # Só salva campos que têm valor — evita lixo no banco
    appointment = Appointment(
        tenant_id      = tenant_id,
        customer_id    = customer_id,
        service_id     = service_id,
        scheduled_at   = scheduled_at,
        status         = "confirmed",
        payment_status = "pending",
        # Pet (None para negócios que não usam)
        pet_id         = pet_id,
        pet_name       = pet_name.strip()  if pet_name   else None,
        pet_breed      = pet_breed.strip() if pet_breed  else None,
        pet_weight     = pet_weight        if pet_weight else None,
        # Busca (None para negócios que não fazem busca)
        pickup_time    = pickup_time.strip()   if pickup_time   else None,
        pickup_address = pickup_address.strip() if pickup_address else None,
        # Notas (só salva se fornecido)
        notes          = notes.strip() if notes else None,
    )

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    # LGPD: nunca loga endereço em texto plano
    print(
        f"[Agendamento] criado | tenant={tenant_id[:8]} "
        f"| endereço: {'sim' if pickup_address else 'não'}"
    )

    return {
        "success":        True,
        "appointment_id": appointment.id,
        "scheduled_at":   scheduled_at.strftime("%d/%m/%Y às %H:%M"),
    }


# ── Cancelar agendamento ──────────────────────────────────────────────────────

def cancel_appointment(db: Session, appointment_id: str, tenant_id: str) -> dict:
    appointment = db.query(Appointment).filter(
        Appointment.id        == appointment_id,
        Appointment.tenant_id == tenant_id
    ).first()

    if not appointment:
        return {"success": False, "error": "Agendamento não encontrado"}
    if appointment.status == "cancelled":
        return {"success": False, "error": "Já cancelado"}

    appointment.status = "cancelled"
    db.commit()
    return {"success": True, "message": "Agendamento cancelado com sucesso"}


# ── Listar agendamentos do cliente ────────────────────────────────────────────

def get_customer_appointments(db: Session, tenant_id: str, customer_id: str) -> list:
    """
    Retorna agendamentos futuros do cliente.
    Carrega serviço em batch para evitar N queries.
    """
    now = agora_brasilia()

    appointments = db.query(Appointment).filter(
        Appointment.tenant_id   == tenant_id,
        Appointment.customer_id == customer_id,
        Appointment.scheduled_at >= now,
        Appointment.status       != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    if not appointments:
        return []

    # Carrega nomes dos serviços em 1 query
    service_ids = list({a.service_id for a in appointments})
    services    = db.query(Service).filter(
        Service.id.in_(service_ids),
        Service.tenant_id == tenant_id
    ).all()
    smap = {s.id: s.name for s in services}

    return [
        {
            "id":             a.id,
            "scheduled_at":   a.scheduled_at.strftime("%d/%m/%Y às %H:%M"),
            "status":         a.status,
            "service_id":     a.service_id,
            "service_name":   smap.get(a.service_id, "Serviço"),
            "pet_name":       a.pet_name,
            "pet_breed":      a.pet_breed,
            "pet_weight":     a.pet_weight,
            "pickup_time":    a.pickup_time,
            "pickup_address": a.pickup_address,
        }
        for a in appointments
    ]