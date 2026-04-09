from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant
from datetime import datetime, timedelta
from typing import Optional
import pytz, json, bcrypt, secrets

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

def login_page_html(tid: str, error: str = "") -> str:
    err = f'<div class="login-error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Entrar no Painel</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{width:360px;padding:36px;background:#1a1d27;border:1px solid #2d3148;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
.logo{{text-align:center;font-size:28px;margin-bottom:6px}}
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
<div class="logo">🐾</div>
<div class="title">Painel de Agendamentos</div>
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
def dash_login_page(tid: str = "", request: Request = None):
    return HTMLResponse(login_page_html(tid))

@router.post("/dashboard/login")
async def dash_do_login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    tid = form.get("tid", "")
    password = form.get("password", "")
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant or not tenant.dashboard_password:
        return HTMLResponse(login_page_html(tid, "Tenant não encontrado ou sem senha."))
    if not bcrypt.checkpw(password.encode(), tenant.dashboard_password.encode()):
        return HTMLResponse(login_page_html(tid, "Senha incorreta. Tente novamente."))
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
def update_status(appointment_id: str, request_data: dict, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    a = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant.id    # ← garante que pertence ao tenant
    ).first()
    if not a: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = request_data.get("status", a.status)
    db.commit()
    return {"success": True}

@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    a = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.tenant_id == tenant.id    # ← garante que pertence ao tenant
    ).first()
    if not a: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = "cancelled"
    db.commit()
    return {"success": True}

