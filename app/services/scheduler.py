"""
scheduler.py — Tarefas agendadas do BotGen.

Jobs diários (18h):
  - Lembretes de agendamento (planos Pro/Agência)

Jobs semanais (segunda 8h):
  - Relatório semanal por email para cada tenant Pro/Agência

Jobs diários (9h):
  - Aviso de vencimento para tenants com assinatura vencendo em 3 dias
  (Kiwify não tem webhook de pré-vencimento, então verificamos pela data)

Otimizações:
  - get_available_slots: 2 queries por dia (antes eram N queries)
  - Relatório: dados agregados — sem dados pessoais individuais (LGPD)
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Appointment, Pet, Tenant, Service, BlockedSlot, Customer
import pytz


def _safe_commit(db) -> bool:
    """Commit seguro com rollback automático em caso de erro."""
    try:
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"[DB] ❌ Erro no commit: {e}")
        return False



BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


# ── Feriados dinâmicos ────────────────────────────────────────────────────────

def _calcular_pascoa(year: int) -> datetime:
    a = year % 19; b = year // 100; c = year % 100
    d = b // 4; e = b % 4; f = (b + 8) // 25
    g = (b - f + 1) // 3; h = (19*a + b - d - g + 15) % 30
    i = c // 4; k = c % 4; l = (32 + 2*e + 2*i - h - k) % 7
    m = (a + 11*h + 22*l) // 451
    month = (h + l - 7*m + 114) // 31
    day   = ((h + l - 7*m + 114) % 31) + 1
    return datetime(year, month, day)


def _build_feriados(anos: list) -> set:
    feriados = set()
    for year in anos:
        p  = _calcular_pascoa(year)
        cs = (p - timedelta(days=48)).strftime("%Y-%m-%d")
        ct = (p - timedelta(days=47)).strftime("%Y-%m-%d")
        ss = (p - timedelta(days=2)).strftime("%Y-%m-%d")
        ps = p.strftime("%Y-%m-%d")
        cc = (p + timedelta(days=60)).strftime("%Y-%m-%d")
        feriados.update([
            f"{year}-01-01", f"{year}-04-21", f"{year}-05-01",
            f"{year}-09-07", f"{year}-10-12", f"{year}-11-02",
            f"{year}-11-15", f"{year}-12-25",
            cs, ct, ss, ps, cc,
        ])
    return feriados


def _get_feriados_ativos() -> set:
    ano = datetime.now().year
    return _build_feriados([ano, ano + 1, ano + 2])


FERIADOS = _get_feriados_ativos()


# ── Horários do tenant ────────────────────────────────────────────────────────

def _get_tenant_hours(db: Session, tenant_id: str) -> tuple:
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


# ── Verificações de horário ───────────────────────────────────────────────────

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


def check_business_hours_for_tenant(db: Session, tenant_id: str, date_str: str) -> dict:
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
    if str(date.weekday()) not in [d.strip() for d in open_days.split(',')]:
        return {"open": False, "reason": "FECHADO"}
    return {"open": True, "reason": ""}


# ── Slots disponíveis (otimizado — 2 queries por dia) ────────────────────────

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

    # Query 1: agendamentos do dia
    inicio_dia = date.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    fim_dia    = date.replace(hour=23, minute=59, second=59, microsecond=0)
    agendamentos = db.query(Appointment.scheduled_at).filter(
        Appointment.tenant_id    == tenant_id,
        Appointment.scheduled_at >= inicio_dia,
        Appointment.scheduled_at <= fim_dia,
        Appointment.status       != "cancelled"
    ).all()
    ocupados = {a.scheduled_at.strftime("%H:%M") for a in agendamentos}

    # Query 2: bloqueios manuais
    bloqueios = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str
    ).all()
    if any(b.time is None for b in bloqueios):
        return []
    for b in bloqueios:
        if b.time:
            ocupados.add(b.time)

    slots = []
    cur   = oh * 60 + om
    end   = ch * 60 + cm
    while cur < end:
        slot_hour = cur // 60
        slot_min  = cur % 60
        slot_time = date.replace(hour=slot_hour, minute=slot_min, second=0, microsecond=0)
        # Comparação segura sem timezone (naive vs naive)
        now_naive = now.replace(tzinfo=None)
        if date.date() == now_naive.date() and slot_time <= now_naive + timedelta(minutes=30):
            cur += 30; continue
        time_str = slot_time.strftime("%H:%M")
        if time_str not in ocupados:
            slots.append({"datetime": slot_time.isoformat(), "time": time_str, "available": True})
        cur += 30
    return slots


def format_slots_for_ai(slots: list, date_str: str = "") -> str:
    now = agora_brasilia()
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date_str in FERIADOS:
                return "🎉 Nesse dia é feriado! Posso verificar outro dia? 😊"
            if date.date() < now.date():
                return "Essa data já passou! Vamos escolher uma data futura? 😊"
        except ValueError:
            pass
    if not slots:
        return "😕 Não há horários disponíveis para esse dia.\n\nPosso verificar outro dia? 😊"
    return "📅 Horários disponíveis:\n\n" + "\n".join(f"🕐 {s['time']}" for s in slots) + "\n\nQual horário prefere? 😊"


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


# ── Pet ───────────────────────────────────────────────────────────────────────

def get_or_create_pet(db: Session, tenant_id: str, customer_id: str, pet_name: str, breed: str = None, weight: float = None) -> Pet:
    pet = db.query(Pet).filter(
        Pet.tenant_id == tenant_id, Pet.customer_id == customer_id,
        Pet.name.ilike(pet_name)
    ).first()
    if not pet:
        pet = Pet(tenant_id=tenant_id, customer_id=customer_id,
                  name=pet_name, breed=breed or None, weight=weight or None)
        db.add(pet); db.commit(); db.refresh(pet)
    else:
        updated = False
        if breed and not pet.breed:   pet.breed = breed;   updated = True
        if weight and not pet.weight: pet.weight = weight; updated = True
        if updated: db.commit()
    return pet


# ── Criar agendamento ─────────────────────────────────────────────────────────

def create_appointment(
    db: Session, tenant_id: str, customer_id: str, service_id: str,
    datetime_str: str, pet_name: str = None, pet_breed: str = None,
    pet_weight: float = None, pickup_time: str = None, pickup_address: str = None,
    notes: str = "",
) -> dict:
    try:
        scheduled_at = datetime.fromisoformat(datetime_str)
    except (ValueError, TypeError):
        return {"success": False, "error": "Data inválida"}

    now = agora_brasilia()
    now_naive = now.replace(tzinfo=None)
    if scheduled_at <= now_naive:
        return {"success": False, "error": "Horário já passou"}

    date_str = scheduled_at.strftime("%Y-%m-%d")
    if date_str in FERIADOS:
        return {"success": False, "error": "Feriado"}

    oh, om, ch, cm, open_days = _get_tenant_hours(db, tenant_id)
    if str(scheduled_at.weekday()) not in [d.strip() for d in open_days.split(',')]:
        return {"success": False, "error": "Estabelecimento fechado nesse dia"}

    slot_min = scheduled_at.hour * 60 + scheduled_at.minute
    if slot_min < oh * 60 + om or slot_min >= ch * 60 + cm:
        return {"success": False, "error": "Fora do horário de atendimento"}

    # Verifica bloqueio manual
    bloqueio = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str,
        BlockedSlot.time      == None
    ).first()
    if bloqueio:
        return {"success": False, "error": "Dia bloqueado"}

    time_str = scheduled_at.strftime("%H:%M")
    bloqueio_hora = db.query(BlockedSlot).filter(
        BlockedSlot.tenant_id == tenant_id,
        BlockedSlot.date      == date_str,
        BlockedSlot.time      == time_str
    ).first()
    if bloqueio_hora:
        return {"success": False, "error": "Horário bloqueado"}

    existing = db.query(Appointment).filter(
        Appointment.tenant_id    == tenant_id,
        Appointment.scheduled_at == scheduled_at,
        Appointment.status       != "cancelled"
    ).first()
    if existing:
        return {"success": False, "error": "Horário já ocupado"}

    pet_id = None
    if pet_name and pet_name.strip():
        pet    = get_or_create_pet(db, tenant_id, customer_id, pet_name.strip(), pet_breed, pet_weight)
        pet_id = pet.id

    appointment = Appointment(
        tenant_id=tenant_id, customer_id=customer_id, service_id=service_id,
        scheduled_at=scheduled_at, status="confirmed", payment_status="pending",
        pet_id=pet_id,
        pet_name=pet_name.strip()   if pet_name   else None,
        pet_breed=pet_breed.strip() if pet_breed  else None,
        pet_weight=pet_weight       if pet_weight else None,
        pickup_time=pickup_time.strip()    if pickup_time    else None,
        pickup_address=pickup_address.strip() if pickup_address else None,
        notes=notes.strip() if notes else None,
    )
    db.add(appointment); db.commit(); db.refresh(appointment)

    # LGPD: nunca loga endereço
    print(f"[Agendamento] criado | tenant={tenant_id[:8]} | endereço: {'sim' if pickup_address else 'não'}")
    return {"success": True, "appointment_id": appointment.id, "scheduled_at": scheduled_at.strftime("%d/%m/%Y às %H:%M")}


def cancel_appointment(db: Session, appointment_id: str, tenant_id: str) -> dict:
    a = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.tenant_id == tenant_id).first()
    if not a:
        return {"success": False, "error": "Agendamento não encontrado"}
    if a.status == "cancelled":
        return {"success": False, "error": "Já cancelado"}
    a.status = "cancelled"; db.commit()
    return {"success": True}


def get_customer_appointments(db: Session, tenant_id: str, customer_id: str) -> list:
    now = agora_brasilia()
    appointments = db.query(Appointment).filter(
        Appointment.tenant_id    == tenant_id,
        Appointment.customer_id  == customer_id,
        Appointment.scheduled_at >= now,
        Appointment.status       != "cancelled"
    ).order_by(Appointment.scheduled_at).all()
    if not appointments:
        return []
    service_ids = list({a.service_id for a in appointments})
    services    = db.query(Service).filter(Service.id.in_(service_ids), Service.tenant_id == tenant_id).all()
    smap        = {s.id: s.name for s in services}
    return [{
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
    } for a in appointments]


# ── Relatório semanal ─────────────────────────────────────────────────────────

async def send_weekly_reports():
    """
    Envia relatório semanal por email para tenants Pro e Agência.
    Dados agregados — sem dados pessoais individuais (LGPD).
    Roda toda segunda-feira às 8h.
    """
    from ..services.email_service import email_relatorio_semanal
    import os

    app_url = os.getenv("APP_URL", "https://web-production-c1b1c.up.railway.app")
    db      = SessionLocal()
    try:
        agora      = agora_brasilia()
        semana_ini = agora - timedelta(days=7)
        tenants    = db.query(Tenant).filter(
            Tenant.bot_active  == True,
            Tenant.plan_active == True,
            Tenant.plan.in_(["pro", "agencia"]),
        ).all()

        print(f"[Relatorio] Enviando para {len(tenants)} tenant(s)...")

        for tenant in tenants:
            if not tenant.billing_email:
                continue

            # Agendamentos da semana
            appts_semana = db.query(Appointment).filter(
                Appointment.tenant_id    == tenant.id,
                Appointment.scheduled_at >= semana_ini,
                Appointment.scheduled_at <= agora,
                Appointment.status       != "cancelled"
            ).all()

            # Agendamentos do mês
            mes_ini = agora.replace(day=1, hour=0, minute=0, second=0)
            total_mes = db.query(Appointment).filter(
                Appointment.tenant_id    == tenant.id,
                Appointment.scheduled_at >= mes_ini,
                Appointment.status       != "cancelled"
            ).count()

            # Clientes novos na semana
            novos = db.query(Customer).filter(
                Customer.tenant_id == tenant.id,
                Customer.created_at >= semana_ini,
            ).count() if hasattr(Customer, 'created_at') else 0

            # Horário mais popular
            from collections import Counter
            horarios   = Counter(a.scheduled_at.strftime("%H:%M") for a in appts_semana)
            horario_pop = horarios.most_common(1)[0][0] if horarios else "—"

            # Serviço mais popular
            service_ids  = [a.service_id for a in appts_semana]
            svc_counter  = Counter(service_ids)
            servico_pop  = "—"
            if svc_counter:
                top_svc_id = svc_counter.most_common(1)[0][0]
                svc_obj    = db.query(Service).filter(Service.id == top_svc_id).first()
                if svc_obj:
                    servico_pop = svc_obj.name

            # Taxa de confirmação (confirmados / total criados)
            total_criados = db.query(Appointment).filter(
                Appointment.tenant_id    == tenant.id,
                Appointment.scheduled_at >= semana_ini,
            ).count()
            taxa = len(appts_semana) / total_criados if total_criados > 0 else 1.0

            dashboard_url = f"{app_url}/dashboard?tid={tenant.id}"

            await email_relatorio_semanal(
                to=tenant.billing_email,
                nome=tenant.display_name or tenant.name or "",
                biz_name=tenant.display_name or tenant.name or "",
                stats={
                    "total_semana":          len(appts_semana),
                    "total_mes":             total_mes,
                    "horario_mais_popular":  horario_pop,
                    "servico_mais_popular":  servico_pop,
                    "novos_clientes":        novos,
                    "taxa_confirmacao":      taxa,
                },
                dashboard_url=dashboard_url,
            )

        print(f"[Relatorio] ✅ Concluído.")
    except Exception as e:
        print(f"[Relatorio] ❌ Erro: {e}")
    finally:
        db.close()


# ── Aviso de vencimento ───────────────────────────────────────────────────────

async def send_expiry_warnings():
    """
    Verifica tenants com campo 'next_billing_date' e envia aviso 3 dias antes.
    Roda diariamente às 9h.
    Nota: requer campo next_billing_date no modelo Tenant (migration v7).
    """
    from ..services.email_service import email_aviso_vencimento

    db  = SessionLocal()
    try:
        agora    = agora_brasilia()
        em_3_dias = (agora + timedelta(days=3)).date()

        tenants = db.query(Tenant).filter(Tenant.plan_active == True).all()
        avisos  = 0

        for tenant in tenants:
            if not tenant.billing_email:
                continue
            next_billing = getattr(tenant, 'next_billing_date', None)
            if not next_billing:
                continue
            if hasattr(next_billing, 'date'):
                next_billing = next_billing.date()
            if next_billing == em_3_dias:
                nome = tenant.display_name or tenant.name or ""
                await email_aviso_vencimento(
                    to=tenant.billing_email,
                    nome=nome,
                    plano=tenant.plan or "basico",
                    dias=3,
                )
                avisos += 1

        print(f"[Vencimento] {avisos} aviso(s) enviado(s).")
    except Exception as e:
        print(f"[Vencimento] ❌ Erro: {e}")
    finally:
        db.close()