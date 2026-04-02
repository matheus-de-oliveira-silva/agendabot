"""
admin.py — Painel administrativo (só seu, protegido por ADMIN_SECRET no .env)
Rotas:
  GET  /admin          → painel com lista de tenants
  POST /admin/tenant   → cria novo tenant
  GET  /admin/tenant/{id}  → página de configuração do tenant
  POST /admin/tenant/{id}/service      → adiciona/edita serviço
  POST /admin/tenant/{id}/service/{sid}/toggle  → ativa/desativa serviço
  DELETE /admin/tenant/{id}/service/{sid}       → remove serviço
  POST /admin/tenant/{id}/password     → define/redefine senha do dashboard
  POST /admin/tenant/{id}/config       → edita configurações gerais
"""

from fastapi import APIRouter, Depends, Request, Header
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

def check_admin(request: Request):
    token = request.cookies.get("admin_token") or request.headers.get("X-Admin-Token")
    return token == ADMIN_SECRET

# ── CSS / JS compartilhado ────────────────────────────────────────────────────
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
label{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}
input:focus,select:focus,textarea:focus{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}
.btn{padding:9px 18px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;transition:all .15s}
.btn-primary{background:#5B5BD6;color:#fff}.btn-primary:hover{background:#7c7de8}
.btn-danger{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}.btn-danger:hover{background:#3d1c1c}
.btn-sm{padding:5px 12px;font-size:12px;border-radius:8px}
.btn-outline{background:transparent;color:#9aa0b8;border:1px solid #2d3148}.btn-outline:hover{border-color:#7c7de8;color:#7c7de8}
.tenant-row{display:flex;align-items:center;gap:14px;padding:14px 16px;border:1px solid #2d3148;border-radius:12px;margin-bottom:10px;background:#22263a;transition:border-color .2s}
.tenant-row:hover{border-color:#7c7de8}
.tenant-name{font-weight:700;font-size:15px;flex:1}
.tenant-type{font-size:12px;color:#9aa0b8;background:#1a1d27;padding:3px 10px;border-radius:20px}
.badge{font-size:11px;padding:3px 8px;border-radius:10px;font-weight:600}
.badge-green{background:#1a2e1a;color:#68d391}
.badge-gray{background:#22263a;color:#9aa0b8}
.service-row{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.service-color{width:12px;height:12px;border-radius:3px;flex-shrink:0}
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
@media(max-width:600px){.grid2,.grid3{grid-template-columns:1fr}}
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

# ── Login ─────────────────────────────────────────────────────────────────────
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

# ── Painel principal ──────────────────────────────────────────────────────────
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
        has_pw = "✅ Sim" if t.dashboard_password else "⚠️ Sem senha"
        badge_pw = "badge-green" if t.dashboard_password else "badge-gray"
        rows += f"""
        <div class="tenant-row">
            <div>
                <div class="tenant-name">{t.display_name or t.name}</div>
                <div style="font-size:12px;color:#9aa0b8;margin-top:2px">{t.phone_number_id or 'sem whatsapp'} · {count} agendamentos · {clientes} clientes</div>
            </div>
            <span class="tenant-type">{tipo}</span>
            <span class="badge {badge_pw}">{has_pw}</span>
            <a href="/admin/tenant/{t.id}" class="btn btn-outline btn-sm">⚙️ Configurar</a>
        </div>"""

    if not rows:
        rows = '<div style="color:#9aa0b8;text-align:center;padding:24px">Nenhum tenant ainda. Crie o primeiro abaixo.</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — Painel</title>{ADMIN_STYLE}</head><body>
<div class="header">
    <div class="logo">⚙️ Admin Panel</div>
    <a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a>
</div>
<div class="container">

<div class="card">
    <div class="card-title">🏢 Clientes ativos ({len(tenants)})</div>
    {rows}
</div>

<div class="card">
    <div class="card-title">➕ Novo cliente</div>
    <form method="POST" action="/admin/tenant">
    <div class="grid2">
        <div class="form-group"><label>Nome do negócio *</label>
        <input name="name" placeholder="Ex: PetShop Amigo Fiel" required></div>
        <div class="form-group"><label>Tipo de negócio *</label>
        <select name="business_type">
            <option value="petshop">🐾 Pet Shop</option>
            <option value="clinica">🏥 Clínica Veterinária</option>
            <option value="adocao">🐶 Clínica de Adoção</option>
            <option value="outro">⚙️ Outro</option>
        </select></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Phone Number ID (WhatsApp)</label>
        <input name="phone_number_id" placeholder="ID do número na Meta"></div>
        <div class="form-group"><label>WA Access Token</label>
        <input name="wa_access_token" placeholder="Token da API do WhatsApp"></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Nome do "sujeito" (singular)</label>
        <input name="subject_label" placeholder="Pet" value="Pet"></div>
        <div class="form-group"><label>Nome do "sujeito" (plural)</label>
        <input name="subject_label_plural" placeholder="Pets" value="Pets"></div>
    </div>
    <div class="form-group"><label>Senha do dashboard *</label>
    <input name="dashboard_password" type="password" placeholder="Senha que o cliente vai usar" required></div>
    <button type="submit" class="btn btn-primary">Criar cliente</button>
    </form>
</div>

</div></body></html>""")

# ── Criar tenant ──────────────────────────────────────────────────────────────
@router.post("/admin/tenant")
async def create_tenant(request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    form = await request.form()
    name = form.get("name", "").strip()
    business_type = form.get("business_type", "petshop")
    phone_number_id = form.get("phone_number_id", "").strip() or None
    wa_access_token = form.get("wa_access_token", "").strip() or None
    subject_label = form.get("subject_label", "Pet").strip()
    subject_label_plural = form.get("subject_label_plural", "Pets").strip()
    raw_pw = form.get("dashboard_password", "").strip()

    if not name or not raw_pw:
        return RedirectResponse("/admin?error=campos_obrigatorios", status_code=302)

    hashed = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()

    tenant = Tenant(
        name=name,
        display_name=name,
        business_type=business_type,
        phone_number_id=phone_number_id,
        wa_access_token=wa_access_token,
        subject_label=subject_label,
        subject_label_plural=subject_label_plural,
        dashboard_password=hashed,
        dashboard_token=secrets.token_urlsafe(32),
    )
    db.add(tenant)
    db.flush()

    # Serviços padrão por tipo de negócio
    default_services = _default_services(business_type, tenant.id)
    for s in default_services:
        db.add(s)

    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant.id}?created=1", status_code=302)

def _default_services(business_type: str, tenant_id: str) -> list:
    defaults = {
        "petshop": [
            ("Banho Simples", 60, 4000, "#74b9ff", "Banho com secagem"),
            ("Banho e Tosa", 90, 7000, "#6C5CE7", "Banho completo com tosa"),
            ("Tosa Higiênica", 45, 3500, "#a29bfe", "Limpeza das partes íntimas"),
            ("Consulta Veterinária", 30, 12000, "#00b894", "Consulta com veterinário"),
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
            ("Castração", 90, 35000, "#6C5CE7", "Procedimento de castração"),
            ("Microchip", 20, 5000, "#74b9ff", "Implante de microchip"),
            ("Vacinação", 20, 6000, "#55efc4", "Carteira de vacinação"),
        ],
        "outro": [
            ("Serviço Padrão", 60, 10000, "#6C5CE7", "Descreva seu serviço"),
        ],
    }
    services = []
    for name, duration, price, color, desc in defaults.get(business_type, defaults["outro"]):
        services.append(Service(
            tenant_id=tenant_id,
            name=name,
            duration_min=duration,
            price=price,
            color=color,
            description=desc,
            active=True,
        ))
    return services

# ── Configurar tenant ─────────────────────────────────────────────────────────
@router.get("/admin/tenant/{tenant_id}", response_class=HTMLResponse)
def tenant_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return HTMLResponse("<h2>Tenant não encontrado</h2>", status_code=404)

    services = db.query(Service).filter(Service.tenant_id == tenant_id).order_by(Service.active.desc(), Service.name).all()
    created = request.query_params.get("created") == "1"
    alert = '<div class="alert alert-success">✅ Cliente criado com sucesso!</div>' if created else ""

    # Gera link do dashboard
    dashboard_url = f"{request.base_url}dashboard?tid={tenant_id}"

    # Lista de serviços
    svc_rows = ""
    for s in services:
        status_badge = '<span class="badge badge-green">Ativo</span>' if s.active else '<span class="badge badge-gray">Inativo</span>'
        price_fmt = f"R$ {s.price/100:.2f}" if s.price else "Grátis"
        svc_rows += f"""
        <div class="service-row">
            <div class="service-color" style="background:{s.color or '#6C5CE7'}"></div>
            <div class="service-name">{s.name}</div>
            <div class="service-meta">{s.duration_min}min · {price_fmt}</div>
            {status_badge}
            <form method="POST" action="/admin/tenant/{tenant_id}/service/{s.id}/toggle" style="display:inline">
                <button type="submit" class="btn btn-outline btn-sm">{'Desativar' if s.active else 'Ativar'}</button>
            </form>
            <form method="POST" action="/admin/tenant/{tenant_id}/service/{s.id}/delete" style="display:inline">
                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Remover serviço?')">✕</button>
            </form>
        </div>"""

    if not svc_rows:
        svc_rows = '<div style="color:#9aa0b8;text-align:center;padding:16px">Nenhum serviço cadastrado.</div>'

    tipo = BUSINESS_TYPES.get(tenant.business_type, tenant.business_type)

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Admin — {tenant.display_name or tenant.name}</title>{ADMIN_STYLE}</head><body>
<div class="header">
    <div class="logo">⚙️ Admin Panel</div>
    <a href="/admin/logout" class="btn btn-outline btn-sm">Sair</a>
</div>
<div class="container">
<a href="/admin" class="back">← Voltar</a>
{alert}

<div class="card">
    <div class="card-title">🏢 {tenant.display_name or tenant.name} <span class="tag">{tipo}</span></div>

    <div style="background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:14px;margin-bottom:18px">
        <div style="font-size:12px;color:#9aa0b8;margin-bottom:6px">🔗 Link do dashboard (envie para o cliente)</div>
        <div style="font-family:'DM Mono',monospace;font-size:13px;color:#7c7de8;word-break:break-all">{dashboard_url}</div>
    </div>

    <form method="POST" action="/admin/tenant/{tenant_id}/config">
    <div class="grid2">
        <div class="form-group"><label>Nome exibido</label>
        <input name="display_name" value="{tenant.display_name or tenant.name}"></div>
        <div class="form-group"><label>Tipo de negócio</label>
        <select name="business_type">
            {''.join(f'<option value="{k}" {"selected" if k==tenant.business_type else ""}>{v}</option>' for k,v in BUSINESS_TYPES.items())}
        </select></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>{tenant.subject_label} (singular)</label>
        <input name="subject_label" value="{tenant.subject_label or 'Pet'}"></div>
        <div class="form-group"><label>{tenant.subject_label_plural} (plural)</label>
        <input name="subject_label_plural" value="{tenant.subject_label_plural or 'Pets'}"></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Phone Number ID</label>
        <input name="phone_number_id" value="{tenant.phone_number_id or ''}"></div>
        <div class="form-group"><label>WA Access Token</label>
        <input name="wa_access_token" value="{tenant.wa_access_token or ''}"></div>
    </div>
    <button type="submit" class="btn btn-primary">Salvar configurações</button>
    </form>
</div>

<div class="card">
    <div class="card-title">🔑 Senha do dashboard</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/password">
    <div style="display:flex;gap:12px;align-items:flex-end">
        <div class="form-group" style="flex:1;margin:0"><label>Nova senha</label>
        <input name="password" type="password" placeholder="Nova senha para o cliente" required></div>
        <button type="submit" class="btn btn-primary">Salvar senha</button>
    </div>
    </form>
</div>

<div class="card">
    <div class="card-title">✂️ Serviços ({len(services)})</div>
    {svc_rows}
    <div class="divider"></div>
    <div class="section-title">Adicionar serviço</div>
    <form method="POST" action="/admin/tenant/{tenant_id}/service">
    <div class="grid3">
        <div class="form-group"><label>Nome *</label>
        <input name="name" placeholder="Ex: Banho e Tosa" required></div>
        <div class="form-group"><label>Duração (min) *</label>
        <input name="duration_min" type="number" value="60" min="5" required></div>
        <div class="form-group"><label>Preço (R$)</label>
        <input name="price" type="number" step="0.01" placeholder="70.00"></div>
    </div>
    <div class="grid2">
        <div class="form-group"><label>Descrição curta (p/ o bot)</label>
        <input name="description" placeholder="Ex: Banho com secagem e perfume"></div>
        <div class="form-group"><label>Cor</label>
        <input name="color" type="color" value="#6C5CE7" style="height:42px;padding:4px 8px"></div>
    </div>
    <button type="submit" class="btn btn-primary">Adicionar serviço</button>
    </form>
</div>

</div></body></html>""")

# ── Config geral ──────────────────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/config")
async def save_config(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return JSONResponse({"error": "Tenant não encontrado"}, status_code=404)
    tenant.display_name = form.get("display_name", tenant.display_name)
    tenant.business_type = form.get("business_type", tenant.business_type)
    tenant.subject_label = form.get("subject_label", tenant.subject_label)
    tenant.subject_label_plural = form.get("subject_label_plural", tenant.subject_label_plural)
    tenant.phone_number_id = form.get("phone_number_id") or tenant.phone_number_id
    tenant.wa_access_token = form.get("wa_access_token") or tenant.wa_access_token
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Senha ─────────────────────────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/password")
async def save_password(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    raw_pw = form.get("password", "").strip()
    if not raw_pw:
        return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        tenant.dashboard_password = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}?saved=1", status_code=302)

# ── Serviços ──────────────────────────────────────────────────────────────────
@router.post("/admin/tenant/{tenant_id}/service")
async def add_service(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
    price_raw = form.get("price", "0")
    try:
        price_cents = int(float(price_raw) * 100)
    except:
        price_cents = 0
    svc = Service(
        tenant_id=tenant_id,
        name=name,
        duration_min=int(form.get("duration_min", 60)),
        price=price_cents,
        description=form.get("description", ""),
        color=form.get("color", "#6C5CE7"),
        active=True,
    )
    db.add(svc)
    db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/toggle")
def toggle_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc:
        svc.active = not svc.active
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)

@router.post("/admin/tenant/{tenant_id}/service/{service_id}/delete")
def delete_service(tenant_id: str, service_id: str, request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant_id).first()
    if svc:
        db.delete(svc)
        db.commit()
    return RedirectResponse(f"/admin/tenant/{tenant_id}", status_code=302)
