from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Tenant, Service
import os, bcrypt, secrets, httpx

router = APIRouter()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")

DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

ADDRESS_LABELS = [
    "Endereço de busca",
    "Endereço de entrega",
    "Endereço de coleta",
    "Endereço do cliente",
]

# ─── CSS / estilo base (mesmo visual do admin) ────────────────────────────────
SETUP_STYLE = """
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh}
.header{background:#13151f;padding:0 28px;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2d3148}
.logo{font-size:18px;font-weight:800;color:#7c7de8}
.container{max-width:680px;margin:0 auto;padding:36px 20px 60px}
.card{background:#1a1d27;border:1px solid #2d3148;border-radius:16px;padding:28px;margin-bottom:20px}
.card-title{font-size:17px;font-weight:800;margin-bottom:6px;color:#e8eaf2}
.card-sub{font-size:13px;color:#9aa0b8;margin-bottom:22px;line-height:1.6}
label{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}
input:focus,select:focus{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}
.btn{padding:10px 22px;border-radius:10px;border:none;cursor:pointer;font-size:14px;font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s}
.btn-primary{background:#5B5BD6;color:#fff}.btn-primary:hover{background:#7c7de8}
.btn-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}.btn-success:hover{background:#243d24}
.btn-outline{background:transparent;color:#9aa0b8;border:1px solid #2d3148}.btn-outline:hover{border-color:#7c7de8;color:#7c7de8}
.btn-danger{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.btn-sm{padding:6px 14px;font-size:12px;border-radius:8px}
.btn-full{width:100%;padding:13px}
.form-group{margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.divider{height:1px;background:#2d3148;margin:20px 0}
.alert{padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:16px}
.alert-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}
.alert-error{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.alert-info{background:#1a1d3a;color:#a29bfe;border:1px solid rgba(162,155,254,.2)}

/* Progress steps */
.steps{display:flex;align-items:center;gap:0;margin-bottom:32px}
.step-item{display:flex;flex-direction:column;align-items:center;flex:1}
.step-circle{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;border:2px solid #2d3148;background:#0f1117;color:#9aa0b8;transition:all .3s}
.step-circle.active{background:#5B5BD6;border-color:#5B5BD6;color:#fff}
.step-circle.done{background:#1a2e1a;border-color:#68d391;color:#68d391}
.step-label{font-size:10px;color:#9aa0b8;margin-top:5px;font-weight:600;text-align:center}
.step-label.active{color:#7c7de8}
.step-line{flex:1;height:2px;background:#2d3148;margin-top:-18px}
.step-line.done{background:#68d391}

/* Toggle */
.toggle-switch{position:relative;display:inline-flex;align-items:center;gap:10px;cursor:pointer}
.toggle-switch input{opacity:0;width:0;height:0}
.slider{width:44px;height:24px;background:#2d3148;border-radius:12px;position:relative;transition:background .2s;flex-shrink:0}
.slider:before{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:white;top:3px;left:3px;transition:transform .2s}
.toggle-switch input:checked + .slider{background:#5B5BD6}
.toggle-switch input:checked + .slider:before{transform:translateX(20px)}

/* Dias */
.days-grid{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.day-btn{padding:6px 14px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#9aa0b8;cursor:pointer;font-size:12px;font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s}
.day-btn.active{background:#23254a;border-color:#7c7de8;color:#7c7de8}

/* Serviços */
.service-row{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.service-dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}

/* WA connection */
.conn-status{padding:14px 18px;border-radius:12px;font-size:14px;font-weight:600;text-align:center;margin-bottom:14px}
.conn-loading{background:#1a1d3a;color:#a29bfe;border:1px solid #2d3148}
.conn-ok{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}
.conn-fail{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}

/* Checklist */
.check-row{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #2d3148}
.check-row:last-child{border-bottom:none}
.check-icon{font-size:18px;width:28px;text-align:center;flex-shrink:0}
.check-label{font-size:14px;font-weight:600}
.check-sub{font-size:12px;color:#9aa0b8;margin-top:2px}

/* Senha */
.pw-strength{height:4px;border-radius:2px;margin-top:6px;transition:all .3s}

@media(max-width:600px){.grid2{grid-template-columns:1fr}.steps{gap:0}.step-label{display:none}}
</style>
"""

