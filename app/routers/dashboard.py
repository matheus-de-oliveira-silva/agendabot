from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Conversation, Service, Tenant
from datetime import datetime, timedelta
from typing import Optional
import pytz, json, bcrypt, secrets

router = APIRouter()

BRASILIA = pytz.timezone("America/Sao_Paulo")

def agora_brasilia():
    return datetime.now(BRASILIA).replace(tzinfo=None)

STATUS_LABELS = {
    "confirmed": ("Confirmado", "#e8f5e9", "#2e7d32"),
    "in_progress": ("Em atendimento", "#fff8e1", "#f57f17"),
    "ready": ("Pronto p/ busca", "#e3f2fd", "#1565c0"),
    "delivered": ("Entregue", "#f3e5f5", "#6a1b9a"),
    "cancelled": ("Cancelado", "#ffebee", "#c62828"),
}

SERVICES_MAP = {
    "banho_simples": "Banho Simples",
    "banho_tosa": "Banho e Tosa",
    "tosa_higienica": "Tosa Higiênica",
    "consulta": "Consulta Veterinária",
}


# ── Auth helpers ──────────────────────────────────────────────────────────────
def get_tenant_from_request(request: Request, db: Session) -> Optional[object]:
    """Retorna tenant autenticado via cookie de sessão, ou None."""
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

# ── Login / Logout do dashboard ───────────────────────────────────────────────
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
        return HTMLResponse(login_page_html(tid, "Tenant não encontrado ou sem senha configurada."))
    if not bcrypt.checkpw(password.encode(), tenant.dashboard_password.encode()):
        return HTMLResponse(login_page_html(tid, "Senha incorreta. Tente novamente."))
    # Gera/renova token de sessão
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


# ── API para atualizar status ─────────────────────────────────────────────────
@router.post("/api/appointment/{appointment_id}/status")
def update_status(appointment_id: str, request_data: dict, db: Session = Depends(get_db)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        return JSONResponse({"error": "Agendamento não encontrado"}, status_code=404)
    appointment.status = request_data.get("status", appointment.status)
    db.commit()
    return {"success": True, "status": appointment.status}

@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, db: Session = Depends(get_db)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        return JSONResponse({"error": "Não encontrado"}, status_code=404)
    appointment.status = "cancelled"
    db.commit()
    return {"success": True}

@router.post("/api/appointment/create")
def create_appt(request_data: dict, request: Request, db: Session = Depends(get_db)):
    """Cria agendamento manual pelo dashboard"""
    try:
        tenant = get_tenant_from_request(request, db)
        if not tenant:
            # fallback: aceita tid no body para chamadas da API
            tid = request_data.get("tenant_id", "")
            tenant = db.query(Tenant).filter(Tenant.id == tid).first() if tid else None
        if not tenant:
            return JSONResponse({"error": "Não autenticado"}, status_code=401)

        customer_name = request_data.get("customer_name", "").strip()
        pet_name = request_data.get("pet_name", "").strip()
        service_key = request_data.get("service", "")
        scheduled_at_str = request_data.get("scheduled_at", "")
        pickup_time = request_data.get("pickup_time", "")
        pet_breed = request_data.get("pet_breed", "")
        pet_weight = request_data.get("pet_weight")

        if not all([customer_name, pet_name, service_key, scheduled_at_str]):
            return JSONResponse({"error": "Preencha todos os campos obrigatórios"}, status_code=400)

        scheduled_at = datetime.fromisoformat(scheduled_at_str)

        # Busca ou cria cliente
        customer = db.query(Customer).filter(
            Customer.tenant_id == tenant.id,
            Customer.name == customer_name
        ).first()

        if not customer:
            customer = Customer(
                tenant_id=tenant.id,
                name=customer_name,
                phone="manual"  # campo obrigatório no modelo
            )
            db.add(customer)
            db.flush()

        # Busca serviço pelo name (modelo não tem campo 'key')
        service_name = SERVICES_MAP.get(service_key, "")
        service = db.query(Service).filter(
            Service.tenant_id == tenant.id,
            Service.name == service_name,
            Service.active == True
        ).first()

        # Se não achar pelo name exato, pega qualquer serviço ativo como fallback
        if not service:
            service = db.query(Service).filter(
                Service.tenant_id == tenant.id,
                Service.active == True
            ).first()

        if not service:
            return JSONResponse({"error": "Nenhum serviço cadastrado no sistema. Verifique os serviços no banco."}, status_code=400)

        appointment = Appointment(
            tenant_id=tenant.id,
            customer_id=customer.id,
            service_id=service.id,
            pet_name=pet_name,
            pet_breed=pet_breed or None,
            pet_weight=float(pet_weight) if pet_weight else None,
            scheduled_at=scheduled_at,
            pickup_time=pickup_time or None,
            status="confirmed"
        )
        db.add(appointment)
        db.commit()
        return {"success": True, "id": str(appointment.id)}
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api/availability")
def check_avail(date: str, request: Request, tid: str = "", db: Session = Depends(get_db)):
    """Retorna horários ocupados para uma data"""
    tenant = get_tenant_from_request(request, db)
    if not tenant and tid:
        tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        return {"busy": []}
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
        start = day.replace(hour=0, minute=0, second=0)
        end = day.replace(hour=23, minute=59, second=59)
        appts = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
            Appointment.status != "cancelled"
        ).all()
        busy = [a.scheduled_at.strftime("%H:%M") for a in appts]
        return {"busy": busy}
    except:
        return {"busy": []}

