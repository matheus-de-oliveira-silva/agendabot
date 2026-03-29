from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Conversation, Service, Tenant
from datetime import datetime, timedelta
import json

router = APIRouter()

TEST_TENANT_ID = "d558102e-7862-4553-a08f-14447d687252"


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == TEST_TENANT_ID).first()
    tenant_name = tenant.name if tenant else "PetShop"

    hoje = datetime.now()
    inicio_hoje = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_hoje = hoje.replace(hour=23, minute=59, second=59, microsecond=0)

    # Agendamentos de hoje
    agendamentos_hoje = db.query(Appointment).filter(
        Appointment.tenant_id == TEST_TENANT_ID,
        Appointment.scheduled_at >= inicio_hoje,
        Appointment.scheduled_at <= fim_hoje,
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    # Próximos 7 dias
    proximos = db.query(Appointment).filter(
        Appointment.tenant_id == TEST_TENANT_ID,
        Appointment.scheduled_at >= hoje,
        Appointment.scheduled_at <= hoje + timedelta(days=7),
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    # Total de clientes
    total_clientes = db.query(Customer).filter(
        Customer.tenant_id == TEST_TENANT_ID
    ).count()

    # Total de agendamentos
    total_agendamentos = db.query(Appointment).filter(
        Appointment.tenant_id == TEST_TENANT_ID,
        Appointment.status == "confirmed"
    ).count()

    # Conversas recentes
    conversas = db.query(Conversation).filter(
        Conversation.tenant_id == TEST_TENANT_ID
    ).all()

    # Monta cards de agendamentos de hoje
    cards_hoje = ""
    if not agendamentos_hoje:
        cards_hoje = '<p style="color:#888; padding:20px;">Nenhum agendamento para hoje.</p>'
    else:
        for a in agendamentos_hoje:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = customer.name or customer.phone if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            horario = a.scheduled_at.strftime("%H:%M")

            cards_hoje += f"""
            <div class="appointment-card">
                <div class="appointment-time">{horario}</div>
                <div class="appointment-info">
                    <strong>{nome_cliente}</strong>
                    <span>{nome_servico}</span>
                </div>
                <div class="appointment-status confirmed">Confirmado</div>
            </div>
            """

    # Monta tabela de próximos agendamentos
    rows_proximos = ""
    if not proximos:
        rows_proximos = '<tr><td colspan="4" style="text-align:center;color:#888;padding:20px;">Nenhum agendamento nos próximos 7 dias.</td></tr>'
    else:
        for a in proximos:
            customer = db.query(Customer).filter(Customer.id == a.customer_id).first()
            service = db.query(Service).filter(Service.id == a.service_id).first()
            nome_cliente = customer.name or customer.phone if customer else "Cliente"
            nome_servico = service.name if service else "Serviço"
            data = a.scheduled_at.strftime("%d/%m/%Y")
            horario = a.scheduled_at.strftime("%H:%M")

            rows_proximos += f"""
            <tr>
                <td>{data}</td>
                <td>{horario}</td>
                <td>{nome_cliente}</td>
                <td>{nome_servico}</td>
            </tr>
            """

    # Monta lista de conversas
    lista_conversas = ""
    for c in conversas[-5:]:
        msgs = json.loads(c.messages)
        ultima = msgs[-1]["content"][:60] + "..." if msgs else "Sem mensagens"
        lista_conversas += f"""
        <div class="conversation-item">
            <div class="conversation-phone">📱 {c.customer_phone}</div>
            <div class="conversation-last">{ultima}</div>
        </div>
        """

    html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{tenant_name} — Painel</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f6fa; color: #333; }}

        .header {{ background: #6C5CE7; color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ font-size: 22px; font-weight: 600; }}
        .header span {{ font-size: 14px; opacity: 0.8; }}

        .container {{ max-width: 1200px; margin: 0 auto; padding: 30px 20px; }}

        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
        .stat-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .stat-card .number {{ font-size: 36px; font-weight: 700; color: #6C5CE7; }}
        .stat-card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}

        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}

        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .card h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #444; }}

        .appointment-card {{ display: flex; align-items: center; gap: 16px; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }}
        .appointment-card:last-child {{ border-bottom: none; }}
        .appointment-time {{ font-size: 20px; font-weight: 700; color: #6C5CE7; min-width: 60px; }}
        .appointment-info {{ flex: 1; }}
        .appointment-info strong {{ display: block; font-size: 14px; }}
        .appointment-info span {{ font-size: 12px; color: #888; }}
        .appointment-status {{ font-size: 11px; padding: 4px 10px; border-radius: 20px; font-weight: 500; }}
        .confirmed {{ background: #e8f5e9; color: #2e7d32; }}

        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; font-size: 12px; color: #888; font-weight: 500; padding: 8px 12px; border-bottom: 2px solid #f0f0f0; }}
        td {{ font-size: 13px; padding: 10px 12px; border-bottom: 1px solid #f5f5f5; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: #fafafa; }}

        .conversation-item {{ padding: 12px 0; border-bottom: 1px solid #f0f0f0; }}
        .conversation-item:last-child {{ border-bottom: none; }}
        .conversation-phone {{ font-size: 13px; font-weight: 600; color: #444; }}
        .conversation-last {{ font-size: 12px; color: #888; margin-top: 3px; }}

        .refresh {{ background: #6C5CE7; color: white; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; }}
        .refresh:hover {{ background: #5a4dd0; }}

        .hoje-badge {{ background: #6C5CE7; color: white; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }}
    </style>
</head>
<body>

<div class="header">
    <h1>🐾 {tenant_name}</h1>
    <span>Painel de Atendimento · {hoje.strftime("%d/%m/%Y %H:%M")}</span>
</div>

<div class="container">

    <!-- Stats -->
    <div class="stats">
        <div class="stat-card">
            <div class="number">{len(agendamentos_hoje)}</div>
            <div class="label">Agendamentos hoje</div>
        </div>
        <div class="stat-card">
            <div class="number">{len(proximos)}</div>
            <div class="label">Próximos 7 dias</div>
        </div>
        <div class="stat-card">
            <div class="number">{total_clientes}</div>
            <div class="label">Clientes cadastrados</div>
        </div>
        <div class="stat-card">
            <div class="number">{total_agendamentos}</div>
            <div class="label">Total de agendamentos</div>
        </div>
    </div>

    <div class="grid">

        <!-- Agendamentos de hoje -->
        <div class="card">
            <h2>Agenda de Hoje <span class="hoje-badge">{hoje.strftime("%d/%m")}</span></h2>
            {cards_hoje}
        </div>

        <!-- Conversas recentes -->
        <div class="card">
            <h2>Conversas Recentes</h2>
            {lista_conversas if lista_conversas else '<p style="color:#888">Nenhuma conversa ainda.</p>'}
        </div>

    </div>

    <!-- Próximos 7 dias -->
    <div class="card">
        <h2 style="margin-bottom:16px">Próximos 7 dias</h2>
        <table>
            <thead>
                <tr>
                    <th>Data</th>
                    <th>Horário</th>
                    <th>Cliente</th>
                    <th>Serviço</th>
                </tr>
            </thead>
            <tbody>
                {rows_proximos}
            </tbody>
        </table>
    </div>

</div>

<script>
    // Atualiza a página a cada 30 segundos
    setTimeout(() => location.reload(), 30000);
</script>

</body>
</html>
"""
    return HTMLResponse(content=html)