def _steps_html(current: int) -> str:
    labels = ["Negócio", "Horários", "Serviços", "WhatsApp", "Finalizar"]
    items = ""
    for i, label in enumerate(labels, 1):
        if i < current:
            circle_cls = "done"
            circle_content = "✓"
        elif i == current:
            circle_cls = "active"
            circle_content = str(i)
        else:
            circle_cls = ""
            circle_content = str(i)

        label_cls = "active" if i == current else ""
        items += f'<div class="step-item"><div class="step-circle {circle_cls}">{circle_content}</div><div class="step-label {label_cls}">{label}</div></div>'
        if i < len(labels):
            line_cls = "done" if i < current else ""
            items += f'<div class="step-line {line_cls}"></div>'
    return f'<div class="steps">{items}</div>'

def _get_tenant_by_token(token: str, db: Session):
    if not token:
        return None
    return db.query(Tenant).filter(Tenant.setup_token == token, Tenant.setup_done == False).first()

def _error_page(msg: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Erro — Setup AgendaBot</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container" style="max-width:480px">
<div class="card" style="text-align:center;padding:40px 28px">
<div style="font-size:40px;margin-bottom:16px">⚠️</div>
<div style="font-size:18px;font-weight:800;margin-bottom:10px">Link inválido</div>
<div style="font-size:14px;color:#9aa0b8;line-height:1.7">{msg}</div>
</div></div></body></html>""", status_code=400)


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 1 — Confirmar nome do negócio e atendente
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_step1(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return _error_page("Nenhum token fornecido. Verifique o link que você recebeu por email.")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Este link é inválido ou já foi utilizado. Entre em contato com o suporte.")

    display = tenant.display_name or tenant.name or ""
    attendant = getattr(tenant, 'bot_attendant_name', 'Mari') or 'Mari'
    biz_name = getattr(tenant, 'bot_business_name', '') or display

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup — Passo 1</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container">
{_steps_html(1)}

<div class="card">
  <div class="card-title">👋 Bem-vindo ao AgendaBot!</div>
  <div class="card-sub">Vamos configurar tudo em 5 passos simples. Confirme as informações básicas do seu negócio abaixo.</div>

  <form method="POST" action="/setup/step1?token={token}">
    <input type="hidden" name="token" value="{token}">

    <div class="form-group">
      <label>Nome do estabelecimento *</label>
      <input name="display_name" value="{display}" required placeholder="Ex: Barbearia do João">
      <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Como aparece para os clientes no WhatsApp</div>
    </div>

    <div class="form-group">
      <label>Nome da atendente virtual *</label>
      <input name="bot_attendant_name" value="{attendant}" required placeholder="Ex: Mari, Ana, Luna...">
      <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Nome da IA que conversa com seus clientes</div>
    </div>

    <div class="form-group">
      <label>Nome do negócio que a atendente usa nas mensagens</label>
      <input name="bot_business_name" value="{biz_name}" placeholder="Ex: Barbearia do João">
      <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Ex: "Olá! Sou a Mari da <strong>Barbearia do João</strong>"</div>
    </div>

    <button type="submit" class="btn btn-primary btn-full">Próximo →</button>
  </form>
</div>
</div></body></html>""")