# ── Dashboard principal ───────────────────────────────────────────────────────
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = get_tenant_from_request(request, db)
    # Se não autenticado mas tem tid, redireciona para login
    if not tenant:
        if tid:
            return RedirectResponse(f"/dashboard/login?tid={tid}", status_code=302)
        return HTMLResponse("<h2>Acesso negado. Use o link fornecido pelo administrador.</h2>", status_code=401)

    tid = tenant.id
    tenant_name = tenant.display_name or tenant.name
    hoje = agora_brasilia()
    inicio_hoje = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_hoje = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

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

    total_clientes = db.query(Customer).filter(Customer.tenant_id == tid).count()
    total_agendamentos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.status.in_(["confirmed", "in_progress", "ready", "delivered"])
    ).count()
    em_atendimento = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.status == "in_progress"
    ).count()
    prontos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.status == "ready"
    ).count()

    # Cards de hoje
    cards_hoje = ""
    if not agendamentos_hoje:
        cards_hoje = '<div class="empty-state">🐾 Nenhum agendamento para hoje</div>'
    else:
        for a in agendamentos_hoje:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            horario = a.scheduled_at.strftime("%H:%M")
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))

            pet_info = a.pet_name or "Pet"
            if a.pet_breed:
                pet_info += f" · {a.pet_breed}"
            if a.pet_weight:
                pet_info += f" · {a.pet_weight}kg"
            pickup = f"<div class='pickup'>🏠 Busca: {a.pickup_time}</div>" if a.pickup_time else ""

            status_options = ""
            for key, (slabel, sbg, scolor) in STATUS_LABELS.items():
                if key == "cancelled":
                    continue
                selected = "selected" if a.status == key else ""
                status_options += f'<option value="{key}" {selected}>{slabel}</option>'

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
                    <div class="status-badge" style="background:{bg};color:{color}" id="badge-{a.id}">{label}</div>
                    <select class="status-select" onchange="updateStatus('{a.id}', this.value)">
                        {status_options}
                    </select>
                    <button class="btn-cancel" onclick="cancelAppt('{a.id}')">✕ Cancelar</button>
                </div>
            </div>
            """

    # Tabela próximos 7 dias
    rows_proximos = ""
    if not proximos:
        rows_proximos = '<tr><td colspan="8" class="empty-row">Nenhum agendamento nos próximos 7 dias.</td></tr>'
    else:
        for a in proximos:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = (customer.name or customer.phone) if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            data = a.scheduled_at.strftime("%d/%m/%Y")
            horario = a.scheduled_at.strftime("%H:%M")
            label, bg, color = STATUS_LABELS.get(a.status, ("Confirmado", "#e8f5e9", "#2e7d32"))
            pet = a.pet_name or "-"
            raca = a.pet_breed or "-"
            peso = f"{a.pet_weight}kg" if a.pet_weight else "-"
            busca = a.pickup_time or "-"

            rows_proximos += f"""
            <tr>
                <td>{data} {horario}</td>
                <td>{nome_cliente}</td>
                <td>{pet}</td>
                <td>{raca} / {peso}</td>
                <td>{nome_servico}</td>
                <td>{busca}</td>
                <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
                <td><button class="btn-cancel-small" onclick="cancelAppt('{a.id}')">✕</button></td>
            </tr>
            """

    # Opções de serviço para o modal
    service_options = ""
    for key, label in SERVICES_MAP.items():
        service_options += f'<option value="{key}">{label}</option>'

    html = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{tenant_name} — Painel</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root[data-theme="light"] {{
            --bg: #f4f6fb;
            --surface: #ffffff;
            --surface2: #f8f9fc;
            --border: #e8ecf2;
            --text: #1a1d23;
            --text2: #5a6172;
            --text3: #9aa0b0;
            --accent: #5B5BD6;
            --accent2: #7c7de8;
            --accent-bg: #ededfc;
            --shadow: rgba(0,0,0,0.06);
            --shadow2: rgba(0,0,0,0.12);
            --header-bg: #1a1d23;
            --header-text: #ffffff;
            --danger: #e53e3e;
            --danger-bg: #fff5f5;
            --success: #2e7d32;
            --success-bg: #e8f5e9;
            --warn: #c67d00;
            --warn-bg: #fff8e1;
            --info: #1565c0;
            --info-bg: #e3f2fd;
            --purple: #6a1b9a;
            --purple-bg: #f3e5f5;
            --overlay: rgba(0,0,0,0.4);
            --input-bg: #f8f9fc;
            --modal-bg: #ffffff;
        }}
        :root[data-theme="dark"] {{
            --bg: #0f1117;
            --surface: #1a1d27;
            --surface2: #22263a;
            --border: #2d3148;
            --text: #e8eaf2;
            --text2: #9aa0b8;
            --text3: #5a6172;
            --accent: #7c7de8;
            --accent2: #9c9df0;
            --accent-bg: #23254a;
            --shadow: rgba(0,0,0,0.3);
            --shadow2: rgba(0,0,0,0.5);
            --header-bg: #13151f;
            --header-text: #e8eaf2;
            --danger: #fc8181;
            --danger-bg: #2d1515;
            --success: #68d391;
            --success-bg: #1a2e1a;
            --warn: #f6c90e;
            --warn-bg: #2a2200;
            --info: #63b3ed;
            --info-bg: #0d2040;
            --purple: #b794f4;
            --purple-bg: #2d1a4a;
            --overlay: rgba(0,0,0,0.7);
            --input-bg: #1a1d27;
            --modal-bg: #1a1d27;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'DM Sans', sans-serif;
            background: var(--bg);
            color: var(--text);
            transition: background 0.3s, color 0.3s;
            min-height: 100vh;
        }}

        /* HEADER */
        .header {{
            background: var(--header-bg);
            color: var(--header-text);
            padding: 0 28px;
            height: 58px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 1px 0 rgba(255,255,255,0.05), 0 4px 20px var(--shadow2);
        }}
        .header-left {{ display: flex; align-items: center; gap: 12px; }}
        .header-logo {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }}
        .header-logo span {{ color: var(--accent2); }}
        .header-right {{ display: flex; align-items: center; gap: 10px; }}
        .header-time {{ font-size: 12px; opacity: 0.5; font-family: 'DM Mono', monospace; }}

        .btn-icon {{
            width: 36px; height: 36px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.07);
            color: var(--header-text);
            cursor: pointer;
            font-size: 16px;
            display: flex; align-items: center; justify-content: center;
            transition: background 0.2s;
        }}
        .btn-icon:hover {{ background: rgba(255,255,255,0.14); }}

        .btn-primary {{
            background: var(--accent);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            font-family: 'DM Sans', sans-serif;
            display: flex; align-items: center; gap: 6px;
            transition: background 0.2s, transform 0.1s;
        }}
        .btn-primary:hover {{ background: var(--accent2); transform: translateY(-1px); }}
        .btn-primary:active {{ transform: translateY(0); }}

        /* CONTAINER */
        .container {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px; }}

        /* STATS */
        .stats {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-bottom: 22px;
        }}
        @media (max-width: 900px) {{ .stats {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (max-width: 500px) {{ .stats {{ grid-template-columns: 1fr; }} }}

        .stat-card {{
            background: var(--surface);
            border-radius: 14px;
            padding: 18px 20px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 8px var(--shadow);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 16px var(--shadow2); }}
        .stat-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
        .stat-icon {{ font-size: 20px; }}
        .stat-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
        .dot-purple {{ background: var(--accent); }}
        .dot-orange {{ background: #f97316; }}
        .dot-blue {{ background: var(--info); }}
        .dot-green {{ background: #16a34a; }}
        .dot-gray {{ background: var(--text3); }}
        .stat-number {{ font-size: 30px; font-weight: 800; color: var(--text); letter-spacing: -1px; line-height: 1; }}
        .stat-label {{ font-size: 12px; color: var(--text3); margin-top: 4px; font-weight: 500; }}

        /* SECTION */
        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 14px;
        }}
        .section-title {{
            font-size: 15px; font-weight: 700; color: var(--text);
            display: flex; align-items: center; gap: 8px;
        }}
        .badge-count {{
            background: var(--accent-bg);
            color: var(--accent);
            font-size: 11px; padding: 2px 8px;
            border-radius: 20px; font-weight: 700;
        }}

        .card {{
            background: var(--surface);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 8px var(--shadow);
            margin-bottom: 18px;
        }}

        /* APPOINTMENT CARDS */
        .appt-card {{
            display: flex; align-items: flex-start; gap: 14px;
            padding: 14px 16px;
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 10px;
            background: var(--surface2);
            transition: box-shadow 0.2s, border-color 0.2s;
        }}
        .appt-card:hover {{ box-shadow: 0 4px 14px var(--shadow2); border-color: var(--accent); }}
        .appt-time {{
            font-size: 20px; font-weight: 800; color: var(--accent);
            min-width: 60px; text-align: center; padding-top: 2px;
            font-family: 'DM Mono', monospace;
        }}
        .appt-body {{ flex: 1; }}
        .appt-client {{ font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 3px; }}
        .appt-pet {{ font-size: 13px; color: var(--text2); margin-bottom: 2px; }}
        .appt-service {{ font-size: 12px; color: var(--text3); }}
        .pickup {{ font-size: 12px; color: var(--info); margin-top: 4px; font-weight: 600; }}
        .appt-actions {{
            display: flex; flex-direction: column; align-items: flex-end;
            gap: 7px; min-width: 160px;
        }}
        .status-badge {{
            font-size: 11px; padding: 3px 10px;
            border-radius: 20px; font-weight: 700; white-space: nowrap;
        }}
        .status-select {{
            font-size: 12px; padding: 5px 8px;
            border: 1px solid var(--border);
            border-radius: 8px; cursor: pointer;
            background: var(--input-bg); color: var(--text);
            width: 100%; font-family: 'DM Sans', sans-serif;
        }}
        .btn-cancel {{
            font-size: 11px; color: var(--danger);
            background: var(--danger-bg);
            border: 1px solid rgba(229,62,62,0.2);
            padding: 4px 10px; border-radius: 8px;
            cursor: pointer; width: 100%;
            font-family: 'DM Sans', sans-serif;
            transition: background 0.2s;
        }}
        .btn-cancel:hover {{ background: #fed7d7; }}
        .btn-cancel-small {{
            font-size: 11px; color: var(--danger);
            background: var(--danger-bg);
            border: 1px solid rgba(229,62,62,0.2);
            padding: 3px 8px; border-radius: 6px;
            cursor: pointer; font-family: 'DM Sans', sans-serif;
            transition: background 0.2s;
        }}
        .btn-cancel-small:hover {{ background: #fed7d7; }}

        .empty-state {{ color: var(--text3); text-align: center; padding: 32px; font-size: 14px; }}

        /* TABLE */
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{
            text-align: left; font-size: 11px; color: var(--text3);
            font-weight: 600; padding: 8px 12px;
            border-bottom: 2px solid var(--border);
            text-transform: uppercase; letter-spacing: 0.5px;
            white-space: nowrap;
        }}
        td {{
            font-size: 13px; padding: 11px 12px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: var(--surface2); }}
        .empty-row {{ text-align: center; color: var(--text3); padding: 30px !important; }}
        .badge {{
            font-size: 11px; padding: 3px 8px;
            border-radius: 12px; font-weight: 600; white-space: nowrap;
        }}

        /* MODAL */
        .modal-overlay {{
            position: fixed; inset: 0;
            background: var(--overlay);
            z-index: 200;
            display: flex; align-items: center; justify-content: center;
            opacity: 0; pointer-events: none;
            transition: opacity 0.25s;
            backdrop-filter: blur(4px);
        }}
        .modal-overlay.open {{ opacity: 1; pointer-events: all; }}
        .modal {{
            background: var(--modal-bg);
            border-radius: 20px;
            padding: 28px;
            width: 100%;
            max-width: 480px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 20px 60px var(--shadow2);
            border: 1px solid var(--border);
            transform: translateY(20px);
            transition: transform 0.25s;
            margin: 20px;
        }}
        .modal-overlay.open .modal {{ transform: translateY(0); }}
        .modal-title {{
            font-size: 18px; font-weight: 800; margin-bottom: 22px;
            color: var(--text); display: flex; align-items: center;
            justify-content: space-between;
        }}
        .modal-close {{
            width: 30px; height: 30px; border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--surface2); color: var(--text2);
            cursor: pointer; font-size: 16px;
            display: flex; align-items: center; justify-content: center;
        }}
        .modal-close:hover {{ background: var(--danger-bg); color: var(--danger); }}

        .form-group {{ margin-bottom: 14px; }}
        .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        label {{
            display: block; font-size: 12px; font-weight: 600;
            color: var(--text2); margin-bottom: 5px; text-transform: uppercase;
            letter-spacing: 0.4px;
        }}
        input, select, .form-input {{
            width: 100%; padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: var(--input-bg); color: var(--text);
            font-size: 14px; font-family: 'DM Sans', sans-serif;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        input:focus, select:focus {{
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-bg);
        }}
        .slots-grid {{
            display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
            margin-top: 8px;
        }}
        .slot-btn {{
            padding: 8px 4px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--surface2);
            color: var(--text);
            cursor: pointer;
            font-size: 13px; font-weight: 600;
            font-family: 'DM Mono', monospace;
            text-align: center;
            transition: all 0.15s;
        }}
        .slot-btn:hover {{ border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }}
        .slot-btn.selected {{ background: var(--accent); color: white; border-color: var(--accent); }}
        .slot-btn.busy {{ background: var(--danger-bg); color: var(--danger); border-color: rgba(229,62,62,0.3); cursor: not-allowed; opacity: 0.6; }}
        .slot-label {{ font-size: 12px; color: var(--text3); margin-bottom: 8px; }}
        .form-divider {{ height: 1px; background: var(--border); margin: 18px 0; }}

        .btn-submit {{
            width: 100%; padding: 12px;
            background: var(--accent); color: white;
            border: none; border-radius: 12px;
            font-size: 15px; font-weight: 700;
            font-family: 'DM Sans', sans-serif;
            cursor: pointer;
            transition: background 0.2s, transform 0.1s;
            margin-top: 4px;
        }}
        .btn-submit:hover {{ background: var(--accent2); transform: translateY(-1px); }}
        .btn-submit:active {{ transform: translateY(0); }}
        .btn-submit:disabled {{ opacity: 0.5; cursor: not-allowed; transform: none; }}

        /* TOAST */
        .toast {{
            position: fixed; bottom: 24px; right: 24px;
            background: var(--surface);
            color: var(--text);
            padding: 12px 20px; border-radius: 12px;
            font-size: 13px; font-weight: 500;
            border: 1px solid var(--border);
            box-shadow: 0 8px 24px var(--shadow2);
            opacity: 0; transition: opacity 0.3s, transform 0.3s;
            z-index: 999; transform: translateY(10px);
        }}
        .toast.show {{ opacity: 1; transform: translateY(0); }}

        /* Dark mode badge adjustments */
        [data-theme="dark"] .status-badge[style*="#e8f5e9"] {{ background: var(--success-bg) !important; color: var(--success) !important; }}
        [data-theme="dark"] .status-badge[style*="#fff8e1"] {{ background: var(--warn-bg) !important; color: var(--warn) !important; }}
        [data-theme="dark"] .status-badge[style*="#e3f2fd"] {{ background: var(--info-bg) !important; color: var(--info) !important; }}
        [data-theme="dark"] .status-badge[style*="#f3e5f5"] {{ background: var(--purple-bg) !important; color: var(--purple) !important; }}
        [data-theme="dark"] .badge[style*="#e8f5e9"] {{ background: var(--success-bg) !important; color: var(--success) !important; }}
        [data-theme="dark"] .badge[style*="#fff8e1"] {{ background: var(--warn-bg) !important; color: var(--warn) !important; }}
        [data-theme="dark"] .badge[style*="#e3f2fd"] {{ background: var(--info-bg) !important; color: var(--info) !important; }}
        [data-theme="dark"] .badge[style*="#f3e5f5"] {{ background: var(--purple-bg) !important; color: var(--purple) !important; }}

        @media (max-width: 600px) {{
            .appt-card {{ flex-direction: column; }}
            .appt-actions {{ width: 100%; flex-direction: row; flex-wrap: wrap; }}
            .form-row {{ grid-template-columns: 1fr; }}
            .slots-grid {{ grid-template-columns: repeat(3, 1fr); }}
        }}
    </style>
</head>
<body>

<div class="header">
    <div class="header-left">
        <div class="header-logo">🐾 <span>{tenant_name}</span></div>
    </div>
    <div class="header-right">
        <span class="header-time">{hoje.strftime("%d/%m/%Y %H:%M")}</span>
        <button class="btn-primary" onclick="openModal()">
            <span>+</span> Novo Agendamento
        </button>
        <button class="btn-icon" onclick="toggleTheme()" id="theme-btn" title="Modo noturno">🌙</button>
        <button class="btn-icon" onclick="location.reload()" title="Atualizar">↻</button>
        <a href="/dashboard/logout" class="btn-icon" title="Sair" style="text-decoration:none">🚪</a>
    </div>
</div>

<div class="container">

    <div class="stats">
        <div class="stat-card">
            <div class="stat-top"><span class="stat-icon">📅</span><span class="stat-dot dot-purple"></span></div>
            <div class="stat-number">{len(agendamentos_hoje)}</div>
            <div class="stat-label">Agendamentos hoje</div>
        </div>
        <div class="stat-card">
            <div class="stat-top"><span class="stat-icon">✂️</span><span class="stat-dot dot-orange"></span></div>
            <div class="stat-number">{em_atendimento}</div>
            <div class="stat-label">Em atendimento</div>
        </div>
        <div class="stat-card">
            <div class="stat-top"><span class="stat-icon">✅</span><span class="stat-dot dot-blue"></span></div>
            <div class="stat-number">{prontos}</div>
            <div class="stat-label">Prontos p/ busca</div>
        </div>
        <div class="stat-card">
            <div class="stat-top"><span class="stat-icon">👤</span><span class="stat-dot dot-green"></span></div>
            <div class="stat-number">{total_clientes}</div>
            <div class="stat-label">Clientes cadastrados</div>
        </div>
        <div class="stat-card">
            <div class="stat-top"><span class="stat-icon">📊</span><span class="stat-dot dot-gray"></span></div>
            <div class="stat-number">{total_agendamentos}</div>
            <div class="stat-label">Total agendamentos</div>
        </div>
    </div>

    <!-- Agenda de Hoje -->
    <div class="card">
        <div class="section-header">
            <div class="section-title">
                📋 Agenda de Hoje
                <span class="badge-count">{hoje.strftime("%d/%m")}</span>
            </div>
        </div>
        {cards_hoje}
    </div>

    <!-- Próximos 7 dias -->
    <div class="card">
        <div class="section-header">
            <div class="section-title">📆 Próximos 7 dias</div>
        </div>
        <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Data / Hora</th>
                    <th>Cliente</th>
                    <th>Pet</th>
                    <th>Raça / Peso</th>
                    <th>Serviço</th>
                    <th>Busca</th>
                    <th>Status</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                {rows_proximos}
            </tbody>
        </table>
        </div>
    </div>

</div>

<!-- Modal Novo Agendamento -->
<div class="modal-overlay" id="modalOverlay" onclick="handleOverlayClick(event)">
    <div class="modal" id="modal">
        <div class="modal-title">
            ➕ Novo Agendamento
            <button class="modal-close" onclick="closeModal()">✕</button>
        </div>

        <div class="form-group">
            <label>👤 Nome do cliente *</label>
            <input type="text" id="f_customer" placeholder="Ex: João Silva" autocomplete="off">
        </div>

        <div class="form-row">
            <div class="form-group">
                <label>🐾 Nome do pet *</label>
                <input type="text" id="f_pet" placeholder="Ex: Rex">
            </div>
            <div class="form-group">
                <label>✂️ Serviço *</label>
                <select id="f_service">
                    {service_options}
                </select>
            </div>
        </div>

        <div class="form-row">
            <div class="form-group">
                <label>🦴 Raça</label>
                <input type="text" id="f_breed" placeholder="Ex: Golden Retriever">
            </div>
            <div class="form-group">
                <label>⚖️ Peso (kg)</label>
                <input type="number" id="f_weight" placeholder="Ex: 15" step="0.1" min="0">
            </div>
        </div>

        <div class="form-divider"></div>

        <div class="form-group">
            <label>📅 Data *</label>
            <input type="date" id="f_date" onchange="loadSlots()">
        </div>

        <div class="form-group" id="slots-group" style="display:none">
            <div class="slot-label">Horários disponíveis (clique para selecionar)</div>
            <div class="slots-grid" id="slots-grid"></div>
            <input type="hidden" id="f_time">
        </div>

        <div class="form-group">
            <label>🏠 Horário de busca</label>
            <input type="time" id="f_pickup" placeholder="Ex: 18:00">
        </div>

        <button class="btn-submit" id="btn-submit" onclick="submitAppt()">
            Confirmar Agendamento
        </button>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
    const TENANT_ID = '{tid}';
    // ── Tema ──────────────────────────────────────────────────────────────────
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    document.getElementById('theme-btn').textContent = savedTheme === 'dark' ? '☀️' : '🌙';

    function toggleTheme() {{
        const html = document.documentElement;
        const current = html.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
        document.getElementById('theme-btn').textContent = next === 'dark' ? '☀️' : '🌙';
    }}

    // ── Toast ─────────────────────────────────────────────────────────────────
    function showToast(msg) {{
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        setTimeout(() => t.classList.remove('show'), 2800);
    }}

    // ── Status ────────────────────────────────────────────────────────────────
    async function updateStatus(id, status) {{
        try {{
            const res = await fetch(`/api/appointment/${{id}}/status`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{status}})
            }});
            const data = await res.json();
            if (data.success) {{
                showToast('✅ Status atualizado!');
                setTimeout(() => location.reload(), 1000);
            }}
        }} catch(e) {{ showToast('❌ Erro ao atualizar status'); }}
    }}

    // ── Cancelar ─────────────────────────────────────────────────────────────
    async function cancelAppt(id) {{
        if (!confirm('Cancelar este agendamento?')) return;
        try {{
            const res = await fetch(`/api/appointment/${{id}}/cancel`);
            const data = await res.json();
            if (data.success) {{
                showToast('🗑️ Agendamento cancelado');
                setTimeout(() => location.reload(), 1000);
            }}
        }} catch(e) {{ showToast('❌ Erro ao cancelar'); }}
    }}

    // ── Modal ─────────────────────────────────────────────────────────────────
    function openModal() {{
        document.getElementById('modalOverlay').classList.add('open');
        // Define data mínima como hoje
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('f_date').min = today;
        document.getElementById('f_date').value = today;
        loadSlots();
    }}
    function closeModal() {{
        document.getElementById('modalOverlay').classList.remove('open');
    }}
    function handleOverlayClick(e) {{
        if (e.target === document.getElementById('modalOverlay')) closeModal();
    }}

    // ── Slots ─────────────────────────────────────────────────────────────────
    let selectedTime = null;
    const ALL_SLOTS = ['09:00','09:30','10:00','10:30','11:00','11:30',
                       '12:00','12:30','13:00','13:30','14:00','14:30',
                       '15:00','15:30','16:00','16:30','17:00','17:30'];

    async function loadSlots() {{
        const date = document.getElementById('f_date').value;
        if (!date) return;

        // Verifica se é domingo
        const d = new Date(date + 'T00:00:00');
        if (d.getDay() === 0) {{
            document.getElementById('slots-group').style.display = 'block';
            document.getElementById('slots-grid').innerHTML =
                '<div style="grid-column:1/-1;color:var(--danger);font-size:13px;text-align:center;padding:12px">🚫 Fechado aos domingos</div>';
            return;
        }}

        selectedTime = null;
        document.getElementById('f_time').value = '';

        let busy = [];
        try {{
            const res = await fetch(`/api/availability?date=${{date}}&tid=${{TENANT_ID}}`);
            const data = await res.json();
            busy = data.busy || [];
        }} catch(e) {{}}

        const grid = document.getElementById('slots-grid');
        grid.innerHTML = '';
        ALL_SLOTS.forEach(slot => {{
            const isBusy = busy.includes(slot);
            const btn = document.createElement('button');
            btn.textContent = slot;
            btn.className = 'slot-btn' + (isBusy ? ' busy' : '');
            btn.disabled = isBusy;
            if (!isBusy) {{
                btn.onclick = () => selectSlot(slot, btn);
            }}
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

    // ── Criar agendamento ────────────────────────────────────────────────────
    async function submitAppt() {{
        const customer = document.getElementById('f_customer').value.trim();
        const pet = document.getElementById('f_pet').value.trim();
        const service = document.getElementById('f_service').value;
        const date = document.getElementById('f_date').value;
        const time = document.getElementById('f_time').value;
        const pickup = document.getElementById('f_pickup').value;
        const breed = document.getElementById('f_breed').value.trim();
        const weight = document.getElementById('f_weight').value;

        if (!customer || !pet || !service || !date || !time) {{
            showToast('⚠️ Preencha todos os campos obrigatórios e escolha um horário');
            return;
        }}

        const btn = document.getElementById('btn-submit');
        btn.disabled = true;
        btn.textContent = 'Salvando...';

        try {{
            const res = await fetch('/api/appointment/create', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    customer_name: customer,
                    pet_name: pet,
                    service: service,
                    scheduled_at: date + 'T' + time + ':00',
                    pickup_time: pickup || null,
                    pet_breed: breed || null,
                    pet_weight: weight ? parseFloat(weight) : null
                }})
            }});
            const data = await res.json();
            if (data.success) {{
                showToast('🎉 Agendamento criado com sucesso!');
                closeModal();
                setTimeout(() => location.reload(), 1200);
            }} else {{
                showToast('❌ ' + (data.error || 'Erro ao criar agendamento'));
            }}
        }} catch(e) {{
            showToast('❌ Erro de conexão');
        }}

        btn.disabled = false;
        btn.textContent = 'Confirmar Agendamento';
    }}

    // Auto-refresh a cada 60 segundos — pausa se modal estiver aberto
    setInterval(() => {{
        const modalAberto = document.getElementById('modalOverlay').classList.contains('open');
        if (!modalAberto) location.reload();
    }}, 60000);
</script>

</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/debug/tenants")
def debug_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).all()
    result = []
    for t in tenants:
        count = db.query(Appointment).filter(Appointment.tenant_id == t.id).count()
        result.append({"id": t.id, "name": t.name, "appointments": count})
    return result
