from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant, BlockedSlot
from datetime import datetime, timedelta
from typing import Optional
import pytz, json, bcrypt, secrets, io, csv

router = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")

def agora_brasilia():
    return datetime.now(BRASILIA).replace(tzinfo=None)

STATUS_LABELS = {
    "confirmed":   ("Confirmado",      "#e8f5e9", "#2e7d32"),
    "in_progress": ("Em atendimento",  "#fff8e1", "#f57f17"),
    "ready":       ("Pronto p/ busca", "#e3f2fd", "#1565c0"),
    "delivered":   ("Entregue",        "#f3e5f5", "#6a1b9a"),
    "cancelled":   ("Cancelado",       "#ffebee", "#c62828"),
}

PAYMENT_LABELS = {
    "pending": ("💳 Pend.",  "#fff8e1", "#c67d00"),
    "paid":    ("✅ Pago",   "#e8f5e9", "#2e7d32"),
    "waived":  ("🎁 Isento", "#f3e5f5", "#6a1b9a"),
}

BUSINESS_NO_SUBJECT = {"barbearia", "salao", "estetica", "outro"}
DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


# ── Plan feature check ────────────────────────────────────────────────────────

def _check_plan_feature(tenant, feature: str) -> bool:
    """
    Verifica se o plano do tenant permite uma feature.
    basico  → sem CSV, sem lembretes, até 7 serviços
    pro     → tudo liberado, 1 tenant
    agencia → tudo liberado, até 3 tenants
    """
    plano       = getattr(tenant, 'plan', 'basico') or 'basico'
    plan_active = getattr(tenant, 'plan_active', True)

    if not plan_active:
        return False

    if feature == "csv":
        return plano in ("pro", "agencia")
    if feature == "lembretes":
        return plano in ("pro", "agencia")
    if feature == "servicos_ilimitados":
        return plano in ("pro", "agencia")
    return True


# ── Helpers de performance ────────────────────────────────────────────────────

def _load_customers_map(db: Session, tenant_id: str, customer_ids: list) -> dict:
    if not customer_ids:
        return {}
    rows = db.query(Customer).filter(
        Customer.tenant_id == tenant_id,
        Customer.id.in_(set(customer_ids))
    ).all()
    return {c.id: c for c in rows}


def _load_services_map(db: Session, tenant_id: str, service_ids: list) -> dict:
    if not service_ids:
        return {}
    rows = db.query(Service).filter(
        Service.tenant_id == tenant_id,
        Service.id.in_(set(service_ids))
    ).all()
    return {s.id: s for s in rows}


def _price_fmt(service) -> str:
    if service and service.price:
        return f"R$ {service.price/100:.2f}"
    return ""


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_tenant_from_request(request: Request, db: Session) -> Optional[object]:
    session_cookie = request.cookies.get("dash_session")
    if not session_cookie or ":" not in session_cookie:
        return None
    tid, token = session_cookie.split(":", 1)
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant or tenant.dashboard_token != token:
        return None
    return tenant


def login_page_html(tid: str, icon: str = "🐾", biz_name: str = "Painel", error: str = "") -> str:
    err = f'<div class="login-error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Entrar — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{width:360px;padding:36px;background:#1a1d27;border:1px solid #2d3148;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