@router.post("/setup/step1", response_class=HTMLResponse)
async def setup_step1_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    form = await request.form()
    token = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    tenant.display_name       = form.get("display_name", "").strip() or tenant.display_name
    tenant.bot_attendant_name = form.get("bot_attendant_name", "Mari").strip()
    tenant.bot_business_name  = form.get("bot_business_name", "").strip() or tenant.display_name
    db.commit()
    return RedirectResponse(f"/setup/step2?token={token}", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 2 — Horários, dias e toggle de endereço
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup/step2", response_class=HTMLResponse)
def setup_step2(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    open_days_list = [d.strip() for d in (getattr(tenant, 'open_days', '0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns = ''.join(
        f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" data-day="{i}" onclick="toggleDay(this)">{d}</button>'
        for i, d in enumerate(DAYS_PT)
    )
    open_time  = getattr(tenant, 'open_time', '09:00') or '09:00'
    close_time = getattr(tenant, 'close_time', '18:00') or '18:00'
    needs_address = getattr(tenant, 'needs_address', False)
    current_label = getattr(tenant, 'address_label', 'Endereço de busca') or 'Endereço de busca'
    na_checked = 'checked' if needs_address else ''
    addr_display = 'block' if needs_address else 'none'

    addr_opts = ''.join(f'<option value="{l}" {"selected" if l == current_label else ""}>{l}</option>' for l in ADDRESS_LABELS)

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup — Passo 2</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container">
{_steps_html(2)}

<div class="card">
  <div class="card-title">⏰ Horário de funcionamento</div>
  <div class="card-sub">Configure os dias e horários em que seu negócio atende. O bot não vai aceitar agendamentos fora desses períodos.</div>

  <form method="POST" action="/setup/step2?token={token}">
    <input type="hidden" name="token" value="{token}">

    <div class="form-group">
      <label>Dias de atendimento</label>
      <div class="days-grid" id="days-grid">{days_btns}</div>
      <input type="hidden" name="open_days" id="open_days_val" value="{','.join(open_days_list)}">
    </div>

    <div class="grid2">
      <div class="form-group">
        <label>Abre às</label>
        <input name="open_time" type="time" value="{open_time}">
      </div>
      <div class="form-group">
        <label>Fecha às</label>
        <input name="close_time" type="time" value="{close_time}">
      </div>
    </div>

    <div class="divider"></div>
    <div style="font-size:13px;font-weight:700;margin-bottom:12px">📍 Coleta de endereço</div>

    <div class="form-group">
      <label class="toggle-switch">
        <input type="checkbox" name="needs_address" value="1" id="needs_addr_cb" {na_checked} onchange="toggleAddr(this.checked)">
        <span class="slider"></span>
        <span style="font-size:13px;color:#e8eaf2;font-weight:600">Meu negócio busca ou entrega no endereço do cliente</span>
      </label>
      <div style="font-size:12px;color:#9aa0b8;margin-top:8px;margin-left:54px">Ativa quando você tem pet shop com busca, delivery, etc.</div>
    </div>

    <div id="addr-label-wrap" style="display:{addr_display}">
      <div class="form-group">
        <label>Como chamar o campo de endereço</label>
        <select name="address_label">{addr_opts}</select>
      </div>
    </div>

    <div style="display:flex;gap:10px;margin-top:8px">
      <a href="/setup?token={token}" class="btn btn-outline" style="flex:1;text-align:center">← Voltar</a>
      <button type="submit" class="btn btn-primary" style="flex:2">Próximo →</button>
    </div>
  </form>
</div>
</div>
<script>
function toggleDay(btn) {{
  btn.classList.toggle('active');
  const active = [...document.querySelectorAll('.day-btn.active')].map(b => b.dataset.day);
  document.getElementById('open_days_val').value = active.join(',');
}}
function toggleAddr(checked) {{
  document.getElementById('addr-label-wrap').style.display = checked ? 'block' : 'none';
}}
</script>
</body></html>""")


@router.post("/setup/step2", response_class=HTMLResponse)
async def setup_step2_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    form = await request.form()
    token = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    tenant.open_days      = form.get("open_days", "0,1,2,3,4,5")
    tenant.open_time      = form.get("open_time", "09:00")
    tenant.close_time     = form.get("close_time", "18:00")
    tenant.needs_address  = form.get("needs_address") == "1"
    tenant.address_label  = form.get("address_label", "Endereço de busca")
    db.commit()
    return RedirectResponse(f"/setup/step3?token={token}", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 3 — Serviços (add / remove inline)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup/step3", response_class=HTMLResponse)
def setup_step3(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    services = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).all()

    svc_rows = ""
    for s in services:
        price_fmt = f"R$ {s.price/100:.2f}" if s.price else "Grátis"
        svc_rows += f"""
        <div class="service-row">
          <div class="service-dot" style="background:{s.color or '#6C5CE7'}"></div>
          <div style="flex:1">
            <div style="font-weight:600;font-size:14px">{s.name}</div>
            <div style="font-size:12px;color:#9aa0b8">{s.duration_min}min · {price_fmt}</div>
          </div>
          <form method="POST" action="/setup/step3/delete/{s.id}?token={token}">
            <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Remover {s.name}?')">✕</button>
          </form>
        </div>"""

    if not svc_rows:
        svc_rows = '<div style="color:#9aa0b8;font-size:13px;text-align:center;padding:18px 0">Nenhum serviço cadastrado ainda.</div>'

    saved = request.query_params.get("saved") == "1"
    alert = '<div class="alert alert-success">✅ Serviço adicionado!</div>' if saved else ""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup — Passo 3</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container">
{_steps_html(3)}

<div class="card">
  <div class="card-title">✂️ Serviços oferecidos</div>
  <div class="card-sub">Cadastre os serviços que seu negócio oferece. O bot vai usar essas informações para apresentar opções aos clientes.</div>

  {alert}

  <div id="svc-list">{svc_rows}</div>

  <div class="divider"></div>
  <div style="font-size:13px;font-weight:700;margin-bottom:14px">Adicionar serviço</div>

  <form method="POST" action="/setup/step3/add?token={token}">
    <input type="hidden" name="token" value="{token}">
    <div class="grid2">
      <div class="form-group">
        <label>Nome do serviço *</label>
        <input name="name" placeholder="Ex: Corte + Barba" required>
      </div>
      <div class="form-group">
        <label>Duração (minutos)</label>
        <input name="duration_min" type="number" value="60" min="5" max="480">
      </div>
    </div>
    <div class="grid2">
      <div class="form-group">
        <label>Preço (R$)</label>
        <input name="price" type="number" step="0.01" placeholder="50.00">
      </div>
      <div class="form-group">
        <label>Descrição (opcional)</label>
        <input name="description" placeholder="Ex: Inclui lavagem e finalização">
      </div>
    </div>
    <button type="submit" class="btn btn-success btn-sm">+ Adicionar serviço</button>
  </form>
</div>

<div style="display:flex;gap:10px">
  <a href="/setup/step2?token={token}" class="btn btn-outline" style="flex:1;text-align:center">← Voltar</a>
  <a href="/setup/step4?token={token}" class="btn btn-primary" style="flex:2;text-align:center;display:flex;align-items:center;justify-content:center">Próximo →</a>
</div>
</div></body></html>""")


@router.post("/setup/step3/add")
async def setup_step3_add(request: Request, token: str = "", db: Session = Depends(get_db)):
    form = await request.form()
    token = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    name = form.get("name", "").strip()
    if name:
        try: price_cents = int(float(form.get("price", "0") or "0") * 100)
        except: price_cents = 0
        try: duration = int(form.get("duration_min", "60") or "60")
        except: duration = 60

        # Cor por index dos serviços existentes
        COLORS = ["#6C5CE7","#74b9ff","#00b894","#fd79a8","#f0a500","#a29bfe","#55efc4","#e17055"]
        count = db.query(Service).filter(Service.tenant_id == tenant.id).count()
        color = COLORS[count % len(COLORS)]

        db.add(Service(
            tenant_id=tenant.id,
            name=name,
            duration_min=duration,
            price=price_cents,
            description=form.get("description", "").strip() or None,
            color=color,
            active=True,
        ))
        db.commit()

    return RedirectResponse(f"/setup/step3?token={token}&saved=1", status_code=302)


@router.post("/setup/step3/delete/{service_id}")
def setup_step3_delete(service_id: str, request: Request, token: str = "", db: Session = Depends(get_db)):
    token = token or request.query_params.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
    if svc:
        db.delete(svc)
        db.commit()
    return RedirectResponse(f"/setup/step3?token={token}", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 4 — Conectar WhatsApp via Evolution API + teste live
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup/step4", response_class=HTMLResponse)
def setup_step4(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    current_instance = tenant.phone_number_id or ""
    evo_url = EVOLUTION_API_URL.rstrip("/") if EVOLUTION_API_URL else ""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup — Passo 4</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container">
{_steps_html(4)}

<div class="card">
  <div class="card-title">📱 Conectar WhatsApp</div>
  <div class="card-sub">Informe o nome da instância da Evolution API que você criou para este negócio. O bot usará esse número para conversar com seus clientes.</div>

  <div class="alert alert-info" style="margin-bottom:20px">
    💡 <strong>Não sabe o que é isso?</strong> Você precisa ter a Evolution API instalada e uma instância criada. Peça ajuda ao suporte ou assista ao tutorial em vídeo.
  </div>

  <div class="form-group">
    <label>Nome da instância Evolution API *</label>
    <input type="text" id="instance-input" value="{current_instance}" placeholder="Ex: barbearia-joao" oninput="resetStatus()">
    <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Exatamente como foi criado no painel da Evolution API (sem espaços)</div>
  </div>

  <div id="conn-status" style="display:none" class="conn-status conn-loading">⏳ Verificando conexão...</div>

  <div style="display:flex;gap:8px;margin-bottom:20px">
    <button onclick="testConnection()" class="btn btn-outline btn-sm">🔍 Testar conexão</button>
  </div>

  <div class="divider"></div>

  <div style="font-size:13px;font-weight:700;margin-bottom:14px">📋 Passos para conectar</div>
  <div style="font-size:13px;color:#9aa0b8;line-height:1.8">
    <div style="padding:8px 0;border-bottom:1px solid #2d3148">1. Acesse o painel da Evolution API no seu servidor</div>
    <div style="padding:8px 0;border-bottom:1px solid #2d3148">2. Crie uma nova instância com um nome sem espaços (ex: <code style="color:#a29bfe;background:#1a1d27;padding:1px 5px;border-radius:4px">meu-petshop</code>)</div>
    <div style="padding:8px 0;border-bottom:1px solid #2d3148">3. Escaneie o QR Code com o WhatsApp Business do seu negócio</div>
    <div style="padding:8px 0;border-bottom:1px solid #2d3148">4. Aguarde aparecer "Connected" na Evolution</div>
    <div style="padding:8px 0">5. Cole o nome da instância acima e clique em "Testar conexão"</div>
  </div>

  <div class="divider"></div>

  <div style="display:flex;gap:10px;margin-top:8px">
    <a href="/setup/step3?token={token}" class="btn btn-outline" style="flex:1;text-align:center">← Voltar</a>
    <button onclick="saveAndNext()" class="btn btn-primary" style="flex:2">Salvar e continuar →</button>
  </div>
</div>
</div>

<script>
const TOKEN = "{token}";
let lastStatus = null;

function resetStatus() {{
  const el = document.getElementById('conn-status');
  el.style.display = 'none';
  lastStatus = null;
}}

async function testConnection() {{
  const instance = document.getElementById('instance-input').value.trim();
  if (!instance) {{ alert('Digite o nome da instância primeiro.'); return; }}
  const el = document.getElementById('conn-status');
  el.style.display = 'block';
  el.className = 'conn-status conn-loading';
  el.textContent = '⏳ Verificando conexão...';

  try {{
    const res = await fetch(`/setup/test-whatsapp?token=${{TOKEN}}&instance=${{encodeURIComponent(instance)}}`);
    const data = await res.json();
    lastStatus = data.status;
    if (data.status === 'connected') {{
      el.className = 'conn-status conn-ok';
      el.textContent = '✅ WhatsApp conectado com sucesso!';
    }} else if (data.status === 'not_found') {{
      el.className = 'conn-status conn-fail';
      el.textContent = '❌ Instância não encontrada. Verifique o nome.';
    }} else {{
      el.className = 'conn-status conn-fail';
      el.textContent = '⚠️ WhatsApp desconectado. Escaneie o QR Code na Evolution API.';
    }}
  }} catch(e) {{
    el.className = 'conn-status conn-fail';
    el.textContent = '❌ Erro ao conectar com a Evolution API.';
  }}
}}

async function saveAndNext() {{
  const instance = document.getElementById('instance-input').value.trim();
  if (!instance) {{ alert('Informe o nome da instância antes de continuar.'); return; }}
  const res = await fetch(`/setup/step4/save?token=${{TOKEN}}`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{instance}})
  }});
  if (res.ok) {{
    window.location.href = `/setup/step5?token=${{TOKEN}}`;
  }} else {{
    const data = await res.json().catch(() => ({{}}));
    alert(data.error || 'Erro ao salvar. Tente novamente.');
  }}
}}
</script>
</body></html>""")


@router.get("/setup/test-whatsapp")
async def test_whatsapp(token: str = "", instance: str = "", db: Session = Depends(get_db)):
    """Testa se a instância Evolution API está conectada."""
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Token inválido"}, status_code=400)

    if not instance:
        return JSONResponse({"status": "error", "message": "Instância não informada"}, status_code=400)

    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        return JSONResponse({"status": "error", "message": "Evolution API não configurada no servidor"}, status_code=500)

    url = f"{EVOLUTION_API_URL.rstrip('/')}/instance/connectionState/{instance}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers={"apikey": EVOLUTION_API_KEY})
        if resp.status_code == 404:
            return JSONResponse({"status": "not_found"})
        data = resp.json()
        state = data.get("instance", {}).get("state", "") or data.get("state", "")
        if state in ("open", "connected"):
            return JSONResponse({"status": "connected"})
        return JSONResponse({"status": "disconnected", "state": state})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/setup/step4/save")
async def setup_step4_save(request: Request, token: str = "", db: Session = Depends(get_db)):
    token = token or request.query_params.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return JSONResponse({"error": "Token inválido"}, status_code=400)

    body = await request.json()
    instance = (body.get("instance") or "").strip()
    if not instance:
        return JSONResponse({"ok": True})

    # Verifica se já está em uso por outro tenant
    existing = db.query(Tenant).filter(
        Tenant.phone_number_id == instance,
        Tenant.id != tenant.id
    ).first()
    if existing:
        return JSONResponse(
            {"error": f"A instância '{instance}' já está em uso por outro negócio. Use um nome diferente."},
            status_code=409
        )

    tenant.phone_number_id = instance
    try:
        db.commit()
    except Exception:
        db.rollback()
        return JSONResponse({"error": "Erro ao salvar. Tente novamente."}, status_code=500)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 5 — Checklist + criar senha + ativar bot
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup/step5", response_class=HTMLResponse)
def setup_step5(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    services = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).count()
    has_wa = bool(tenant.phone_number_id)
    has_services = services > 0

    checks = [
        ("✅" if (tenant.display_name or tenant.name) else "⚠️",
         "Nome do negócio", tenant.display_name or tenant.name or "Não informado",
         bool(tenant.display_name or tenant.name)),
        ("✅" if getattr(tenant, 'open_days', None) else "⚠️",
         "Horários configurados",
         f"{getattr(tenant,'open_time','09:00')} às {getattr(tenant,'close_time','18:00')}",
         bool(getattr(tenant, 'open_days', None))),
        ("✅" if has_services else "⚠️",
         "Serviços cadastrados",
         f"{services} serviço(s)" if has_services else "Nenhum serviço cadastrado",
         has_services),
        ("✅" if has_wa else "⚠️",
         "WhatsApp conectado",
         tenant.phone_number_id if has_wa else "Instância não configurada",
         has_wa),
    ]

    check_rows = ""
    for icon, label, sub, ok in checks:
        color = "#68d391" if ok else "#f6c90e"
        check_rows += f"""
        <div class="check-row">
          <div class="check-icon">{icon}</div>
          <div style="flex:1">
            <div class="check-label" style="color:{color}">{label}</div>
            <div class="check-sub">{sub}</div>
          </div>
        </div>"""

    error = request.query_params.get("error", "")
    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup — Passo 5</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container">
{_steps_html(5)}

<div class="card">
  <div class="card-title">📋 Resumo da configuração</div>
  <div class="card-sub">Verifique se tudo está correto antes de ativar o bot.</div>
  {check_rows}
</div>

<div class="card">
  <div class="card-title">🔑 Criar senha do painel</div>
  <div class="card-sub">Crie uma senha para acessar seu painel de agendamentos. Guarde em local seguro.</div>

  {err_html}

  <form method="POST" action="/setup/complete?token={token}">
    <input type="hidden" name="token" value="{token}">

    <div class="form-group">
      <label>Nova senha *</label>
      <input type="password" name="password" id="pw" placeholder="Mínimo 6 caracteres" required minlength="6" oninput="checkPw()">
      <div class="pw-strength" id="pw-bar" style="background:#2d3148;width:0%"></div>
    </div>

    <div class="form-group">
      <label>Confirmar senha *</label>
      <input type="password" name="password2" id="pw2" placeholder="Repita a senha" required minlength="6">
    </div>

    <button type="submit" class="btn btn-primary btn-full" style="margin-top:8px">🚀 Ativar bot e finalizar</button>
  </form>
</div>

<div style="display:flex;gap:10px">
  <a href="/setup/step4?token={token}" class="btn btn-outline" style="flex:1;text-align:center">← Voltar</a>
</div>
</div>

<script>
function checkPw() {{
  const pw = document.getElementById('pw').value;
  const bar = document.getElementById('pw-bar');
  let strength = 0;
  if (pw.length >= 6) strength++;
  if (pw.length >= 10) strength++;
  if (/[A-Z]/.test(pw)) strength++;
  if (/[0-9]/.test(pw)) strength++;
  const colors = ['#fc8181','#f6c90e','#68d391','#00b894'];
  const widths = ['25%','50%','75%','100%'];
  bar.style.background = colors[strength-1] || '#2d3148';
  bar.style.width = widths[strength-1] || '0%';
}}
</script>
</body></html>""")


