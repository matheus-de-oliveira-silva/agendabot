from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant, Conversation, BlockedSlot
from datetime import datetime
import pytz, os, bcrypt, secrets

router = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "troca-essa-senha-admin")

BUSINESS_TYPES = {
    "petshop": "🐾 Pet Shop",
    "clinica": "🏥 Clínica Veterinária",
    "adocao": "🐶 Clínica de Adoção",
    "barbearia": "💈 Barbearia",
    "salao": "💅 Salão de Beleza",
    "estetica": "✨ Estética",
    "outro": "⚙️ Outro",
}

# Ícones disponíveis por tipo de negócio (sugestões)
ICON_SUGGESTIONS = {
    "petshop":   ["🐾", "🐶", "🐱", "🐕", "✂️"],
    "clinica":   ["🏥", "🩺", "💉", "🐾", "⚕️"],
    "adocao":    ["🐶", "🏡", "❤️", "🐱", "🐾"],
    "barbearia": ["💈", "✂️", "🪒", "👨", "💇"],
    "salao":     ["💅", "💆", "✨", "💄", "👩"],
    "estetica":  ["✨", "💆", "🌸", "💎", "🌿"],
    "outro":     ["⚙️", "📅", "🏢", "⭐", "🎯"],
}

PLANS = {
    "basico":  "⭐ Básico",
    "pro":     "🚀 Pro",
    "agencia": "🏢 Agência",
}

ADDRESS_LABELS = [
    "Endereço de busca",
    "Endereço de entrega",
    "Endereço de coleta",
    "Endereço do cliente",
]

DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

def check_admin(request: Request):
    token = request.cookies.get("admin_token") or request.headers.get("X-Admin-Token")
    return token == ADMIN_SECRET

def get_base_url(request: Request) -> str:
    host = request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return f"{proto}://{host}"
    if "localhost" in host or "127.0.0.1" in host:
        return f"http://{host}"
    return f"https://{host}"

ADMIN_STYLE = """
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh}
.header{background:#13151f;padding:0 28px;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2d3148;position:sticky;top:0;z-index:10}
.logo{font-size:18px;font-weight:800;color:#7c7de8}
.container{max-width:1100px;margin:0 auto;padding:28px 20px}
.card{background:#1a1d27;border:1px solid #2d3148;border-radius:16px;padding:24px;margin-bottom:20px}
.card-title{font-size:15px;font-weight:700;margin-bottom:18px;color:#e8eaf2;display:flex;align-items:center;gap:8px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px}
label{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}
input:focus,select:focus,textarea:focus{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}
.btn{padding:9px 18px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;transition:all .15s}
.btn-primary{background:#5B5BD6;color:#fff}.btn-primary:hover{background:#7c7de8}
.btn-danger{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}.btn-danger:hover{background:#c62828;color:#fff}
.btn-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}.btn-success:hover{background:#243d24}
.btn-sm{padding:5px 12px;font-size:12px;border-radius:8px}
.btn-outline{background:transparent;color:#9aa0b8;border:1px solid #2d3148}.btn-outline:hover{border-color:#7c7de8;color:#7c7de8}
.tenant-row{display:flex;align-items:center;gap:14px;padding:14px 16px;border:1px solid #2d3148;border-radius:12px;margin-bottom:10px;background:#22263a;transition:border-color .2s}
.tenant-row:hover{border-color:#7c7de8}
.tenant-icon{font-size:24px;width:40px;text-align:center}
.tenant-name{font-weight:700;font-size:15px;flex:1}
.tenant-type{font-size:12px;color:#9aa0b8;background:#1a1d27;padding:3px 10px;border-radius:20px}
.badge{font-size:11px;padding:3px 8px;border-radius:10px;font-weight:600}
.badge-green{background:#1a2e1a;color:#68d391}
.badge-red{background:#2d1515;color:#fc8181}
.badge-gray{background:#22263a;color:#9aa0b8}
.service-row{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.form-group{margin-bottom:14px}
.divider{height:1px;background:#2d3148;margin:20px 0}
.alert{padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:16px}
.alert-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}
.alert-error{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.back{font-size:13px;color:#9aa0b8;text-decoration:none;display:inline-flex;align-items:center;gap:6px;margin-bottom:20px}
.back:hover{color:#7c7de8}
.tag{font-size:11px;background:#23254a;color:#7c7de8;padding:2px 8px;border-radius:6px;font-weight:600}
.section-title{font-size:13px;font-weight:700;color:#9aa0b8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.days-grid{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.day-btn{padding:6px 12px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#9aa0b8;cursor:pointer;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif;transition:all .15s}
.day-btn.active{background:#23254a;border-color:#7c7de8;color:#7c7de8}
.icon-picker{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.icon-opt{width:42px;height:42px;border-radius:10px;border:2px solid #2d3148;background:#0f1117;cursor:pointer;font-size:22px;display:flex;align-items:center;justify-content:center;transition:all .15s}
.icon-opt:hover{border-color:#7c7de8;background:#23254a}
.icon-opt.selected{border-color:#7c7de8;background:#23254a;box-shadow:0 0 0 3px #23254a}
.toggle-switch{position:relative;display:inline-flex;align-items:center;gap:10px;cursor:pointer}
.toggle-switch input{opacity:0;width:0;height:0}
.slider{width:44px;height:24px;background:#2d3148;border-radius:12px;position:relative;transition:background .2s}
.slider:before{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:white;top:3px;left:3px;transition:transform .2s}
.toggle-switch input:checked + .slider{background:#5B5BD6}
.toggle-switch input:checked + .slider:before{transform:translateX(20px)}
.link-box{background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:14px;margin-bottom:18px}
.link-url{font-family:'DM Mono',monospace;font-size:13px;color:#7c7de8;word-break:break-all}
.stat-mini{background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:12px 16px;text-align:center}
.stat-mini-num{font-size:24px;font-weight:800;color:#7c7de8}
.stat-mini-label{font-size:11px;color:#9aa0b8;margin-top:2px}
.danger-zone{background:#1a0a0a;border:1px solid rgba(252,129,129,.2);border-radius:12px;padding:18px;margin-top:20px}
.danger-title{font-size:13px;font-weight:700;color:#fc8181;margin-bottom:12px;display:flex;align-items:center;gap:6px}
/* Tutorial WhatsApp */
.tutorial-step{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid #2d3148}
.tutorial-step:last-child{border-bottom:none}
.step-num{width:28px;height:28px;border-radius:50%;background:#23254a;color:#7c7de8;font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.step-text{font-size:13px;color:#9aa0b8;line-height:1.6}
.step-text strong{color:#e8eaf2}
.step-text a{color:#7c7de8;text-decoration:none}
.step-text a:hover{text-decoration:underline}
.code-box{background:#0f1117;border:1px solid #2d3148;border-radius:8px;padding:8px 12px;font-family:'DM Mono',monospace;font-size:12px;color:#a29bfe;margin-top:6px;word-break:break-all}
/* Bloqueio de horários */
.blocked-row{display:flex;align-items:center;gap:10px;padding:10px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.blocked-date{font-weight:700;font-size:13px;min-width:90px}
.blocked-time{font-size:12px;color:#9aa0b8;flex:1}
.blocked-reason{font-size:12px;color:#7c7de8}
@media(max-width:600px){.grid2,.grid3,.grid4{grid-template-columns:1fr}}
</style>
"""

