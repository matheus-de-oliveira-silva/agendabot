from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Appointment, Customer, Service, Tenant
from datetime import datetime
import pytz, os, bcrypt, secrets

router = APIRouter()
BRASILIA = pytz.timezone("America/Sao_Paulo")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "troca-essa-senha-admin")

BUSINESS_TYPES = {
    "petshop": "🐾 Pet Shop",
    "clinica": "🏥 Clínica Veterinária",
    "adocao": "🐶 Clínica de Adoção",
    "outro": "⚙️ Outro",
}

DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

def check_admin(request: Request):
    token = request.cookies.get("admin_token") or request.headers.get("X-Admin-Token")
    return token == ADMIN_SECRET

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
.btn-danger{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}.btn-danger:hover{background:#3d1c1c}
.btn-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}.btn-success:hover{background:#243d24}
.btn-sm{padding:5px 12px;font-size:12px;border-radius:8px}
.btn-outline{background:transparent;color:#9aa0b8;border:1px solid #2d3148}.btn-outline:hover{border-color:#7c7de8;color:#7c7de8}
.tenant-row{display:flex;align-items:center;gap:14px;padding:14px 16px;border:1px solid #2d3148;border-radius:12px;margin-bottom:10px;background:#22263a;transition:border-color .2s}
.tenant-row:hover{border-color:#7c7de8}
.tenant-name{font-weight:700;font-size:15px;flex:1}
.tenant-type{font-size:12px;color:#9aa0b8;background:#1a1d27;padding:3px 10px;border-radius:20px}
.badge{font-size:11px;padding:3px 8px;border-radius:10px;font-weight:600}
.badge-green{background:#1a2e1a;color:#68d391}
.badge-red{background:#2d1515;color:#fc8181}
.badge-gray{background:#22263a;color:#9aa0b8}
.service-row{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.service-color-dot{width:12px;height:12px;border-radius:3px;flex-shrink:0}
.service-name{font-weight:600;font-size:14px;flex:1}
.service-meta{font-size:12px;color:#9aa0b8}
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
def login_page():
    return admin_login_page()

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
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    rows = ""
    for t in tenants:
        count = db.query(Appointment).filter(Appointment.tenant_id == t.id).count()
        clientes = db.query(Customer).filter(Customer.tenant_id == t.id).count()
        tipo = BUSINESS_TYPES.get(t.business_type, t.business_type)
        has_pw = "✅ Com senha" if t.dashboard_password else "⚠️ Sem senha"
        badge_pw = "badge-green" if t.dashboard_password else "badge-gray"
        bot_status = "badge-green" if getattr(t, 'bot_active', True) else "badge-red"
        bot_label = "🤖 Bot ativo" if getattr(t, 'bot_active', True) else "🤖 Bot pausado"
        rows += f"""
        <div class="tenant-row">
            <div style="flex:1">
                <div class="tenant-name">{t.display_name or t.name}</div>
                <div style="font-size:12px;color:#9aa0b8;margin-top:2px">{count} agendamentos · {clientes} clientes</div>
            </div>
            <span class="tenant-type">{tipo}</span>
            <span class="badge {bot_status}">{bot_label}</span>
            <span class="badge {badge_pw}">{has_pw}</span>
            <a href="/admin/tenant/{t.id}" class="btn btn-outline btn-sm">⚙️ Configurar</a>
        </div>"""

    if not rows:
        rows = '<div style="color:#9aa0b8;text-align:center;padding:24px">Nenhum cliente ainda.</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — Painel</title>{ADMIN_STYLE}</head><body>
<div class="header">
    <div class="logo">⚙️ Admin Panel</div>
    <a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a>
</div>
<div class="container">

<div class="card">
    <div class="card-title">🏢 Clientes ({len(tenants)})</div>
    {rows}
</div>

<div class="card">
    <div class="card-title">➕ Novo cliente</div>
    <form method="POST" action="/admin/tenant">
    <div class="grid2">
        <div class="form-group"><label>Nome do negócio *</label>
        <input name="name" placeholder="Ex: PetShop Amigo Fiel" required></div>
        <div class="form-group"><label>Tipo *</label>
        <select name="business_type">
            <option value="petshop">🐾 Pet Shop</option>
            <option value="clinica">🏥 Clínica Veterinária</option>
            <option value="adocao">🐶 Clínica de Adoção</option>
            <option value="outro">⚙️ Outro</option>
        </select></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Nome da atendente virtual</label>
        <input name="bot_attendant_name" placeholder="Mari" value="Mari"></div>
        <div class="form-group"><label>Nome do "sujeito" (singular/plural)</label>
        <div style="display:flex;gap:8px">
        <input name="subject_label" placeholder="Pet" value="Pet">
        <input name="subject_label_plural" placeholder="Pets" value="Pets">
        </div></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Phone Number ID (WhatsApp)</label>
        <input name="phone_number_id" placeholder="ID do número na Meta"></div>
        <div class="form-group"><label>WA Access Token</label>
        <input name="wa_access_token" placeholder="Token da API"></div>
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
function toggleDay(btn, suffix) {{
    btn.classList.toggle('active');
    const grid = document.getElementById('days-' + suffix);
    const active = [...grid.querySelectorAll('.day-btn.active')].map(b => b.dataset.day);
    document.getElementById('open_days_' + suffix).value = active.join(',');
}}
</script>
</body></html>""")

@router.post("/admin/tenant")
async def create_tenant(request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    form = await request.form()
    name = form.get("name", "").strip()
    raw_pw = form.get("dashboard_password", "").strip()
    if not name or not raw_pw:
        return RedirectResponse("/admin?error=campos", status_code=302)

    hashed = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
    tenant = Tenant(
        name=name,
        display_name=name,
        business_type=form.get("business_type", "petshop"),
        phone_number_id=form.get("phone_number_id") or None,
        wa_access_token=form.get("wa_access_token") or None,
        subject_label=form.get("subject_label", "Pet"),
        subject_label_plural=form.get("subject_label_plural", "Pets"),
        bot_attendant_name=form.get("bot_attendant_name", "Mari"),
        bot_business_name=name,
        open_days=form.get("open_days", "0,1,2,3,4,5"),
        open_time=form.get("open_time", "09:00"),
        close_time=form.get("close_time", "18:00"),
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

def _default_services(business_type, tenant_id):
    defaults = {
        "petshop": [
            ("Banho Simples", 60, 4000, "#74b9ff", "Banho com secagem"),
            ("Banho e Tosa", 90, 7000, "#6C5CE7", "Banho completo com tosa"),
            ("Tosa Higiênica", 45, 3500, "#a29bfe", "Limpeza higiênica"),
            ("Consulta Veterinária", 30, 12000, "#00b894", "Consulta com vet"),
        ],
        "clinica": [
            ("Consulta Clínica", 30, 15000, "#00b894", "Consulta geral"),
            ("Vacinação", 20, 8000, "#55efc4", "Aplicação de vacinas"),
            ("Exame de Sangue", 15, 12000, "#fd79a8", "Coleta e análise"),
            ("Cirurgia", 120, 80000, "#e17055", "Procedimento cirúrgico"),
            ("Internação Diária", 1440, 25000, "#fdcb6e", "Internação 24h"),
        ],
        "adocao": [
            ("Consulta Pré-adoção", 30, 0, "#00b894", "Avaliação para adoção"),
            ("Castração", 90, 35000, "#6C5CE7", "Castração"),
            ("Microchip", 20, 5000, "#74b9ff", "Implante de microchip"),
            ("Vacinação", 20, 6000, "#55efc4", "Carteira de vacinação"),
        ],
        "outro": [("Serviço Padrão", 60, 10000, "#6C5CE7", "Descreva seu serviço")],
    }
    return [
        Service(tenant_id=tenant_id, name=n, duration_min=d, price=p, color=c, description=desc, active=True)
        for n, d, p, c, desc in defaults.get(business_type, defaults["outro"])
    ]

@router.get("/admin/tenant/{tenant_id}", response_class=HTMLResponse)
def tenant_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return HTMLResponse("<h2>Não encontrado</h2>", status_code=404)

    services = db.query(Service).filter(Service.tenant_id == tenant_id).order_by(Service.active.desc(), Service.name).all()
    created = request.query_params.get("created") == "1"
    saved = request.query_params.get("saved") == "1"
    alert = ""
    if created: alert = '<div class="alert alert-success">✅ Cliente criado!</div>'
    if saved: alert = '<div class="alert alert-success">✅ Salvo com sucesso!</div>'

    dashboard_url = f"{request.base_url}dashboard?tid={tenant_id}"
    tipo = BUSINESS_TYPES.get(tenant.business_type, tenant.business_type)

    # Stats rápidos
    total_appts = db.query(Appointment).filter(Appointment.tenant_id == tenant_id).count()
    total_clients = db.query(Customer).filter(Customer.tenant_id == tenant_id).count()
    active_appts = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.status.in_(["confirmed", "in_progress"])
    ).count()

    # Serviços
    svc_rows = ""
    for s in services:
        status_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        price_fmt = f"R$ {s.price/100:.2f}" if s.price else "Grátis"
        svc_rows += f"""
        <div class="service-row">
            <div class="service-color-dot" style="background:{s.color or '#6C5CE7'}"></div>
            <div style="flex:1">
                <div class="service-name">{s.name}</div>
                <div class="service-meta">{s.duration_min}min · {price_fmt} · {s.description or ''}</div>
            </div>
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

    if not svc_rows:
        svc_rows = '<div style="color:#9aa0b8;text-align:center;padding:16px">Nenhum serviço.</div>'

    # Dias de funcionamento
    open_days_list = [d.strip() for d in (getattr(tenant, 'open_days', '0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns = ''.join(
        f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" data-day="{i}" onclick="toggleDay(this,\'edit\')">{d}</button>'
        for i, d in enumerate(DAYS_PT)
    )

    bot_checked = 'checked' if getattr(tenant, 'bot_active', True) else ''

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — {tenant.display_name or tenant.name}</title>{ADMIN_STYLE}</head><body>
<div class="header">
    <div class="logo">⚙️ Admin Panel</div>
    <a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a>
</div>
<div class="container">
<a href="/admin" class="back">← Voltar</a>
{alert}

<!-- Stats rápidos -->
<div class="grid3" style="margin-bottom:20px">
    <div class="stat-mini"><div class="stat-mini-num">{total_appts}</div><div class="stat-mini-label">Total agendamentos</div></div>
    <div class="stat-mini"><div class="stat-mini-num">{total_clients}</div><div class="stat-mini-label">Clientes</div></div>
    <div class="stat-mini"><div class="stat-mini-num">{active_appts}</div><div class="stat-mini-label">Em aberto</div></div>
</div>

<!-- Link dashboard -->
<div class="card">
    <div class="card-title">🔗 Acesso do cliente <span class="tag">{tipo}</span></div>
    <div class="link-box">
        <div style="font-size:12px;color:#9aa0b8;margin-bottom:6px">Link do painel (envie para o cliente)</div>
        <div class="link-url">{dashboard_url}</div>
    </div>
    <button onclick="navigator.clipboard.writeText('{dashboard_url}');this.textContent='✅ Copiado!';setTimeout(()=>this.textContent='📋 Copiar link',2000)" class="btn btn-outline btn-sm">📋 Copiar link</button>
</div>

<!-- Config geral -->
<div class="card">
    <div class="card-title">🏢 Configurações do negócio</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/config">
    <div class="grid2">
        <div class="form-group"><label>Nome exibido</label>
        <input name="display_name" value="{tenant.display_name or tenant.name}"></div>
        <div class="form-group"><label>Tipo</label>
        <select name="business_type">
            {''.join(f'<option value="{k}" {"selected" if k==tenant.business_type else ""}>{v}</option>' for k,v in BUSINESS_TYPES.items())}
        </select></div>
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
        <div class="form-group"><label>Phone Number ID</label>
        <input name="phone_number_id" value="{tenant.phone_number_id or ''}"></div>
        <div class="form-group"><label>WA Access Token</label>
        <input name="wa_access_token" value="{tenant.wa_access_token or ''}"></div>
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
    <div style="display:flex;align-items:center;justify-content:space-between">
        <label class="toggle-switch">
            <input type="checkbox" name="bot_active" value="1" {bot_checked}>
            <span class="slider"></span>
            <span style="font-size:13px;color:#e8eaf2;font-weight:600">Bot ativo</span>
        </label>
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

<!-- Serviços -->
<div class="card">
    <div class="card-title">✂️ Serviços ({len(services)})</div>
    {svc_rows}
    <div class="divider"></div>
    <div class="section-title">Adicionar serviço</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/service">
    <div class="grid3">
        <div class="form-group"><label>Nome *</label>
        <input name="name" placeholder="Ex: Banho e Tosa" required></div>
        <div class="form-group"><label>Duração (min)</label>
        <input name="duration_min" type="number" value="60" min="5"></div>
        <div class="form-group"><label>Preço (R$)</label>
        <input name="price" type="number" step="0.01" placeholder="70.00"></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Descrição (para o bot)</label>
        <input name="description" placeholder="Ex: Banho com secagem e perfume"></div>
        <div class="form-group"><label>Cor</label>
        <input name="color" type="color" value="#6C5CE7" style="height:42px;padding:4px 8px"></div>
    </div>
    <button type="submit" class="btn btn-primary">Adicionar serviço</button>
    </form>
</div>

</div>
<script>
function toggleDay(btn, suffix) {{
    btn.classList.toggle('active');
    const grid = document.getElementById('days-' + suffix);
    const active = [...grid.querySelectorAll('.day-btn.active')].map(b => b.dataset.day);
    document.getElementById('open_days_' + suffix).value = active.join(',');
}}
</script>
</body></html>""")

@router.post("/admin/tenant/{tenant_id}/config")
async def save_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t: return JSONResponse({"error": "Não encontrado"}, status_code=404)
    t.display_name = form.get("display_name", t.display_name)
    t.business_type = form.get("business_type", t.business_type)
    t.subject_label = form.get("subject_label", t.subject_label)
    t.subject_label_plural = form.get("subject_label_plural", t.subject_label_plural)
    t.bot_attendant_name = form.get("bot_attendant_name", getattr(t, 'bot_attendant_name', 'Mari'))
    t.phone_number_id = form.get("phone_number_id") or t.phone_number_id
    t.wa_access_token = form.get("wa_access_token") or t.wa_access_token
    t.open_time = form.get("open_time", getattr(t, 'open_time', '09:00'))
    t.close_time = form.get("close_time", getattr(t, 'close_time', '18:00'))
    t.open_days = form.get("open_days", getattr(t, 'open_days', '0,1,2,3,4,5'))
    t.bot_active = form.get("bot_active") == "1"
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
    try: price_cents = int(float(form.get("price", "0")) * 100)
    except: price_cents = 0
    db.add(Service(
        tenant_id=tenant_id, name=name,
        duration_min=int(form.get("duration_min", 60)),
        price=price_cents,
        description=form.get("description", ""),
        color=form.get("color", "#6C5CE7"),
        active=True,
    ))
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
    if svc:
        svc.active = not svc.active
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/delete")
def delete_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request): return JSONResponse({"error": "Unauthorized"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc:
        db.delete(svc)
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)