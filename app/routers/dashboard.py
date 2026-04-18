from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant, BlockedSlot
from datetime import datetime, timedelta
import pytz, json, bcrypt, secrets, io, csv

router   = APIRouter()
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

BUSINESS_NO_SUBJECT = {"barbearia", "salao", "estetica", "outro", "clinica_humana", "delivery"}
DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

COLLECT_DEFAULTS = {
    "petshop":        {"pet_name": True,  "pet_breed": True,  "pet_weight": True,  "pickup_time": True,  "address": True,  "notes": False, "phone": False},
    "clinica":        {"pet_name": True,  "pet_breed": True,  "pet_weight": True,  "pickup_time": False, "address": False, "notes": False, "phone": False},
    "clinica_humana": {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "adocao":         {"pet_name": True,  "pet_breed": True,  "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "barbearia":      {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": False, "phone": False},
    "salao":          {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "estetica":       {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "delivery":       {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": True,  "notes": True,  "phone": False},
    "outro":          {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": False, "phone": False},
}

def _get_collect_fields(tenant) -> dict:
    import json as _j
    biz_type = getattr(tenant, 'business_type', 'outro') or 'outro'
    defaults = COLLECT_DEFAULTS.get(biz_type, COLLECT_DEFAULTS["outro"]).copy()
    raw = getattr(tenant, 'collect_fields', None)
    if raw:
        try:
            defaults.update(_j.loads(raw))
        except Exception:
            pass
    return defaults

CHECKOUT_LINKS = {
    "basico":  "https://pay.kiwify.com.br/ypIXFRM",
    "pro":     "https://pay.kiwify.com.br/pndpF39",
    "agencia": "https://pay.kiwify.com.br/O0oUFkt",
}


def _check_plan_feature(tenant, feature: str) -> bool:
    plano       = getattr(tenant, 'plan', 'basico') or 'basico'
    plan_active = getattr(tenant, 'plan_active', True)
    if not plan_active:
        return False
    if feature in ("csv", "lembretes", "servicos_ilimitados"):
        return plano in ("pro", "agencia")
    return True


def _load_customers_map(db, tenant_id, customer_ids):
    if not customer_ids: return {}
    rows = db.query(Customer).filter(Customer.tenant_id == tenant_id, Customer.id.in_(set(customer_ids))).all()
    return {c.id: c for c in rows}


def _load_services_map(db, tenant_id, service_ids):
    if not service_ids: return {}
    rows = db.query(Service).filter(Service.tenant_id == tenant_id, Service.id.in_(set(service_ids))).all()
    return {s.id: s for s in rows}


def get_tenant_from_request(request, db):
    session_cookie = request.cookies.get("dash_session")
    if not session_cookie or ":" not in session_cookie:
        return None
    tid, token = session_cookie.split(":", 1)
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant or tenant.dashboard_token != token:
        return None
    return tenant


def login_page_html(tid, icon="🐾", biz_name="Painel", error=""):
    err = f'<div class="login-error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Entrar — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}}
.box{{width:100%;max-width:360px;padding:36px;background:#1a1d27;border:1px solid #2d3148;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
.logo{{text-align:center;font-size:42px;margin-bottom:6px}}
.title{{text-align:center;font-size:20px;font-weight:800;color:#7c7de8;margin-bottom:4px}}
.sub{{text-align:center;font-size:13px;color:#9aa0b8;margin-bottom:24px}}
label{{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}}
input{{width:100%;padding:11px 14px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none}}
input:focus{{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}}
.btn{{width:100%;padding:13px;background:#5B5BD6;color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:16px;min-height:48px}}
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
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    a = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id).first()
    if not a: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = data.get("status", a.status)
    db.commit()
    return {"success": True}


@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    a = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id).first()
    if not a: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.status = "cancelled"
    db.commit()
    return {"success": True}


@router.post("/api/appointment/{appointment_id}/payment")
async def update_payment(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    a = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.tenant_id == tenant.id).first()
    if not a: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    a.payment_status = data.get("payment_status", a.payment_status)
    a.payment_method = data.get("payment_method", a.payment_method)
    if data.get("payment_amount"):
        try: a.payment_amount = int(float(data["payment_amount"]) * 100)
        except: pass
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
        if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)

        customer_name = data.get("customer_name", "").strip()
        service_id    = data.get("service_id", "")
        scheduled_str = data.get("scheduled_at", "")
        if not all([customer_name, service_id, scheduled_str]):
            return JSONResponse({"error": "Preencha todos os campos obrigatórios"}, status_code=400)

        scheduled_at = datetime.fromisoformat(scheduled_str)
        existing = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id, Appointment.scheduled_at == scheduled_at, Appointment.status != "cancelled"
        ).first()
        if existing: return JSONResponse({"error": "Horário já ocupado"}, status_code=409)

        customer = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.name == customer_name).first()
        if not customer:
            customer = Customer(tenant_id=tenant.id, name=customer_name, phone="manual")
            db.add(customer); db.flush()

        service = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
        if not service: return JSONResponse({"error": "Serviço não encontrado"}, status_code=400)

        pet_name  = (data.get("pet_name") or "").strip() or None
        pet_breed = (data.get("pet_breed") or "").strip() or None
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
        db.add(appt); db.commit()
        return {"success": True, "id": str(appt.id)}
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/availability")
def check_avail(date: str, request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant and tid:
        tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant: return {"busy": []}
    try:
        day   = datetime.strptime(date, "%Y-%m-%d")
        start = day.replace(hour=0,  minute=0,  second=0)
        end   = day.replace(hour=23, minute=59, second=59)
        appts = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id, Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end, Appointment.status != "cancelled"
        ).all()
        busy    = [a.scheduled_at.strftime("%H:%M") for a in appts]
        blocked = db.query(BlockedSlot).filter(BlockedSlot.tenant_id == tenant.id, BlockedSlot.date == date).all()
        for b in blocked:
            if b.time: busy.append(b.time)
        return {"busy": busy, "day_blocked": any(b.time is None for b in blocked)}
    except Exception:
        return {"busy": []}


@router.get("/api/services")
def get_services(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return {"services": []}
    services = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).order_by(Service.name).all()
    return {"services": [{"id": s.id, "name": s.name, "price": s.price, "duration_min": s.duration_min, "color": s.color} for s in services]}


@router.post("/api/service/{service_id}/update")
async def update_service(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    svc  = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
    if not svc: return JSONResponse({"error": "Não encontrado"}, status_code=404)
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
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    if not _check_plan_feature(tenant, "servicos_ilimitados"):
        count = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).count()
        if count >= 7:
            return JSONResponse({"error": "Plano Básico permite até 7 serviços. Faça upgrade para o Plano Pro para adicionar mais."}, status_code=403)
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name: return JSONResponse({"error": "Nome obrigatório"}, status_code=400)
    try: price_cents = int(float(data.get("price", 0)) * 100)
    except: price_cents = 0
    svc = Service(tenant_id=tenant.id, name=name, duration_min=int(data.get("duration_min", 60)),
                  price=price_cents, description=data.get("description", ""), color=data.get("color", "#6C5CE7"), active=True)
    db.add(svc); db.commit()
    return {"success": True, "id": str(svc.id)}


@router.delete("/api/service/{service_id}")
def delete_service_api(service_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
    if svc: svc.active = False; db.commit()
    return {"success": True}


@router.post("/api/tenant/config")
async def save_tenant_config(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    data = await request.json()
    if "display_name" in data and data["display_name"].strip():
        tenant.display_name      = data["display_name"].strip()
        tenant.bot_business_name = data["display_name"].strip()
    if "bot_attendant_name" in data and data["bot_attendant_name"].strip():
        tenant.bot_attendant_name = data["bot_attendant_name"].strip()
    if "owner_phone"  in data: tenant.owner_phone  = (data["owner_phone"] or "").strip() or None
    if "open_time"    in data: tenant.open_time    = data["open_time"]  or "09:00"
    if "close_time"   in data: tenant.close_time   = data["close_time"] or "18:00"
    if "open_days"    in data: tenant.open_days    = data["open_days"]  or "0,1,2,3,4,5"
    if "bot_active"       in data: tenant.bot_active       = bool(data["bot_active"])
    if "notify_new_appt"  in data: tenant.notify_new_appt  = bool(data["notify_new_appt"])
    if "pix_key"          in data: tenant.pix_key          = (data["pix_key"] or "").strip() or None
    if "pix_type"         in data: tenant.pix_type         = data["pix_type"] or "telefone"
    if "payment_methods"  in data: tenant.payment_methods  = (data["payment_methods"] or "").strip() or None
    if "payment_note"     in data: tenant.payment_note     = (data["payment_note"] or "").strip() or None
    if "collect_fields"  in data:
        import json as _j
        try:
            cf = data["collect_fields"]
            if isinstance(cf, dict):
                tenant.collect_fields = _j.dumps(cf)
                tenant.needs_address  = bool(cf.get("address", False))
        except Exception:
            pass
    db.commit()
    return {"success": True}


@router.post("/api/tenant/password")
async def change_password(request: Request, db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
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


@router.get("/api/export/relatorio")
def export_relatorio(request: Request, mes: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    if not tenant: return JSONResponse({"error": "Não autenticado"}, status_code=401)
    if not _check_plan_feature(tenant, "csv"):
        return JSONResponse({"error": "Exportação disponível apenas nos planos Pro e Agência."}, status_code=403)

    needs_address = bool(getattr(tenant, 'needs_address', False))
    address_label = getattr(tenant, 'address_label', 'Endereço') or 'Endereço'
    biz_type      = getattr(tenant, 'business_type', 'outro') or 'outro'
    show_pet      = biz_type not in BUSINESS_NO_SUBJECT
    hoje = agora_brasilia()
    try:    mes_dt = datetime.strptime(mes, "%Y-%m") if mes else hoje.replace(day=1)
    except: mes_dt = hoje.replace(day=1)
    if mes_dt.month == 12: fim_mes = mes_dt.replace(year=mes_dt.year+1, month=1, day=1) - timedelta(seconds=1)
    else:                   fim_mes = mes_dt.replace(month=mes_dt.month+1, day=1) - timedelta(seconds=1)

    appts = db.query(Appointment).filter(
        Appointment.tenant_id == tenant.id,
        Appointment.scheduled_at >= mes_dt, Appointment.scheduled_at <= fim_mes,
    ).order_by(Appointment.scheduled_at).all()

    cmap = _load_customers_map(db, tenant.id, [a.customer_id for a in appts])
    smap = _load_services_map(db, tenant.id, [a.service_id  for a in appts])

    # CSV em StringIO → encode utf-8-sig (BOM) no final
    # Garante que Excel BR abre com acentos corretos e separador ";"
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    header = (["Data/Hora", "Cliente", "Pet", "Raça", "Peso(kg)", "Serviço",
                "Valor(R$)", "Status", "Pagamento", "Método", "PIX", "Busca"]
              if show_pet else
              ["Data/Hora", "Cliente", "Serviço", "Valor(R$)", "Status",
               "Pagamento", "Método", "PIX", "Busca"])
    if needs_address: header.append(address_label)
    writer.writerow(header)

    for a in appts:
        customer     = cmap.get(a.customer_id)
        service      = smap.get(a.service_id)
        # Cliente: mostra nome ou telefone formatado se não tem nome
        if customer:
            if customer.name and customer.name.strip() and customer.name != customer.phone:
                nome_cliente = customer.name.strip()
            else:
                phone = customer.phone or ""
                nome_cliente = phone if phone else "Sem nome"
        else:
            nome_cliente = "Sem nome"

        nome_servico = service.name if service else "-"
        price_raw    = a.payment_amount or (service.price if service else 0) or 0
        valor        = f"R$ {price_raw/100:.2f}".replace(".", ",")
        status_label = STATUS_LABELS.get(a.status, (a.status, "", ""))[0]
        pay_raw      = PAYMENT_LABELS.get(a.payment_status or "pending", (a.payment_status or "", "", ""))[0]
        pay_label    = pay_raw.replace("💳","").replace("✅","").replace("🎁","").strip()
        metodo       = a.payment_method or ""
        pix          = a.payment_pix_key or ""
        busca        = a.pickup_time or ""
        peso         = str(a.pet_weight).replace(".", ",") if a.pet_weight else ""

        row = ([a.scheduled_at.strftime("%d/%m/%Y %H:%M"), nome_cliente,
                a.pet_name or "", a.pet_breed or "", peso,
                nome_servico, valor, status_label, pay_label, metodo, pix, busca]
               if show_pet else
               [a.scheduled_at.strftime("%d/%m/%Y %H:%M"), nome_cliente,
                nome_servico, valor, status_label, pay_label, metodo, pix, busca])
        if needs_address: row.append(a.pickup_address or "")
        writer.writerow(row)

    # Encode com BOM utf-8-sig — acentos corretos no Excel sem configuração
    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    filename  = f"relatorio_{tenant.name}_{mes_dt.strftime('%Y-%m')}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8\'\'{filename}"}
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
        if tid: return RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        return HTMLResponse("<h2>Acesso negado.</h2>", status_code=401)

    tid = tenant.id

    # ── Plano suspenso ────────────────────────────────────────────────────────
    if not getattr(tenant, 'plan_active', True):
        biz_name_sp = tenant.display_name or tenant.name
        return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Conta suspensa — {biz_name_sp}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:#0f0f1a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.box{{max-width:520px;width:100%;background:#1a1a2e;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:40px 32px;text-align:center}}
h1{{font-size:22px;font-weight:800;color:#fff;margin:16px 0 10px}}
p{{font-size:14px;color:#94a3b8;line-height:1.7;margin-bottom:20px}}
.alert{{background:#2d1515;border:1px solid rgba(252,129,129,.2);border-radius:10px;padding:14px 18px;font-size:13px;color:#fc8181;margin-bottom:28px;text-align:left}}
.plans{{display:flex;flex-direction:column;gap:10px;margin-bottom:24px}}
a.plan-btn{{display:block;padding:14px 20px;border-radius:12px;text-decoration:none;font-weight:700;font-size:14px;transition:all .2s}}
.plan-basic{{background:#4c1d95;color:#fff}}.plan-pro{{background:#7c3aed;color:#fff}}
.plan-agency{{background:rgba(124,58,237,0.15);color:#a78bfa;border:1px solid rgba(124,58,237,0.4)}}
.footer{{font-size:12px;color:#475569}}
</style></head><body>
<div class="box">
  <div style="font-size:48px">⚠️</div>
  <h1>Conta suspensa</h1>
  <p>O bot do <strong style="color:#fff">{biz_name_sp}</strong> está pausado porque a assinatura foi cancelada ou houve uma falha no pagamento.</p>
  <div class="alert">✅ Seus dados estão preservados. Reative para voltar a receber agendamentos automaticamente.</div>
  <div class="plans">
    <a href="{CHECKOUT_LINKS['basico']}" class="plan-btn plan-basic" target="_blank">⭐ Reativar — Plano Básico R$97,90/mês</a>
    <a href="{CHECKOUT_LINKS['pro']}" class="plan-btn plan-pro" target="_blank">🚀 Reativar — Plano Pro R$197,90/mês</a>
    <a href="{CHECKOUT_LINKS['agencia']}" class="plan-btn plan-agency" target="_blank">🏢 Reativar — Plano Agência R$497,90/mês</a>
  </div>
  <div class="footer">Dúvidas? Responda o email que você recebeu ou nos chame pelo WhatsApp.</div>
</div></body></html>""")

    # ── Dados do tenant ───────────────────────────────────────────────────────
    tenant_name    = tenant.display_name or tenant.name
    tenant_icon    = getattr(tenant, 'tenant_icon', '🐾') or '🐾'
    biz_type       = getattr(tenant, 'business_type', 'outro') or 'outro'
    subject        = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    subject_plural = getattr(tenant, 'subject_label_plural', 'Pets') or 'Pets'
    needs_address  = bool(getattr(tenant, 'needs_address', False))
    address_label  = getattr(tenant, 'address_label', 'Endereço de busca') or 'Endereço de busca'
    show_pet       = biz_type not in BUSINESS_NO_SUBJECT

    plano           = getattr(tenant, 'plan', 'basico') or 'basico'
    _cf             = _get_collect_fields(tenant)
    plan_active     = getattr(tenant, 'plan_active', True)
    pode_csv        = _check_plan_feature(tenant, "csv")
    pode_lembretes  = _check_plan_feature(tenant, "lembretes")
    pode_svc_ilimit = _check_plan_feature(tenant, "servicos_ilimitados")
    plan_label      = {"basico": "⭐ Básico", "pro": "🚀 Pro", "agencia": "🏢 Agência"}.get(plano, "⭐ Básico")

    hoje        = agora_brasilia()
    inicio_hoje = hoje.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    fim_hoje    = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

    agendamentos_hoje = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.scheduled_at >= inicio_hoje,
        Appointment.scheduled_at <= fim_hoje, Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    amanha_inicio = (hoje + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    proximos = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.scheduled_at >= amanha_inicio,
        Appointment.scheduled_at <= amanha_inicio + timedelta(days=7), Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    historico = db.query(Appointment).filter(Appointment.tenant_id == tid).order_by(Appointment.scheduled_at.desc()).limit(200).all()

    pendentes_all = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.payment_status == "pending", Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at.desc()).all()

    services_all = db.query(Service).filter(Service.tenant_id == tid).order_by(Service.active.desc(), Service.name).all()

    all_appts = list({a.id: a for a in agendamentos_hoje + proximos + historico + pendentes_all}.values())
    cmap = _load_customers_map(db, tid, [a.customer_id for a in all_appts])
    smap = _load_services_map(db, tid, [a.service_id  for a in all_appts])

    total_clientes = db.query(Customer).filter(Customer.tenant_id == tid).count()
    em_atendimento = db.query(Appointment).filter(Appointment.tenant_id == tid, Appointment.status == "in_progress").count()
    prontos        = db.query(Appointment).filter(Appointment.tenant_id == tid, Appointment.status == "ready").count()

    mes_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    appts_mes_pagos = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.scheduled_at >= mes_inicio, Appointment.payment_status == "paid"
    ).all()
    sids_fat = list({a.service_id for a in appts_mes_pagos})
    smap_fat = _load_services_map(db, tid, sids_fat)
    fat_mes  = sum(a.payment_amount if a.payment_amount else (smap_fat.get(a.service_id).price if smap_fat.get(a.service_id) else 0) for a in appts_mes_pagos)

    appts_mes_pend = db.query(Appointment).filter(
        Appointment.tenant_id == tid, Appointment.scheduled_at >= mes_inicio,
        Appointment.payment_status == "pending", Appointment.status != "cancelled"
    ).all()
    sids_pend    = list({a.service_id for a in appts_mes_pend})
    smap_pend    = _load_services_map(db, tid, sids_pend)
    fat_pendente = sum((smap_pend.get(a.service_id).price if smap_pend.get(a.service_id) else 0) for a in appts_mes_pend)
    fat_fmt          = f"R$ {fat_mes/100:.2f}"
    fat_pendente_fmt = f"R$ {fat_pendente/100:.2f}"

    from collections import Counter
    svc_counts = Counter(a.service_id for a in historico if a.status != "cancelled")
    top_svc = ""
    if svc_counts:
        top_s = smap.get(svc_counts.most_common(1)[0][0])
        if top_s: top_svc = top_s.name

    has_services    = any(s.active for s in services_all)
    has_appts       = bool(historico)
    show_onboarding = not has_services and not has_appts
    onboarding_html = ""
    if show_onboarding:
        wa_ok    = bool(getattr(tenant, 'phone_number_id', None))
        own_ok   = bool(getattr(tenant, 'owner_phone', None))
        steps    = [
            ("✅" if has_services else "⬜", "Cadastre seus serviços na aba <strong>Serviços</strong>"),
            ("✅" if wa_ok else "⬜", "WhatsApp configurado pelo suporte"),
            ("✅" if own_ok else "⬜", "Adicione seu número em <strong>Configurações</strong> para receber notificações"),
            ("⬜", "Faça seu primeiro agendamento clicando em <strong>+ Agendar</strong>"),
        ]
        steps_html = "".join(
            f'<div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px">'
            f'<span style="font-size:16px">{s}</span><span style="color:var(--text2)">{t}</span></div>'
            for s, t in steps
        )
        onboarding_html = f'<div class="card" style="border-color:var(--accent);background:var(--accent-bg)"><div class="section-title" style="color:var(--accent)">🚀 Bem-vindo! Configure sua agenda em 4 passos</div>{steps_html}</div>'

    # ── Banner de upgrade ─────────────────────────────────────────────────────
    plano_banner     = ""
    svc_count_banner = sum(1 for s in services_all if s.active)
    if plano == "basico":
        svc_aviso    = f"{svc_count_banner}/7 serviços"
        plano_banner = f"""<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid rgba(124,58,237,0.3);border-radius:14px;padding:16px 20px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
            <div>
                <div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:3px">⭐ Plano Básico · {svc_aviso} · Sem CSV · Sem lembretes</div>
                <div style="font-size:12px;color:#94a3b8">Faça upgrade e desbloqueie relatórios, lembretes automáticos e serviços ilimitados</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <a href="{CHECKOUT_LINKS['pro']}" target="_blank" style="background:#7c3aed;color:#fff;text-decoration:none;padding:8px 16px;border-radius:8px;font-size:12px;font-weight:700;white-space:nowrap">🚀 Upgrade Pro — R$197,90</a>
                <a href="{CHECKOUT_LINKS['agencia']}" target="_blank" style="background:rgba(124,58,237,0.15);color:#a78bfa;text-decoration:none;padding:8px 16px;border-radius:8px;font-size:12px;font-weight:700;border:1px solid rgba(124,58,237,0.3);white-space:nowrap">🏢 Agência — R$497,90</a>
            </div>
        </div>"""
    elif plano == "pro":
        plano_banner = f"""<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid rgba(124,58,237,0.3);border-radius:14px;padding:14px 20px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
            <div style="font-size:13px;color:#94a3b8">🚀 <strong style="color:#a78bfa">Plano Pro</strong> · Tem mais de um negócio? O Plano Agência inclui até 3 negócios no mesmo plano.</div>
            <a href="{CHECKOUT_LINKS['agencia']}" target="_blank" style="background:rgba(124,58,237,0.15);color:#a78bfa;text-decoration:none;padding:8px 16px;border-radius:8px;font-size:12px;font-weight:700;border:1px solid rgba(124,58,237,0.3);white-space:nowrap">🏢 Ver Plano Agência</a>
        </div>"""

    def _pay_btn(a):
        svc      = smap.get(a.service_id)
        price_val = (svc.price / 100) if svc and svc.price else 0
        ps       = getattr(a, 'payment_status', 'pending') or 'pending'
        pl, pbg, pc = PAYMENT_LABELS.get(ps, ("💳 Pend.", "#fff8e1", "#c67d00"))
        return (f'<button onclick="openPayModal(\'{a.id}\', {price_val})" '
                f'style="background:{pbg};color:{pc};border:1px solid {pc}33;font-size:10px;'
                f'padding:3px 8px;border-radius:6px;cursor:pointer;font-family:\'DM Sans\',sans-serif;font-weight:700">{pl}</button>')

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
            status_opts = "".join(
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
                    <select class="status-select" onchange="updateStatus('{a.id}', this.value)">{status_opts}</select>
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
            if show_pet: row += f"<td>{a.pet_name or '-'}</td><td>{a.pet_breed or '-'}/{f'{a.pet_weight}kg' if a.pet_weight else '-'}</td>"
            row += f"<td>{nome_servico}</td><td>{a.pickup_time or '-'}</td>"
            if needs_address: row += f"<td style='font-size:11px;color:var(--success)'>{getattr(a,'pickup_address',None) or '-'}</td>"
            row += (f"<td><span class='badge' style='background:{bg};color:{color}'>{label}</span></td>"
                    f"<td><span class='badge' style='background:{pbg};color:{pc};cursor:pointer' onclick=\"openPayModal('{a.id}',{price_val})\">{pl}</span></td>"
                    f"<td><button class='btn-cancel-small' onclick=\"cancelAppt('{a.id}')\">✕</button></td>")
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
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td><td>{nome_cliente}</td>
                <td>{a.pet_name or '-'}</td><td>{nome_servico}</td><td>{price_str}</td>
                <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
                <td><span class="badge" style="background:{pbg};color:{pc};cursor:pointer" onclick="openPayModal('{a.id}',{price_val})">{pl}</span></td>
                <td>{criado}</td></tr>"""

    # ── Pendentes ─────────────────────────────────────────────────────────────
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
                <td>{a.scheduled_at.strftime("%d/%m/%Y %H:%M")}</td><td>{nome_cliente}</td>{pet_td}
                <td>{nome_servico}</td>
                <td style="font-weight:700;color:var(--warn)">R$ {price_val:.2f}</td>
                <td><span class="badge" style="background:{sbg};color:{sc}">{sl}</span></td>
                <td><button class="btn-pay-now" onclick="openPayModal('{a.id}',{price_val})">💳 Registrar</button></td></tr>"""
    pend_th_pet = f"<th>{subject}</th>" if show_pet else ""

    # ── Serviços ──────────────────────────────────────────────────────────────
    svc_count_active = sum(1 for s in services_all if s.active)
    svc_limite_html  = ""
    if not pode_svc_ilimit:
        cor = "#fc8181" if svc_count_active >= 7 else "#9aa0b8"
        svc_limite_html = f'<div style="font-size:12px;color:{cor};margin-bottom:12px">Plano Básico: {svc_count_active}/7 serviços. {"⚠️ Limite atingido." if svc_count_active >= 7 else ""}</div>'

    svc_rows = ""
    for s in services_all:
        active_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        svc_rows += f"""
        <div class="service-edit-row" id="srow-{s.id}">
            <div class="svc-color-dot" style="background:{s.color or '#6C5CE7'}"></div>
            <div style="flex:1;min-width:0">
                <div style="font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{s.name}</div>
                <div style="font-size:12px;color:var(--text3)">{s.description or ''}</div>
            </div>
            {active_badge}
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <div><div style="font-size:10px;color:var(--text3);margin-bottom:2px">PREÇO</div>
                <input class="svc-input" id="price-{s.id}" value="{s.price/100:.2f}" type="number" step="0.01" style="width:80px"></div>
                <div><div style="font-size:10px;color:var(--text3);margin-bottom:2px">MIN</div>
                <input class="svc-input" id="dur-{s.id}" value="{s.duration_min}" type="number" style="width:60px"></div>
                <button class="btn-save-svc" onclick="saveService('{s.id}')">💾</button>
                <button class="btn-del-svc"  onclick="deleteService('{s.id}')">✕</button>
            </div>
        </div>"""

    service_options = "".join(
        f'<option value="{s.id}">{s.name} — R$ {s.price/100:.2f}</option>'
        for s in services_all if s.active
    )

    add_svc_bloqueado = (not pode_svc_ilimit and svc_count_active >= 7)
    if add_svc_bloqueado:
        add_svc_form = f"""<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid rgba(124,58,237,0.3);border-radius:12px;padding:16px 20px;margin-top:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
            <div>
                <div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:3px">⚠️ Limite de 7 serviços atingido</div>
                <div style="font-size:12px;color:#94a3b8">Faça upgrade para o Plano Pro e tenha serviços ilimitados</div>
            </div>
            <a href="{CHECKOUT_LINKS['pro']}" target="_blank" style="background:#7c3aed;color:#fff;text-decoration:none;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:700;white-space:nowrap">🚀 Upgrade Pro</a>
        </div>"""
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

    # ── Config ────────────────────────────────────────────────────────────────
    open_days_list     = [d.strip() for d in (getattr(tenant, 'open_days', '0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns          = ''.join(f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" data-day="{i}" onclick="toggleConfigDay(this)">{d}</button>' for i,d in enumerate(DAYS_PT))
    bot_active_checked = 'checked' if getattr(tenant, 'bot_active', True) else ''
    notify_checked     = 'checked' if getattr(tenant, 'notify_new_appt', True) else ''
    current_open       = getattr(tenant, 'open_time', '09:00') or '09:00'
    current_close      = getattr(tenant, 'close_time', '18:00') or '18:00'
    current_owner_ph   = getattr(tenant, 'owner_phone', '') or ''
    current_attendant  = getattr(tenant, 'bot_attendant_name', 'Mari') or 'Mari'
    plan_badge_cls     = "badge-green" if plan_active else "badge-red"
    plan_badge_txt     = "Ativo" if plan_active else "Suspenso"

    lembretes_info = ""
    if not pode_lembretes:
        _url_pro = CHECKOUT_LINKS['pro']
        lembretes_info = f'<div style="font-size:12px;color:#94a3b8;margin-top:8px;padding:8px 12px;background:rgba(124,58,237,0.08);border-radius:8px;border-left:3px solid rgba(124,58,237,0.4)">⚠️ Lembretes automáticos disponíveis nos planos Pro e Agência. <a href="{_url_pro}" target="_blank" style="color:#a78bfa;font-weight:700">Fazer upgrade →</a></div>'

    csv_info = ""
    if not pode_csv:
        _url_pro = CHECKOUT_LINKS['pro']
        csv_info = f'<div style="font-size:12px;color:#94a3b8;margin-top:8px;padding:8px 12px;background:rgba(124,58,237,0.08);border-radius:8px;border-left:3px solid rgba(124,58,237,0.4)">⚠️ Exportação CSV disponível nos planos Pro e Agência. <a href="{_url_pro}" target="_blank" style="color:#a78bfa;font-weight:700">Fazer upgrade →</a></div>'

    # Cards upgrade na config
    upgrade_cards_html = ""
    if plano == "basico":
        upgrade_cards_html = f"""
        <div style="display:flex;flex-direction:column;gap:10px;margin:12px 0 4px">
            <div style="border:2px solid #7c3aed;border-radius:12px;padding:16px;background:rgba(124,58,237,0.08)">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                    <div><div style="font-weight:700;color:#a78bfa;font-size:14px">🚀 Plano Pro — R$197,90/mês</div>
                    <div style="font-size:12px;color:var(--text3);margin-top:4px">Serviços ilimitados · Lembretes · CSV · Relatório semanal</div></div>
                    <a href="{CHECKOUT_LINKS['pro']}" target="_blank" style="background:#7c3aed;color:#fff;text-decoration:none;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:700;white-space:nowrap">Fazer upgrade →</a>
                </div>
            </div>
            <div style="border:1px solid var(--border);border-radius:12px;padding:16px;background:var(--surface2)">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                    <div><div style="font-weight:700;color:var(--text);font-size:14px">🏢 Plano Agência — R$497,90/mês</div>
                    <div style="font-size:12px;color:var(--text3);margin-top:4px">Tudo do Pro · Até 3 negócios · Suporte prioritário</div></div>
                    <a href="{CHECKOUT_LINKS['agencia']}" target="_blank" style="background:var(--surface);color:var(--accent);text-decoration:none;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:700;border:1px solid var(--border);white-space:nowrap">Ver Agência →</a>
                </div>
            </div>
        </div>"""
    elif plano == "pro":
        upgrade_cards_html = f"""
        <div style="border:1px solid var(--border);border-radius:12px;padding:16px;background:var(--surface2);margin:12px 0 4px">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
                <div><div style="font-weight:700;color:var(--text);font-size:14px">🏢 Plano Agência — R$497,90/mês</div>
                <div style="font-size:12px;color:var(--text3);margin-top:4px">Tudo do Pro · Até 3 negócios no mesmo plano</div></div>
                <a href="{CHECKOUT_LINKS['agencia']}" target="_blank" style="background:var(--surface);color:var(--accent);text-decoration:none;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:700;border:1px solid var(--border);white-space:nowrap">Ver Agência →</a>
            </div>
        </div>"""
    else:
        upgrade_cards_html = '<div style="font-size:13px;color:var(--text3);padding:8px 0">🏢 Você está no plano Agência — o plano mais completo.</div>'

    # Slots para modal
    open_time  = getattr(tenant, 'open_time', '09:00') or '09:00'
    close_time = getattr(tenant, 'close_time', '18:00') or '18:00'
    try:
        oh, om = map(int, open_time.split(':'))
        ch, cm = map(int, close_time.split(':'))
    except: oh, om, ch, cm = 9, 0, 18, 0
    slots, cur = [], oh * 60 + om
    while cur < ch * 60 + cm:
        slots.append(f"{cur//60:02d}:{cur%60:02d}")
        cur += 30
    slots_json = json.dumps(slots)

    bot_status = getattr(tenant, 'bot_active', True)
    bot_badge  = ('<span class="badge badge-green">🤖 Ativo</span>' if bot_status else '<span class="badge badge-red">🤖 Pausado</span>')
    mes_atual  = hoje.strftime("%Y-%m")
    mes_label  = hoje.strftime("%B/%Y").capitalize()

    address_modal_field = ""
    if needs_address:
        address_modal_field = f'<div class="form-group"><label>📍 {address_label} *</label><input type="text" id="f_address" placeholder="Ex: Rua das Flores, 123 — Centro"></div>'

    if show_pet:
        pet_modal_fields = f"""
        <div class="form-row">
            <div class="form-group"><label>{tenant_icon} {subject} *</label><input type="text" id="f_pet" placeholder="Ex: Rex"></div>
            <div class="form-group"><label>✂️ Serviço *</label><select id="f_service">{service_options}</select></div>
        </div>
        <div class="form-row">
            <div class="form-group"><label>🦴 Raça</label><input type="text" id="f_breed" placeholder="Ex: Golden"></div>
            <div class="form-group"><label>⚖️ Peso (kg)</label><input type="number" id="f_weight" placeholder="15" step="0.1" min="0"></div>
        </div>"""
    else:
        pet_modal_fields = f'<div class="form-group"><label>✂️ Serviço *</label><select id="f_service">{service_options}</select></div>'

    # Botão CSV limpo (sem chr(34))
    if pode_csv:
        csv_btn_html = f'<a href="/api/export/relatorio?mes={mes_atual}" class="btn-icon" title="Exportar {mes_label}" style="text-decoration:none">📥</a>'
    else:
        _url_pro = CHECKOUT_LINKS['pro']
        csv_btn_html = f'<a href="{_url_pro}" target="_blank" class="btn-icon" title="CSV disponível no Plano Pro — clique para fazer upgrade" style="opacity:.5">📥</a>'

    # ── HTML PRINCIPAL ────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
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
.header{{background:var(--header-bg);color:var(--header-text);padding:0 16px;height:56px;
    display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;
    box-shadow:0 2px 12px var(--shadow)}}
.header-logo{{font-size:15px;font-weight:800;display:flex;align-items:center;gap:6px;min-width:0}}
.header-logo .icon{{font-size:20px;flex-shrink:0}}
.header-logo span{{color:var(--accent2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.header-right{{display:flex;align-items:center;gap:5px;flex-wrap:nowrap}}
.btn-icon{{width:36px;height:36px;border-radius:9px;border:1px solid rgba(255,255,255,0.1);
    background:rgba(255,255,255,0.07);color:var(--header-text);cursor:pointer;font-size:15px;
    display:flex;align-items:center;justify-content:center;text-decoration:none;transition:background .2s;flex-shrink:0}}
.btn-icon:hover{{background:rgba(255,255,255,0.14)}}
.btn-primary{{background:var(--accent);color:white;border:none;padding:8px 12px;border-radius:9px;
    cursor:pointer;font-size:13px;font-weight:700;font-family:'DM Sans',sans-serif;
    display:flex;align-items:center;gap:4px;transition:background .15s;white-space:nowrap}}
.btn-primary:hover{{background:var(--accent2)}}
.container{{max-width:1300px;margin:0 auto;padding:16px}}
.tabs{{display:flex;gap:4px;margin-bottom:16px;background:var(--surface);
    border:1px solid var(--border);border-radius:12px;padding:4px;width:fit-content;flex-wrap:wrap}}
.tab{{padding:7px 12px;border-radius:9px;border:none;background:transparent;
    color:var(--text2);cursor:pointer;font-size:12px;font-weight:600;
    font-family:'DM Sans',sans-serif;transition:all .15s;white-space:nowrap}}
.tab.active{{background:var(--accent);color:white}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}}
.stat-card{{background:var(--surface);border-radius:12px;padding:12px 14px;border:1px solid var(--border);transition:box-shadow .2s}}
.stat-card:hover{{box-shadow:0 4px 16px var(--shadow)}}
.stat-number{{font-size:clamp(16px,2.5vw,22px);font-weight:800;color:var(--text);line-height:1}}
.stat-label{{font-size:11px;color:var(--text3);margin-top:3px;font-weight:500}}
.stat-card.warn{{border-color:#c67d0060;background:var(--warn-bg)}}
.stat-card.warn .stat-number{{color:var(--warn)}}
.card{{background:var(--surface);border-radius:14px;padding:16px;border:1px solid var(--border);margin-bottom:14px}}
.section-title{{font-size:14px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:7px;margin-bottom:12px}}
.badge-count{{background:var(--accent-bg);color:var(--accent);font-size:11px;padding:2px 7px;border-radius:20px;font-weight:700}}
.appt-card{{display:flex;align-items:flex-start;gap:10px;padding:11px 12px;border-radius:10px;
    border:1px solid var(--border);margin-bottom:8px;background:var(--surface2);transition:box-shadow .2s,border-color .2s}}
.appt-card:hover{{box-shadow:0 4px 14px var(--shadow2);border-color:var(--accent)}}
.appt-time{{font-size:18px;font-weight:800;color:var(--accent);min-width:52px;text-align:center;font-family:'DM Mono',monospace;padding-top:2px}}
.appt-body{{flex:1;min-width:0}}
.appt-client{{font-size:13px;font-weight:700;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.appt-pet,.appt-service{{font-size:12px;color:var(--text2);margin-bottom:1px}}
.pickup{{font-size:11px;color:var(--info);margin-top:3px;font-weight:600}}
.appt-actions{{display:flex;flex-direction:column;align-items:flex-end;gap:5px;min-width:150px}}
.status-badge{{font-size:11px;padding:3px 9px;border-radius:20px;font-weight:700;white-space:nowrap}}
.status-select{{font-size:12px;padding:4px 7px;border:1px solid var(--border);border-radius:7px;
    cursor:pointer;background:var(--input-bg);color:var(--text);width:100%;font-family:'DM Sans',sans-serif;outline:none}}
.btn-cancel{{font-size:11px;color:var(--danger);background:var(--danger-bg);
    border:1px solid rgba(229,62,62,0.2);padding:4px 8px;border-radius:7px;cursor:pointer;
    width:100%;font-family:'DM Sans',sans-serif;min-height:30px}}
.btn-cancel-small{{font-size:11px;color:var(--danger);background:var(--danger-bg);
    border:1px solid rgba(229,62,62,0.2);padding:3px 7px;border-radius:6px;cursor:pointer;font-family:'DM Sans',sans-serif}}
.btn-pay-now{{font-size:12px;background:var(--warn-bg);color:var(--warn);border:1px solid #c67d0040;
    padding:5px 10px;border-radius:7px;cursor:pointer;font-weight:600;font-family:'DM Sans',sans-serif;white-space:nowrap}}
.btn-pay-now:hover{{background:#c67d00;color:white}}
.empty-state{{color:var(--text3);text-align:center;padding:24px;font-size:13px}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;min-width:500px}}
th{{text-align:left;font-size:10px;color:var(--text3);font-weight:600;
    padding:7px 10px;border-bottom:2px solid var(--border);
    text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
td{{font-size:12px;padding:9px 10px;border-bottom:1px solid var(--border);color:var(--text)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--surface2)}}
.empty-row{{text-align:center;color:var(--text3);padding:24px !important;min-width:unset}}
.badge{{font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;white-space:nowrap}}
.badge-green{{background:var(--success-bg);color:var(--success)}}
.badge-red{{background:var(--danger-bg);color:var(--danger)}}
.badge-gray{{background:var(--surface2);color:var(--text3)}}
.service-edit-row{{display:flex;align-items:center;gap:10px;padding:10px 12px;
    border:1px solid var(--border);border-radius:10px;margin-bottom:8px;background:var(--surface2);flex-wrap:wrap}}
.svc-color-dot{{width:10px;height:10px;border-radius:3px;flex-shrink:0}}
.svc-input{{padding:6px 8px;border:1px solid var(--border);border-radius:8px;
    background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none}}
.svc-input:focus{{border-color:var(--accent)}}
.btn-save-svc{{padding:6px 10px;border-radius:8px;border:1px solid var(--accent);
    background:var(--accent-bg);color:var(--accent);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif}}
.btn-save-svc:hover{{background:var(--accent);color:white}}
.btn-del-svc{{padding:6px 10px;border-radius:8px;border:1px solid rgba(229,62,62,0.3);
    background:var(--danger-bg);color:var(--danger);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif}}
.add-svc-form{{background:var(--accent-bg);border:1px dashed var(--accent);border-radius:12px;padding:14px;margin-top:12px}}
.add-svc-title{{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}}
.form-row2{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end}}
.config-section{{margin-bottom:20px}}
.config-section-title{{font-size:12px;font-weight:700;color:var(--text3);text-transform:uppercase;
    letter-spacing:.5px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border)}}
.config-grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.toggle-wrap{{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;
    background:var(--surface2);border:1px solid var(--border);border-radius:10px;margin-bottom:8px}}
.toggle-label{{font-size:13px;font-weight:600}}
.toggle-sub{{font-size:11px;color:var(--text3);margin-top:2px}}
.toggle-switch{{position:relative;display:inline-block;width:44px;height:24px}}
.toggle-switch input{{opacity:0;width:0;height:0}}
.toggle-slider{{width:44px;height:24px;background:var(--border);border-radius:12px;
    position:absolute;top:0;left:0;transition:background .2s;cursor:pointer}}
.toggle-slider:before{{content:'';position:absolute;width:18px;height:18px;border-radius:50%;
    background:white;top:3px;left:3px;transition:transform .2s}}
.toggle-switch input:checked + .toggle-slider{{background:var(--accent)}}
.toggle-switch input:checked + .toggle-slider:before{{transform:translateX(20px)}}
.days-grid{{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}}
.day-btn{{padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--input-bg);
    color:var(--text2);cursor:pointer;font-size:12px;font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s}}
.day-btn.active{{background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}}
.plan-info{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;
    padding:12px 14px;display:flex;align-items:center;justify-content:space-between}}
.modal-overlay{{position:fixed;inset:0;background:var(--overlay);z-index:200;display:flex;align-items:center;
    justify-content:center;opacity:0;pointer-events:none;transition:opacity .25s;backdrop-filter:blur(4px)}}
.modal-overlay.open{{opacity:1;pointer-events:all}}
.modal{{background:var(--modal-bg);border-radius:18px;padding:24px;width:100%;max-width:480px;
    max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px var(--shadow2);border:1px solid var(--border);
    transform:translateY(20px);transition:transform .25s;margin:16px}}
.modal-overlay.open .modal{{transform:translateY(0)}}
.modal-title{{font-size:16px;font-weight:800;margin-bottom:16px;color:var(--text);
    display:flex;align-items:center;justify-content:space-between}}
.modal-close{{width:28px;height:28px;border-radius:7px;border:1px solid var(--border);
    background:var(--surface2);color:var(--text2);cursor:pointer;font-size:14px;
    display:flex;align-items:center;justify-content:center}}
.form-group{{margin-bottom:12px}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
label{{display:block;font-size:11px;font-weight:600;color:var(--text2);margin-bottom:4px;
    text-transform:uppercase;letter-spacing:.4px}}
input,select{{width:100%;padding:9px 10px;border:1px solid var(--border);border-radius:9px;
    background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;
    outline:none;transition:border-color .2s}}
input:focus,select:focus{{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}}
.slots-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px}}
.slot-btn{{padding:7px 4px;border:1px solid var(--border);border-radius:7px;background:var(--surface2);
    color:var(--text);cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Mono',monospace;text-align:center;transition:all .15s}}
.slot-btn:hover{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.slot-btn.selected{{background:var(--accent);color:white;border-color:var(--accent)}}
.slot-btn.busy{{background:var(--danger-bg);color:var(--danger);cursor:not-allowed;opacity:.6}}
.btn-submit{{width:100%;padding:11px;background:var(--accent);color:white;border:none;border-radius:11px;
    font-size:14px;font-weight:700;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:4px;transition:background .15s;min-height:44px}}
.btn-submit:hover{{background:var(--accent2)}}
.btn-submit:disabled{{opacity:.5;cursor:not-allowed}}
.pay-method-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:6px}}
.pay-method-btn{{padding:10px;border:2px solid var(--border);border-radius:9px;background:var(--surface2);
    cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;color:var(--text);text-align:center;transition:all .15s;min-height:44px}}
.pay-method-btn:hover,.pay-method-btn.active{{border-color:var(--accent);background:var(--accent-bg);color:var(--accent)}}
.pix-section{{background:var(--success-bg);border:1px solid rgba(46,125,50,.3);border-radius:10px;padding:12px;margin-top:10px}}
.pix-review-box{{background:var(--warn-bg);border:1px solid rgba(198,125,0,.3);border-radius:10px;padding:12px;margin-top:10px;font-size:12px;color:var(--warn)}}
.search-box{{display:flex;gap:8px;margin-bottom:12px}}
.search-input{{flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:9px;
    background:var(--input-bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none}}
.toast{{position:fixed;bottom:20px;right:20px;background:var(--surface);color:var(--text);
    padding:11px 16px;border-radius:11px;font-size:12px;font-weight:500;border:1px solid var(--border);
    box-shadow:0 8px 24px var(--shadow2);opacity:0;transition:opacity .3s,transform .3s;z-index:999;transform:translateY(10px);max-width:280px}}
.toast.show{{opacity:1;transform:translateY(0)}}
.alert-info{{background:var(--info-bg);color:var(--info);border:1px solid rgba(21,101,192,.2);
    padding:10px 14px;border-radius:8px;font-size:12px;margin-bottom:12px}}
.spinner{{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);
    border-top-color:white;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@media(max-width:1000px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:600px){{
    .stats{{grid-template-columns:repeat(2,1fr);gap:8px}}
    .appt-card{{flex-direction:column}}
    .appt-time{{min-width:unset;text-align:left}}
    .appt-actions{{width:100%;flex-direction:row;flex-wrap:wrap}}
    .form-row{{grid-template-columns:1fr}}
    .form-row2{{grid-template-columns:1fr 1fr}}
    .config-grid2{{grid-template-columns:1fr}}
    .slots-grid{{grid-template-columns:repeat(3,1fr)}}
    .header-logo span{{max-width:120px}}
    .modal{{margin:8px}}
    .tab{{padding:6px 10px;font-size:11px}}
}}
@media(max-width:380px){{
    .stats{{grid-template-columns:1fr 1fr}}
    .btn-primary span{{display:none}}
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
        <span style="font-size:11px;opacity:.4;font-family:'DM Mono',monospace;display:none" id="time-display"></span>
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
    <button class="tab"        onclick="switchTab('proximos',this)">📆 7 dias</button>
    <button class="tab"        onclick="switchTab('pendentes',this)">⏳ Pgtos <span class="badge-count">{len(pendentes_all)}</span></button>
    <button class="tab"        onclick="switchTab('historico',this)">📁 Histórico</button>
    <button class="tab"        onclick="switchTab('servicos',this)">✂️ Serviços</button>
    <button class="tab"        onclick="switchTab('config',this)">⚙️ Config</button>
</div>

<div id="tab-hoje" class="tab-content active">
    <div class="card">
        <div class="section-title">📋 Hoje <span class="badge-count">{hoje.strftime("%d/%m")}</span></div>
        {cards_hoje}
    </div>
</div>

<div id="tab-proximos" class="tab-content">
    <div class="card">
        <div class="section-title">📆 Próximos 7 dias</div>
        <div class="table-wrap"><table>
            <thead><tr>{prox_th}</tr></thead>
            <tbody>{rows_proximos}</tbody>
        </table></div>
    </div>
</div>

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

<div id="tab-historico" class="tab-content">
    <div class="card">
        <div class="section-title" style="justify-content:space-between">
            <span>📁 Histórico <span style="font-size:11px;color:var(--text3);font-weight:400">(últimos 200)</span></span>
            {'<a href="/api/export/relatorio?mes=' + mes_atual + '" class="btn-save-svc" style="font-size:11px;padding:4px 10px;text-decoration:none">📥 CSV ' + mes_label + '</a>' if pode_csv else '<span style="font-size:11px;color:var(--text3)">CSV disponível no Plano Pro</span>'}
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

<div id="tab-config" class="tab-content">
    <div class="card">
        <div class="section-title">⚙️ Configurações</div>
        <div class="alert-info">💡 Alterações entram em vigor imediatamente para o bot.</div>

        <div class="config-section">
            <div class="config-section-title">📦 Plano e Upgrade</div>
            <div class="plan-info" style="margin-bottom:12px">
                <div>
                    <div style="font-weight:700;font-size:15px">{plan_label}</div>
                    <div style="font-size:12px;color:var(--text3);margin-top:2px">Assinatura gerenciada pela Kiwify</div>
                </div>
                <span class="badge {plan_badge_cls}">{plan_badge_txt}</span>
            </div>
            {upgrade_cards_html}
            {csv_info}
            {lembretes_info}
        </div>

        <div class="config-section">
            <div class="config-section-title">🤖 Bot</div>
            <div class="toggle-wrap">
                <div><div class="toggle-label">Bot ativo</div><div class="toggle-sub">Quando pausado, o bot não responde mensagens</div></div>
                <label class="toggle-switch"><input type="checkbox" id="cfg_bot_active" {bot_active_checked} onchange="saveToggle('bot_active',this.checked)"><span class="toggle-slider"></span></label>
            </div>
            <div class="toggle-wrap">
                <div><div class="toggle-label">Notificações de novos agendamentos</div><div class="toggle-sub">Receber WhatsApp quando o bot confirmar</div></div>
                <label class="toggle-switch"><input type="checkbox" id="cfg_notify" {notify_checked} onchange="saveToggle('notify_new_appt',this.checked)"><span class="toggle-slider"></span></label>
            </div>
        </div>

        <div class="config-section">
            <div class="config-section-title">🏢 Dados do negócio</div>
            <div class="config-grid2">
                <div class="form-group"><label>Nome exibido</label><input type="text" id="cfg_display_name" value="{tenant_name}"></div>
                <div class="form-group"><label>Nome da atendente virtual</label><input type="text" id="cfg_attendant" value="{current_attendant}"></div>
            </div>
            <div class="form-group">
                <label>WhatsApp para notificações (com DDI e DDD)</label>
                <input type="text" id="cfg_owner_phone" value="{current_owner_ph}" placeholder="Ex: 5511999999999">
            </div>
            <button class="btn-submit" style="max-width:200px" onclick="saveConfig()">💾 Salvar dados</button>
        </div>

        <div class="config-section">
            <div class="config-section-title">💳 Pagamento</div>
            <div class="form-group">
                <label>Chave PIX (o bot vai informar ao cliente após confirmar)</label>
                <input type="text" id="cfg_pix_key" value="{{current_pix_key}}" placeholder="Ex: 11999999999 ou email@negocio.com">
                <div style="font-size:11px;color:var(--text3);margin-top:4px">Deixe em branco se preferir combinar pagamento pessoalmente</div>
            </div>
            <div class="form-group">
                <label>Observação de pagamento (aparece após agendamento)</label>
                <input type="text" id="cfg_payment_note" value="{{current_payment_note}}" placeholder="Ex: Pagamento na entrega ou PIX antecipado">
            </div>
            <button class="btn-submit" style="max-width:200px" onclick="savePayment()">💾 Salvar pagamento</button>
        </div>

        <div class="config-section">
            <div class="config-section-title">📋 Campos que o bot coleta</div>
            <div style="font-size:12px;color:var(--text3);margin-bottom:12px">Configure o que a IA pergunta ao cliente durante o agendamento.</div>
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px" id="collect-fields-list">
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">🐾 Nome do pet/animal</div>
                <input type="checkbox" id="cf_pet_name" {"checked" if _cf.get("pet_name") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">🦴 Raça do pet</div>
                <input type="checkbox" id="cf_pet_breed" {"checked" if _cf.get("pet_breed") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">⚖️ Peso do pet</div>
                <input type="checkbox" id="cf_pet_weight" {"checked" if _cf.get("pet_weight") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">🏠 Horário de busca/entrega</div>
                <input type="checkbox" id="cf_pickup_time" {"checked" if _cf.get("pickup_time") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">📍 Endereço de busca/entrega</div>
                <input type="checkbox" id="cf_address" {"checked" if _cf.get("address") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">📝 Observações do cliente</div>
                <input type="checkbox" id="cf_notes" {"checked" if _cf.get("notes") else ""} onchange="saveCollectFields()">
              </label>
              <label style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;cursor:pointer">
                <div style="font-size:13px;font-weight:600">📱 Telefone de contato</div>
                <input type="checkbox" id="cf_phone" {"checked" if _cf.get("phone") else ""} onchange="saveCollectFields()">
              </label>
            </div>
            <div style="font-size:11px;color:var(--text3)">💡 Alterações entram em vigor imediatamente para o bot</div>
        </div>

        <div class="config-section">
            <div class="config-section-title">⏰ Horários de atendimento</div>
            <div class="config-grid2">
                <div class="form-group"><label>Abre às</label><input type="time" id="cfg_open_time" value="{current_open}"></div>
                <div class="form-group"><label>Fecha às</label><input type="time" id="cfg_close_time" value="{current_close}"></div>
            </div>
            <div class="form-group">
                <label>Dias de atendimento</label>
                <div class="days-grid" id="cfg-days-grid">{days_btns}</div>
                <input type="hidden" id="cfg_open_days" value="{','.join(open_days_list)}">
            </div>
            <button class="btn-submit" style="max-width:200px" onclick="saveHorarios()">💾 Salvar horários</button>
        </div>

        <div class="config-section">
            <div class="config-section-title">🔑 Alterar senha</div>
            <div class="config-grid2">
                <div class="form-group"><label>Senha atual</label><input type="password" id="cfg_pw_current" placeholder="••••••••"></div>
                <div class="form-group"><label>Nova senha (mín. 6 caracteres)</label><input type="password" id="cfg_pw_new" placeholder="••••••••"></div>
            </div>
            <button class="btn-submit" style="max-width:200px;background:var(--warn)" onclick="changePassword()">🔑 Alterar senha</button>
            <div style="font-size:11px;color:var(--text3);margin-top:8px">⚠️ Você será desconectado após trocar a senha.</div>
        </div>
    </div>
</div>

</div>

<!-- Modal Agendamento -->
<div class="modal-overlay" id="modalOverlay" onclick="handleOverlayClick(event)">
<div class="modal">
    <div class="modal-title">➕ Novo Agendamento <button class="modal-close" onclick="closeModal()">✕</button></div>
    <div class="form-group"><label>👤 Nome do cliente *</label><input type="text" id="f_customer" placeholder="Ex: João Silva" autocomplete="off"></div>
    {pet_modal_fields}
    <div class="form-group"><label>📅 Data *</label><input type="date" id="f_date" onchange="loadSlots()"></div>
    <div class="form-group" id="slots-group" style="display:none">
        <div style="font-size:11px;color:var(--text3);margin-bottom:6px">Horários disponíveis</div>
        <div class="slots-grid" id="slots-grid"></div>
        <input type="hidden" id="f_time">
    </div>
    <div class="form-group"><label>🏠 Horário de busca (opcional)</label><input type="time" id="f_pickup"></div>
    {address_modal_field}
    <button class="btn-submit" id="btn-submit" onclick="submitAppt()">Confirmar Agendamento</button>
</div>
</div>

<!-- Modal Pagamento -->
<div class="modal-overlay" id="payModalOverlay" onclick="handlePayOverlayClick(event)">
<div class="modal">
    <div class="modal-title">💳 Registrar Pagamento <button class="modal-close" onclick="closePayModal()">✕</button></div>
    <input type="hidden" id="pay_appt_id">
    <div class="form-group"><label>Valor (R$)</label><input type="number" id="pay_amount" step="0.01" placeholder="0.00"></div>
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
        <div class="pix-section"><label style="color:var(--success);margin-bottom:6px;display:block">📱 Comprovante PIX</label>
        <input type="text" id="pay_pix_key" placeholder="Cole o ID/código do comprovante">
        <div style="font-size:11px;color:var(--success);margin-top:6px">💡 Cole o ID para rastreio</div></div>
        <div class="pix-review-box">⚠️ <strong>Atenção:</strong> Confirme no seu app bancário antes de registrar.</div>
    </div>
    <div class="form-group" style="margin-top:12px"><label>Observação</label><input type="text" id="pay_notes" placeholder="Ex: Desconto aplicado..."></div>
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

const savedTheme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);
document.getElementById('theme-btn').textContent = savedTheme === 'dark' ? '☀️' : '🌙';

function toggleTheme() {{
    const n = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', n);
    localStorage.setItem('theme', n);
    document.getElementById('theme-btn').textContent = n === 'dark' ? '☀️' : '🌙';
}}

function updateTime() {{
    const now = new Date();
    const el  = document.getElementById('time-display');
    if (el) {{ el.textContent = now.toLocaleTimeString('pt-BR', {{hour:'2-digit',minute:'2-digit'}}); el.style.display=''; }}
}}
updateTime(); setInterval(updateTime, 30000);

function switchTab(name, btn) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
}}

function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2800);
}}

let refreshTimer = null;
function scheduleRefresh() {{
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {{
        const open = ['modalOverlay','payModalOverlay'].some(id => document.getElementById(id).classList.contains('open'));
        if (!open) location.reload(); else scheduleRefresh();
    }}, 60000);
}}
function refreshData() {{
    document.getElementById('refresh-btn').innerHTML = '<span class="spinner"></span>';
    setTimeout(() => location.reload(), 300);
}}
scheduleRefresh();

async function updateStatus(id, status) {{
    const r = await fetch(`/api/appointment/${{id}}/status`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{status}})}});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Status atualizado!'); setTimeout(()=>location.reload(),900); }}
    else showToast('❌ Erro ao atualizar');
}}

async function cancelAppt(id) {{
    if (!confirm('Cancelar este agendamento?')) return;
    const r = await fetch(`/api/appointment/${{id}}/cancel`);
    const d = await r.json();
    if (d.success) {{ showToast('🗑️ Cancelado'); setTimeout(()=>location.reload(),900); }}
    else showToast('❌ Erro ao cancelar');
}}

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
        busy = d.busy || []; dayBlocked = d.day_blocked || false;
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
            const btn = document.createElement('button');
            btn.textContent = slot;
            btn.className = 'slot-btn' + (isBusy ? ' busy' : '');
            btn.disabled = isBusy;
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
    if (!customer || !service_id || !date || !time) {{ showToast('⚠️ Preencha todos os campos e escolha um horário'); return; }}
    if (SHOW_PET && !pet) {{ showToast('⚠️ Informe o nome do {subject}'); return; }}
    if (NEEDS_ADDR && !address.trim()) {{ showToast('⚠️ Informe o endereço'); return; }}
    const btn = document.getElementById('btn-submit');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Salvando...';
    try {{
        const r = await fetch('/api/appointment/create',{{method:'POST',headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{customer_name:customer,service_id,scheduled_at:date+'T'+time+':00',
            pickup_time:pickup||null,pickup_address:address||null,
            pet_name:pet||null,pet_breed:breed||null,pet_weight:weight?parseFloat(weight):null}})}});
        const d = await r.json();
        if (d.success) {{ showToast('🎉 Agendado!'); closeModal(); setTimeout(()=>location.reload(),1000); }}
        else showToast('❌ ' + (d.error || 'Erro ao agendar'));
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
    btn.disabled = false; btn.innerHTML = 'Confirmar Agendamento';
}}

function openPayModal(apptId, defaultAmount) {{
    document.getElementById('pay_appt_id').value  = apptId;
    document.getElementById('pay_amount').value   = defaultAmount ? defaultAmount.toFixed(2) : '';
    document.getElementById('pay_method').value   = '';
    document.getElementById('pay_notes').value    = '';
    document.getElementById('pay_pix_key').value  = '';
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
        const r = await fetch(`/api/appointment/${{apptId}}/payment`,{{method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{payment_status:status,payment_method:method||null,
            payment_amount:amount?parseFloat(amount):null,
            payment_pix_key:pixKey||null,payment_notes:notes||null}})}});
        const d = await r.json();
        if (d.success) {{
            const msgs={{paid:'✅ Pagamento confirmado!',waived:'🎁 Isento!',pending:'⏳ Mantido pendente'}};
            showToast(msgs[status]||'✅ Atualizado!'); closePayModal(); setTimeout(()=>location.reload(),900);
        }} else showToast('❌ '+(d.error||'Erro'));
    }} catch(e) {{ showToast('❌ Erro de conexão'); }}
}}

async function saveService(id) {{
    const price = document.getElementById('price-'+id).value;
    const dur   = document.getElementById('dur-'+id).value;
    const r = await fetch(`/api/service/${{id}}/update`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{price:parseFloat(price),duration_min:parseInt(dur)}})}});
    const d = await r.json();
    if (d.success) showToast('✅ Serviço salvo!'); else showToast('❌ Erro ao salvar');
}}
async function deleteService(id) {{
    if (!confirm('Desativar este serviço?')) return;
    const r = await fetch(`/api/service/${{id}}`,{{method:'DELETE'}});
    const d = await r.json();
    if (d.success) {{ showToast('🗑️ Desativado'); setTimeout(()=>location.reload(),800); }} else showToast('❌ Erro');
}}
async function addService() {{
    const name  = document.getElementById('ns_name').value.trim();
    const price = document.getElementById('ns_price').value;
    const dur   = document.getElementById('ns_dur').value;
    const desc  = document.getElementById('ns_desc').value.trim();
    if (!name) {{ showToast('⚠️ Nome é obrigatório'); return; }}
    const r = await fetch('/api/service/create',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{name,price:parseFloat(price)||0,duration_min:parseInt(dur)||60,description:desc}})}});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Serviço adicionado!'); setTimeout(()=>location.reload(),800); }}
    else showToast('❌ '+(d.error||'Erro'));
}}

function filterTable() {{
    const q = document.getElementById('search-input').value.toLowerCase();
    document.querySelectorAll('#historico-body tr').forEach(row => {{
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
}}

function toggleConfigDay(btn) {{
    btn.classList.toggle('active');
    const active = [...document.querySelectorAll('#cfg-days-grid .day-btn.active')].map(b => b.dataset.day);
    document.getElementById('cfg_open_days').value = active.join(',');
}}
async function saveCollectFields() {{
    const fields = {{
        pet_name:    document.getElementById('cf_pet_name').checked,
        pet_breed:   document.getElementById('cf_pet_breed').checked,
        pet_weight:  document.getElementById('cf_pet_weight').checked,
        pickup_time: document.getElementById('cf_pickup_time').checked,
        address:     document.getElementById('cf_address').checked,
        notes:       document.getElementById('cf_notes').checked,
        phone:       document.getElementById('cf_phone').checked,
    }};
    const r = await fetch('/api/tenant/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{collect_fields:fields}})}});
    const d = await r.json();
    if (d.success) showToast('✅ Campos atualizados!'); else showToast('❌ Erro ao salvar');
}}
async function savePayment() {{
    const pix_key      = document.getElementById('cfg_pix_key').value.trim();
    const payment_note = document.getElementById('cfg_payment_note').value.trim();
    const r = await fetch('/api/tenant/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pix_key,payment_note}})}});
    const d = await r.json();
    if (d.success) showToast('✅ Pagamento salvo!'); else showToast('❌ '+(d.error||'Erro'));
}}
async function saveConfig() {{
    const display_name       = document.getElementById('cfg_display_name').value.trim();
    const bot_attendant_name = document.getElementById('cfg_attendant').value.trim();
    const owner_phone        = document.getElementById('cfg_owner_phone').value.trim();
    if (!display_name) {{ showToast('⚠️ Nome não pode ser vazio'); return; }}
    const r = await fetch('/api/tenant/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{display_name,bot_attendant_name,owner_phone}})}});
    const d = await r.json();
    if (d.success) showToast('✅ Dados salvos!'); else showToast('❌ '+(d.error||'Erro'));
}}
async function saveHorarios() {{
    const open_time  = document.getElementById('cfg_open_time').value;
    const close_time = document.getElementById('cfg_close_time').value;
    const open_days  = document.getElementById('cfg_open_days').value;
    if (!open_days) {{ showToast('⚠️ Selecione ao menos 1 dia'); return; }}
    const r = await fetch('/api/tenant/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{open_time,close_time,open_days}})}});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Horários salvos!'); setTimeout(()=>location.reload(),1200); }}
    else showToast('❌ '+(d.error||'Erro'));
}}
async function saveToggle(field, value) {{
    const payload = {{}};
    payload[field] = value;
    const r = await fetch('/api/tenant/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
    const d = await r.json();
    const label = field==='bot_active'?(value?'🤖 Bot ativado!':'⏸ Bot pausado!'):(value?'🔔 Notificações ativadas!':'🔕 Notificações desativadas!');
    if (d.success) showToast(label); else showToast('❌ Erro ao salvar');
}}
async function changePassword() {{
    const current = document.getElementById('cfg_pw_current').value;
    const newpw   = document.getElementById('cfg_pw_new').value;
    if (!current || !newpw) {{ showToast('⚠️ Preencha os dois campos'); return; }}
    if (newpw.length < 6) {{ showToast('⚠️ Nova senha deve ter ao menos 6 caracteres'); return; }}
    const r = await fetch('/api/tenant/password',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{current_password:current,new_password:newpw}})}});
    const d = await r.json();
    if (d.success) {{ showToast('✅ Senha alterada! Fazendo logout...'); setTimeout(()=>window.location.href='/dashboard/logout?tid={tid}',1500); }}
    else showToast('❌ '+(d.error||'Erro ao alterar senha'));
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/debug/tenants")
def debug_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).all()
    return [{"id": t.id, "name": t.name, "appointments": db.query(Appointment).filter(Appointment.tenant_id == t.id).count()} for t in tenants]