def admin_login_page(error=""):
    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin Login</title>{ADMIN_STYLE}</head><body>
<div style="min-height:100vh;display:flex;align-items:center;justify-content:center">
<div style="width:360px">
<div style="text-align:center;margin-bottom:28px">
<div style="font-size:32px">🔐</div>
<div style="font-size:22px;font-weight:800;color:#7c7de8;margin-top:8px">Admin</div>
<div style="font-size:13px;color:#9aa0b8;margin-top:4px">Acesso restrito</div>
</div>
<div class="card">{err_html}
<form method="POST" action="/admin/login">
<div class="form-group"><label>Senha admin</label>
<input type="password" name="password" placeholder="••••••••" autofocus required></div>
<button type="submit" class="btn btn-primary" style="width:100%;padding:11px">Entrar</button>
</form></div></div></div></body></html>""")

@router.get("/admin/login", response_class=HTMLResponse)
def login_page(): return admin_login_page()

@router.post("/admin/login")
async def do_login(request: Request):
    form = await request.form()
    pw = form.get("password", "")
    if pw == ADMIN_SECRET:
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie("admin_token", ADMIN_SECRET, httponly=True, max_age=86400*7)
        return resp
    return admin_login_page("Senha incorreta.")

@router.get("/admin/logout")
def do_logout():
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie("admin_token")
    return resp

@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return RedirectResponse("/admin/login", status_code=302)
    base_url = get_base_url(request)
    deleted = request.query_params.get("deleted") == "1"
    alert = '<div class="alert alert-success" style="margin-bottom:16px">✅ Cliente deletado.</div>' if deleted else ""
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    rows = ""
    for t in tenants:
        count = db.query(Appointment).filter(Appointment.tenant_id == t.id).count()
        clientes = db.query(Customer).filter(Customer.tenant_id == t.id).count()
        tipo = BUSINESS_TYPES.get(t.business_type, t.business_type)
        badge_pw = "badge-green" if t.dashboard_password else "badge-gray"
        has_pw = "✅ Senha" if t.dashboard_password else "⚠️ Sem senha"
        bot_status = "badge-green" if getattr(t, 'bot_active', True) else "badge-red"
        bot_label = "🤖 Ativo" if getattr(t, 'bot_active', True) else "🤖 Pausado"
        icon = getattr(t, 'tenant_icon', '🐾') or '🐾'
        dash_url = f"{base_url}/dashboard?tid={t.id}"
        plan_label = PLANS.get(getattr(t, 'plan', 'basico') or 'basico', '⭐ Básico')
        plan_active = getattr(t, 'plan_active', True)
        plan_badge = "badge-green" if plan_active else "badge-red"
        setup_done = getattr(t, 'setup_done', False)
        setup_badge = "badge-green" if setup_done else "badge-gray"
        setup_label = "✅ Setup ok" if setup_done else "⚠️ Setup pendente"
        rows += f"""
        <div class="tenant-row">
            <div class="tenant-icon">{icon}</div>
            <div style="flex:1">
                <div class="tenant-name">{t.display_name or t.name}</div>
                <div style="font-size:12px;color:#9aa0b8;margin-top:2px">{count} agendamentos · {clientes} clientes</div>
            </div>
            <span class="tenant-type">{tipo}</span>
            <span class="badge {plan_badge}">{plan_label}</span>
            <span class="badge {setup_badge}">{setup_label}</span>
            <span class="badge {bot_status}">{bot_label}</span>
            <span class="badge {badge_pw}">{has_pw}</span>
            <a href="{dash_url}" target="_blank" class="btn btn-outline btn-sm">🔗 Painel</a>
            <a href="/admin/tenant/{t.id}" class="btn btn-outline btn-sm">⚙️ Config</a>
            <form method="POST" action="/admin/tenant/{t.id}/delete" onsubmit="return confirm('⚠️ DELETAR {t.display_name or t.name}?\\n\\nApaga TODOS os dados. Sem volta!')">
                <button type="submit" class="btn btn-danger btn-sm">🗑️</button>
            </form>
        </div>"""
    if not rows:
        rows = '<div style="color:#9aa0b8;text-align:center;padding:24px">Nenhum cliente ainda.</div>'

    # Ícones iniciais para o form de novo cliente
    icon_opts_new = ''.join(
        f'<div class="icon-opt {"selected" if i==0 else ""}" data-icon="{ico}" onclick="selectIcon(this,\'new\')">{ico}</div>'
        for i, ico in enumerate(["🐾","💈","💅","✨","🏥","🐶","⚙️","📅"])
    )

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — Painel</title>{ADMIN_STYLE}</head><body>
<div class="header"><div class="logo">⚙️ Admin Panel</div>
<a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a></div>
<div class="container">
{alert}
<div class="card">
    <div class="card-title">🏢 Clientes ({len(tenants)})</div>
    {rows}
</div>

<div class="card">
    <div class="card-title">➕ Novo cliente</div>
    <form method="POST" action="/admin/tenant">
    <div class="grid2">
        <div class="form-group"><label>Nome do negócio *</label>
        <input name="name" placeholder="Ex: Barbearia do João" required></div>
        <div class="form-group"><label>Tipo *</label>
        <select name="business_type" onchange="updateIcons(this.value,'new')">
            {''.join(f'<option value="{k}">{v}</option>' for k,v in BUSINESS_TYPES.items())}
        </select></div>
    </div>
    <div class="form-group">
        <label>Ícone do painel</label>
        <div class="icon-picker" id="icons-new">{icon_opts_new}</div>
        <input type="hidden" name="tenant_icon" id="icon_val_new" value="🐾">
    </div>
    <div class="grid2">
        <div class="form-group"><label>Nome da atendente virtual</label>
        <input name="bot_attendant_name" placeholder="Mari" value="Mari"></div>
        <div class="form-group"><label>Sujeito (singular / plural)</label>
        <div style="display:flex;gap:8px">
        <input name="subject_label" placeholder="Pet" value="Pet">
        <input name="subject_label_plural" placeholder="Pets" value="Pets">
        </div></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Instância Evolution API (ou Phone Number ID Meta)</label>
        <input name="phone_number_id" placeholder="Ex: barbearia-joao">
        <div style="font-size:11px;color:#9aa0b8;margin-top:4px">⚡ Evolution: nome da instância. Meta API: ID do número.</div></div>
        <div class="form-group"><label>WA Token (somente Meta API — vazio para Evolution)</label>
        <input name="wa_access_token" placeholder="EAAxxxxxxx... (só Meta API)"></div>
    </div>
    <div class="form-group"><label>WhatsApp do dono (para receber notificações de novos agendamentos)</label>
    <input name="owner_phone" placeholder="Ex: 5511999999999 (com DDI e DDD, sem + ou espaços)"></div>
    <div class="grid2">
        <div class="form-group"><label>Plano</label>
        <select name="plan">
            {''.join(f'<option value="{k}">{v}</option>' for k,v in PLANS.items())}
        </select></div>
        <div class="form-group"><label>Email do comprador (Hotmart/Kiwify)</label>
        <input name="billing_email" placeholder="email@cliente.com" type="email"></div>
    </div>
    <div class="form-group">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" name="needs_address" value="1" style="width:auto;margin:0">
            <span>Este negócio coleta endereço do cliente (busca/entrega)</span>
        </label>
    </div>
    <div class="form-group" id="address-label-group-new" style="display:none">
        <label>Label do endereço</label>
        <select name="address_label">
            {''.join(f'<option value="{l}">{l}</option>' for l in ADDRESS_LABELS)}
        </select>
    </div>
    <div class="grid3">
        <div class="form-group"><label>Abre às</label>
        <input name="open_time" type="time" value="09:00"></div>
        <div class="form-group"><label>Fecha às</label>
        <input name="close_time" type="time" value="18:00"></div>
        <div class="form-group"><label>Senha do dashboard *</label>
        <input name="dashboard_password" type="password" required></div>
    </div>
    <div class="form-group">
        <label>Dias de funcionamento</label>
        <div class="days-grid" id="days-new">
            {''.join(f'<button type="button" class="day-btn active" data-day="{i}" onclick="toggleDay(this,\'new\')">{d}</button>' for i,d in enumerate(DAYS_PT) if i < 6)}
            <button type="button" class="day-btn" data-day="6" onclick="toggleDay(this,'new')">Dom</button>
        </div>
        <input type="hidden" name="open_days" id="open_days_new" value="0,1,2,3,4,5">
    </div>
    <button type="submit" class="btn btn-primary">Criar cliente</button>
    </form>
</div>
</div>

<script>
const ICON_SUGGESTIONS = {str(ICON_SUGGESTIONS).replace("'", '"')};

function selectIcon(el, suffix) {{
    document.querySelectorAll('#icons-' + suffix + ' .icon-opt').forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('icon_val_' + suffix).value = el.dataset.icon;
}}
function updateIcons(bizType, suffix) {{
    const icons = ICON_SUGGESTIONS[bizType] || ICON_SUGGESTIONS['outro'];
    const container = document.getElementById('icons-' + suffix);
    container.innerHTML = icons.map((ic, i) =>
        `<div class="icon-opt ${{i===0?'selected':''}}" data-icon="${{ic}}" onclick="selectIcon(this,'${{suffix}}')">${{ic}}</div>`
    ).join('');
    document.getElementById('icon_val_' + suffix).value = icons[0];
}}
function toggleDay(btn, suffix) {{
    btn.classList.toggle('active');
    const grid = document.getElementById('days-' + suffix);
    const active = [...grid.querySelectorAll('.day-btn.active')].map(b => b.dataset.day);
    document.getElementById('open_days_' + suffix).value = active.join(',');
}}
document.addEventListener('DOMContentLoaded', function() {{
    const cb = document.querySelector('input[name="needs_address"]');
    const grp = document.getElementById('address-label-group-new');
    if (cb && grp) cb.addEventListener('change', () => grp.style.display = cb.checked ? 'block' : 'none');
}});
</script>
</body></html>""")