.logo{{text-align:center;font-size:42px;margin-bottom:6px}}
.title{{text-align:center;font-size:20px;font-weight:800;color:#7c7de8;margin-bottom:4px}}
.sub{{text-align:center;font-size:13px;color:#9aa0b8;margin-bottom:24px}}
label{{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}}
input{{width:100%;padding:11px 14px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none}}
input:focus{{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}}
.btn{{width:100%;padding:12px;background:#5B5BD6;color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:16px}}
.btn:hover{{background:#7c7de8}}
.login-error{{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2);padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:14px}}
</style></head><body>
<div class="box">
<div class="logo">{icon}</div>
<div class="title">{biz_name}</div>
<div class="sub">Entre com sua senha para continuar</div>
{err}
<form method="POST" action="/dashboard/login">
<input type="hidden" name="tid" value="{tid}">
<div style="margin-bottom:14px"><label>Senha</label>
<input type="password" name="password" placeholder="••••••••" autofocus required></div>
<button type="submit" class="btn">Entrar</button>
</form>
</div></body></html>"""


@router.get("/dashboard/login", response_class=HTMLResponse)
def dash_login_page(tid: str = "", request: Request = None, db: Session = Depends(get_db)):
    icon, biz_name = "🐾", "Painel de Agendamentos"
    if tid:
        t = db.query(Tenant).filter(Tenant.id == tid).first()
        if t:
            icon     = getattr(t, 'tenant_icon', '🐾') or '🐾'
            biz_name = t.display_name or t.name
    return HTMLResponse(login_page_html(tid, icon, biz_name))


@router.post("/dashboard/login")
async def dash_do_login(request: Request, db: Session = Depends(get_db)):
    form     = await request.form()
    tid      = form.get("tid", "")
    password = form.get("password", "")
    tenant   = db.query(Tenant).filter(Tenant.id == tid).first()
    icon     = getattr(tenant, 'tenant_icon', '🐾') if tenant else '🐾'
    biz_name = (tenant.display_name or tenant.name) if tenant else "Painel"
    if not tenant or not tenant.dashboard_password:
        return HTMLResponse(login_page_html(tid, icon, biz_name, "Tenant não encontrado."))
    if not bcrypt.checkpw(password.encode(), tenant.dashboard_password.encode()):
        return HTMLResponse(login_page_html(tid, icon, biz_name, "Senha incorreta. Tente novamente."))
    if not tenant.dashboard_token:
        tenant.dashboard_token = secrets.token_urlsafe(32)
        db.commit()
    resp = RedirectResponse(f"/dashboard?tid={tid}", status_code=302)
    resp.set_cookie("dash_session", f"{tid}:{tenant.dashboard_token}", httponly=True, max_age=86400*30)
    return resp


@router.get("/dashboard/logout")
def dash_logout(tid: str = ""):
    resp = RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
    resp.delete_cookie("dash_session")
    return resp


# ── APIs ──────────────────────────────────────────────────────────────────────

@router.post("/api/appointment/{appointment_id}/status")
async def update_status(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    a = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant.id
    ).first()
    if not a:
        return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = data.get("status", a.status)
    db.commit()
    return {"success": True}


@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    a = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant.id
    ).first()
    if not a:
        return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = "cancelled"
    db.commit()
    return {"success": True}


@router.post("/api/appointment/{appointment_id}/payment")
async def update_payment(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    a = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant.id
    ).first()
    if not a:
        return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.payment_status = data.get("payment_status", a.payment_status)
    a.payment_method = data.get("payment_method", a.payment_method)
    if data.get("payment_amount"):
        try:
            a.payment_amount = int(float(data["payment_amount"]) * 100)
        except Exception:
            pass
    a.payment_pix_key = data.get("payment_pix_key", a.payment_pix_key)
    a.payment_notes   = data.get("payment_notes",   a.payment_notes)
    if a.payment_status == "paid" and not a.payment_paid_at:
        a.payment_paid_at = agora_brasilia()
    elif a.payment_status != "paid":
        a.payment_paid_at = None
    db.commit()
    return {"success": True}


@router.post("/api/appointment/create")
async def create_appt(request: Request, db: Session = Depends(get_db)):
    try:
        data   = await request.json()
        tenant = get_tenant_from_request(request, db)
        if not tenant:
            tid    = data.get("tenant_id", "")
            tenant = db.query(Tenant).filter(Tenant.id == tid).first() if tid else None
        if not tenant:
            return JSONResponse({"error": "Não autenticado"}, status_code=401)

        customer_name = data.get("customer_name", "").strip()
        service_id    = data.get("service_id", "")
        scheduled_str = data.get("scheduled_at", "")
        if not all([customer_name, service_id, scheduled_str]):
            return JSONResponse({"error": "Preencha todos os campos obrigatórios"}, status_code=400)

        scheduled_at = datetime.fromisoformat(scheduled_str)

        existing = db.query(Appointment).filter(
            Appointment.tenant_id   == tenant.id,
            Appointment.scheduled_at == scheduled_at,
            Appointment.status      != "cancelled"
        ).first()
        if existing:
            return JSONResponse({"error": "Horário já ocupado"}, status_code=409)

        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.name      == customer_name
        ).first()
        if not customer:
            customer = Customer(tenant_id=tenant.id, name=customer_name, phone="manual")
            db.add(customer)
            db.flush()

        service = db.query(Service).filter(
            Service.id        == service_id,
            Service.tenant_id == tenant.id
        ).first()
        if not service:
            return JSONResponse({"error": "Serviço não encontrado"}, status_code=400)

        pet_name   = (data.get("pet_name") or "").strip() or None
        pet_breed  = (data.get("pet_breed") or "").strip() or None
        pet_weight = None
        if data.get("pet_weight"):
            try: pet_weight = float(data["pet_weight"])
            except: pass

        appt = Appointment(
            tenant_id=tenant.id, customer_id=customer.id, service_id=service.id,
            pet_name=pet_name, pet_breed=pet_breed, pet_weight=pet_weight,
            scheduled_at=scheduled_at,
            pickup_time=data.get("pickup_time") or None,
            pickup_address=data.get("pickup_address") or None,
            status="confirmed", payment_status="pending",
        )
        db.add(appt)
        db.commit()
        return {"success": True, "id": str(appt.id)}
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/availability")
def check_avail(date: str, request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant and tid:
        tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        return {"busy": []}
    try:
        day   = datetime.strptime(date, "%Y-%m-%d")
        start = day.replace(hour=0,  minute=0,  second=0)
        end   = day.replace(hour=23, minute=59, second=59)
        appts = db.query(Appointment).filter(
            Appointment.tenant_id    == tenant.id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status       != "cancelled"
        ).all()
        busy    = [a.scheduled_at.strftime("%H:%M") for a in appts]
        blocked = db.query(BlockedSlot).filter(
            BlockedSlot.tenant_id == tenant.id,
            BlockedSlot.date      == date
        ).all()
        for b in blocked:
            if b.time:
                busy.append(b.time)
        return {"busy": busy, "day_blocked": any(b.time is None for b in blocked)}
    except Exception:
        return {"busy": []}


@router.get("/api/services")
def get_services(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return {"services": []}
    services = db.query(Service).filter(
        Service.tenant_id == tenant.id,
        Service.active    == True
    ).order_by(Service.name).all()
    return {"services": [
        {"id": s.id, "name": s.name, "price": s.price, "duration_min": s.duration_min, "color": s.color}
        for s in services
    ]}


@router.post("/api/service/{service_id}/update")
async def update_service(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    svc  = db.query(Service).filter(
        Service.id        == service_id,
        Service.tenant_id == tenant.id
    ).first()
    if not svc:
        return JSONResponse({"error": "Não encontrado"}, status_code=404)
    if "price" in data:
        try: svc.price = int(float(data["price"]) * 100)
        except: pass
    if "duration_min" in data:
        try: svc.duration_min = int(data["duration_min"])
        except: pass
    if "name" in data and data["name"].strip():
        svc.name = data["name"].strip()
    db.commit()
    return {"success": True}


@router.post("/api/service/create")
async def create_service(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)

    # ── Limite de 7 serviços no plano básico ──────────────────────────────
    if not _check_plan_feature(tenant, "servicos_ilimitados"):
        count = db.query(Service).filter(
            Service.tenant_id == tenant.id,
            Service.active    == True
        ).count()
        if count >= 7:
            return JSONResponse(
                {"error": "Plano Básico permite até 7 serviços. Faça upgrade para o plano Pro para adicionar mais."},
                status_code=403
            )

    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Nome obrigatório"}, status_code=400)
    try: price_cents = int(float(data.get("price", 0)) * 100)
    except: price_cents = 0

    svc = Service(
        tenant_id=tenant.id, name=name,
        duration_min=int(data.get("duration_min", 60)),
        price=price_cents, description=data.get("description", ""),
        color=data.get("color", "#6C5CE7"), active=True,
    )
    db.add(svc)
    db.commit()
    return {"success": True, "id": str(svc.id)}


@router.delete("/api/service/{service_id}")
def delete_service_api(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    svc = db.query(Service).filter(
        Service.id        == service_id,
        Service.tenant_id == tenant.id
    ).first()
    if svc:
        svc.active = False
        db.commit()
    return {"success": True}


# ── API: Configurações ────────────────────────────────────────────────────────

@router.post("/api/tenant/config")
async def save_tenant_config(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()

    if "display_name" in data and data["display_name"].strip():
        tenant.display_name      = data["display_name"].strip()
        tenant.bot_business_name = data["display_name"].strip()
    if "bot_attendant_name" in data and data["bot_attendant_name"].strip():
        tenant.bot_attendant_name = data["bot_attendant_name"].strip()
    if "owner_phone" in data:
        tenant.owner_phone = (data["owner_phone"] or "").strip() or None
    if "open_time" in data:
        tenant.open_time = data["open_time"] or "09:00"
    if "close_time" in data:
        tenant.close_time = data["close_time"] or "18:00"
    if "open_days" in data:
        tenant.open_days = data["open_days"] or "0,1,2,3,4,5"
    if "bot_active" in data:
        tenant.bot_active = bool(data["bot_active"])
    if "notify_new_appt" in data:
        tenant.notify_new_appt = bool(data["notify_new_appt"])

    db.commit()
    return {"success": True}


@router.post("/api/tenant/password")
async def change_password(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data       = await request.json()
    current_pw = data.get("current_password", "")
    new_pw     = data.get("new_password", "")

    if not bcrypt.checkpw(current_pw.encode(), tenant.dashboard_password.encode()):
        return JSONResponse({"error": "Senha atual incorreta"}, status_code=400)
    if len(new_pw) < 6:
        return JSONResponse({"error": "Nova senha deve ter ao menos 6 caracteres"}, status_code=400)

    tenant.dashboard_password = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    tenant.dashboard_token    = secrets.token_urlsafe(32)
    db.commit()
    return {"success": True, "new_token": tenant.dashboard_token}


# ── Exportação CSV ────────────────────────────────────────────────────────────

@router.get("/api/export/relatorio")
def export_relatorio(request: Request, mes: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)

    # ── Bloqueia para plano básico ────────────────────────────────────────
    if not _check_plan_feature(tenant, "csv"):
        return JSONResponse(
            {"error": "Exportação de relatório disponível apenas nos planos Pro e Agência. Faça upgrade para acessar."},
            status_code=403
        )

    needs_address = bool(getattr(tenant, 'needs_address', False))
    address_label = getattr(tenant, 'address_label', 'Endereço') or 'Endereço'
    biz_type      = getattr(tenant, 'business_type', 'outro') or 'outro'
    show_pet      = biz_type not in BUSINESS_NO_SUBJECT

    hoje = agora_brasilia()
    try:
        mes_dt = datetime.strptime(mes, "%Y-%m") if mes else hoje.replace(day=1)
    except Exception:
        mes_dt = hoje.replace(day=1)

    if mes_dt.month == 12:
        fim_mes = mes_dt.replace(year=mes_dt.year + 1, month=1, day=1) - timedelta(seconds=1)
    else:
        fim_mes = mes_dt.replace(month=mes_dt.month + 1, day=1) - timedelta(seconds=1)

    appts = db.query(Appointment).filter(
        Appointment.tenant_id    == tenant.id,
        Appointment.scheduled_at >= mes_dt,
        Appointment.scheduled_at <= fim_mes,
    ).order_by(Appointment.scheduled_at).all()

    cids = [a.customer_id for a in appts]
    sids = [a.service_id  for a in appts]
    cmap = _load_customers_map(db, tenant.id, cids)
    smap = _load_services_map(db, tenant.id, sids)

    output = io.StringIO()
    writer = csv.writer(output)

    if show_pet:
        header = ["Data/Hora", "Cliente", "Pet", "Raça", "Peso(kg)", "Serviço", "Valor(R$)", "Status", "Pagamento", "Método", "PIX", "Busca(Horário)"]
    else:
        header = ["Data/Hora", "Cliente", "Serviço", "Valor(R$)", "Status", "Pagamento", "Método", "PIX", "Busca(Horário)"]
    if needs_address:
        header.append(address_label)
    writer.writerow(header)

    for a in appts:
        customer     = cmap.get(a.customer_id)
        service      = smap.get(a.service_id)
        nome_cliente = (customer.name or customer.phone) if customer else "-"
        nome_servico = service.name if service else "-"
        price_raw    = a.payment_amount or (service.price if service else 0) or 0
        valor        = f"{price_raw/100:.2f}"
        status_label = STATUS_LABELS.get(a.status, (a.status, "", ""))[0]
        pay_label    = PAYMENT_LABELS.get(a.payment_status or "pending", (a.payment_status or "-", "", ""))[0]
        pay_label    = pay_label.replace("💳","").replace("✅","").replace("🎁","").strip()

        if show_pet:
            row = [
                a.scheduled_at.strftime("%d/%m/%Y %H:%M"), nome_cliente,
                a.pet_name or "-", a.pet_breed or "-",
                a.pet_weight or "-", nome_servico, valor,
                status_label, pay_label,
                a.payment_method or "-", a.payment_pix_key or "-",
                a.pickup_time or "-",
            ]
        else:
            row = [
                a.scheduled_at.strftime("%d/%m/%Y %H:%M"), nome_cliente,
                nome_servico, valor, status_label, pay_label,
                a.payment_method or "-", a.payment_pix_key or "-",
                a.pickup_time or "-",
            ]
        if needs_address:
            row.append(a.pickup_address or "-")
        writer.writerow(row)

    output.seek(0)
    filename = f"relatorio_{tenant.name}_{mes_dt.strftime('%Y-%m')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── Dashboard principal ───────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)

    if tid and tenant and tenant.id != tid:
        resp = RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        resp.delete_cookie("dash_session")
        return resp
    if not tenant:
        if tid:
            return RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        return HTMLResponse("<h2>Acesso negado.</h2>", status_code=401)

    tid            = tenant.id
    tenant_name    = tenant.display_name or tenant.name
    tenant_icon    = getattr(tenant, 'tenant_icon', '🐾') or '🐾'
    biz_type       = getattr(tenant, 'business_type', 'outro') or 'outro'
    subject        = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    subject_plural = getattr(tenant, 'subject_label_plural', 'Pets') or 'Pets'
    needs_address  = bool(getattr(tenant, 'needs_address', False))
    address_label  = getattr(tenant, 'address_label', 'Endereço de busca') or 'Endereço de busca'
    show_pet       = biz_type not in BUSINESS_NO_SUBJECT

    # Plano
    plano           = getattr(tenant, 'plan', 'basico') or 'basico'
    plan_active     = getattr(tenant, 'plan_active', True)
    pode_csv        = _check_plan_feature(tenant, "csv")
    pode_lembretes  = _check_plan_feature(tenant, "lembretes")
    pode_svc_ilimit = _check_plan_feature(tenant, "servicos_ilimitados")
    plan_label      = {"basico": "⭐ Básico", "pro": "🚀 Pro", "agencia": "🏢 Agência"}.get(plano, "⭐ Básico")

    hoje        = agora_brasilia()
    inicio_hoje = hoje.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    fim_hoje    = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

    agendamentos_hoje = db.query(Appointment).filter(
        Appointment.tenant_id    == tid,
        Appointment.scheduled_at >= inicio_hoje,
        Appointment.scheduled_at <= fim_hoje,
        Appointment.status       != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    amanha_inicio = (hoje + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    proximos = db.query(Appointment).filter(
        Appointment.tenant_id    == tid,
        Appointment.scheduled_at >= amanha_inicio,
        Appointment.scheduled_at <= amanha_inicio + timedelta(days=7),
        Appointment.status       != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    historico = db.query(Appointment).filter(
        Appointment.tenant_id == tid
    ).order_by(Appointment.scheduled_at.desc()).limit(200).all()

    pendentes_all = db.query(Appointment).filter(
        Appointment.tenant_id    == tid,
        Appointment.payment_status == "pending",
        Appointment.status       != "cancelled"
    ).order_by(Appointment.scheduled_at.desc()).all()

    services_all = db.query(Service).filter(
        Service.tenant_id == tid
    ).order_by(Service.active.desc(), Service.name).all()

    all_appts = list({a.id: a for a in agendamentos_hoje + proximos + historico + pendentes_all}.values())
    all_cids  = [a.customer_id for a in all_appts]
    all_sids  = [a.service_id  for a in all_appts]
    cmap = _load_customers_map(db, tid, all_cids)
    smap = _load_services_map(db, tid, all_sids)

    total_clientes = db.query(Customer).filter(Customer.tenant_id == tid).count()
    em_atendimento = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.status == "in_progress"
    ).count()
    prontos = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.status == "ready"
    ).count()

    mes_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    appts_mes_pagos = db.query(Appointment).filter(
        Appointment.tenant_id    == tid,
        Appointment.scheduled_at >= mes_inicio,
        Appointment.payment_status == "paid"
    ).all()
    sids_fat = list({a.service_id for a in appts_mes_pagos})
    smap_fat = _load_services_map(db, tid, sids_fat)
    fat_mes  = sum(
        a.payment_amount if a.payment_amount
        else (smap_fat.get(a.service_id).price if smap_fat.get(a.service_id) else 0)
        for a in appts_mes_pagos
    )

    appts_mes_pend = db.query(Appointment).filter(
        Appointment.tenant_id      == tid,
        Appointment.scheduled_at   >= mes_inicio,
        Appointment.payment_status == "pending",
        Appointment.status         != "cancelled"
    ).all()
    sids_pend = list({a.service_id for a in appts_mes_pend})
    smap_pend = _load_services_map(db, tid, sids_pend)
    fat_pendente = sum(
        (smap_pend.get(a.service_id).price if smap_pend.get(a.service_id) else 0)
        for a in appts_mes_pend
    )

    fat_fmt          = f"R$ {fat_mes/100:.2f}"
    fat_pendente_fmt = f"R$ {fat_pendente/100:.2f}"

    from collections import Counter
    svc_counts = Counter(a.service_id for a in historico if a.status != "cancelled")
    top_svc = ""
    if svc_counts:
        top_s = smap.get(svc_counts.most_common(1)[0][0])
        if top_s:
            top_svc = top_s.name

    has_services    = any(s.active for s in services_all)
    has_appts       = bool(historico)
    show_onboarding = not has_services and not has_appts
    onboarding_html = ""
    if show_onboarding:
        wa_configured    = bool(getattr(tenant, 'phone_number_id', None))
        owner_configured = bool(getattr(tenant, 'owner_phone', None))
        steps = [
            ("✅" if has_services else "⬜", "Cadastre seus serviços na aba <strong>Serviços</strong>"),
            ("✅" if wa_configured else "⬜", "WhatsApp configurado pelo admin"),
            ("✅" if owner_configured else "⬜", "Adicione seu número na aba <strong>Configurações</strong> para receber notificações"),
            ("⬜", "Faça seu primeiro agendamento clicando em <strong>+ Agendar</strong>"),
        ]
        steps_html = "".join(
            f'<div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px">'
            f'<span style="font-size:16px">{s}</span><span style="color:var(--text2)">{t}</span></div>'
            for s, t in steps
        )
        onboarding_html = f'<div class="card" style="border-color:var(--accent);background:var(--accent-bg)"><div class="section-title" style="color:var(--accent)">🚀 Bem-vindo! Configure sua agenda em 4 passos</div>{steps_html}</div>'

    # Banner de plano básico (CSV bloqueado)
    plano_banner = ""
    if plano == "basico":
        svc_count  = sum(1 for s in services_all if s.active)
        svc_aviso  = f" — {svc_count}/7 serviços usados" if True else ""
        plano_banner = f"""<div style="background:var(--warn-bg);border:1px solid rgba(198,125,0,.3);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:var(--warn);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <span>⭐ <strong>Plano Básico</strong>{svc_aviso} · Sem relatório CSV · Sem lembretes automáticos</span>
            <span style="font-size:11px;opacity:.7">Faça upgrade para Pro ou Agência para desbloquear</span>
        </div>"""

    def _pay_btn(a):
        svc       = smap.get(a.service_id)
        price_val = (svc.price / 100) if svc and svc.price else 0
        ps        = getattr(a, 'payment_status', 'pending') or 'pending'
        pl, pbg, pc = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
        return (
            f'<button class="pay-btn" onclick="openPayModal(\'{a.id}\', {price_val})" '
            f'style="background:{pbg};color:{pc};border:1px solid {pc}33;font-size:10px;'
            f'padding:3px 8px;border-radius:6px;cursor:pointer;font-family:\'DM Sans\',sans-serif;font-weight:700">{pl}</button>'
        )

    # ── Cards hoje ────────────────────────────────────────────────────────────
    cards_hoje = ""
    if not agendamentos_hoje:
        cards_hoje = '<div class="empty-state">Nenhum agendamento para hoje 🎉</div>'
    else:
        for a in agendamentos_hoje:
            customer     = cmap.get(a.customer_id)
            service      = smap.get(a.service_id)
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            horario      = a.scheduled_at.strftime("%H:%M")
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))

            pet_html = ""
            if show_pet and a.pet_name:
                pet_info = a.pet_name
                if a.pet_breed:  pet_info += f" · {a.pet_breed}"
                if a.pet_weight: pet_info += f" · {a.pet_weight}kg"
                pet_html = f'<div class="appt-pet">{tenant_icon} {pet_info}</div>'

            pickup_html  = f'<div class="pickup">🏠 Busca: {a.pickup_time}</div>' if a.pickup_time else ""
            address_html = ""
            if needs_address and getattr(a, 'pickup_address', None):
                address_html = f'<div class="pickup" style="color:var(--success)">📍 {address_label}: {a.pickup_address}</div>'

            status_options = "".join(
                f'<option value="{k}" {"selected" if a.status == k else ""}>{sl}</option>'
                for k, (sl, sb, sc) in STATUS_LABELS.items() if k != "cancelled"
            )
            cards_hoje += f"""
            <div class="appt-card" id="card-{a.id}">
                <div class="appt-time">{horario}</div>
                <div class="appt-body">
                    <div class="appt-client">👤 {nome_cliente}</div>
                    {pet_html}
                    <div class="appt-service">✂️ {nome_servico}</div>
                    {pickup_html}{address_html}
                </div>
                <div class="appt-actions">
                    <div class="status-badge" style="background:{bg};color:{color}">{label}</div>
                    <select class="status-select" onchange="updateStatus('{a.id}', this.value)">{status_options}</select>
                    {_pay_btn(a)}
                    <button class="btn-cancel" onclick="cancelAppt('{a.id}')">✕ Cancelar</button>
                </div>
            </div>"""

    # ── Próximos 7 dias ───────────────────────────────────────────────────────
    prox_cols = ["Data/Hora", "Cliente"]
    if show_pet:      prox_cols += [subject, "Raça/Peso"]
    prox_cols += ["Serviço", "Busca"]
    if needs_address: prox_cols.append(address_label)
    prox_cols += ["Status", "Pgto", ""]
    prox_th = "".join(f"<th>{c}</th>" for c in prox_cols)

    rows_proximos = ""
    if not proximos:
        rows_proximos = f'<tr><td colspan="{len(prox_cols)}" class="empty-row">Nenhum agendamento nos próximos 7 dias.</td></tr>'
    else:
        for a in proximos:
            customer     = cmap.get(a.customer_id)
            service      = smap.get(a.service_id)
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            ps           = getattr(a, 'payment_status', 'pending') or 'pending'
            pl, pbg, pc  = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
            price_val    = (service.price / 100) if service and service.price else 0

            row = f"<td>{a.scheduled_at.strftime('%d/%m %H:%M')}</td><td>{nome_cliente}</td>"
            if show_pet:
                row += f"<td>{a.pet_name or '-'}</td><td>{a.pet_breed or '-'}/{f'{a.pet_weight}kg' if a.pet_weight else '-'}</td>"
            row += f"<td>{nome_servico}</td><td>{a.pickup_time or '-'}</td>"
            if needs_address:
                row += f"<td style='font-size:11px;color:var(--success)'>{getattr(a,'pickup_address',None) or '-'}</td>"
            row += (
                f"<td><span class='badge' style='background:{bg};color:{color}'>{label}</span></td>"
                f"<td><span class='badge' style='background:{pbg};color:{pc};cursor:pointer' "
                f"onclick=\"openPayModal('{a.id}',{price_val})\">{pl}</span></td>"
                f"<td><button class='btn-cancel-small' onclick=\"cancelAppt('{a.id}')\">✕</button></td>"
            )
            rows_proximos += f"<tr>{row}</tr>"

    # ── Histórico ─────────────────────────────────────────────────────────────
    rows_historico = ""
    if not historico:
        rows_historico = '<tr><td colspan="8" class="empty-row">Nenhum histórico.</td></tr>'
    else:
        for a in historico:
            customer     = cmap.get(a.customer_id)
            service      = smap.get(a.service_id)
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            ps           = getattr(a, 'payment_status', 'pending') or 'pending'
            pl, pbg, pc  = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
            price_raw    = a.payment_amount or (service.price if service else 0) or 0
            price_str    = f"R$ {price_raw/100:.2f}" if price_raw else "-"
            price_val    = (service.price / 100) if service and service.price else 0
            criado       = a.created_at.strftime("%d/%m/%Y") if a.created_at else "-"
            rows_historico += f"""<tr>
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td>
                <td>{nome_cliente}</td>
                <td>{a.pet_name or '-'}</td>
                <td>{nome_servico}</td>
                <td>{price_str}</td>
                <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
                <td><span class="badge" style="background:{pbg};color:{pc};cursor:pointer" onclick="openPayModal('{a.id}',{price_val})">{pl}</span></td>
                <td>{criado}</td>
            </tr>"""

    # ── Pagamentos pendentes ──────────────────────────────────────────────────
    rows_pendentes = ""
    if not pendentes_all:
        rows_pendentes = '<tr><td colspan="7" class="empty-row">🎉 Nenhum pagamento pendente!</td></tr>'
    else:
        for a in pendentes_all:
            customer     = cmap.get(a.customer_id)
            service      = smap.get(a.service_id)
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            price_val    = (service.price / 100) if service and service.price else 0
            sl, sbg, sc  = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            pet_td       = f"<td>{a.pet_name or '-'}</td>" if show_pet else ""
            rows_pendentes += f"""<tr>
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td>
                <td>{nome_cliente}</td>
                {pet_td}
                <td>{nome_servico}</td>
                <td style="font-weight:700;color:var(--warn)">R$ {price_val:.2f}</td>
                <td><span class="badge" style="background:{sbg};color:{sc}">{sl}</span></td>
                <td><button class="btn-pay-now" onclick="openPayModal('{a.id}',{price_val})">💳 Registrar</button></td>
            </tr>"""

    pend_th_pet = f"<th>{subject}</th>" if show_pet else ""

    # ── Serviços ──────────────────────────────────────────────────────────────
    svc_count_active = sum(1 for s in services_all if s.active)
    svc_limite_html  = ""
    if not pode_svc_ilimit:
        cor = "#fc8181" if svc_count_active >= 7 else "#9aa0b8"
        svc_limite_html = f'<div style="font-size:12px;color:{cor};margin-bottom:12px">Plano Básico: {svc_count_active}/7 serviços ativos. {"⚠️ Limite atingido." if svc_count_active >= 7 else ""}</div>'

    svc_rows = ""
    for s in services_all:
        active_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        svc_rows += f"""
        <div class="service-edit-row" id="srow-{s.id}">
            <div class="svc-color-dot" style="background:{s.color or '#6C5CE7'}"></div>
            <div style="flex:1">
                <div style="font-weight:700;font-size:14px">{s.name}</div>
                <div style="font-size:12px;color:var(--text3)">{s.description or ''}</div>
            </div>
            {active_badge}
            <div style="display:flex;gap:8px;align-items:center">
                <div>
                    <div style="font-size:10px;color:var(--text3);margin-bottom:2px">PREÇO</div>
                    <input class="svc-input" id="price-{s.id}" value="{s.price/100:.2f}" type="number" step="0.01" style="width:90px">
                </div>
                <div>
                    <div style="font-size:10px;color:var(--text3);margin-bottom:2px">MIN</div>
                    <input class="svc-input" id="dur-{s.id}" value="{s.duration_min}" type="number" style="width:65px">
                </div>
                <button class="btn-save-svc" onclick="saveService('{s.id}')">💾</button>
                <button class="btn-del-svc" onclick="deleteService('{s.id}')">✕</button>
            </div>
        </div>"""

    service_options = "".join(
        f'<option value="{s.id}">{s.name} — R$ {s.price/100:.2f}</option>'
        for s in services_all if s.active
    )

    # Add service form — esconde se limite atingido no básico
    add_svc_bloqueado = (not pode_svc_ilimit and svc_count_active >= 7)
    add_svc_form = ""
    if add_svc_bloqueado:
        add_svc_form = '<div class="alert-info" style="background:var(--warn-bg);color:var(--warn);border:1px solid rgba(198,125,0,.3);padding:12px 16px;border-radius:8px;font-size:13px;margin-top:14px">⚠️ Limite de 7 serviços do Plano Básico atingido. Faça upgrade para o Plano Pro para adicionar mais.</div>'
    else:
        add_svc_form = f"""
        <div class="add-svc-form">
            <div class="add-svc-title">➕ Adicionar novo serviço</div>
            <div class="form-row2">
                <div class="form-group" style="margin:0"><label>Nome *</label><input id="ns_name" placeholder="Ex: Corte + Barba"></div>
                <div class="form-group" style="margin:0"><label>Preço (R$)</label><input id="ns_price" type="number" step="0.01" placeholder="50.00"></div>
                <div class="form-group" style="margin:0"><label>Duração (min)</label><input id="ns_dur" type="number" value="60"></div>
                <div style="display:flex;align-items:flex-end"><button class="btn-submit" onclick="addService()" style="padding:9px 16px;margin:0;width:auto">Adicionar</button></div>
            </div>
            <div class="form-group" style="margin-top:10px;margin-bottom:0">
                <label>Descrição (para o bot)</label>
                <input id="ns_desc" placeholder="Ex: Inclui lavagem e finalização">
            </div>
        </div>"""

    # ── Aba Configurações ─────────────────────────────────────────────────────
    open_days_list     = [d.strip() for d in (getattr(tenant, 'open_days', '0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns          = ''.join(
        f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" '
        f'data-day="{i}" onclick="toggleConfigDay(this)">{d}</button>'
        for i, d in enumerate(DAYS_PT)
    )
    bot_active_checked  = 'checked' if getattr(tenant, 'bot_active', True) else ''
    notify_checked      = 'checked' if getattr(tenant, 'notify_new_appt', True) else ''
    current_open        = getattr(tenant, 'open_time', '09:00') or '09:00'
    current_close       = getattr(tenant, 'close_time', '18:00') or '18:00'
    current_owner_phone = getattr(tenant, 'owner_phone', '') or ''
    current_attendant   = getattr(tenant, 'bot_attendant_name', 'Mari') or 'Mari'
    plan_badge_cls      = "badge-green" if plan_active else "badge-red"
    plan_badge_txt      = "Ativo" if plan_active else "Suspenso"

    lembretes_info = ""
    if not pode_lembretes:
        lembretes_info = '<div style="font-size:11px;color:var(--warn);margin-top:6px">⚠️ Lembretes automáticos disponíveis apenas nos planos Pro e Agência.</div>'

    csv_info = ""
    if not pode_csv:
        csv_info = '<div style="font-size:11px;color:var(--warn);margin-top:6px">⚠️ Exportação CSV disponível apenas nos planos Pro e Agência.</div>'

    # ── Slots para o modal ────────────────────────────────────────────────────
    open_time  = getattr(tenant, 'open_time', '09:00') or '09:00'
    close_time = getattr(tenant, 'close_time', '18:00') or '18:00'
    try:
        oh, om = map(int, open_time.split(':'))
        ch, cm = map(int, close_time.split(':'))
    except Exception:
        oh, om, ch, cm = 9, 0, 18, 0
    slots, cur = [], oh * 60 + om
    while cur < ch * 60 + cm:
        slots.append(f"{cur//60:02d}:{cur%60:02d}")
        cur += 30
    slots_json = json.dumps(slots)

    bot_status = getattr(tenant, 'bot_active', True)
    bot_badge  = ('<span class="badge badge-green">🤖 Ativo</span>' if bot_status
                  else '<span class="badge badge-red">🤖 Pausado</span>')
    mes_atual  = hoje.strftime("%Y-%m")
    mes_label  = hoje.strftime("%B/%Y").capitalize()

    # Campo endereço no modal
    address_modal_field = ""
    if needs_address:
        address_modal_field = f"""
        <div class="form-group">
            <label>📍 {address_label} *</label>
            <input type="text" id="f_address" placeholder="Ex: Rua das Flores, 123 — Centro">
        </div>"""

    # Campos pet no modal
    if show_pet:
        pet_modal_fields = f"""
        <div class="form-row">
            <div class="form-group">
                <label>{tenant_icon} {subject} *</label>
                <input type="text" id="f_pet" placeholder="Ex: Rex">
            </div>
            <div class="form-group">
                <label>✂️ Serviço *</label>
                <select id="f_service">{service_options}</select>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>🦴 Raça</label>
                <input type="text" id="f_breed" placeholder="Ex: Golden">
            </div>
            <div class="form-group">
                <label>⚖️ Peso (kg)</label>
                <input type="number" id="f_weight" placeholder="15" step="0.1" min="0">
            </div>
        </div>"""
    else:
        pet_modal_fields = f"""
        <div class="form-group">
            <label>✂️ Serviço *</label>
            <select id="f_service">{service_options}</select>
        </div>"""

    # Botão CSV — desabilitado no básico
    csv_btn_html = ""
    if pode_csv:
        csv_btn_html = f'<a href="/api/export/relatorio?mes={mes_atual}" class="btn-icon" title="Exportar {mes_label}" style="text-decoration:none">📥</a>'
    else:
        csv_btn_html = f'<button class="btn-icon" title="CSV disponível no Plano Pro" onclick="showToast(\'📊 Exportação CSV disponível no Plano Pro e Agência\')" style="opacity:.4;cursor:not-allowed">📥</button>'

    # ─────────────────────────────────────────────────────────────────────────
    # HTML principal
    # ─────────────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{tenant_name} — Painel</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root[data-theme="light"]{{
    --bg:#f4f6fb;--surface:#ffffff;--surface2:#f8f9fc;--border:#e8ecf2;
    --text:#1a1d23;--text2:#5a6172;--text3:#9aa0b0;
    --accent:#5B5BD6;--accent2:#7c7de8;--accent-bg:#ededfc;
    --shadow:rgba(0,0,0,0.08);--shadow2:rgba(0,0,0,0.12);
    --header-bg:#1a1d23;--header-text:#ffffff;
    --danger:#e53e3e;--danger-bg:#fff5f5;
    --success:#2e7d32;--success-bg:#e8f5e9;
    --warn:#c67d00;--warn-bg:#fff8e1;
    --info:#1565c0;--info-bg:#e3f2fd;
    --overlay:rgba(0,0,0,0.4);--input-bg:#f8f9fc;--modal-bg:#ffffff;
}}
:root[data-theme="dark"]{{
    --bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2d3148;
    --text:#e8eaf2;--text2:#9aa0b8;--text3:#5a6172;
    --accent:#7c7de8;--accent2:#9c9df0;--accent-bg:#23254a;
    --shadow:rgba(0,0,0,0.3);--shadow2:rgba(0,0,0,0.5);
    --header-bg:#13151f;--header-text:#e8eaf2;
    --danger:#fc8181;--danger-bg:#2d1515;
    --success:#68d391;--success-bg:#1a2e1a;
    --warn:#f6c90e;--warn-bg:#2a2200;
    --info:#63b3ed;--info-bg:#1a2540;
    --overlay:rgba(0,0,0,0.7);--input-bg:#1a1d27;--modal-bg:#1a1d27;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.header{{background:var(--header-bg);color:var(--header-text);padding:0 24px;height:56px;
    display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;
    box-shadow:0 2px 12px var(--shadow)}}
.header-logo{{font-size:17px;font-weight:800;display:flex;align-items:center;gap:8px}}
.header-logo .icon{{font-size:22px}}
.header-logo span{{color:var(--accent2)}}
.header-right{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.btn-icon{{width:34px;height:34px;border-radius:9px;border:1px solid rgba(255,255,255,0.1);
    background:rgba(255,255,255,0.07);color:var(--header-text);cursor:pointer;font-size:15px;
    display:flex;align-items:center;justify-content:center;text-decoration:none;transition:background .2s}}
.btn-icon:hover{{background:rgba(255,255,255,0.14)}}
.btn-primary{{background:var(--accent);color:white;border:none;padding:8px 14px;border-radius:9px;
    cursor:pointer;font-size:13px;font-weight:700;font-family:'DM Sans',sans-serif;
    display:flex;align-items:center;gap:5px;transition:background .15s}}
.btn-primary:hover{{background:var(--accent2)}}
.container{{max-width:1300px;margin:0 auto;padding:20px}}
.tabs{{display:flex;gap:4px;margin-bottom:20px;background:var(--surface);
    border:1px solid var(--border);border-radius:12px;padding:4px;width:fit-content;flex-wrap:wrap}}
.tab{{padding:8px 16px;border-radius:9px;border:none;background:transparent;
    color:var(--text2);cursor:pointer;font-size:13px;font-weight:600;
    font-family:'DM Sans',sans-serif;transition:all .15s;white-space:nowrap}}
.tab.active{{background:var(--accent);color:white}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}}
@media(max-width:1000px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:600px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}
.stat-card{{background:var(--surface);border-radius:12px;padding:14px 16px;
    border:1px solid var(--border);transition:box-shadow .2s}}
.stat-card:hover{{box-shadow:0 4px 16px var(--shadow)}}
.stat-number{{font-size:22px;font-weight:800;color:var(--text);line-height:1}}
.stat-label{{font-size:11px;color:var(--text3);margin-top:3px;font-weight:500}}
.stat-card.warn{{border-color:#c67d0060;background:var(--warn-bg)}}
.stat-card.warn .stat-number{{color:var(--warn)}}
.card{{background:var(--surface);border-radius:14px;padding:18px;
    border:1px solid var(--border);margin-bottom:16px}}
.section-title{{font-size:14px;font-weight:700;color:var(--text);
    display:flex;align-items:center;gap:7px;margin-bottom:14px}}
.badge-count{{background:var(--accent-bg);color:var(--accent);
    font-size:11px;padding:2px 7px;border-radius:20px;font-weight:700}}
.appt-card{{display:flex;align-items:flex-start;gap:12px;padding:12px 14px;
    border-radius:10px;border:1px solid var(--border);margin-bottom:8px;
    background:var(--surface2);transition:box-shadow .2s,border-color .2s}}
.appt-card:hover{{box-shadow:0 4px 14px var(--shadow2);border-color:var(--accent)}}
.appt-time{{font-size:18px;font-weight:800;color:var(--accent);
    min-width:55px;text-align:center;font-family:'DM Mono',monospace;padding-top:2px}}
.appt-body{{flex:1;min-width:0}}
.appt-client{{font-size:13px;font-weight:700;margin-bottom:2px}}
.appt-pet,.appt-service{{font-size:12px;color:var(--text2);margin-bottom:1px}}
.pickup{{font-size:11px;color:var(--info);margin-top:3px;font-weight:600}}
.appt-actions{{display:flex;flex-direction:column;align-items:flex-end;gap:6px;min-width:160px}}
.status-badge{{font-size:11px;padding:3px 9px;border-radius:20px;font-weight:700;white-space:nowrap}}
.status-select{{font-size:12px;padding:4px 7px;border:1px solid var(--border);border-radius:7px;
    cursor:pointer;background:var(--input-bg);color:var(--text);width:100%;
    font-family:'DM Sans',sans-serif;outline:none}}
.btn-cancel{{font-size:11px;color:var(--danger);background:var(--danger-bg);
    border:1px solid rgba(229,62,62,0.2);padding:3px 8px;border-radius:7px;
    cursor:pointer;width:100%;font-family:'DM Sans',sans-serif}}
.btn-cancel-small{{font-size:11px;color:var(--danger);background:var(--danger-bg);
    border:1px solid rgba(229,62,62,0.2);padding:2px 7px;border-radius:6px;
    cursor:pointer;font-family:'DM Sans',sans-serif}}
.btn-pay-now{{font-size:12px;background:var(--warn-bg);color:var(--warn);
    border:1px solid #c67d0040;padding:5px 12px;border-radius:7px;cursor:pointer;
    font-weight:600;font-family:'DM Sans',sans-serif;white-space:nowrap}}
.btn-pay-now:hover{{background:#c67d00;color:white}}
.empty-state{{color:var(--text3);text-align:center;padding:28px;font-size:13px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:10px;color:var(--text3);font-weight:600;
    padding:7px 10px;border-bottom:2px solid var(--border);
    text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
td{{font-size:12px;padding:10px;border-bottom:1px solid var(--border);color:var(--text)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--surface2)}}
.empty-row{{text-align:center;color:var(--text3);padding:24px !important}}
.badge{{font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;white-space:nowrap}}
.badge-green{{background:var(--success-bg);color:var(--success)}}
.badge-red{{background:var(--danger-bg);color:var(--danger)}}
.badge-gray{{background:var(--surface2);color:var(--text3)}}
.service-edit-row{{display:flex;align-items:center;gap:10px;padding:11px 14px;
    border:1px solid var(--border);border-radius:10px;margin-bottom:8px;
    background:var(--surface2);flex-wrap:wrap}}
.svc-color-dot{{width:10px;height:10px;border-radius:3px;flex-shrink:0}}
.svc-input{{padding:6px 9px;border:1px solid var(--border);border-radius:8px;
    background:var(--input-bg);color:var(--text);font-size:13px;
    font-family:'DM Sans',sans-serif;outline:none}}
.svc-input:focus{{border-color:var(--accent)}}
.btn-save-svc{{padding:6px 10px;border-radius:8px;border:1px solid var(--accent);
    background:var(--accent-bg);color:var(--accent);cursor:pointer;font-size:12px;
    font-weight:600;font-family:'DM Sans',sans-serif}}
.btn-save-svc:hover{{background:var(--accent);color:white}}
.btn-del-svc{{padding:6px 10px;border-radius:8px;border:1px solid rgba(229,62,62,0.3);
    background:var(--danger-bg);color:var(--danger);cursor:pointer;font-size:12px;
    font-weight:600;font-family:'DM Sans',sans-serif}}
.add-svc-form{{background:var(--accent-bg);border:1px dashed var(--accent);
    border-radius:12px;padding:16px;margin-top:14px}}
.add-svc-title{{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:12px}}
.form-row2{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end}}
@media(max-width:600px){{.form-row2{{grid-template-columns:1fr 1fr}}}}
.config-section{{margin-bottom:22px}}
.config-section-title{{font-size:12px;font-weight:700;color:var(--text3);
    text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px;
    padding-bottom:6px;border-bottom:1px solid var(--border)}}
.config-grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:600px){{.config-grid2{{grid-template-columns:1fr}}}}
.toggle-wrap{{display:flex;align-items:center;justify-content:space-between;
    padding:12px 14px;background:var(--surface2);border:1px solid var(--border);
    border-radius:10px;margin-bottom:8px}}
.toggle-label{{font-size:13px;font-weight:600}}
.toggle-sub{{font-size:11px;color:var(--text3);margin-top:2px}}
.toggle-switch{{position:relative;display:inline-block;width:44px;height:24px}}
.toggle-switch input{{opacity:0;width:0;height:0}}
.toggle-slider{{width:44px;height:24px;background:var(--border);border-radius:12px;
    position:absolute;top:0;left:0;transition:background .2s;cursor:pointer}}
.toggle-slider:before{{content:'';position:absolute;width:18px;height:18px;
    border-radius:50%;background:white;top:3px;left:3px;transition:transform .2s}}
.toggle-switch input:checked + .toggle-slider{{background:var(--accent)}}
.toggle-switch input:checked + .toggle-slider:before{{transform:translateX(20px)}}
.days-grid{{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}}
.day-btn{{padding:6px 12px;border-radius:8px;border:1px solid var(--border);
    background:var(--input-bg);color:var(--text2);cursor:pointer;font-size:12px;
    font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s}}
.day-btn.active{{background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}}
.plan-info{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;
    padding:14px 16px;display:flex;align-items:center;justify-content:space-between}}
.modal-overlay{{position:fixed;inset:0;background:var(--overlay);z-index:200;
    display:flex;align-items:center;justify-content:center;
    opacity:0;pointer-events:none;transition:opacity .25s;backdrop-filter:blur(4px)}}
.modal-overlay.open{{opacity:1;pointer-events:all}}
.modal{{background:var(--modal-bg);border-radius:18px;padding:26px;
    width:100%;max-width:500px;max-height:90vh;overflow-y:auto;
    box-shadow:0 20px 60px var(--shadow2);border:1px solid var(--border);
    transform:translateY(20px);transition:transform .25s;margin:20px}}
.modal-overlay.open .modal{{transform:translateY(0)}}
.modal-title{{font-size:16px;font-weight:800;margin-bottom:18px;color:var(--text);
    display:flex;align-items:center;justify-content:space-between}}
.modal-close{{width:28px;height:28px;border-radius:7px;border:1px solid var(--border);
    background:var(--surface2);color:var(--text2);cursor:pointer;font-size:14px;
    display:flex;align-items:center;justify-content:center}}
.form-group{{margin-bottom:12px}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
label{{display:block;font-size:11px;font-weight:600;color:var(--text2);
    margin-bottom:4px;text-transform:uppercase;letter-spacing:.4px}}
input,select{{width:100%;padding:9px 11px;border:1px solid var(--border);
    border-radius:9px;background:var(--input-bg);color:var(--text);font-size:13px;
    font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}}
input:focus,select:focus{{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}}
.slots-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px}}
.slot-btn{{padding:7px 4px;border:1px solid var(--border);border-radius:7px;
    background:var(--surface2);color:var(--text);cursor:pointer;font-size:12px;
    font-weight:600;font-family:'DM Mono',monospace;text-align:center;transition:all .15s}}
.slot-btn:hover{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.slot-btn.selected{{background:var(--accent);color:white;border-color:var(--accent)}}
.slot-btn.busy{{background:var(--danger-bg);color:var(--danger);cursor:not-allowed;opacity:.6}}
.btn-submit{{width:100%;padding:11px;background:var(--accent);color:white;
    border:none;border-radius:11px;font-size:14px;font-weight:700;
    font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:4px;transition:background .15s}}
.btn-submit:hover{{background:var(--accent2)}}
.btn-submit:disabled{{opacity:.5;cursor:not-allowed}}
.pay-method-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:6px}}
.pay-method-btn{{padding:10px;border:2px solid var(--border);border-radius:9px;
    background:var(--surface2);cursor:pointer;font-size:13px;font-weight:600;
    font-family:'DM Sans',sans-serif;color:var(--text);text-align:center;transition:all .15s}}
.pay-method-btn:hover,.pay-method-btn.active{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.pix-section{{background:var(--success-bg);border:1px solid rgba(46,125,50,.3);border-radius:10px;padding:12px;margin-top:10px}}
.pix-review-box{{background:var(--warn-bg);border:1px solid rgba(198,125,0,.3);border-radius:10px;padding:12px;margin-top:10px;font-size:12px;color:var(--warn)}}
.search-box{{display:flex;gap:8px;margin-bottom:14px}}
.search-input{{flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:9px;
    background:var(--input-bg);color:var(--text);font-size:13px;
    font-family:'DM Sans',sans-serif;outline:none}}
.toast{{position:fixed;bottom:20px;right:20px;background:var(--surface);color:var(--text);
    padding:11px 18px;border-radius:11px;font-size:12px;font-weight:500;
    border:1px solid var(--border);box-shadow:0 8px 24px var(--shadow2);
    opacity:0;transition:opacity .3s,transform .3s;z-index:999;transform:translateY(10px)}}
.toast.show{{opacity:1;transform:translateY(0)}}
.alert-info{{background:var(--info-bg);color:var(--info);border:1px solid rgba(21,101,192,.2);
    padding:10px 14px;border-radius:8px;font-size:12px;margin-bottom:12px}}
.spinner{{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);
    border-top-color:white;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@media(max-width:600px){{
    .appt-card{{flex-direction:column}}
    .appt-actions{{width:100%;flex-direction:row;flex-wrap:wrap}}
    .form-row{{grid-template-columns:1fr}}
    .slots-grid{{grid-template-columns:repeat(3,1fr)}}
}}
</style>
</head>
<body>

<div class="header">
    <div class="header-logo">
        <span class="icon">{tenant_icon}</span>
        <span>{tenant_name}</span>
    </div>
    <div class="header-right">
        <span style="font-size:11px;opacity:.5;font-family:'DM Mono',monospace">{hoje.strftime("%d/%m %H:%M")}</span>
        {bot_badge}
        <button class="btn-primary" onclick="openModal()"><span>+</span> Agendar</button>
        {csv_btn_html}
        <button class="btn-icon" onclick="toggleTheme()" id="theme-btn" title="Tema">🌙</button>
        <button class="btn-icon" onclick="refreshData()" title="Atualizar" id="refresh-btn">↻</button>
        <a href="/dashboard/logout" class="btn-icon" title="Sair" style="text-decoration:none">🚪</a>
    </div>
</div>

<div class="container">
{plano_banner}
{onboarding_html}

<div class="stats">
    <div class="stat-card"><div class="stat-number">{len(agendamentos_hoje)}</div><div class="stat-label">📅 Hoje</div></div>
    <div class="stat-card"><div class="stat-number">{em_atendimento}</div><div class="stat-label">✂️ Em atend.</div></div>
    <div class="stat-card"><div class="stat-number">{prontos}</div><div class="stat-label">✅ Prontos</div></div>
    <div class="stat-card"><div class="stat-number">{total_clientes}</div><div class="stat-label">👤 Clientes</div></div>
    <div class="stat-card"><div class="stat-number" style="font-size:14px">{fat_fmt}</div><div class="stat-label">💰 Recebido/mês</div></div>
    <div class="stat-card warn"><div class="stat-number" style="font-size:14px">{fat_pendente_fmt}</div><div class="stat-label">⏳ Pendente/mês</div></div>
</div>

<div class="tabs">
    <button class="tab active" onclick="switchTab('hoje',this)">📋 Hoje</button>
    <button class="tab"        onclick="switchTab('proximos',this)">📆 Próximos 7 dias</button>
    <button class="tab"        onclick="switchTab('pendentes',this)">⏳ Pgtos <span class="badge-count">{len(pendentes_all)}</span></button>
    <button class="tab"        onclick="switchTab('historico',this)">📁 Histórico</button>
    <button class="tab"        onclick="switchTab('servicos',this)">✂️ Serviços</button>
    <button class="tab"        onclick="switchTab('config',this)">⚙️ Config</button>
</div>

<!-- Hoje -->
<div id="tab-hoje" class="tab-content active">
    <div class="card">
        <div class="section-title">📋 Agenda de Hoje <span class="badge-count">{hoje.strftime("%d/%m")}</span></div>
        {cards_hoje}
    </div>
</div>

<!-- Próximos 7 dias -->
<div id="tab-proximos" class="tab-content">
    <div class="card">
        <div class="section-title">📆 Próximos 7 dias</div>
        <div class="table-wrap"><table>
            <thead><tr>{prox_th}</tr></thead>
            <tbody>{rows_proximos}</tbody>
        </table></div>
    </div>
</div>

<!-- Pagamentos pendentes -->
<div id="tab-pendentes" class="tab-content">
    <div class="card">
        <div class="section-title">⏳ Pagamentos Pendentes
            <span style="font-size:12px;color:var(--text3);font-weight:400">Total: <strong style="color:var(--warn)">{fat_pendente_fmt}</strong></span>
        </div>
        <div class="table-wrap"><table>
            <thead><tr><th>Data/Hora</th><th>Cliente</th>{pend_th_pet}<th>Serviço</th><th>Valor</th><th>Status</th><th>Ação</th></tr></thead>
            <tbody>{rows_pendentes}</tbody>
        </table></div>
    </div>
</div>

<!-- Histórico -->
<div id="tab-historico" class="tab-content">
    <div class="card">
        <div class="section-title" style="justify-content:space-between">
            <span>📁 Histórico <span style="font-size:11px;color:var(--text3);font-weight:400">(últimos 200)</span></span>
            {'<a href="/api/export/relatorio?mes=' + mes_atual + '" class="btn-save-svc" style="font-size:11px;padding:4px 10px;text-decoration:none">📥 CSV ' + mes_label + '</a>' if pode_csv else '<span style="font-size:11px;color:var(--text3)">📥 CSV disponível no Plano Pro</span>'}
        </div>
        <div class="search-box">
            <input class="search-input" id="search-input" placeholder="🔍 Buscar por cliente, {subject.lower()}, serviço..." oninput="filterTable()">
        </div>
        <div class="table-wrap"><table>
            <thead><tr><th>Data/Hora</th><th>Cliente</th><th>{subject}</th><th>Serviço</th><th>Valor</th><th>Status</th><th>Pgto</th><th>Criado</th></tr></thead>
            <tbody id="historico-body">{rows_historico}</tbody>
        </table></div>
    </div>
</div>

<!-- Serviços -->
<div id="tab-servicos" class="tab-content">
    <div class="card">
        <div class="section-title">✂️ Seus serviços</div>
        <div style="font-size:12px;color:var(--text3);margin-bottom:8px">Edite preço e duração. A IA usa esses valores em tempo real.</div>
        {svc_limite_html}
        {("" if svc_rows else '<div class="empty-state">Nenhum serviço. Adicione abaixo!</div>') + svc_rows}
        {"<div style='font-size:12px;color:var(--text3);margin-top:8px;padding:10px 14px;background:var(--accent-bg);border-radius:8px'>⭐ Mais agendado: <strong>" + top_svc + "</strong></div>" if top_svc else ""}
        {add_svc_form}
    </div>
</div>

<!-- Configurações -->
<div id="tab-config" class="tab-content">
    <div class="card">
        <div class="section-title">⚙️ Configurações do negócio</div>
        <div class="alert-info">💡 Alterações entram em vigor imediatamente para o bot.</div>

        <!-- Plano -->
        <div class="config-section">
            <div class="config-section-title">📦 Plano</div>
            <div class="plan-info">
                <div>
                    <div style="font-weight:700;font-size:15px">{plan_label}</div>
                    <div style="font-size:12px;color:var(--text3);margin-top:2px">Entre em contato para alterar o plano</div>
                </div>
                <span class="badge {plan_badge_cls}">{plan_badge_txt}</span>
            </div>
            {csv_info}
            {lembretes_info}
        </div>

        <!-- Bot -->
        <div class="config-section">
            <div class="config-section-title">🤖 Bot</div>
            <div class="toggle-wrap">
                <div>
                    <div class="toggle-label">Bot ativo</div>
                    <div class="toggle-sub">Quando pausado, o bot não responde nenhuma mensagem</div>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox" id="cfg_bot_active" {bot_active_checked} onchange="saveToggle('bot_active',this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="toggle-wrap">
                <div>
                    <div class="toggle-label">Notificações de novos agendamentos</div>
                    <div class="toggle-sub">Receber WhatsApp quando o bot confirmar um agendamento</div>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox" id="cfg_notify" {notify_checked} onchange="saveToggle('notify_new_appt',this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
        </div>

        <!-- Dados do negócio -->
        <div class="config-section">
            <div class="config-section-title">🏢 Dados do negócio</div>
            <div class="config-grid2">
                <div class="form-group">
                    <label>Nome exibido</label>
                    <input type="text" id="cfg_display_name" value="{tenant_name}">
                </div>
                <div class="form-group">
                    <label>Nome da atendente virtual</label>
                    <input type="text" id="cfg_attendant" value="{current_attendant}">
                </div>
            </div>
            <div class="form-group">
                <label>WhatsApp para notificações (com DDI e DDD)</label>
                <input type="text" id="cfg_owner_phone" value="{current_owner_phone}" placeholder="Ex: 5511999999999">
            </div>
            <button class="btn-submit" style="max-width:200px" onclick="saveConfig()">💾 Salvar dados</button>
        </div>

        <!-- Horários -->
        <div class="config-section">
            <div class="config-section-title">⏰ Horários de atendimento</div>
            <div class="config-grid2">
                <div class="form-group">
                    <label>Abre às</label>
                    <input type="time" id="cfg_open_time" value="{current_open}">
                </div>
                <div class="form-group">
                    <label>Fecha às</label>
                    <input type="time" id="cfg_close_time" value="{current_close}">
                </div>
            </div>
            <div class="form-group">
                <label>Dias de atendimento</label>
                <div class="days-grid" id="cfg-days-grid">{days_btns}</div>
                <input type="hidden" id="cfg_open_days" value="{','.join(open_days_list)}">
            </div>
            <button class="btn-submit" style="max-width:200px" onclick="saveHorarios()">💾 Salvar horários</button>
        </div>

        <!-- Senha -->
        <div class="config-section">
            <div class="config-section-title">🔑 Alterar senha</div>
            <div class="config-grid2">
                <div class="form-group">
                    <label>Senha atual</label>
                    <input type="password" id="cfg_pw_current" placeholder="••••••••">
                </div>
                <div class="form-group">
                    <label>Nova senha (mín. 6 caracteres)</label>
                    <input type="password" id="cfg_pw_new" placeholder="••••••••">
                </div>
            </div>
            <button class="btn-submit" style="max-width:200px;background:var(--warn)" onclick="changePassword()">🔑 Alterar senha</button>
            <div style="font-size:11px;color:var(--text3);margin-top:8px">⚠️ Você será desconectado após trocar a senha.</div>
        </div>
    </div>
</div>

</div><!-- /container -->

<!-- Modal: Agendamento -->
<div class="modal-overlay" id="modalOverlay" onclick="handleOverlayClick(event)">
<div class="modal">
    <div class="modal-title">➕ Novo Agendamento <button class="modal-close" onclick="closeModal()">✕</button></div>
    <div class="form-group">
        <label>👤 Nome do cliente *</label>
        <input type="text" id="f_customer" placeholder="Ex: João Silva" autocomplete="off">
    </div>
    {pet_modal_fields}
    <div class="form-group">
        <label>📅 Data *</label>
        <input type="date" id="f_date" onchange="loadSlots()">
    </div>
    <div class="form-group" id="slots-group" style="display:none">
        <div style="font-size:11px;color:var(--text3);margin-bottom:6px">Horários disponíveis</div>
        <div class="slots-grid" id="slots-grid"></div>
        <input type="hidden" id="f_time">
    </div>
    <div class="form-group">
        <label>🏠 Horário de busca (opcional)</label>
        <input type="time" id="f_pickup">
    </div>
    {address_modal_field}
    <button class="btn-submit" id="btn-submit" onclick="submitAppt()">Confirmar Agendamento</button>
</div>
</div>

<!-- Modal: Pagamento -->
<div class="modal-overlay" id="payModalOverlay" onclick="handlePayOverlayClick(event)">
<div class="modal">
    <div class="modal-title">💳 Registrar Pagamento <button class="modal-close" onclick="closePayModal()">✕</button></div>
    <input type="hidden" id="pay_appt_id">
    <div class="form-group">
        <label>Valor (R$)</label>
        <input type="number" id="pay_amount" step="0.01" placeholder="0.00">
    </div>
    <div class="form-group">
        <label>Forma de pagamento</label>
        <div class="pay-method-grid">
            <button class="pay-method-btn" onclick="selectPayMethod('pix',this)">📱 PIX</button>
            <button class="pay-method-btn" onclick="selectPayMethod('dinheiro',this)">💵 Dinheiro</button>
            <button class="pay-method-btn" onclick="selectPayMethod('cartao',this)">💳 Cartão</button>
            <button class="pay-method-btn" onclick="selectPayMethod('outro',this)">📝 Outro</button>
        </div>
        <input type="hidden" id="pay_method" value="">
    </div>
    <div id="pix_section" style="display:none">
        <div class="pix-section">
            <label style="color:var(--success);margin-bottom:6px;display:block">📱 Comprovante PIX</label>
            <input type="text" id="pay_pix_key" placeholder="Cole o ID/código do comprovante">
            <div style="font-size:11px;color:var(--success);margin-top:6px">💡 Cole o ID para rastreio e auditoria</div>
        </div>
        <div class="pix-review-box">
            ⚠️ <strong>Atenção:</strong> Confirme no seu app bancário antes de registrar.
        </div>
    </div>
    <div class="form-group" style="margin-top:12px">
        <label>Observação</label>
        <input type="text" id="pay_notes" placeholder="Ex: Desconto aplicado...">
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px">
        <button class="btn-submit" style="background:var(--success)" onclick="confirmPayment('paid')">✅ Confirmar Pago</button>
        <button class="btn-submit" style="background:#6a1b9a" onclick="confirmPayment('waived')">🎁 Isentar</button>
    </div>
    <button class="btn-submit" style="background:var(--danger-bg);color:var(--danger);border:1px solid rgba(229,62,62,.2);margin-top:8px" onclick="confirmPayment('pending')">⏳ Manter Pendente</button>
</div>
</div>

<div class="toast" id="toast"></div>

<script>
const TENANT_ID  = '{tid}';
const ALL_SLOTS  = {slots_json};
const SHOW_PET   = {'true' if show_pet else 'false'};
const NEEDS_ADDR = {'true' if needs_address else 'false'};

// Tema
const savedTheme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);
document.getElementById('theme-btn').textContent = savedTheme === 'dark' ? '☀️' : '🌙';
function toggleTheme() {{
    const n = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', n);
    localStorage.setItem('theme', n);
    document.getElementById('theme-btn').textContent = n === 'dark' ? '☀️' : '🌙';
}}

// Tabs
function switchTab(name, btn) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
}}

// Toast
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2800);
}}

// Auto refresh
let refreshTimer = null;
function scheduleRefresh() {{
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {{
        const modalsOpen = ['modalOverlay','payModalOverlay'].some(
            id => document.getElementById(id).classList.contains('open')
        );
        if (!modalsOpen) location.reload();
        else scheduleRefresh();
    }}, 60000);
}}
function refreshData() {{
    const btn = document.getElementById('refresh-btn');
    btn.innerHTML = '<span class="spinner"></span>';
    setTimeout(() => location.reload(), 300);
}}
scheduleRefresh();

// Status
async function updateStatus(id, status) {{
    const r = await fetch(`/api/appointment/${{id}}/status`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{status}})
    }});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Status atualizado!'); setTimeout(() => location.reload(), 900); }}
    else showToast('❌ Erro ao atualizar');
}}

async function cancelAppt(id) {{
    if (!confirm('Cancelar este agendamento?')) return;
    const r = await fetch(`/api/appointment/${{id}}/cancel`);
    const d = await r.json();
    if (d.success) {{ showToast('🗑️ Cancelado'); setTimeout(() => location.reload(), 900); }}
    else showToast('❌ Erro ao cancelar');
}}

// Modal agendamento
function openModal() {{
    document.getElementById('modalOverlay').classList.add('open');
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('f_date').min   = today;
    document.getElementById('f_date').value = today;
    loadSlots();
}}
function closeModal() {{ document.getElementById('modalOverlay').classList.remove('open'); }}
function handleOverlayClick(e) {{ if (e.target === document.getElementById('modalOverlay')) closeModal(); }}

let selectedTime = null;
async function loadSlots() {{
    const date = document.getElementById('f_date').value;
    if (!date) return;
    selectedTime = null;
    document.getElementById('f_time').value = '';
    let busy = [], dayBlocked = false;
    try {{
        const r = await fetch(`/api/availability?date=${{date}}&tid=${{TENANT_ID}}`);
        const d = await r.json();
        busy = d.busy || [];
        dayBlocked = d.day_blocked || false;
    }} catch(e) {{}}
    const grid = document.getElementById('slots-grid');
    grid.innerHTML = '';
    if (dayBlocked) {{
        grid.innerHTML = '<div style="grid-column:1/-1;color:var(--danger);font-size:13px;text-align:center;padding:12px">🚫 Este dia está bloqueado</div>';
    }} else if (ALL_SLOTS.length === 0) {{
        grid.innerHTML = '<div style="grid-column:1/-1;color:var(--text3);font-size:13px;text-align:center;padding:12px">Nenhum horário configurado</div>';
    }} else {{
        ALL_SLOTS.forEach(slot => {{
            const isBusy = busy.includes(slot);
            const btn    = document.createElement('button');
            btn.textContent = slot;
            btn.className   = 'slot-btn' + (isBusy ? ' busy' : '');
            btn.disabled    = isBusy;
            if (!isBusy) btn.onclick = () => selectSlot(slot, btn);
            grid.appendChild(btn);
        }});
    }}
    document.getElementById('slots-group').style.display = 'block';
}}
function selectSlot(time, btn) {{
    document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
    selectedTime = time;
    document.getElementById('f_time').value = time;
}}

async function submitAppt() {{
    const customer   = document.getElementById('f_customer').value.trim();
    const service_id = document.getElementById('f_service').value;
    const date       = document.getElementById('f_date').value;
    const time       = document.getElementById('f_time').value;
    const pickup     = document.getElementById('f_pickup').value;
    const address    = NEEDS_ADDR ? (document.getElementById('f_address')?.value || '') : '';
    const pet        = SHOW_PET ? document.getElementById('f_pet')?.value.trim() : '';
    const breed      = SHOW_PET ? document.getElementById('f_breed')?.value.trim() : '';
    const weight     = SHOW_PET ? document.getElementById('f_weight')?.value : '';

    if (!customer || !service_id || !date || !time) {{
        showToast('⚠️ Preencha todos os campos obrigatórios e escolha um horário');
        return;
    }}
    if (SHOW_PET && !pet) {{ showToast('⚠️ Informe o nome do {subject}'); return; }}
    if (NEEDS_ADDR && !address.trim()) {{ showToast('⚠️ Informe o endereço'); return; }}

    const btn = document.getElementById('btn-submit');
    btn.disabled    = true;
    btn.innerHTML   = '<span class="spinner"></span> Salvando...';

    try {{
        const payload = {{
            customer_name: customer, service_id,
            scheduled_at: date + 'T' + time + ':00',
            pickup_time:    pickup || null,
            pickup_address: address || null,
            pet_name:   pet    || null,
            pet_breed:  breed  || null,
            pet_weight: weight ? parseFloat(weight) : null,
        }};
        const r = await fetch('/api/appointment/create', {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(payload),
        }});
        const d = await r.json();
        if (d.success) {{
            showToast('🎉 Agendado com sucesso!');
            closeModal();
            setTimeout(() => location.reload(), 1000);
        }} else {{
            showToast('❌ ' + (d.error || 'Erro ao agendar'));
        }}
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
    btn.disabled  = false;
    btn.innerHTML = 'Confirmar Agendamento';
}}

// Modal pagamento
function openPayModal(apptId, defaultAmount) {{
    document.getElementById('pay_appt_id').value = apptId;
    document.getElementById('pay_amount').value  = defaultAmount ? defaultAmount.toFixed(2) : '';
    document.getElementById('pay_method').value  = '';
    document.getElementById('pay_notes').value   = '';
    document.getElementById('pay_pix_key').value = '';
    document.getElementById('pix_section').style.display = 'none';
    document.querySelectorAll('.pay-method-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('payModalOverlay').classList.add('open');
}}
function closePayModal() {{ document.getElementById('payModalOverlay').classList.remove('open'); }}
function handlePayOverlayClick(e) {{ if (e.target === document.getElementById('payModalOverlay')) closePayModal(); }}
function selectPayMethod(method, btn) {{
    document.querySelectorAll('.pay-method-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('pay_method').value = method;
    document.getElementById('pix_section').style.display = method === 'pix' ? 'block' : 'none';
}}
async function confirmPayment(status) {{
    const apptId = document.getElementById('pay_appt_id').value;
    const amount = document.getElementById('pay_amount').value;
    const method = document.getElementById('pay_method').value;
    const notes  = document.getElementById('pay_notes').value;
    const pixKey = document.getElementById('pay_pix_key').value;
    if (status === 'paid' && !method) {{ showToast('⚠️ Selecione a forma de pagamento'); return; }}
    if (status === 'paid' && method === 'pix' && !pixKey) {{
        if (!confirm('⚠️ Confirmou o recebimento no seu banco?\\n\\nNão confirme sem verificar o extrato.')) return;
    }}
    try {{
        const r = await fetch(`/api/appointment/${{apptId}}/payment`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                payment_status: status, payment_method: method || null,
                payment_amount: amount ? parseFloat(amount) : null,
                payment_pix_key: pixKey || null, payment_notes: notes || null,
            }}),
        }});
        const d = await r.json();
        if (d.success) {{
            const msgs = {{paid:'✅ Pagamento confirmado!', waived:'🎁 Isento!', pending:'⏳ Mantido pendente'}};
            showToast(msgs[status] || '✅ Atualizado!');
            closePayModal();
            setTimeout(() => location.reload(), 900);
        }} else showToast('❌ ' + (d.error || 'Erro'));
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
}}

// Serviços
async function saveService(id) {{
    const price = document.getElementById('price-' + id).value;
    const dur   = document.getElementById('dur-' + id).value;
    const r = await fetch(`/api/service/${{id}}/update`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{price: parseFloat(price), duration_min: parseInt(dur)}}),
    }});
    const d = await r.json();
    if (d.success) showToast('✅ Serviço salvo!');
    else showToast('❌ Erro ao salvar');
}}
async function deleteService(id) {{
    if (!confirm('Desativar este serviço?')) return;
    const r = await fetch(`/api/service/${{id}}`, {{method: 'DELETE'}});
    const d = await r.json();
    if (d.success) {{ showToast('🗑️ Serviço desativado'); setTimeout(() => location.reload(), 800); }}
    else showToast('❌ Erro');
}}
async function addService() {{
    const name  = document.getElementById('ns_name').value.trim();
    const price = document.getElementById('ns_price').value;
    const dur   = document.getElementById('ns_dur').value;
    const desc  = document.getElementById('ns_desc').value.trim();
    if (!name) {{ showToast('⚠️ Nome é obrigatório'); return; }}
    const r = await fetch('/api/service/create', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{name, price: parseFloat(price)||0, duration_min: parseInt(dur)||60, description: desc}}),
    }});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Serviço adicionado!'); setTimeout(() => location.reload(), 800); }}
    else showToast('❌ ' + (d.error || 'Erro'));
}}

// Histórico busca
function filterTable() {{
    const q = document.getElementById('search-input').value.toLowerCase();
    document.querySelectorAll('#historico-body tr').forEach(row => {{
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
}}

// Configurações
function toggleConfigDay(btn) {{
    btn.classList.toggle('active');
    const active = [...document.querySelectorAll('#cfg-days-grid .day-btn.active')].map(b => b.dataset.day);
    document.getElementById('cfg_open_days').value = active.join(',');
}}

async function saveConfig() {{
    const display_name       = document.getElementById('cfg_display_name').value.trim();
    const bot_attendant_name = document.getElementById('cfg_attendant').value.trim();
    const owner_phone        = document.getElementById('cfg_owner_phone').value.trim();
    if (!display_name) {{ showToast('⚠️ Nome não pode ser vazio'); return; }}
    const r = await fetch('/api/tenant/config', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{display_name, bot_attendant_name, owner_phone}}),
    }});
    const d = await r.json();
    if (d.success) showToast('✅ Dados salvos!');
    else showToast('❌ ' + (d.error || 'Erro'));
}}

async function saveHorarios() {{
    const open_time  = document.getElementById('cfg_open_time').value;
    const close_time = document.getElementById('cfg_close_time').value;
    const open_days  = document.getElementById('cfg_open_days').value;
    if (!open_days) {{ showToast('⚠️ Selecione ao menos 1 dia'); return; }}
    const r = await fetch('/api/tenant/config', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{open_time, close_time, open_days}}),
    }});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Horários salvos! Recarregando...'); setTimeout(() => location.reload(), 1200); }}
    else showToast('❌ ' + (d.error || 'Erro'));
}}

async function saveToggle(field, value) {{
    const payload = {{}};
    payload[field] = value;
    const r = await fetch('/api/tenant/config', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload),
    }});
    const d = await r.json();
    const label = field === 'bot_active'
        ? (value ? '🤖 Bot ativado!' : '⏸ Bot pausado!')
        : (value ? '🔔 Notificações ativadas!' : '🔕 Notificações desativadas!');
    if (d.success) showToast(label);
    else showToast('❌ Erro ao salvar');
}}

async function changePassword() {{
    const current = document.getElementById('cfg_pw_current').value;
    const newpw   = document.getElementById('cfg_pw_new').value;
    if (!current || !newpw) {{ showToast('⚠️ Preencha os dois campos'); return; }}
    if (newpw.length < 6) {{ showToast('⚠️ Nova senha deve ter ao menos 6 caracteres'); return; }}
    const r = await fetch('/api/tenant/password', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{current_password: current, new_password: newpw}}),
    }});
    const d = await r.json();
    if (d.success) {{
        showToast('✅ Senha alterada! Fazendo logout...');
        setTimeout(() => window.location.href = '/dashboard/logout?tid={tid}', 1500);
    }} else {{
        showToast('❌ ' + (d.error || 'Erro ao alterar senha'));
    }}
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/debug/tenants")
def debug_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "appointments": db.query(Appointment).filter(Appointment.tenant_id == t.id).count()
        }
        for t in tenants
    ]