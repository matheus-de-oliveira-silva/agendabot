from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant
from datetime import datetime
import pytz

router = APIRouter()

BRASILIA = pytz.timezone("America/Sao_Paulo")

def agora():
    return datetime.now(BRASILIA).replace(tzinfo=None)

STATUS_LABELS = {
    "confirmed": ("Confirmado", "status-confirmed"),
    "in_progress": ("Em atendimento", "status-progress"),
    "ready": ("Pronto", "status-ready"),
    "delivered": ("Entregue", "status-delivered"),
    "cancelled": ("Cancelado", "status-cancelled"),
}

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):

    tenant = db.query(Tenant).first()

    if not tenant:
        return HTMLResponse("<h2>Nenhum tenant configurado</h2>")

    agora_dt = agora()

    inicio = agora_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = agora_dt.replace(hour=23, minute=59, second=59)

    agendamentos = db.query(Appointment).filter(
        Appointment.tenant_id == tenant.id,
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    hoje = []
    futuros = []

    for a in agendamentos:
        if inicio <= a.scheduled_at <= fim:
            hoje.append(a)
        elif a.scheduled_at > agora_dt:
            futuros.append(a)

    total_clientes = db.query(Customer).filter(Customer.tenant_id == tenant.id).count()

    em_atendimento = len([a for a in agendamentos if a.status == "in_progress"])
    prontos = len([a for a in agendamentos if a.status == "ready"])

    cards = ""

    for a in hoje:

        cliente = db.query(Customer).filter(Customer.id == a.customer_id).first()

        nome = cliente.name if cliente else "Cliente"
        horario = a.scheduled_at.strftime("%H:%M")

        label, css = STATUS_LABELS.get(a.status)

        cards += f"""
        <div class="appt">
            <div class="time">{horario}</div>

            <div class="info">
                <div class="name">{nome}</div>
                <div class="pet">🐾 {a.pet_name or "-"}</div>
            </div>

            <div class="actions">

                <span class="badge {css}">
                {label}
                </span>

                <select onchange="updateStatus('{a.id}',this.value)">
                    <option value="confirmed" {"selected" if a.status=="confirmed" else ""}>Confirmado</option>
                    <option value="in_progress" {"selected" if a.status=="in_progress" else ""}>Em atendimento</option>
                    <option value="ready" {"selected" if a.status=="ready" else ""}>Pronto</option>
                    <option value="delivered" {"selected" if a.status=="delivered" else ""}>Entregue</option>
                </select>

                <button class="cancel" onclick="cancelAppt('{a.id}')">✖</button>

            </div>
        </div>
        """

    rows = ""

    for a in futuros[:20]:

        cliente = db.query(Customer).filter(Customer.id == a.customer_id).first()
        nome = cliente.name if cliente else "Cliente"

        data = a.scheduled_at.strftime("%d/%m %H:%M")

        rows += f"""
        <tr>
        <td>{data}</td>
        <td>{nome}</td>
        <td>{a.pet_name}</td>
        <td><button class="cancel" onclick="cancelAppt('{a.id}')">Cancelar</button></td>
        </tr>
        """

    html = f"""

<html>

<head>

<meta name="viewport" content="width=device-width">

<style>

:root {{
--bg:#f6f7fb;
--card:#ffffff;
--text:#222;
--accent:#6C5CE7;
}}

body.dark {{
--bg:#121212;
--card:#1e1e1e;
--text:#eee;
}}

body {{
font-family:system-ui;
background:var(--bg);
color:var(--text);
margin:0;
}}

.header {{
background:var(--accent);
color:white;
padding:15px 25px;
display:flex;
justify-content:space-between;
align-items:center;
}}

.header button {{
background:white;
border:none;
padding:6px 12px;
border-radius:6px;
cursor:pointer;
}}

.container {{
max-width:1100px;
margin:auto;
padding:20px;
}}

.stats {{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:12px;
margin-bottom:20px;
}}

.stat {{
background:var(--card);
padding:16px;
border-radius:10px;
box-shadow:0 4px 10px rgba(0,0,0,0.05);
}}

.appt {{
display:flex;
justify-content:space-between;
align-items:center;
background:var(--card);
padding:14px;
border-radius:10px;
margin-bottom:10px;
box-shadow:0 2px 6px rgba(0,0,0,0.05);
}}

.appt:hover {{
transform:scale(1.01);
}}

.time {{
font-weight:bold;
font-size:18px;
}}

.badge {{
padding:4px 8px;
border-radius:6px;
font-size:12px;
}}

.status-confirmed {{background:#e8f5e9;color:#2e7d32}}
.status-progress {{background:#fff8e1;color:#f57f17}}
.status-ready {{background:#e3f2fd;color:#1565c0}}
.status-delivered {{background:#ede7f6;color:#6a1b9a}}
.status-cancelled {{background:#ffebee;color:#c62828}}

.cancel {{
background:#ff5252;
color:white;
border:none;
padding:5px 10px;
border-radius:6px;
cursor:pointer;
}}

table {{
width:100%;
background:var(--card);
border-radius:10px;
padding:10px;
border-collapse:collapse;
}}

td,th {{
padding:10px;
border-bottom:1px solid #ddd;
}}

.modal {{
display:none;
position:fixed;
inset:0;
background:rgba(0,0,0,0.5);
align-items:center;
justify-content:center;
}}

.modal-content {{
background:var(--card);
padding:20px;
border-radius:10px;
display:flex;
flex-direction:column;
gap:10px;
width:300px;
position:relative;
}}

.close {{
position:absolute;
right:10px;
top:10px;
cursor:pointer;
font-weight:bold;
}}

input {{
padding:8px;
border-radius:6px;
border:1px solid #ccc;
}}

</style>

</head>

<body>

<div class="header">

<b>{tenant.name}</b>

<div>

<button onclick="openModal()">Novo</button>
<button onclick="toggleDark()">🌙</button>

</div>

</div>

<div class="container">

<div class="stats">

<div class="stat">Hoje<br><b>{len(hoje)}</b></div>
<div class="stat">Em atendimento<br><b>{em_atendimento}</b></div>
<div class="stat">Prontos<br><b>{prontos}</b></div>
<div class="stat">Clientes<br><b>{total_clientes}</b></div>

</div>

<h3>Agenda hoje</h3>

{cards}

<h3>Próximos agendamentos</h3>

<table>

<tr>

<th>Data</th>
<th>Cliente</th>
<th>Pet</th>
<th></th>

</tr>

{rows}

</table>

</div>

<div class="modal" id="modal">

<div class="modal-content">

<span class="close" onclick="closeModal()">✖</span>

<input id="name" placeholder="Nome do dono">

<input id="pet" placeholder="Nome do pet">

<input id="breed" placeholder="Raça">

<input id="weight" placeholder="Peso (kg)">

<input type="datetime-local" id="date">

<input id="pickup" placeholder="Horário de busca">

<button onclick="create()">Salvar</button>

</div>

</div>

<script>

function toggleDark(){{

document.body.classList.toggle("dark")
localStorage.setItem("dark",document.body.classList.contains("dark"))

}}

if(localStorage.getItem("dark")==="true"){{

document.body.classList.add("dark")

}}

function openModal(){{
document.getElementById("modal").style.display="flex"
}}

function closeModal(){{
document.getElementById("modal").style.display="none"
}}

window.onclick=function(e){{
if(e.target.id==="modal") closeModal()
}}

async function create(){{

await fetch("/api/manual-appointment",{{
method:"POST",
headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{

customer_name:document.getElementById("name").value,
pet_name:document.getElementById("pet").value,
breed:document.getElementById("breed").value,
weight:document.getElementById("weight").value,
datetime:document.getElementById("date").value,
pickup_time:document.getElementById("pickup").value

}})
}})

location.reload()

}}

async function updateStatus(id,status){{

await fetch(`/api/appointment/${{id}}/status`,{{
method:"POST",
headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{status}})
}})

location.reload()

}}

async function cancelAppt(id){{

if(!confirm("Cancelar agendamento?")) return

await fetch(`/api/appointment/${{id}}/cancel`)

location.reload()

}}

</script>

</body>

</html>
"""

    return HTMLResponse(html)