@router.post("/admin/tenant")
async def create_tenant(request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return RedirectResponse("/admin/login", status_code=302)
    form = await request.form()
    name = form.get("name", "").strip()
    raw_pw = form.get("dashboard_password", "").strip()
    if not name or not raw_pw: return RedirectResponse("/admin?error=campos", status_code=302)
    hashed = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
    tenant = Tenant(
        name=name, display_name=name,
        business_type=form.get("business_type", "petshop"),
        tenant_icon=form.get("tenant_icon", "🐾"),
        phone_number_id=form.get("phone_number_id") or None,
        wa_access_token=form.get("wa_access_token") or None,
        subject_label=form.get("subject_label", "Pet"),
        subject_label_plural=form.get("subject_label_plural", "Pets"),
        bot_attendant_name=form.get("bot_attendant_name", "Mari"),
        bot_business_name=name,
        open_days=form.get("open_days", "0,1,2,3,4,5"),
        open_time=form.get("open_time", "09:00"),
        close_time=form.get("close_time", "18:00"),
        owner_phone=form.get("owner_phone") or None,
        notify_new_appt=True,
        needs_address=form.get("needs_address") == "1",
        address_label=form.get("address_label", "Endereço de busca"),
        plan=form.get("plan", "basico"),
        plan_active=True,
        billing_email=form.get("billing_email") or None,
        setup_token=secrets.token_urlsafe(32),
        setup_done=False,
        dashboard_password=hashed,
        dashboard_token=secrets.token_urlsafe(32),
        bot_active=True,
    )
    db.add(tenant)
    db.flush()
    for s in _default_services(tenant.business_type, tenant.id):
        db.add(s)
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant.id}?created=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/delete")
def delete_tenant(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return RedirectResponse("/admin/login", status_code=302)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant: return RedirectResponse("/admin", status_code=302)
    db.query(Appointment).filter(Appointment.tenant_id == tenant_id).delete()
    db.query(Customer).filter(Customer.tenant_id == tenant_id).delete()
    db.query(Service).filter(Service.tenant_id == tenant_id).delete()
    db.query(Conversation).filter(Conversation.tenant_id == tenant_id).delete()
    db.query(BlockedSlot).filter(BlockedSlot.tenant_id == tenant_id).delete()
    db.delete(tenant)
    db.commit()
    return RedirectResponse("/admin?deleted=1", status_code=302)

def _default_services(business_type, tenant_id):
    defaults = {
        "petshop":   [("Banho Simples",60,4000,"#74b9ff","Banho com secagem"),("Banho e Tosa",90,7000,"#6C5CE7","Banho completo com tosa"),("Tosa Higiênica",45,3500,"#a29bfe","Limpeza higiênica"),("Consulta Veterinária",30,12000,"#00b894","Consulta com vet")],
        "clinica":   [("Consulta Clínica",30,15000,"#00b894","Consulta geral"),("Vacinação",20,8000,"#55efc4","Aplicação de vacinas"),("Exame de Sangue",15,12000,"#fd79a8","Coleta e análise"),("Cirurgia",120,80000,"#e17055","Procedimento cirúrgico")],
        "adocao":    [("Consulta Pré-adoção",30,0,"#00b894","Avaliação para adoção"),("Castração",90,35000,"#6C5CE7","Castração"),("Microchip",20,5000,"#74b9ff","Implante de microchip"),("Vacinação",20,6000,"#55efc4","Carteira de vacinação")],
        "barbearia": [("Corte",30,4000,"#74b9ff","Corte masculino"),("Barba",20,3000,"#6C5CE7","Barba completa"),("Corte + Barba",50,6500,"#a29bfe","Combo completo"),("Sobrancelha",15,1500,"#00b894","Design de sobrancelha")],
        "salao":     [("Corte Feminino",60,8000,"#fd79a8","Corte e finalização"),("Escova",45,6000,"#f0a500","Escova progressiva"),("Coloração",120,15000,"#6C5CE7","Coloração completa"),("Manicure",40,4000,"#00b894","Unhas mãos")],
        "estetica":  [("Limpeza de Pele",60,9000,"#74b9ff","Limpeza profunda"),("Depilação",45,6000,"#fd79a8","Depilação a cera"),("Massagem",60,12000,"#00b894","Massagem relaxante"),("Design de Sobrancelha",30,5000,"#6C5CE7","Design completo")],
        "outro":     [("Serviço Padrão",60,10000,"#6C5CE7","Descreva seu serviço")],
    }
    return [
        Service(tenant_id=tenant_id, name=n, duration_min=d, price=p, color=c, description=desc, active=True)
        for n, d, p, c, desc in defaults.get(business_type, defaults["outro"])
    ]

@router.get("/admin/tenant/{tenant_id}", response_class=HTMLResponse)
def tenant_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return RedirectResponse("/admin/login", status_code=302)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant: return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)

    services = db.query(Service).filter(Service.tenant_id == tenant_id).order_by(Service.active.desc(), Service.name).all()
    blocked = db.query(BlockedSlot).filter(BlockedSlot.tenant_id == tenant_id).order_by(BlockedSlot.date, BlockedSlot.time).all()

    created = request.query_params.get("created") == "1"
    saved   = request.query_params.get("saved") == "1"
    alert = ""
    if created: alert = '<div class="alert alert-success">✅ Cliente criado com sucesso!</div>'
    if saved:   alert = '<div class="alert alert-success">✅ Salvo com sucesso!</div>'

    base_url = get_base_url(request)
    dashboard_url = f"{base_url}/dashboard?tid={tenant_id}"
    tipo = BUSINESS_TYPES.get(tenant.business_type, tenant.business_type)
    current_icon = getattr(tenant, 'tenant_icon', '🐾') or '🐾'

    total_appts   = db.query(Appointment).filter(Appointment.tenant_id == tenant_id).count()
    total_clients = db.query(Customer).filter(Customer.tenant_id == tenant_id).count()
    active_appts  = db.query(Appointment).filter(Appointment.tenant_id == tenant_id, Appointment.status.in_(["confirmed","in_progress"])).count()

    # Serviços
    svc_rows = ""
    for s in services:
        status_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        price_fmt = f"R$ {s.price/100:.2f}" if s.price else "Grátis"
        svc_rows += f"""<div class="service-row">
            <div style="width:12px;height:12px;border-radius:3px;flex-shrink:0;background:{s.color or '#6C5CE7'}"></div>
            <div style="flex:1"><div style="font-weight:600;font-size:14px">{s.name}</div>
            <div style="font-size:12px;color:#9aa0b8">{s.duration_min}min · {price_fmt} · {s.description or ''}</div></div>
            {status_badge}
            <form method="POST" action="/admin/tenant/{tenant_id}/service/{s.id}/edit" style="display:flex;gap:6px;align-items:center">
                <input name="price" type="number" step="0.01" value="{s.price/100:.2f}" style="width:80px;padding:4px 8px;font-size:12px">
                <input name="duration_min" type="number" value="{s.duration_min}" style="width:60px;padding:4px 8px;font-size:12px">
                <button type="submit" class="btn btn-outline btn-sm">💾</button>
            </form>
            <form method="POST" action="/admin/tenant/{tenant_id}/service/{s.id}/toggle">
                <button type="submit" class="btn btn-outline btn-sm">{'⏸' if s.active else '▶'}</button>
            </form>
            <form method="POST" action="/admin/tenant/{tenant_id}/service/{s.id}/delete">
                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Remover?')">✕</button>
            </form>
        </div>"""
    if not svc_rows: svc_rows = '<div style="color:#9aa0b8;text-align:center;padding:16px">Nenhum serviço.</div>'

    # Dias
    open_days_list = [d.strip() for d in (getattr(tenant,'open_days','0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns = ''.join(
        f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" data-day="{i}" onclick="toggleDay(this,\'edit\')">{d}</button>'
        for i, d in enumerate(DAYS_PT)
    )
    bot_checked    = 'checked' if getattr(tenant, 'bot_active', True) else ''
    notify_checked = 'checked' if getattr(tenant, 'notify_new_appt', True) else ''
    needs_address_checked = 'checked' if getattr(tenant, 'needs_address', False) else ''
    current_address_label = getattr(tenant, 'address_label', 'Endereço de busca') or 'Endereço de busca'
    current_plan    = getattr(tenant, 'plan', 'basico') or 'basico'
    plan_active     = getattr(tenant, 'plan_active', True)
    setup_done      = getattr(tenant, 'setup_done', False)
    setup_token_val = getattr(tenant, 'setup_token', None) or ''
    billing_email_val = getattr(tenant, 'billing_email', '') or ''
    setup_url = f"{base_url}/setup?token={setup_token_val}" if setup_token_val else ""
    if setup_url:
        _cpbtn = "navigator.clipboard.writeText(document.getElementById('setup-url').textContent)"
        setup_link_html = (
            '<div class="link-box">'
            '<div style="font-size:11px;color:#9aa0b8;margin-bottom:6px">Envie este link por email para o cliente:</div>'
            f'<div class="link-url" id="setup-url">{setup_url}</div>'
            '</div>'
            '<div style="display:flex;gap:8px;margin-top:8px">'
            f'<button onclick="{_cpbtn}" class="btn btn-outline btn-sm">Copiar link setup</button>'
            '</div>'
        )
        setup_btn_label = 'Gerar novo link'
    else:
        setup_link_html = '<div style="color:#9aa0b8;font-size:13px;margin-bottom:8px">Nenhum link gerado ainda.</div>'
        setup_btn_label = 'Gerar link de setup'

    # Ícones
    suggestions = ICON_SUGGESTIONS.get(tenant.business_type, ICON_SUGGESTIONS['outro'])
    all_icons = list(dict.fromkeys(suggestions + ["🐾","💈","💅","✨","🏥","🐶","⚙️","📅","🌟","🎯"]))
    icon_opts = ''.join(
        f'<div class="icon-opt {"selected" if ico == current_icon else ""}" data-icon="{ico}" onclick="selectIcon(this,\'edit\')">{ico}</div>'
        for ico in all_icons
    )

    # Horários bloqueados
    blocked_rows = ""
    for b in blocked:
        time_label = b.time if b.time else "Dia inteiro"
        reason_label = f'<span class="blocked-reason">{b.reason}</span>' if b.reason else ""
        blocked_rows += f"""<div class="blocked-row">
            <div class="blocked-date">{b.date}</div>
            <div class="blocked-time">{time_label}</div>
            {reason_label}
            <form method="POST" action="/admin/tenant/{tenant_id}/blocked/{b.id}/delete" style="margin-left:auto">
                <button type="submit" class="btn btn-danger btn-sm">✕</button>
            </form>
        </div>"""
    if not blocked_rows:
        blocked_rows = '<div style="color:#9aa0b8;font-size:13px;padding:10px 0">Nenhum horário bloqueado.</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — {tenant.display_name or tenant.name}</title>{ADMIN_STYLE}</head><body>
<div class="header"><div class="logo">⚙️ Admin Panel</div>
<a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a></div>
<div class="container">
<a href="/admin" class="back">← Voltar</a>
{alert}

<div class="grid3" style="margin-bottom:20px">
    <div class="stat-mini"><div class="stat-mini-num">{total_appts}</div><div class="stat-mini-label">Total agendamentos</div></div>
    <div class="stat-mini"><div class="stat-mini-num">{total_clients}</div><div class="stat-mini-label">Clientes</div></div>
    <div class="stat-mini"><div class="stat-mini-num">{active_appts}</div><div class="stat-mini-label">Em aberto</div></div>
</div>

<!-- Link -->
<div class="card">
    <div class="card-title">🔗 Acesso do cliente <span class="tag">{tipo}</span></div>
    <div class="link-box">
        <div style="font-size:12px;color:#9aa0b8;margin-bottom:6px">Link do painel — envie para o cliente</div>
        <div class="link-url" id="dash-url">{dashboard_url}</div>
    </div>
    <div style="display:flex;gap:8px">
        <button onclick="navigator.clipboard.writeText(document.getElementById('dash-url').textContent);this.textContent='✅ Copiado!';setTimeout(()=>this.textContent='📋 Copiar link',2000)" class="btn btn-outline btn-sm">📋 Copiar link</button>
        <a href="{dashboard_url}" target="_blank" class="btn btn-outline btn-sm">🔗 Abrir painel</a>
    </div>
</div>

<!-- Plano e Setup -->
<div class="card">
    <div class="card-title">💼 Plano e acesso de setup</div>
    <div class="grid2" style="margin-bottom:16px">
        <div>
            <div style="font-size:11px;color:#9aa0b8;font-weight:600;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Plano atual</div>
            <div style="display:flex;align-items:center;gap:8px">
                <span style="font-size:15px;font-weight:700">{PLANS.get(current_plan, current_plan)}</span>
                <span class="badge {'badge-green' if plan_active else 'badge-red'}">{'Ativo' if plan_active else 'Suspenso'}</span>
            </div>
        </div>
        <div>
            <div style="font-size:11px;color:#9aa0b8;font-weight:600;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Setup do cliente</div>
            <div style="display:flex;align-items:center;gap:8px">
                <span class="badge {'badge-green' if setup_done else 'badge-gray'}">{'✅ Concluído' if setup_done else '⚠️ Pendente'}</span>
            </div>
        </div>
    </div>
    <form method="POST" action="/admin/tenant/{tenant_id}/plan" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:16px">
        <div style="flex:1">
            <label>Alterar plano</label>
            <select name="plan">
                {''.join(f'<option value="{k}" {"selected" if k==current_plan else ""}>{v}</option>' for k,v in PLANS.items())}
            </select>
        </div>
        <div style="flex:1">
            <label>Email Hotmart/Kiwify</label>
            <input name="billing_email" type="email" value="{billing_email_val}" placeholder="email@cliente.com">
        </div>
        <div style="display:flex;gap:6px">
            <button type="submit" name="action" value="save" class="btn btn-primary">Salvar</button>
            <button type="submit" name="action" value="suspend" class="btn btn-danger btn-sm" onclick="return confirm('Suspender assinatura?')" style="white-space:nowrap">{'▶ Reativar' if not plan_active else '⏸ Suspender'}</button>
        </div>
    </form>
    <div class="divider"></div>
    <div style="font-size:13px;font-weight:700;margin-bottom:10px">🔗 Link de setup para o cliente</div>
    {setup_link_html}
    <form method="POST" action="/admin/tenant/{tenant_id}/generate-setup-link" style="display:inline">
        <button type="submit" class="btn btn-success btn-sm">{setup_btn_label}</button>
    </form>
</div>

<!-- Config -->
<div class="card">
    <div class="card-title">🏢 Configurações do negócio</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/config">
    <div class="grid2">
        <div class="form-group"><label>Nome exibido</label>
        <input name="display_name" value="{tenant.display_name or tenant.name}"></div>
        <div class="form-group"><label>Tipo</label>
        <select name="business_type" onchange="updateIcons(this.value,'edit')">
            {''.join(f'<option value="{k}" {"selected" if k==tenant.business_type else ""}>{v}</option>' for k,v in BUSINESS_TYPES.items())}
        </select></div>
    </div>
    <div class="form-group">
        <label>Ícone do painel</label>
        <div class="icon-picker" id="icons-edit">{icon_opts}</div>
        <input type="hidden" name="tenant_icon" id="icon_val_edit" value="{current_icon}">
    </div>
    <div class="grid3">
        <div class="form-group"><label>Nome da atendente (IA)</label>
        <input name="bot_attendant_name" value="{getattr(tenant,'bot_attendant_name','Mari') or 'Mari'}"></div>
        <div class="form-group"><label>Sujeito singular</label>
        <input name="subject_label" value="{tenant.subject_label or 'Pet'}"></div>
        <div class="form-group"><label>Sujeito plural</label>
        <input name="subject_label_plural" value="{tenant.subject_label_plural or 'Pets'}"></div>
    </div>
    <div class="grid2">
        <div class="form-group">
            <label>Instância Evolution API (ou Phone Number ID Meta)</label>
            <input name="phone_number_id" value="{tenant.phone_number_id or ''}" placeholder="Ex: barbearia-joao">
            <div style="font-size:11px;color:#9aa0b8;margin-top:4px">⚡ Evolution: nome da instância. Meta API: ID do número.</div>
        </div>
        <div class="form-group">
            <label>WA Token (somente Meta API — vazio para Evolution)</label>
            <input name="wa_access_token" value="{tenant.wa_access_token or ''}" placeholder="EAAxxxxxxx... (só Meta API)">
            <div style="font-size:11px;color:#9aa0b8;margin-top:4px">⚡ Evolution API: deixe em branco.</div>
        </div>
    </div>
    <div class="form-group"><label>WhatsApp do dono (notificações de novos agendamentos)</label>
    <input name="owner_phone" value="{getattr(tenant,'owner_phone','') or ''}" placeholder="5511999999999"></div>
    <div class="divider"></div>
    <div class="section-title">📍 Endereço e entrega</div>
    <div class="form-group">
        <label class="toggle-switch" style="margin-bottom:10px">
            <input type="checkbox" name="needs_address" value="1" {needs_address_checked} onchange="toggleAddressLabel(this.checked,'edit')">
            <span class="slider"></span>
            <span style="font-size:13px;color:#e8eaf2;font-weight:600">Este negócio coleta endereço do cliente</span>
        </label>
        <div id="address-label-edit" style="display:{'block' if needs_address_checked else 'none'};margin-top:10px">
            <label>Label do endereço (como aparece no bot e no painel)</label>
            <select name="address_label">
                {''.join(f'<option value="{l}" {"selected" if l==current_address_label else ""}>{l}</option>' for l in ADDRESS_LABELS)}
            </select>
        </div>
    </div>
    <div class="divider"></div>
    <div class="section-title">⏰ Horário de funcionamento</div>
    <div class="grid2">
        <div class="form-group"><label>Abre às</label>
        <input name="open_time" type="time" value="{getattr(tenant,'open_time','09:00') or '09:00'}"></div>
        <div class="form-group"><label>Fecha às</label>
        <input name="close_time" type="time" value="{getattr(tenant,'close_time','18:00') or '18:00'}"></div>
    </div>
    <div class="form-group">
        <label>Dias de funcionamento</label>
        <div class="days-grid" id="days-edit">{days_btns}</div>
        <input type="hidden" name="open_days" id="open_days_edit" value="{getattr(tenant,'open_days','0,1,2,3,4,5') or '0,1,2,3,4,5'}">
    </div>
    <div class="divider"></div>
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
        <div style="display:flex;gap:20px;flex-wrap:wrap">
            <label class="toggle-switch">
                <input type="checkbox" name="bot_active" value="1" {bot_checked}>
                <span class="slider"></span>
                <span style="font-size:13px;color:#e8eaf2;font-weight:600">Bot ativo</span>
            </label>
            <label class="toggle-switch">
                <input type="checkbox" name="notify_new_appt" value="1" {notify_checked}>
                <span class="slider"></span>
                <span style="font-size:13px;color:#e8eaf2;font-weight:600">Notificar novos agendamentos</span>
            </label>
        </div>
        <button type="submit" class="btn btn-primary">Salvar configurações</button>
    </div>
    </form>
</div>

<!-- Senha -->
<div class="card">
    <div class="card-title">🔑 Senha do dashboard</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/password">
    <div style="display:flex;gap:12px;align-items:flex-end">
        <div class="form-group" style="flex:1;margin:0"><label>Nova senha</label>
        <input name="password" type="password" placeholder="Nova senha para o cliente" required></div>
        <button type="submit" class="btn btn-primary">Salvar</button>
    </div>
    </form>
</div>

<!-- Tutorial WhatsApp -->
<div class="card">
    <div class="card-title">📱 Como conectar o WhatsApp</div>

    <!-- Tabs de modo -->
    <div style="display:flex;gap:8px;margin-bottom:20px">
        <button onclick="showMode('evolution',this)" id="btn-evo" class="btn btn-primary btn-sm">⚡ Evolution API (recomendado)</button>
        <button onclick="showMode('meta',this)" id="btn-meta" class="btn btn-outline btn-sm">🏢 Meta API Oficial</button>
    </div>

    <!-- Evolution API -->
    <div id="mode-evolution">
        <div style="background:#1a2e1a;border:1px solid rgba(104,211,145,.2);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#68d391">
            ⚡ <strong>Mais fácil e rápido</strong> — conecta qualquer número WhatsApp via QR Code em minutos. Ideal para começar.
        </div>
        <div class="tutorial-step">
            <div class="step-num">1</div>
            <div class="step-text">Você precisa ter a <strong>Evolution API</strong> rodando. Se ainda não tem, instale com Docker:<br>
            <div class="code-box">docker run -d -p 8080:8080 --name evolution atendai/evolution-api:latest</div>
            Ou use um serviço hospedado como <a href="https://evolution-api.com" target="_blank">evolution-api.com</a>.</div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">2</div>
            <div class="step-text">Acesse o painel da Evolution API (normalmente em <strong>http://seu-servidor:8080</strong>) e crie uma nova instância com o nome do cliente.<br>
            <div class="code-box">Nome sugerido: barbearia-joao (sem espaços)</div></div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">3</div>
            <div class="step-text">Conecte o número escaneando o <strong>QR Code</strong> que aparece no painel da Evolution com o WhatsApp Business do cliente. Aguarde aparecer "Connected".</div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">4</div>
            <div class="step-text">Cole o <strong>nome da instância</strong> no campo "Instância Evolution API" acima.<br>
            <div class="code-box">Ex: barbearia-joao</div></div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">5</div>
            <div class="step-text">Configure o Webhook na Evolution API apontando para:<br>
            <div class="code-box">{get_base_url(request)}/whatsapp/webhook</div>
            Evento: marque <strong>MESSAGES_UPSERT</strong> e salve.</div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">6</div>
            <div class="step-text">Configure as variáveis de ambiente no Railway:<br>
            <div class="code-box">EVOLUTION_API_URL=http://seu-servidor:8080
EVOLUTION_API_KEY=sua-api-key
EVOLUTION_INSTANCE=barbearia-joao</div>
            Depois salve as configurações acima. ✅</div>
        </div>
    </div>

    <!-- Meta API Oficial -->
    <div id="mode-meta" style="display:none">
        <div style="background:#2a2200;border:1px solid rgba(246,201,14,.2);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#f6c90e">
            🏢 <strong>Mais burocrático</strong> — requer aprovação da Meta e verificação de empresa. Melhor para volumes altos e uso profissional.
        </div>
        <div class="tutorial-step">
            <div class="step-num">1</div>
            <div class="step-text">Acesse <a href="https://developers.facebook.com" target="_blank">developers.facebook.com</a> e faça login com a conta Facebook do cliente.</div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">2</div>
            <div class="step-text">Crie um <strong>App do tipo Business</strong>. No painel, vá em <strong>Adicionar produto</strong> e selecione <strong>WhatsApp</strong>.</div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">3</div>
            <div class="step-text">Em <strong>WhatsApp → Configuração</strong>, você verá o <strong>Phone Number ID</strong> — cole no campo "Instância" acima.<br>
            <div class="code-box">Exemplo: 123456789012345</div></div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">4</div>
            <div class="step-text">Clique em <strong>Gerar token de acesso</strong>. Cole no campo <strong>WA Token</strong> acima.<br>
            <div class="code-box">Começa com: EAAxxxxxxx...</div></div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">5</div>
            <div class="step-text">Configure o Webhook em <strong>WhatsApp → Configuração → Webhooks</strong>:<br>
            URL: <div class="code-box">{get_base_url(request)}/webhook</div>
            Token: <div class="code-box">{os.getenv('WHATSAPP_VERIFY_TOKEN','agendabot123')}</div></div>
        </div>
        <div class="tutorial-step">
            <div class="step-num">6</div>
            <div class="step-text">Marque o evento <strong>messages</strong> no webhook, salve e teste. ✅</div>
        </div>
    </div>
</div>

<script>
function showMode(mode, btn) {{
    document.getElementById('mode-evolution').style.display = mode==='evolution' ? '' : 'none';
    document.getElementById('mode-meta').style.display      = mode==='meta'      ? '' : 'none';
    document.getElementById('btn-evo').className  = mode==='evolution' ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm';
    document.getElementById('btn-meta').className = mode==='meta'      ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm';
}}
</script>

<!-- Serviços -->
<div class="card">
    <div class="card-title">✂️ Serviços ({len(services)})</div>
    {svc_rows}
    <div class="divider"></div>
    <div class="section-title">Adicionar serviço</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/service">
    <div class="grid3">
        <div class="form-group"><label>Nome *</label>
        <input name="name" placeholder="Ex: Corte + Barba" required></div>
        <div class="form-group"><label>Duração (min)</label>
        <input name="duration_min" type="number" value="60" min="5"></div>
        <div class="form-group"><label>Preço (R$)</label>
        <input name="price" type="number" step="0.01" placeholder="50.00"></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Descrição (para o bot)</label>
        <input name="description" placeholder="Ex: Corte e acabamento completo"></div>
        <div class="form-group"><label>Cor</label>
        <input name="color" type="color" value="#6C5CE7" style="height:42px;padding:4px 8px"></div>
    </div>
    <button type="submit" class="btn btn-primary">Adicionar serviço</button>
    </form>
</div>

<!-- Bloqueio de horários -->
<div class="card">
    <div class="card-title">🚫 Bloquear horários</div>
    <div style="font-size:12px;color:#9aa0b8;margin-bottom:14px">Bloqueie dias ou horários específicos. O bot não vai agendar nesses períodos.</div>
    {blocked_rows}
    <div class="divider"></div>
    <div class="section-title">Adicionar bloqueio</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/blocked">
    <div class="grid3">
        <div class="form-group"><label>Data *</label>
        <input name="date" type="date" required></div>
        <div class="form-group"><label>Horário (vazio = dia inteiro)</label>
        <input name="time" type="time" placeholder="Deixe vazio para bloquear o dia todo"></div>
        <div class="form-group"><label>Motivo</label>
        <input name="reason" placeholder="Ex: Férias, Feriado local..."></div>
    </div>
    <button type="submit" class="btn btn-primary">Bloquear</button>
    </form>
</div>

<!-- Zona de perigo -->
<div class="danger-zone">
    <div class="danger-title">⚠️ Zona de Perigo</div>
    <p style="font-size:13px;color:#9aa0b8;margin-bottom:14px">Deletar remove permanentemente todos os dados. Sem volta.</p>
    <form method="POST" action="/admin/tenant/{tenant_id}/delete"
          onsubmit="return confirm('⚠️ DELETAR {tenant.display_name or tenant.name}?\\n\\nTodos os dados apagados. Sem volta!')">
        <button type="submit" class="btn btn-danger">🗑️ Deletar este cliente permanentemente</button>
    </form>
</div>

</div>
<script>
const ICON_SUGGESTIONS = {str(ICON_SUGGESTIONS).replace("'", '"')};
function selectIcon(el, suffix) {{
    document.querySelectorAll('#icons-' + suffix + ' .icon-opt').forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('icon_val_' + suffix).value = el.dataset.icon;
}}
function updateIcons(bizType, suffix) {{
    const icons = ICON_SUGGESTIONS[bizType] || ICON_SUGGESTIONS['outro'];
    const container = document.getElementById('icons-' + suffix);
    if (!container) return;
    container.innerHTML = icons.map((ic, i) =>
        `<div class="icon-opt ${{i===0?'selected':''}}" data-icon="${{ic}}" onclick="selectIcon(this,'${{suffix}}')">${{ic}}</div>`
    ).join('');
    document.getElementById('icon_val_' + suffix).value = icons[0];
}}
function toggleDay(btn, suffix) {{
    btn.classList.toggle('active');
    const grid = document.getElementById('days-' + suffix);
    const active = [...grid.querySelectorAll('.day-btn.active')].map(b => b.dataset.day);
    document.getElementById('open_days_' + suffix).value = active.join(',');
}}
function toggleAddressLabel(checked, suffix) {{
    const el = document.getElementById('address-label-' + suffix);
    if (el) el.style.display = checked ? 'block' : 'none';
}}
</script>
</body></html>""")

@router.post("/admin/tenant/{tenant_id}/config")
async def save_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    t.display_name         = form.get("display_name", t.display_name)
    t.business_type        = form.get("business_type", t.business_type)
    t.tenant_icon          = form.get("tenant_icon", getattr(t, 'tenant_icon', '🐾'))
    t.subject_label        = form.get("subject_label", t.subject_label)
    t.subject_label_plural = form.get("subject_label_plural", t.subject_label_plural)
    t.bot_attendant_name   = form.get("bot_attendant_name", getattr(t, 'bot_attendant_name', 'Mari'))
    t.phone_number_id      = form.get("phone_number_id") or t.phone_number_id
    t.wa_access_token      = form.get("wa_access_token") or t.wa_access_token
    t.open_time            = form.get("open_time", getattr(t, 'open_time', '09:00'))
    t.close_time           = form.get("close_time", getattr(t, 'close_time', '18:00'))
    t.open_days            = form.get("open_days", getattr(t, 'open_days', '0,1,2,3,4,5'))
    t.owner_phone          = form.get("owner_phone") or getattr(t, 'owner_phone', None)
    t.bot_active           = form.get("bot_active") == "1"
    t.notify_new_appt      = form.get("notify_new_appt") == "1"
    t.needs_address        = form.get("needs_address") == "1"
    t.address_label        = form.get("address_label") or getattr(t, 'address_label', 'Endereço de busca')
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/password")
async def save_password(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    raw_pw = form.get("password", "").strip()
    if not raw_pw: return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if t:
        t.dashboard_password = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service")
async def add_service(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    name = form.get("name", "").strip()
    if not name: return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
    try: price_cents = int(float(form.get("price","0")) * 100)
    except: price_cents = 0
    db.add(Service(tenant_id=tenant_id, name=name, duration_min=int(form.get("duration_min",60)),
        price=price_cents, description=form.get("description",""), color=form.get("color","#6C5CE7"), active=True))
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/edit")
async def edit_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc:
        try: svc.price = int(float(form.get("price", svc.price/100)) * 100)
        except: pass
        try: svc.duration_min = int(form.get("duration_min", svc.duration_min))
        except: pass
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/toggle")
def toggle_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc: svc.active = not svc.active; db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/delete")
def delete_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc: db.delete(svc); db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Bloqueio de horários ──────────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/blocked")
async def add_blocked(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    date = form.get("date", "").strip()
    if not date: return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
    time_val = form.get("time", "").strip() or None
    reason = form.get("reason", "").strip() or None
    from ..models import BlockedSlot
    import uuid
    db.add(BlockedSlot(id=str(uuid.uuid4()), tenant_id=tenant_id, date=date, time=time_val, reason=reason))
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/blocked/{blocked_id}/delete")
def delete_blocked(tenant_id: str, blocked_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    b = db.query(BlockedSlot).filter(BlockedSlot.id == blocked_id, BlockedSlot.tenant_id == tenant_id).first()
    if b: db.delete(b); db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Gerar link de setup ──────────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/generate-setup-link")
def generate_setup_link(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    t.setup_token = secrets.token_urlsafe(32)
    t.setup_done  = False
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Alterar plano / suspender ─────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/plan")
async def update_plan(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    action = form.get("action", "save")
    if action == "suspend":
        t.plan_active = not getattr(t, 'plan_active', True)
        t.bot_active  = t.plan_active
    else:
        t.plan = form.get("plan", getattr(t, 'plan', 'basico'))
        t.billing_email = form.get("billing_email") or getattr(t, 'billing_email', None)
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Migração v3 via HTTP ──────────────────────────────────────────────────────
@router.post("/admin/migrate-v3")
def migrate_v3_route(request: Request):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from ..database import engine
    from migrate_v3 import run_migration
    try:
        results = run_migration(engine)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}