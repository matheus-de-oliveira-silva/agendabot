from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):

    appointments = db.query(Appointment).all()

    agenda_html = ""

    for a in appointments:

        customer = a.customer_name if a.customer_name else "Cliente"
        pet = a.pet_name if a.pet_name else "Pet"
        date = str(a.datetime) if a.datetime else "Sem data"
        status = a.status if a.status else "Confirmado"

        agenda_html += f"""
        <div class="agenda-item">
            <div>
                <strong>{date}</strong><br>
                {customer} - {pet}
            </div>

            <div>

                <span class="status">{status}</span>

                <select onchange="updateStatus({a.id},this.value)">
                    <option value="Confirmado">Confirmado</option>
                    <option value="Em atendimento">Em atendimento</option>
                    <option value="Finalizado">Finalizado</option>
                </select>

                <button onclick="cancelAppointment({a.id})">X</button>

            </div>
        </div>
        """

    total_clientes = len(set([a.customer_name for a in appointments if a.customer_name]))

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
max-width:1000px;
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
}}

.dark .agenda-item {{
background:#2b2b3d;
}}

button {{
padding:6px 10px;
border:none;
border-radius:6px;
cursor:pointer;
background:#ff5c5c;
color:white;
}}

select {{
padding:5px;
border-radius:5px;
}}

.status {{
padding:4px 8px;
background:#d7f3df;
border-radius:5px;
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
Agendamentos
<h2>{len(appointments)}</h2>
</div>

<div class="card">
Clientes
<h2>{total_clientes}</h2>
</div>

</div>

<h3>Agenda</h3>

{agenda_html}

</div>

<script>

function toggleDark(){{

document.body.classList.toggle("dark")

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
let date = prompt("Data e hora")

if(!name || !pet || !date) return

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
