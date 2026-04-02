from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant
from datetime import datetime, timedelta
import pytz

router = APIRouter()

BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora():
    return datetime.now(BRASILIA).replace(tzinfo=None)


STATUS_LABELS = {
    "confirmed": ("Confirmado", "#e8f5e9", "#2e7d32"),
    "in_progress": ("Em atendimento", "#fff8e1", "#f57f17"),
    "ready": ("Pronto p/ busca", "#e3f2fd", "#1565c0"),
    "delivered": ("Entregue", "#f3e5f5", "#6a1b9a"),
    "cancelled": ("Cancelado", "#ffebee", "#c62828"),
}

# ------------------ API STATUS ------------------

@router.post("/api/appointment/{appointment_id}/status")
def update_status(appointment_id: str, data: dict, db: Session = Depends(get_db)):

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appt:
        return JSONResponse({"error": "Agendamento não encontrado"}, status_code=404)

    appt.status = data.get("status", appt.status)

    db.commit()

    return {"success": True}


@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, db: Session = Depends(get_db)):

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appt:
        return JSONResponse({"error": "Agendamento não encontrado"}, status_code=404)

    appt.status = "cancelled"

    db.commit()

    return {"success": True}


# ------------------ CRIAR MANUAL ------------------

@router.post("/api/manual-appointment")
def create_manual(data: dict, db: Session = Depends(get_db)):

    tenant = db.query(Tenant).first()

    customer = Customer(
        tenant_id=tenant.id,
        name=data["customer_name"]
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    appt = Appointment(
        tenant_id=tenant.id,
        customer_id=customer.id,
        pet_name=data["pet_name"],
        scheduled_at=datetime.fromisoformat(data["datetime"]),
        pickup_time=data.get("pickup_time"),
        status="confirmed"
    )

    db.add(appt)
    db.commit()

    return {"success": True}


# ------------------ DASHBOARD ------------------

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

    # ------------------ CARDS HOJE ------------------

    cards = ""

    for a in hoje:

        cliente = db.query(Customer).filter(Customer.id == a.customer_id).first()

        nome = cliente.name if cliente else "Cliente"

        horario = a.scheduled_at.strftime("%H:%M")

        label, bg, color = STATUS_LABELS.get(a.status)

        cards += f"""
        <div class="appt">
            <div class="time">{horario}</div>

            <div class="info">
                <b>{nome}</b><br>
                🐾 {a.pet_name or "-"}
            </div>

            <div class="actions">

                <span class="badge" style="background:{bg};color:{color}">
                {label}
                </span>

                <select onchange="updateStatus('{a.id}',this.value)">
                    <option value="confirmed">Confirmado</option>
                    <option value="in_progress">Em atendimento</option>
                    <option value="ready">Pronto</option>
                    <option value="delivered">Entregue</option>
                </select>

                <button onclick="cancelAppt('{a.id}')">Cancelar</button>

            </div>
        </div>
        """

    # ------------------ FUTUROS ------------------

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
        <td>
        <button onclick="cancelAppt('{a.id}')">Cancelar</button>
        </td>
        </tr>
        """

    html = f"""
<html>

<head>

<meta name="viewport" content="width=device-width">

<style>

body {{
font-family: Arial;
background:#f5f5f5;
margin:0;
}}

body.dark {{
background:#1e1e1e;
color:white;
}}

.header {{
background:#6C5CE7;
color:white;
padding:15px;
display:flex;
justify-content:space-between;
}}

.container {{
max-width:1100px;
margin:auto;
padding:20px;
}}

.stats {{
display:flex;
gap:10px;
margin-bottom:20px;
}}

.stat {{
background:white;
padding:15px;
border-radius:8px;
flex:1;
}}

.appt {{
display:flex;
justify-content:space-between;
background:white;
padding:12px;
border-radius:8px;
margin-bottom:10px;
}}

.badge {{
padding:3px 8px;
border-radius:8px;
font-size:12px;
}}

table {{
width:100%;
background:white;
border-radius:8px;
padding:10px;
}}

.modal {{
display:none;
position:fixed;
inset:0;
background:rgba(0,0,0,0.4);
align-items:center;
justify-content:center;
}}

.modal-content {{
background:white;
padding:20px;
border-radius:10px;
display:flex;
flex-direction:column;
gap:8px;
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

<input id="name" placeholder="Cliente">

<input id="pet" placeholder="Pet">

<input type="datetime-local" id="date">

<input id="pickup" placeholder="Busca">

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

async function create(){{

await fetch("/api/manual-appointment",{{

method:"POST",

headers:{{"Content-Type":"application/json"}},

body:JSON.stringify({{

customer_name:document.getElementById("name").value,

pet_name:document.getElementById("pet").value,

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