@router.post("/setup/complete")
async def setup_complete(request: Request, token: str = "", db: Session = Depends(get_db)):
    form = await request.form()
    token = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido ou expirado.")

    pw  = form.get("password", "").strip()
    pw2 = form.get("password2", "").strip()

    if len(pw) < 6:
        return RedirectResponse(f"/setup/step5?token={token}&error=A+senha+deve+ter+ao+menos+6+caracteres.", status_code=302)
    if pw != pw2:
        return RedirectResponse(f"/setup/step5?token={token}&error=As+senhas+não+coincidem.", status_code=302)

    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    tenant.dashboard_password = hashed
    if not tenant.dashboard_token:
        tenant.dashboard_token = secrets.token_urlsafe(32)
    tenant.bot_active  = True
    tenant.setup_done  = True
    tenant.setup_token = None   # invalida o link — não pode ser reutilizado
    db.commit()

    return RedirectResponse(f"/setup/done?tid={tenant.id}", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# DONE — Página de conclusão
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/setup/done", response_class=HTMLResponse)
def setup_done(request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == tid, Tenant.setup_done == True).first()
    if not tenant:
        return _error_page("Página não encontrada.")

    base_url = request.headers.get("x-forwarded-proto", "https") + "://" + request.headers.get("host", "")
    dashboard_url = f"{base_url}/dashboard?tid={tenant.id}"
    display = tenant.display_name or tenant.name

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup concluído! 🎉</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">🤖 AgendaBot Setup</div></div>
<div class="container" style="max-width:520px">

<div class="card" style="text-align:center;padding:40px 28px">
  <div style="font-size:48px;margin-bottom:16px">🎉</div>
  <div style="font-size:22px;font-weight:800;margin-bottom:8px">Tudo pronto!</div>
  <div style="font-size:14px;color:#9aa0b8;line-height:1.7;margin-bottom:24px">
    O AgendaBot do <strong style="color:#e8eaf2">{display}</strong> está configurado e ativo.<br>
    Seus clientes já podem agendar pelo WhatsApp! 🚀
  </div>

  <div style="background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:16px;margin-bottom:20px;text-align:left">
    <div style="font-size:11px;color:#9aa0b8;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:.4px">Seu painel de agendamentos</div>
    <div style="font-family:'DM Mono',monospace;font-size:13px;color:#7c7de8;word-break:break-all">{dashboard_url}</div>
  </div>

  <a href="{dashboard_url}" class="btn btn-primary btn-full">Acessar meu painel →</a>
  <div style="font-size:12px;color:#9aa0b8;margin-top:12px">Salve esse link nos seus favoritos!</div>
</div>

</div></body></html>""")