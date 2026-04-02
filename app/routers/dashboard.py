from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Conversation, Service, Tenant
from datetime import datetime, timedelta
import pytz
import json

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

# ── Dashboard principal ───────────────────────────────────────────────────────
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    tenant = db.query(Tenant).first()
    if not tenant:
        return HTMLResponse("<h2>Nenhum tenant configurado ainda.</h2>")

    tenant_name = tenant.name
    tid = tenant.id
    hoje = agora_brasilia()
    inicio_hoje = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_hoje = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

    agendamentos_hoje = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= inicio_hoje,
        Appointment.scheduled_at <= fim_hoje,
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    proximos = db.query(Appointment).filter(
        Appointment.tenant_id == tid,
        Appointment.scheduled_at >= hoje,
        Appointment.scheduled_at <= hoje + timedelta(days=7),
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
        rows_proximos = '<tr><td colspan="7" class="empty-row">Nenhum agendamento nos próximos 7 dias.</td></tr>'
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
            </tr>
            """

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{tenant_name} — Painel</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; }}

        .header {{ background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: white; padding: 18px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(108,92,231,0.3); }}
        .header h1 {{ font-size: 22px; font-weight: 700; }}
        .header-right {{ display: flex; align-items: center; gap: 16px; }}
        .header span {{ font-size: 13px; opacity: 0.9; }}
        .btn-refresh {{ background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.4); color: white; padding: 6px 14px; border-radius: 8px; cursor: pointer; font-size: 13px; }}
        .btn-refresh:hover {{ background: rgba(255,255,255,0.3); }}

        .container {{ max-width: 1300px; margin: 0 auto; padding: 24px 20px; }}

        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px; }}
        .stat-card {{ background: white; border-radius: 14px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-left: 4px solid #6C5CE7; }}
        .stat-card.orange {{ border-left-color: #fd79a8; }}
        .stat-card.blue {{ border-left-color: #74b9ff; }}
        .stat-card.green {{ border-left-color: #55efc4; }}
        .stat-number {{ font-size: 32px; font-weight: 800; color: #6C5CE7; }}
        .stat-card.orange .stat-number {{ color: #e17055; }}
        .stat-card.blue .stat-number {{ color: #0984e3; }}
        .stat-card.green .stat-number {{ color: #00b894; }}
        .stat-label {{ font-size: 12px; color: #888; margin-top: 4px; font-weight: 500; }}

        .section-title {{ font-size: 16px; font-weight: 700; color: #444; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
        .badge-count {{ background: #6C5CE7; color: white; font-size: 11px; padding: 2px 8px; border-radius: 20px; }}

        .card {{ background: white; border-radius: 14px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }}

        .appt-card {{ display: flex; align-items: flex-start; gap: 16px; padding: 16px; border-radius: 10px; border: 1px solid #f0f0f0; margin-bottom: 12px; background: #fafafa; transition: box-shadow 0.2s; }}
        .appt-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .appt-time {{ font-size: 22px; font-weight: 800; color: #6C5CE7; min-width: 65px; text-align: center; padding-top: 4px; }}
        .appt-body {{ flex: 1; }}
        .appt-client {{ font-size: 14px; font-weight: 700; color: #333; margin-bottom: 4px; }}
        .appt-pet {{ font-size: 13px; color: #555; margin-bottom: 2px; }}
        .appt-service {{ font-size: 12px; color: #888; }}
        .pickup {{ font-size: 12px; color: #0984e3; margin-top: 4px; font-weight: 500; }}
        .appt-actions {{ display: flex; flex-direction: column; align-items: flex-end; gap: 8px; min-width: 160px; }}
        .status-badge {{ font-size: 11px; padding: 4px 10px; border-radius: 20px; font-weight: 600; white-space: nowrap; }}
        .status-select {{ font-size: 12px; padding: 5px 8px; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; background: white; width: 100%; }}
        .btn-cancel {{ font-size: 11px; color: #e17055; background: #fff5f5; border: 1px solid #ffccbc; padding: 4px 10px; border-radius: 8px; cursor: pointer; width: 100%; }}
        .btn-cancel:hover {{ background: #ffebee; }}

        .empty-state {{ color: #aaa; text-align: center; padding: 30px; font-size: 14px; }}

        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; font-size: 11px; color: #999; font-weight: 600; padding: 10px 12px; border-bottom: 2px solid #f0f0f0; text-transform: uppercase; letter-spacing: 0.5px; }}
        td {{ font-size: 13px; padding: 12px 12px; border-bottom: 1px solid #f5f5f5; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: #fafafa; }}
        .empty-row {{ text-align: center; color: #aaa; padding: 30px !important; }}
        .badge {{ font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: 600; white-space: nowrap; }}

        .toast {{ position: fixed; bottom: 20px; right: 20px; background: #2d3436; color: white; padding: 12px 20px; border-radius: 10px; font-size: 13px; opacity: 0; transition: opacity 0.3s; z-index: 999; }}
        .toast.show {{ opacity: 1; }}

        @media (max-width: 768px) {{
            .appt-card {{ flex-direction: column; }}
            .appt-actions {{ width: 100%; flex-direction: row; flex-wrap: wrap; }}
        }}
    </style>
</head>
<body>

<div class="header">
    <h1>🐾 {tenant_name}</h1>
    <div class="header-right">
        <span>Atualizado: {hoje.strftime("%d/%m/%Y %H:%M")}</span>
        <button class="btn-refresh" onclick="location.reload()">↻ Atualizar</button>
    </div>
</div>

<div class="container">

    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{len(agendamentos_hoje)}</div>
            <div class="stat-label">📅 Agendamentos hoje</div>
        </div>
        <div class="stat-card orange">
            <div class="stat-number">{em_atendimento}</div>
            <div class="stat-label">✂️ Em atendimento</div>
        </div>
        <div class="stat-card blue">
            <div class="stat-number">{prontos}</div>
            <div class="stat-label">✅ Prontos p/ busca</div>
        </div>
        <div class="stat-card green">
            <div class="stat-number">{total_clientes}</div>
            <div class="stat-label">👤 Clientes cadastrados</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{total_agendamentos}</div>
            <div class="stat-label">📊 Total agendamentos</div>
        </div>
    </div>

    <!-- Agenda de Hoje -->
    <div class="card">
        <div class="section-title">
            📋 Agenda de Hoje
            <span class="badge-count">{hoje.strftime("%d/%m")}</span>
        </div>
        {cards_hoje}
    </div>

    <!-- Próximos 7 dias -->
    <div class="card">
        <div class="section-title">📆 Próximos 7 dias</div>
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
                </tr>
            </thead>
            <tbody>
                {rows_proximos}
            </tbody>
        </table>
    </div>

</div>

<div class="toast" id="toast"></div>

<script>
    function showToast(msg) {{
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        setTimeout(() => t.classList.remove('show'), 2500);
    }}

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
        }} catch(e) {{
            showToast('❌ Erro ao atualizar status');
        }}
    }}

    async function cancelAppt(id) {{
        if (!confirm('Cancelar este agendamento?')) return;
        try {{
            const res = await fetch(`/api/appointment/${{id}}/cancel`);
            const data = await res.json();
            if (data.success) {{
                showToast('🗑️ Agendamento cancelado');
                setTimeout(() => location.reload(), 1000);
            }}
        }} catch(e) {{
            showToast('❌ Erro ao cancelar');
        }}
    }}

    // Auto-refresh a cada 60 segundos
    setTimeout(() => location.reload(), 60000);
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
