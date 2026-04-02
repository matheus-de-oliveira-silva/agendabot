from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Appointment

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):

    appointments = db.query(Appointment).all()

    today_html = ""
    future_html = ""

    for a in appointments:

        item = f"""
        <div class="agenda-item">
            <div>
                <strong>{a.datetime}</strong><br>
                {a.customer_name} - {a.pet_name}
            </div>

            <div>

                <span class="status confirmado">{a.status}</span>

                <select onchange="updateStatus({a.id},this.value)">
                    <option>Confirmado</option>
                    <option>Em atendimento</option>
                    <option>Finalizado</option>
                </select>

                <button class="btn-danger" onclick="cancelAppointment({a.id})">X</button>

            </div>
        </div>
        """

        today_html += item

    return f"""
<!DOCTYPE html>
<html>
<head>

<meta charset="UTF-8">

<title>Dashboard</title>

<style>

body {{
font-family: Arial;
background:#f4f6fb;
margin:0;
}}

.dark {{
background:#1e1e2f;
color:white;
}}

header {{
background:linear-gradient(90deg,#6c63ff,#7a6cff);
padding:20px;
color:white;
display:flex;
justify-content:space-between;
}}

.container {{
max-width:1100px;
margin:auto;
padding:20px;
}}

.cards {{
display:grid;
grid-template-columns:repeat(4,1fr);
gap:15px;
margin-bottom:20px;
}}

.card {{
background:white;
padding:15px;
border-radius:10px;
box-shadow:0 3px 8px rgba(0,0,0,0.08);
}}

.dark .card {{
background:#2b2b3d;
}}

.agenda-item {{
background:white;
padding:15px;
border-radius:10px;
margin-bottom:10px;
display:flex;
justify-content:space-between;
align-items:center;
}}

.dark .agenda-item {{
background:#2b2b3d;
}}

button {{
border:none;
padding:8px 12px;
border-radius:6px;
cursor:pointer;
}}

.btn-danger {{
background:#ff5c5c;
color:white;
}}

.status {{
padding:4px 8px;
border-radius:5px;
font-size:12px;
background:#d7f3df;
color:#0a7b2d;
}}

table {{
width:100%;
border-collapse:collapse;
background:white;
border-radius:10px;
}}

th,td {{
padding:12px;
border-bottom:1px solid #eee;
}}

</style>

</head>


<body>

<header>

<h2>Agenda do Petshop</h2>

<div>

<button onclick="novoAgendamento()">Novo</button>
<button onclick="toggleDark()">🌙</button>

</div>

</header>


<div class="container">


<div class="cards">

<div class="card">
Hoje
<h2>{len(appointments)}</h2>
</div>

<div class="card">
Em atendimento
<h2>0</h2>
</div>

<div class="card">
Finalizados
<h2>0</h2>
</div>

<div class="card">
Clientes
<h2>{len(set([a.customer_name for a in appointments]))}</h2>
</div>

</div>


<h3>Agenda de hoje</h3>

{today_html}


</div>


<script>

function toggleDark(){{

document.body.classList.toggle("dark")

localStorage.setItem("darkMode",
document.body.classList.contains("dark"))

}}

if(localStorage.getItem("darkMode")==="true"){{

document.body.classList.add("dark")

}}



async function updateStatus(id,status){{

await fetch(`/api/appointment/${{id}}/status`,{{
method:"PUT",
headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{status:status}})
}})

}}



async function cancelAppointment(id){{

if(!confirm("Cancelar agendamento?")) return

await fetch(`/api/appointment/${{id}}`,{{method:"DELETE"}})

location.reload()

}}



async function novoAgendamento(){{

let name = prompt("Nome do cliente")
let pet = prompt("Nome do pet")
let date = prompt("Data e hora (YYYY-MM-DD HH:MM)")

if(!name || !pet || !date){{

alert("Preencha tudo")
return

}}

await fetch("/api/manual-appointment",{{

method:"POST",

headers:{{"Content-Type":"application/json"}},

body:JSON.stringify({{

customer_name:name,
pet_name:pet,
datetime:date

}})

}})

location.reload()

}}

</script>

</body>
</html>
"""