@router.post("/api/appointment/{appointment_id}/payment")
async def update_payment(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    """Marca pagamento de um agendamento (PIX, dinheiro, etc.)"""
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
        try: a.payment_amount = int(float(data["payment_amount"]) * 100)
        except: pass
    a.payment_pix_key = data.get("payment_pix_key", a.payment_pix_key)
    a.payment_notes = data.get("payment_notes", a.payment_notes)
    if a.payment_status == "paid" and not a.payment_paid_at:
        a.payment_paid_at = agora_brasilia()
    elif a.payment_status != "paid":
        a.payment_paid_at = None
    db.commit()
    return {"success": True}

@router.post("/api/appointment/create")
async def create_appt(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        tenant = get_tenant_from_request(request, db)
        if not tenant:
            tid = data.get("tenant_id", "")
            tenant = db.query(Tenant).filter(Tenant.id == tid).first() if tid else None
        if not tenant:
            return JSONResponse({"error": "Não autenticado"}, status_code=401)

        customer_name = data.get("customer_name", "").strip()
        pet_name      = data.get("pet_name", "").strip()
        service_id    = data.get("service_id", "")
        scheduled_str = data.get("scheduled_at", "")

        if not all([customer_name, pet_name, service_id, scheduled_str]):
            return JSONResponse({"error": "Preencha todos os campos obrigatórios"}, status_code=400)

        scheduled_at = datetime.fromisoformat(scheduled_str)

        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id, Customer.name == customer_name
        ).first()
        if not customer:
            customer = Customer(tenant_id=tenant.id, name=customer_name, phone="manual")
            db.add(customer)
            db.flush()

        service = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
        if not service:
            return JSONResponse({"error": "Serviço não encontrado"}, status_code=400)

        appt = Appointment(
            tenant_id=tenant.id, customer_id=customer.id, service_id=service.id,
            pet_name=pet_name,
            pet_breed=data.get("pet_breed") or None,
            pet_weight=float(data.get("pet_weight")) if data.get("pet_weight") else None,
            scheduled_at=scheduled_at,
            pickup_time=data.get("pickup_time") or None,
            status="confirmed",
            payment_status="pending",
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
            Appointment.tenant_id == tenant.id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status != "cancelled"
        ).all()
        return {"busy": [a.scheduled_at.strftime("%H:%M") for a in appts]}
    except:
        return {"busy": []}

@router.get("/api/services")
def get_services(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return {"services": []}
    services = db.query(Service).filter(
        Service.tenant_id == tenant.id, Service.active == True
    ).order_by(Service.name).all()
    return {"services": [
        {"id": s.id, "name": s.name, "price": s.price,
         "duration_min": s.duration_min, "color": s.color}
        for s in services
    ]}

@router.post("/api/service/{service_id}/update")
async def update_service(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
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
    """Cria novo serviço pelo painel do cliente (sem precisar do admin)."""
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Nome é obrigatório"}, status_code=400)
    try:
        price_cents = int(float(data.get("price", 0)) * 100)
    except:
        price_cents = 0
    svc = Service(
        tenant_id=tenant.id,
        name=name,
        duration_min=int(data.get("duration_min", 60)),
        price=price_cents,
        description=data.get("description", ""),
        color=data.get("color", "#6C5CE7"),
        active=True,
    )
    db.add(svc)
    db.commit()
    return {"success": True, "id": str(svc.id)}

@router.delete("/api/service/{service_id}")
def delete_service_api(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant:
        return JSONResponse({"error": "Não autenticado"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
    if svc:
        svc.active = False   # soft-delete (mantém histórico)
        db.commit()
    return {"success": True}

# ── Dashboard principal ────────────────────────────────────────────────────────
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, tid: str = "", tab: str = "hoje", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)

    # Se tem tid na URL e é diferente do tenant logado → força novo login
    # Isso resolve o bug de todos os clientes irem para a mesma agenda
    if tid and tenant and tenant.id != tid:
        resp = RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        resp.delete_cookie("dash_session")  # limpa cookie do tenant anterior
        return resp

    if not tenant:
        if tid:
            return RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        return HTMLResponse("<h2>Acesso negado.</h2>", status_code=401)

    tid = tenant.id
    tenant_name   = tenant.display_name or tenant.name
    subject       = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    subject_plural = getattr(tenant, 'subject_label_plural', 'Pets') or 'Pets'
    hoje = agora_brasilia()
    inicio_hoje = hoje.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    fim_hoje    = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

    agendamentos_hoje = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= inicio_hoje,
        Appointment.scheduled_at <= fim_hoje,
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    amanha_inicio = (hoje + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    proximos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= amanha_inicio,
        Appointment.scheduled_at <= amanha_inicio + timedelta(days=7),
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    historico = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
    ).order_by(Appointment.scheduled_at.desc()).limit(100).all()

    services_all = db.query(Service).filter(Service.tenant_id == tid).order_by(Service.active.desc(), Service.name).all()

    total_clientes    = db.query(Customer).filter(Customer.tenant_id == tid).count()
    em_atendimento    = db.query(Appointment).filter(Appointment.tenant_id == tid, Appointment.status == "in_progress").count()
    prontos           = db.query(Appointment).filter(Appointment.tenant_id == tid, Appointment.status == "ready").count()
    total_agendamentos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.status.in_(["confirmed", "in_progress", "ready", "delivered"])
    ).count()

    # ── Faturamento real do mês (somente pagamentos confirmados) ──
    mes_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    appts_mes_pagos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= mes_inicio,
        Appointment.payment_status == "paid",          # ← SOMENTE pagos
    ).all()
    fat_mes = sum(
        (a.payment_amount or (db.query(Service).filter(Service.id == a.service_id).first() or type('', (), {'price': 0})()).price or 0)
        for a in appts_mes_pagos
    )
    fat_fmt = f"R$ {fat_mes/100:.2f}"

    # ── Pagamentos pendentes do mês ──
    pendentes_mes = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= mes_inicio,
        Appointment.payment_status == "pending",
        Appointment.status != "cancelled",
    ).all()
    fat_pendente = 0
    for a in pendentes_mes:
        svc = db.query(Service).filter(Service.id == a.service_id).first()
        fat_pendente += svc.price if svc else 0
    fat_pendente_fmt = f"R$ {fat_pendente/100:.2f}"

    # Serviço mais agendado
    from collections import Counter
    svc_ids = [a.service_id for a in historico if a.status != "cancelled"]
    top_svc = ""
    if svc_ids:
        most_common_id = Counter(svc_ids).most_common(1)[0][0]
        top_s = db.query(Service).filter(Service.id == most_common_id).first()
        if top_s: top_svc = top_s.name

    # ── Cards de hoje ──
    def _payment_btn(a, svc):
        price_val = (svc.price / 100) if svc else 0
        ps = getattr(a, 'payment_status', 'pending') or 'pending'
        pl, pbg, pc = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
        return f"""<button class="pay-btn" onclick="openPayModal('{a.id}', {price_val})"
            style="background:{pbg};color:{pc};border:1px solid {pc}33;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer;font-family:'DM Sans',sans-serif;font-weight:700">{pl}</button>"""

    cards_hoje = ""
    if not agendamentos_hoje:
        cards_hoje = '<div class="empty-state">🐾 Nenhum agendamento para hoje</div>'
    else:
        for a in agendamentos_hoje:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service  = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            horario  = a.scheduled_at.strftime("%H:%M")
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            pet_info = a.pet_name or subject
            if a.pet_breed: pet_info += f" · {a.pet_breed}"
            if a.pet_weight: pet_info += f" · {a.pet_weight}kg"
            pickup = f"<div class='pickup'>🏠 Busca: {a.pickup_time}</div>" if a.pickup_time else ""
            status_options = "".join(
                f'<option value="{k}" {"selected" if a.status == k else ""}>{sl}</option>'
                for k, (sl, sb, sc) in STATUS_LABELS.items() if k != "cancelled"
            )
            pay_btn = _payment_btn(a, service)
            cards_hoje += f"""
            <div class="appt-card" id="card-{a.id}">
                <div class="appt-time">{horario}</div>
                <div class="appt-body">
                    <div class="appt-client">👤 {nome_cliente}</div>
                    <div class="appt-pet">🐾 {pet_info}</div>
                    <div class="appt-service">✂️ {nome_servico}</div>
                    {pickup}
                </div>
                <div class="appt-actions">
                    <div class="status-badge" style="background:{bg};color:{color}">{label}</div>
                    <select class="status-select" onchange="updateStatus('{a.id}', this.value)">{status_options}</select>
                    {pay_btn}
                    <button class="btn-cancel" onclick="cancelAppt('{a.id}')">✕ Cancelar</button>
                </div>
            </div>"""

    # ── Próximos 7 dias ──
    rows_proximos = ""
    if not proximos:
        rows_proximos = '<tr><td colspan="8" class="empty-row">Nenhum agendamento nos próximos 7 dias.</td></tr>'
    else:
        for a in proximos:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service  = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            ps = getattr(a, 'payment_status', 'pending') or 'pending'
            pl, pbg, pc = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
            rows_proximos += f"""<tr>
                <td>{a.scheduled_at.strftime("%d/%m %H:%M")}</td>
                <td>{nome_cliente}</td>
                <td>{a.pet_name or '-'}</td>
                <td>{(a.pet_breed or '-')} / {(f"{a.pet_weight}kg" if a.pet_weight else '-')}</td>
                <td>{nome_servico}</td>
                <td>{a.pickup_time or '-'}</td>
                <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
                <td><span class="badge" style="background:{pbg};color:{pc};cursor:pointer" onclick="openPayModal('{a.id}', {(service.price/100) if service else 0})">{pl}</span></td>
                <td><button class="btn-cancel-small" onclick="cancelAppt('{a.id}')">✕</button></td>
            </tr>"""

    # ── Histórico ──
    rows_historico = ""
    if not historico:
        rows_historico = '<tr><td colspan="8" class="empty-row">Nenhum histórico.</td></tr>'
    else:
        for a in historico:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service  = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            ps = getattr(a, 'payment_status', 'pending') or 'pending'
            pl, pbg, pc = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
            price_str = f"R$ {(a.payment_amount/100):.2f}" if a.payment_amount else (f"R$ {service.price/100:.2f}" if service else "-")
            rows_historico += f"""<tr>
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td>
                <td>{nome_cliente}</td>
                <td>{a.pet_name or '-'}</td>
                <td>{nome_servico}</td>
                <td>{price_str}</td>
                <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
                <td><span class="badge" style="background:{pbg};color:{pc};cursor:pointer" onclick="openPayModal('{a.id}', {(service.price/100) if service else 0})">{pl}</span></td>
                <td>{a.created_at.strftime("%d/%m/%Y") if a.created_at else '-'}</td>
            </tr>"""

    # ── Aba Pagamentos Pendentes ──
    pendentes_all = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.payment_status == "pending",
        Appointment.status != "cancelled",
    ).order_by(Appointment.scheduled_at.desc()).all()

    rows_pendentes = ""
    if not pendentes_all:
        rows_pendentes = '<tr><td colspan="7" class="empty-row">🎉 Nenhum pagamento pendente!</td></tr>'
    else:
        for a in pendentes_all:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service  = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            price_val  = (service.price / 100) if service else 0
            price_str  = f"R$ {price_val:.2f}"
            status_label, status_bg, status_color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            rows_pendentes += f"""<tr>
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td>
                <td>{nome_cliente}</td>
                <td>{a.pet_name or '-'}</td>
                <td>{nome_servico}</td>
                <td style="font-weight:700;color:#c67d00">{price_str}</td>
                <td><span class="badge" style="background:{status_bg};color:{status_color}">{status_label}</span></td>
                <td>
                    <button class="btn-pay-now" onclick="openPayModal('{a.id}', {price_val})">💳 Registrar pagamento</button>
                </td>
            </tr>"""

    # ── Aba Serviços (com add) ──
    svc_rows = ""
    for s in services_all:
        active_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        price_fmt = f"R$ {s.price/100:.2f}" if s.price else "Grátis"
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

    # Opções de serviço para modal
    service_options = "".join(
        f'<option value="{s.id}">{s.name} — R$ {s.price/100:.2f}</option>'
        for s in services_all if s.active
    )

    # Slots
    open_time  = getattr(tenant, 'open_time',  '09:00') or '09:00'
    close_time = getattr(tenant, 'close_time', '18:00') or '18:00'
    try:
        oh, om = map(int, open_time.split(':'))
        ch, cm = map(int, close_time.split(':'))
    except:
        oh, om, ch, cm = 9, 0, 18, 0
    slots, cur = [], oh * 60 + om
    while cur < ch * 60 + cm:
        slots.append(f"{cur//60:02d}:{cur%60:02d}")
        cur += 30
    slots_json = json.dumps(slots)

    bot_status = getattr(tenant, 'bot_active', True)
    bot_badge  = '<span class="badge badge-green">🤖 Bot ativo</span>' if bot_status else '<span class="badge badge-red">🤖 Bot pausado</span>'

    # ────────────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{tenant_name} — Painel</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root[data-theme="light"]{{--bg:#f4f6fb;--surface:#ffffff;--surface2:#f8f9fc;--border:#e8ecf2;--text:#1a1d23;--text2:#5a6172;--text3:#9aa0b0;--accent:#5B5BD6;--accent2:#7c7de8;--accent-bg:#ededfc;--shadow:rgba(0,0,0,0.06);--shadow2:rgba(0,0,0,0.12);--header-bg:#1a1d23;--header-text:#ffffff;--danger:#e53e3e;--danger-bg:#fff5f5;--success:#2e7d32;--success-bg:#e8f5e9;--warn:#c67d00;--warn-bg:#fff8e1;--info:#1565c0;--info-bg:#e3f2fd;--purple:#6a1b9a;--purple-bg:#f3e5f5;--overlay:rgba(0,0,0,0.4);--input-bg:#f8f9fc;--modal-bg:#ffffff;}}
:root[data-theme="dark"]{{--bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2d3148;--text:#e8eaf2;--text2:#9aa0b8;--text3:#5a6172;--accent:#7c7de8;--accent2:#9c9df0;--accent-bg:#23254a;--shadow:rgba(0,0,0,0.3);--shadow2:rgba(0,0,0,0.5);--header-bg:#13151f;--header-text:#e8eaf2;--danger:#fc8181;--danger-bg:#2d1515;--success:#68d391;--success-bg:#1a2e1a;--warn:#f6c90e;--warn-bg:#2a2200;--info:#63b3ed;--info-bg:#0d2040;--purple:#b794f4;--purple-bg:#2d1a4a;--overlay:rgba(0,0,0,0.7);--input-bg:#1a1d27;--modal-bg:#1a1d27;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.header{{background:var(--header-bg);color:var(--header-text);padding:0 24px;height:56px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}}
.header-logo{{font-size:18px;font-weight:800}}
.header-logo span{{color:var(--accent2)}}
.header-right{{display:flex;align-items:center;gap:8px}}
.btn-icon{{width:34px;height:34px;border-radius:9px;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.07);color:var(--header-text);cursor:pointer;font-size:15px;display:flex;align-items:center;justify-content:center;text-decoration:none;transition:background .2s}}
.btn-icon:hover{{background:rgba(255,255,255,0.14)}}
.btn-primary{{background:var(--accent);color:white;border:none;padding:8px 14px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;display:flex;align-items:center;gap:5px;transition:background .2s}}
.btn-primary:hover{{background:var(--accent2)}}
.container{{max-width:1280px;margin:0 auto;padding:20px}}
.tabs{{display:flex;gap:4px;margin-bottom:20px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px;width:fit-content;flex-wrap:wrap}}
.tab{{padding:8px 16px;border-radius:9px;border:none;background:transparent;color:var(--text2);cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;transition:all .15s}}
.tab.active{{background:var(--accent);color:white}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}}
@media(max-width:900px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
.stat-card{{background:var(--surface);border-radius:12px;padding:14px 16px;border:1px solid var(--border)}}
.stat-number{{font-size:22px;font-weight:800;color:var(--text);line-height:1}}
.stat-label{{font-size:11px;color:var(--text3);margin-top:3px;font-weight:500}}
.stat-card.warn{{border-color:#c67d0060;background:var(--warn-bg)}}
.stat-card.warn .stat-number{{color:var(--warn)}}
.card{{background:var(--surface);border-radius:14px;padding:18px;border:1px solid var(--border);margin-bottom:16px}}
.section-title{{font-size:14px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:7px;margin-bottom:14px}}
.badge-count{{background:var(--accent-bg);color:var(--accent);font-size:11px;padding:2px 7px;border-radius:20px;font-weight:700}}
.appt-card{{display:flex;align-items:flex-start;gap:12px;padding:12px 14px;border-radius:10px;border:1px solid var(--border);margin-bottom:8px;background:var(--surface2);transition:box-shadow .2s,border-color .2s}}
.appt-card:hover{{box-shadow:0 4px 14px var(--shadow2);border-color:var(--accent)}}
.appt-time{{font-size:18px;font-weight:800;color:var(--accent);min-width:55px;text-align:center;font-family:'DM Mono',monospace}}
.appt-body{{flex:1}}
.appt-client{{font-size:13px;font-weight:700;margin-bottom:2px}}
.appt-pet{{font-size:12px;color:var(--text2);margin-bottom:1px}}
.appt-service{{font-size:11px;color:var(--text3)}}
.pickup{{font-size:11px;color:var(--info);margin-top:3px;font-weight:600}}
.appt-actions{{display:flex;flex-direction:column;align-items:flex-end;gap:6px;min-width:160px}}
.status-badge{{font-size:11px;padding:3px 9px;border-radius:20px;font-weight:700;white-space:nowrap}}
.status-select{{font-size:12px;padding:4px 7px;border:1px solid var(--border);border-radius:7px;cursor:pointer;background:var(--input-bg);color:var(--text);width:100%;font-family:'DM Sans',sans-serif}}
.btn-cancel{{font-size:11px;color:var(--danger);background:var(--danger-bg);border:1px solid rgba(229,62,62,0.2);padding:3px 8px;border-radius:7px;cursor:pointer;width:100%;font-family:'DM Sans',sans-serif}}
.btn-cancel-small{{font-size:11px;color:var(--danger);background:var(--danger-bg);border:1px solid rgba(229,62,62,0.2);padding:2px 7px;border-radius:6px;cursor:pointer;font-family:'DM Sans',sans-serif}}
.btn-pay-now{{font-size:12px;background:var(--warn-bg);color:var(--warn);border:1px solid #c67d0040;padding:5px 12px;border-radius:7px;cursor:pointer;font-weight:600;font-family:'DM Sans',sans-serif;white-space:nowrap}}
.btn-pay-now:hover{{background:#c67d00;color:white}}
.empty-state{{color:var(--text3);text-align:center;padding:28px;font-size:13px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:10px;color:var(--text3);font-weight:600;padding:7px 10px;border-bottom:2px solid var(--border);text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
td{{font-size:12px;padding:10px 10px;border-bottom:1px solid var(--border);color:var(--text)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--surface2)}}
.empty-row{{text-align:center;color:var(--text3);padding:24px !important}}
.badge{{font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;white-space:nowrap}}
.badge-green{{background:var(--success-bg);color:var(--success)}}
.badge-red{{background:var(--danger-bg);color:var(--danger)}}
.badge-gray{{background:var(--surface2);color:var(--text3)}}
/* Serviços */
.service-edit-row{{display:flex;align-items:center;gap:10px;padding:11px 14px;border:1px solid var(--border);border-radius:10px;margin-bottom:8px;background:var(--surface2);flex-wrap:wrap}}
.svc-color-dot{{width:10px;height:10px;border-radius:3px;flex-shrink:0}}
.svc-input{{padding:6px 9px;border:1px solid var(--border);border-radius:8px;background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none}}
.svc-input:focus{{border-color:var(--accent)}}
.btn-save-svc{{padding:6px 10px;border-radius:8px;border:1px solid var(--accent);background:var(--accent-bg);color:var(--accent);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif}}
.btn-save-svc:hover{{background:var(--accent);color:white}}
.btn-del-svc{{padding:6px 10px;border-radius:8px;border:1px solid rgba(229,62,62,0.3);background:var(--danger-bg);color:var(--danger);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif}}
/* Add service form */
.add-svc-form{{background:var(--accent-bg);border:1px dashed var(--accent);border-radius:12px;padding:16px;margin-top:14px}}
.add-svc-title{{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:12px}}
.form-row2{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end}}
@media(max-width:600px){{.form-row2{{grid-template-columns:1fr 1fr}}}}
/* Modal */
.modal-overlay{{position:fixed;inset:0;background:var(--overlay);z-index:200;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .25s;backdrop-filter:blur(4px)}}
.modal-overlay.open{{opacity:1;pointer-events:all}}
.modal{{background:var(--modal-bg);border-radius:18px;padding:26px;width:100%;max-width:460px;max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px var(--shadow2);border:1px solid var(--border);transform:translateY(20px);transition:transform .25s;margin:20px}}
.modal-overlay.open .modal{{transform:translateY(0)}}
.modal-title{{font-size:16px;font-weight:800;margin-bottom:18px;color:var(--text);display:flex;align-items:center;justify-content:space-between}}
.modal-close{{width:28px;height:28px;border-radius:7px;border:1px solid var(--border);background:var(--surface2);color:var(--text2);cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center}}
.form-group{{margin-bottom:12px}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
label{{display:block;font-size:11px;font-weight:600;color:var(--text2);margin-bottom:4px;text-transform:uppercase;letter-spacing:.4px}}
input,select{{width:100%;padding:9px 11px;border:1px solid var(--border);border-radius:9px;background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}}
input:focus,select:focus{{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}}
.slots-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px}}
.slot-btn{{padding:7px 4px;border:1px solid var(--border);border-radius:7px;background:var(--surface2);color:var(--text);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Mono',monospace;text-align:center;transition:all .15s}}
.slot-btn:hover{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.slot-btn.selected{{background:var(--accent);color:white;border-color:var(--accent)}}
.slot-btn.busy{{background:var(--danger-bg);color:var(--danger);cursor:not-allowed;opacity:.6}}
.btn-submit{{width:100%;padding:11px;background:var(--accent);color:white;border:none;border-radius:11px;font-size:14px;font-weight:700;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:4px}}
.btn-submit:hover{{background:var(--accent2)}}
.btn-submit:disabled{{opacity:.5;cursor:not-allowed}}
.pay-method-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:6px}}
.pay-method-btn{{padding:10px;border:2px solid var(--border);border-radius:9px;background:var(--surface2);cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;color:var(--text);text-align:center;transition:all .15s}}
.pay-method-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.pay-method-btn.active{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.pix-section{{background:var(--success-bg);border:1px solid var(--success)33;border-radius:10px;padding:12px;margin-top:10px}}
.search-box{{display:flex;gap:8px;margin-bottom:14px}}
.search-input{{flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:9px;background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none}}
.toast{{position:fixed;bottom:20px;right:20px;background:var(--surface);color:var(--text);padding:11px 18px;border-radius:11px;font-size:12px;font-weight:500;border:1px solid var(--border);box-shadow:0 8px 24px var(--shadow2);opacity:0;transition:opacity .3s,transform .3s;z-index:999;transform:translateY(10px)}}
.toast.show{{opacity:1;transform:translateY(0)}}
@media(max-width:600px){{.appt-card{{flex-direction:column}}.appt-actions{{width:100%;flex-direction:row;flex-wrap:wrap}}.form-row{{grid-template-columns:1fr}}.slots-grid{{grid-template-columns:repeat(3,1fr)}}.stats{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>

<div class="header">
    <div class="header-logo">🐾 <span>{tenant_name}</span></div>
    <div class="header-right">
        <span style="font-size:11px;opacity:.5;font-family:'DM Mono',monospace">{hoje.strftime("%d/%m %H:%M")}</span>
        {bot_badge}
        <button class="btn-primary" onclick="openModal()"><span>+</span> Agendar</button>
        <button class="btn-icon" onclick="toggleTheme()" id="theme-btn" title="Tema">🌙</button>
        <button class="btn-icon" onclick="location.reload()" title="Atualizar">↻</button>
        <a href="/dashboard/logout" class="btn-icon" title="Sair" style="text-decoration:none">🚪</a>
    </div>
</div>

<div class="container">

<!-- Stats -->
<div class="stats">
    <div class="stat-card"><div class="stat-number">{len(agendamentos_hoje)}</div><div class="stat-label">📅 Hoje</div></div>
    <div class="stat-card"><div class="stat-number">{em_atendimento}</div><div class="stat-label">✂️ Em atend.</div></div>
    <div class="stat-card"><div class="stat-number">{prontos}</div><div class="stat-label">✅ Prontos</div></div>
    <div class="stat-card"><div class="stat-number">{total_clientes}</div><div class="stat-label">👤 Clientes</div></div>
    <div class="stat-card"><div class="stat-number" style="font-size:14px">{fat_fmt}</div><div class="stat-label">💰 Recebido/mês</div></div>
    <div class="stat-card warn"><div class="stat-number" style="font-size:14px">{fat_pendente_fmt}</div><div class="stat-label">⏳ Pendente/mês</div></div>
</div>

<!-- Tabs -->
<div class="tabs">
    <button class="tab active"  onclick="switchTab('hoje',      this)">📋 Hoje</button>
    <button class="tab"         onclick="switchTab('proximos',  this)">📆 Próximos 7 dias</button>
    <button class="tab"         onclick="switchTab('pendentes', this)">⏳ Pagamentos Pendentes <span class="badge-count">{len(pendentes_all)}</span></button>
    <button class="tab"         onclick="switchTab('historico', this)">📁 Histórico</button>
    <button class="tab"         onclick="switchTab('servicos',  this)">✂️ Serviços</button>
</div>

<!-- Tab: Hoje -->
<div id="tab-hoje" class="tab-content active">
    <div class="card">
        <div class="section-title">📋 Agenda de Hoje <span class="badge-count">{hoje.strftime("%d/%m")}</span></div>
        {cards_hoje}
    </div>
</div>

<!-- Tab: Próximos -->
<div id="tab-proximos" class="tab-content">
    <div class="card">
        <div class="section-title">📆 Próximos 7 dias</div>
        <div class="table-wrap"><table>
            <thead><tr><th>Data/Hora</th><th>Cliente</th><th>{subject}</th><th>Raça/Peso</th><th>Serviço</th><th>Busca</th><th>Status</th><th>Pagamento</th><th></th></tr></thead>
            <tbody>{rows_proximos}</tbody>
        </table></div>
    </div>
</div>

<!-- Tab: Pagamentos Pendentes -->
<div id="tab-pendentes" class="tab-content">
    <div class="card">
        <div class="section-title">⏳ Pagamentos Pendentes
            <span style="font-size:12px;color:var(--text3);font-weight:400">Total a receber: <strong style="color:var(--warn)">{fat_pendente_fmt}</strong></span>
        </div>
        <div class="table-wrap"><table>
            <thead><tr><th>Data/Hora</th><th>Cliente</th><th>{subject}</th><th>Serviço</th><th>Valor</th><th>Status</th><th>Ação</th></tr></thead>
            <tbody>{rows_pendentes}</tbody>
        </table></div>
    </div>
</div>

<!-- Tab: Histórico -->
<div id="tab-historico" class="tab-content">
    <div class="card">
        <div class="section-title">📁 Histórico completo</div>
        <div class="search-box">
            <input class="search-input" id="search-input" placeholder="🔍 Buscar por cliente ou pet..." oninput="filterTable()">
        </div>
        <div class="table-wrap"><table>
            <thead><tr><th>Data/Hora</th><th>Cliente</th><th>{subject}</th><th>Serviço</th><th>Valor</th><th>Status</th><th>Pagamento</th><th>Criado em</th></tr></thead>
            <tbody id="historico-body">{rows_historico}</tbody>
        </table></div>
    </div>
</div>

<!-- Tab: Serviços -->
<div id="tab-servicos" class="tab-content">
    <div class="card">
        <div class="section-title">✂️ Seus serviços</div>
        <div style="font-size:12px;color:var(--text3);margin-bottom:14px">Edite preço e duração diretamente. A IA usa esses dados em tempo real.</div>
        {("" if svc_rows else '<div class="empty-state">Nenhum serviço cadastrado.</div>') + svc_rows}
        {"<div style='font-size:12px;color:var(--text3);margin-top:8px;padding:10px 14px;background:var(--accent-bg);border-radius:8px'>⭐ Mais agendado: <strong>" + top_svc + "</strong></div>" if top_svc else ""}

        <!-- Formulário de novo serviço -->
        <div class="add-svc-form">
            <div class="add-svc-title">➕ Adicionar novo serviço</div>
            <div class="form-row2">
                <div class="form-group" style="margin:0">
                    <label>Nome *</label>
                    <input id="ns_name" placeholder="Ex: Hidratação">
                </div>
                <div class="form-group" style="margin:0">
                    <label>Preço (R$)</label>
                    <input id="ns_price" type="number" step="0.01" placeholder="50.00">
                </div>
                <div class="form-group" style="margin:0">
                    <label>Duração (min)</label>
                    <input id="ns_dur" type="number" value="60">
                </div>
                <div style="display:flex;align-items:flex-end">
                    <button class="btn-submit" onclick="addService()" style="padding:9px 16px;margin:0;width:auto">Adicionar</button>
                </div>
            </div>
            <div class="form-group" style="margin-top:10px;margin-bottom:0">
                <label>Descrição (para o bot)</label>
                <input id="ns_desc" placeholder="Ex: Hidratação com óleos essenciais">
            </div>
        </div>
    </div>
</div>

</div>

<!-- Modal: Novo Agendamento -->
<div class="modal-overlay" id="modalOverlay" onclick="handleOverlayClick(event)">
    <div class="modal" id="modal">
        <div class="modal-title">➕ Novo Agendamento
            <button class="modal-close" onclick="closeModal()">✕</button>
        </div>
        <div class="form-group"><label>👤 Nome do cliente *</label>
        <input type="text" id="f_customer" placeholder="Ex: João Silva" autocomplete="off"></div>
        <div class="form-row">
            <div class="form-group"><label>🐾 {subject} *</label>
            <input type="text" id="f_pet" placeholder="Ex: Rex"></div>
            <div class="form-group"><label>✂️ Serviço *</label>
            <select id="f_service">{service_options}</select></div>
        </div>
        <div class="form-row">
            <div class="form-group"><label>🦴 Raça</label>
            <input type="text" id="f_breed" placeholder="Ex: Golden"></div>
            <div class="form-group"><label>⚖️ Peso (kg)</label>
            <input type="number" id="f_weight" placeholder="15" step="0.1" min="0"></div>
        </div>
        <div class="form-group"><label>📅 Data *</label>
        <input type="date" id="f_date" onchange="loadSlots()"></div>
        <div class="form-group" id="slots-group" style="display:none">
            <div style="font-size:11px;color:var(--text3);margin-bottom:6px">Horários disponíveis</div>
            <div class="slots-grid" id="slots-grid"></div>
            <input type="hidden" id="f_time">
        </div>
        <div class="form-group"><label>🏠 Horário de busca</label>
        <input type="time" id="f_pickup"></div>
        <button class="btn-submit" id="btn-submit" onclick="submitAppt()">Confirmar Agendamento</button>
    </div>
</div>

<!-- Modal: Pagamento -->
<div class="modal-overlay" id="payModalOverlay" onclick="handlePayOverlayClick(event)">
    <div class="modal" id="payModal">
        <div class="modal-title">💳 Registrar Pagamento
            <button class="modal-close" onclick="closePayModal()">✕</button>
        </div>

        <input type="hidden" id="pay_appt_id">

        <div class="form-group">
            <label>Valor (R$)</label>
            <input type="number" id="pay_amount" step="0.01" placeholder="0.00">
        </div>

        <div class="form-group">
            <label>Forma de pagamento</label>
            <div class="pay-method-grid">
                <button class="pay-method-btn" onclick="selectPayMethod('pix', this)">📱 PIX</button>
                <button class="pay-method-btn" onclick="selectPayMethod('dinheiro', this)">💵 Dinheiro</button>
                <button class="pay-method-btn" onclick="selectPayMethod('cartao', this)">💳 Cartão</button>
                <button class="pay-method-btn" onclick="selectPayMethod('outro', this)">📝 Outro</button>
            </div>
            <input type="hidden" id="pay_method" value="">
        </div>

        <div id="pix_section" class="pix-section" style="display:none">
            <label style="color:var(--success);margin-bottom:6px">📱 Chave PIX / Comprovante</label>
            <input type="text" id="pay_pix_key" placeholder="ID do comprovante ou chave PIX">
            <div style="font-size:11px;color:var(--success);margin-top:6px">💡 Cole o ID do comprovante PIX para rastreio</div>
        </div>

        <div class="form-group" style="margin-top:12px">
            <label>Observação</label>
            <input type="text" id="pay_notes" placeholder="Ex: Pagou adiantado, desconto aplicado...">
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px">
            <button class="btn-submit" style="background:var(--success)" onclick="confirmPayment('paid')">✅ Confirmar Pagamento</button>
            <button class="btn-submit" style="background:var(--purple,#6a1b9a)" onclick="confirmPayment('waived')">🎁 Isentar</button>
        </div>
        <button class="btn-submit" style="background:var(--danger-bg);color:var(--danger);border:1px solid rgba(229,62,62,.2);margin-top:8px" onclick="confirmPayment('pending')">⏳ Manter Pendente</button>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const TENANT_ID = '{tid}';
const ALL_SLOTS = {slots_json};

// Tema
const savedTheme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);
document.getElementById('theme-btn').textContent = savedTheme === 'dark' ? '☀️' : '🌙';
function toggleTheme() {{
    const cur  = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    document.getElementById('theme-btn').textContent = next === 'dark' ? '☀️' : '🌙';
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

// Status
async function updateStatus(id, status) {{
    const res  = await fetch(`/api/appointment/${{id}}/status`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{status}})
    }});
    const data = await res.json();
    if (data.success) {{ showToast('✅ Status atualizado!'); setTimeout(() => location.reload(), 900); }}
    else showToast('❌ Erro');
}}

// Cancelar
async function cancelAppt(id) {{
    if (!confirm('Cancelar este agendamento?')) return;
    const res  = await fetch(`/api/appointment/${{id}}/cancel`);
    const data = await res.json();
    if (data.success) {{ showToast('🗑️ Cancelado'); setTimeout(() => location.reload(), 900); }}
    else showToast('❌ Erro');
}}

// ── Modal Agendamento
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
    let busy = [];
    try {{
        const res  = await fetch(`/api/availability?date=${{date}}&tid=${{TENANT_ID}}`);
        const data = await res.json();
        busy = data.busy || [];
    }} catch(e) {{}}
    const grid = document.getElementById('slots-grid');
    grid.innerHTML = '';
    ALL_SLOTS.forEach(slot => {{
        const isBusy = busy.includes(slot);
        const btn    = document.createElement('button');
        btn.textContent = slot;
        btn.className   = 'slot-btn' + (isBusy ? ' busy' : '');
        btn.disabled    = isBusy;
        if (!isBusy) btn.onclick = () => selectSlot(slot, btn);
        grid.appendChild(btn);
    }});
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
    const pet        = document.getElementById('f_pet').value.trim();
    const service_id = document.getElementById('f_service').value;
    const date       = document.getElementById('f_date').value;
    const time       = document.getElementById('f_time').value;
    const pickup     = document.getElementById('f_pickup').value;
    const breed      = document.getElementById('f_breed').value.trim();
    const weight     = document.getElementById('f_weight').value;
    if (!customer || !pet || !service_id || !date || !time) {{
        showToast('⚠️ Preencha todos os campos e escolha um horário');
        return;
    }}
    const btn = document.getElementById('btn-submit');
    btn.disabled = true; btn.textContent = 'Salvando...';
    try {{
        const res  = await fetch('/api/appointment/create', {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{customer_name:customer,pet_name:pet,service_id,
                scheduled_at:date+'T'+time+':00',pickup_time:pickup||null,
                pet_breed:breed||null,pet_weight:weight?parseFloat(weight):null}})
        }});
        const data = await res.json();
        if (data.success) {{ showToast('🎉 Agendado!'); closeModal(); setTimeout(() => location.reload(), 1000); }}
        else showToast('❌ ' + (data.error || 'Erro'));
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
    btn.disabled = false; btn.textContent = 'Confirmar Agendamento';
}}

// ── Modal Pagamento
let payMethod = '';
function openPayModal(apptId, defaultAmount) {{
    document.getElementById('pay_appt_id').value  = apptId;
    document.getElementById('pay_amount').value   = defaultAmount ? defaultAmount.toFixed(2) : '';
    document.getElementById('pay_method').value   = '';
    document.getElementById('pay_notes').value    = '';
    document.getElementById('pay_pix_key').value  = '';
    document.getElementById('pix_section').style.display = 'none';
    document.querySelectorAll('.pay-method-btn').forEach(b => b.classList.remove('active'));
    payMethod = '';
    document.getElementById('payModalOverlay').classList.add('open');
}}
function closePayModal() {{ document.getElementById('payModalOverlay').classList.remove('open'); }}
function handlePayOverlayClick(e) {{ if (e.target === document.getElementById('payModalOverlay')) closePayModal(); }}
function selectPayMethod(method, btn) {{
    payMethod = method;
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
    if (status === 'paid' && !method) {{
        showToast('⚠️ Selecione a forma de pagamento');
        return;
    }}
    try {{
        const res  = await fetch(`/api/appointment/${{apptId}}/payment`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                payment_status: status,
                payment_method: method || null,
                payment_amount: amount ? parseFloat(amount) : null,
                payment_pix_key: pixKey || null,
                payment_notes:  notes  || null,
            }})
        }});
        const data = await res.json();
        if (data.success) {{
            const msgs = {{ paid: '✅ Pagamento registrado!', waived: '🎁 Isento!', pending: '⏳ Mantido como pendente' }};
            showToast(msgs[status] || '✅ Atualizado!');
            closePayModal();
            setTimeout(() => location.reload(), 900);
        }} else showToast('❌ ' + (data.error || 'Erro'));
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
}}

// ── Serviços
async function saveService(id) {{
    const price = document.getElementById('price-' + id).value;
    const dur   = document.getElementById('dur-'   + id).value;
    const res   = await fetch(`/api/service/${{id}}/update`, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{price: parseFloat(price), duration_min: parseInt(dur)}})
    }});
    const data = await res.json();
    if (data.success) showToast('✅ Serviço salvo! A IA já usa os novos valores.');
    else showToast('❌ Erro ao salvar');
}}
async function deleteService(id) {{
    if (!confirm('Desativar este serviço?')) return;
    const res  = await fetch(`/api/service/${{id}}`, {{method: 'DELETE'}});
    const data = await res.json();
    if (data.success) {{ showToast('🗑️ Serviço desativado'); setTimeout(() => location.reload(), 800); }}
    else showToast('❌ Erro');
}}
async function addService() {{
    const name  = document.getElementById('ns_name').value.trim();
    const price = document.getElementById('ns_price').value;
    const dur   = document.getElementById('ns_dur').value;
    const desc  = document.getElementById('ns_desc').value.trim();
    if (!name) {{ showToast('⚠️ Nome é obrigatório'); return; }}
    const res  = await fetch('/api/service/create', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{name, price: parseFloat(price)||0, duration_min: parseInt(dur)||60, description: desc}})
    }});
    const data = await res.json();
    if (data.success) {{ showToast('✅ Serviço adicionado!'); setTimeout(() => location.reload(), 800); }}
    else showToast('❌ ' + (data.error || 'Erro'));
}}

// Busca histórico
function filterTable() {{
    const q = document.getElementById('search-input').value.toLowerCase();
    document.querySelectorAll('#historico-body tr').forEach(row => {{
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
}}

// Auto-refresh (para quando modal estiver fechado)
setInterval(() => {{
    const modals = ['modalOverlay','payModalOverlay'];
    if (!modals.some(id => document.getElementById(id).classList.contains('open'))) location.reload();
}}, 60000);
</script>
</body></html>"""

    return HTMLResponse(content=html)

@router.get("/debug/tenants")
def debug_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).all()
    return [{{
        "id": t.id, "name": t.name,
        "appointments": db.query(Appointment).filter(Appointment.tenant_id == t.id).count()
    }} for t in tenants]