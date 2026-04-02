from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Tenant
from datetime import datetime
import pytz

router = APIRouter()

BRASILIA = pytz.timezone("America/Sao_Paulo")

def agora():
    return datetime.now(BRASILIA).replace(tzinfo=None)

STATUS_LABELS = {
    "confirmed": ("Confirmado", "#22c55e"),
    "in_progress": ("Em atendimento", "#f59e0b"),
    "ready": ("Pronto", "#3b82f6"),
    "delivered": ("Entregue", "#8b5cf6"),
}

# ---------------- STATUS ----------------

@router.post("/api/appointment/{appointment_id}/status")
def update_status(appointment_id: str, data: dict, db: Session = Depends(get_db)):

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appt:
        return JSONResponse({"error": "Agendamento não encontrado"}, status_code=404)

    appt.status = data["status"]

    db.commit()

    return {"success": True}

# ---------------- CANCELAR ----------------

@router.get("/api/appointment/{appointment_id}/cancel")
def cancel_appt(appointment_id: str, db: Session = Depends(get_db)):

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appt:
        return JSONResponse({"error": "Agendamento não encontrado"}, status_code=404)

    appt.status = "cancelled"

    db.commit()

    return {"success": True}

# ---------------- CRIAR ----------------

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

# ---------------- DASHBOARD ----------------

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):

    tenant = db.query(Tenant).first()

    agendamentos = db.query(Appointment).filter(
        Appointment.status != "cancelled"
    ).order_by(Appointment.scheduled_at).all()

    cards = ""

    for a in agendamentos:

        cliente = db.query(Customer).filter(Customer.id == a.customer_id).first()
        nome = cliente.name if cliente else "Cliente"

        horario = a.scheduled_at.strftime("%H:%M")

        label,color = STATUS_LABELS.get(a.status)

        cards += f"""

        <div class="appt">

        <div class="time">{horario}</div>

        <div class="info">

        <b>{nome}</b><br>
        🐾 {a.pet_name}

        </div>

        <div class="actions">

        <span class="badge" style="background:{color}20;color:{color}">{label}</span>

        <select onchange="updateStatus('{a.id}',this.value)">

        <option value="confirmed">Confirmado</option>
        <option value="in_progress">Em atendimento</option>
        <option value="ready">Pronto</option>
        <option value="delivered">Entregue</option>

        </select>

        <button onclick="cancelAppt('{a.id}')">✖</button>

        </div>

        </div>

        """

    html = f"""

<html>

<head>

<meta name="viewport" content="width=device-width">

<style>

body {{
font-family:system-ui;
background:#f3f4f6;
margin:0;
}}

.header {{
background:linear-gradient(90deg,#6C5CE7,#7C3AED);
color:white;
padding:16px;
display:flex;
justify-content:space-between;
}}

.container {{
max-width:1000px;
margin:auto;
padding:20px;
}}

.appt {{
background:white;
border-radius:10px;
padding:14px;
margin-bottom:12px;
display:flex;
justify-content:space-between;
align-items:center;
box-shadow:0 3px 10px rgba(0,0,0,0.05);
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

button {{
border:none;
background:#ef4444;
color:white;
padding:6px 10px;
border-radius:6px;
cursor:pointer;
}}

select {{
padding:4px;
border-radius:6px;
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
background:white;
padding:20px;
border-radius:10px;
display:flex;
flex-direction:column;
gap:8px;
width:300px;
}}

input {{
padding:8px;
border-radius:6px;
border:1px solid #ddd;
}}

</style>

</head>

<body>

<div class="header">

<b>{tenant.name}</b>

<button onclick="openModal()">Novo</button>

</div>

<div class="container">

{cards}

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

function openModal(){{
document.getElementById("modal").style.display="flex"
}}

async function create(){{

let name=document.getElementById("name").value
let pet=document.getElementById("pet").value
let date=document.getElementById("date").value

if(!name||!pet||!date){{
alert("Preencha todos os campos")
return
}}

await fetch("/api/manual-appointment",{{
method:"POST",
headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{
customer_name:name,
pet_name:pet,
datetime:date,
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
