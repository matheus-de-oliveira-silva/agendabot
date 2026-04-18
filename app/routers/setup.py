"""
setup.py — Wizard de onboarding do BotGen.

Correções v2:
- Rebranding: AgendaBot → BotGen
- setup_token NÃO é zerado após conclusão (admin precisa ver o link no painel)
- _get_tenant_by_token não filtra setup_done — permite reabrir setup
- Passo 4 (WhatsApp) é OPCIONAL — cliente pode pular e aguardar suporte
- bot_active = True APENAS se phone_number_id estiver configurado
- setup_done = True sempre ao concluir (independente do WhatsApp)
- Mensagem clara na tela final sobre próximo passo se WhatsApp não configurado
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Tenant, Service
import os, bcrypt, secrets, httpx, re as _re

router = APIRouter()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
APP_URL           = os.getenv("APP_URL", "")
APP_URL           = os.getenv("APP_URL", "")

DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

ADDRESS_LABELS = [
    "Endereço de busca",
    "Endereço de entrega",
    "Endereço de coleta",
    "Endereço do cliente",
]

COLLECT_DEFAULTS = {
    "petshop":        {"pet_name": True,  "pet_breed": True,  "pet_weight": True,  "pickup_time": True,  "address": True,  "notes": False, "phone": False},
    "clinica":        {"pet_name": True,  "pet_breed": True,  "pet_weight": True,  "pickup_time": False, "address": False, "notes": False, "phone": False},
    "clinica_humana": {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "adocao":         {"pet_name": True,  "pet_breed": True,  "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "barbearia":      {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": False, "phone": False},
    "salao":          {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "estetica":       {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": True,  "phone": False},
    "delivery":       {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": True,  "notes": True,  "phone": False},
    "outro":          {"pet_name": False, "pet_breed": False, "pet_weight": False, "pickup_time": False, "address": False, "notes": False, "phone": False},
}

COLLECT_LABELS = {
    "pet_name":    ("Nome do pet/animal",       "🐾"),
    "pet_breed":   ("Raça do pet",              "🦴"),
    "pet_weight":  ("Peso do pet",              "⚖️"),
    "pickup_time": ("Horário de busca/entrega", "🏠"),
    "address":     ("Endereço de busca/entrega","📍"),
    "notes":       ("Observações do cliente",   "📝"),
    "phone":       ("Telefone de contato",      "📱"),
}

BUSINESS_TYPES = {
    "petshop":        {"label": "🐾 Pet Shop",               "subject": "Pet",     "subject_plural": "Pets",     "icon": "🐾", "needs_address_suggest": True},
    "clinica":        {"label": "🏥 Clínica Veterinária",    "subject": "Animal",  "subject_plural": "Animais",  "icon": "🏥", "needs_address_suggest": False},
    "clinica_humana": {"label": "🩺 Clínica / Consultório",  "subject": "",        "subject_plural": "",         "icon": "🩺", "needs_address_suggest": False},
    "adocao":         {"label": "🐶 ONG / Adoção",           "subject": "Animal",  "subject_plural": "Animais",  "icon": "🐶", "needs_address_suggest": False},
    "barbearia":      {"label": "💈 Barbearia",               "subject": "",        "subject_plural": "",         "icon": "💈", "needs_address_suggest": False},
    "salao":          {"label": "💅 Salão de Beleza",         "subject": "",        "subject_plural": "",         "icon": "💅", "needs_address_suggest": False},
    "estetica":       {"label": "✨ Estética / Spa",          "subject": "",        "subject_plural": "",         "icon": "✨", "needs_address_suggest": False},
    "delivery":       {"label": "🛵 Delivery / Restaurante",  "subject": "",        "subject_plural": "",         "icon": "🛵", "needs_address_suggest": True},
    "outro":          {"label": "⚙️ Outro",                  "subject": "",        "subject_plural": "",         "icon": "⚙️", "needs_address_suggest": False},
}

SERVICOS_PADRAO = {
    "petshop":   [("Banho Simples",60,4000,"#74b9ff","Banho com secagem"),("Banho e Tosa",90,7000,"#6C5CE7","Banho completo com tosa"),("Tosa Higiênica",45,3500,"#a29bfe","Limpeza higiênica"),("Consulta Veterinária",30,12000,"#00b894","Consulta com vet")],
    "clinica":   [("Consulta Clínica",30,15000,"#00b894","Consulta geral"),("Vacinação",20,8000,"#55efc4","Aplicação de vacinas"),("Exame de Sangue",15,12000,"#fd79a8","Coleta e análise"),("Cirurgia",120,80000,"#e17055","Procedimento cirúrgico")],
    "adocao":    [("Consulta Pré-adoção",30,0,"#00b894","Avaliação para adoção"),("Castração",90,35000,"#6C5CE7","Castração"),("Microchip",20,5000,"#74b9ff","Implante de microchip"),("Vacinação",20,6000,"#55efc4","Carteira de vacinação")],
    "barbearia": [("Corte",30,4000,"#74b9ff","Corte masculino"),("Barba",20,3000,"#6C5CE7","Barba completa"),("Corte + Barba",50,6500,"#a29bfe","Combo completo"),("Sobrancelha",15,1500,"#00b894","Design de sobrancelha")],
    "salao":     [("Corte Feminino",60,8000,"#fd79a8","Corte e finalização"),("Escova",45,6000,"#f0a500","Escova progressiva"),("Coloração",120,15000,"#6C5CE7","Coloração completa"),("Manicure",40,4000,"#00b894","Unhas mãos")],
    "estetica":  [("Limpeza de Pele",60,9000,"#74b9ff","Limpeza profunda"),("Depilação",45,6000,"#fd79a8","Depilação a cera"),("Massagem",60,12000,"#00b894","Massagem relaxante"),("Design de Sobrancelha",30,5000,"#6C5CE7","Design completo")],
    "clinica_humana": [("Consulta",30,15000,"#00b894","Consulta médica"),("Retorno",20,8000,"#55efc4","Consulta de retorno"),("Exame",15,12000,"#fd79a8","Exame laboratorial"),("Procedimento",60,35000,"#e17055","Procedimento clínico")],
    "delivery":       [("Hamburguer",30,3000,"#e17055","Hamburguer artesanal"),("Pizza",40,4500,"#f0a500","Pizza média"),("Marmita",20,2000,"#00b894","Marmita do dia"),("Combo",45,5500,"#6C5CE7","Combo especial")],
    "outro":          [("Serviço Padrão",60,10000,"#6C5CE7","Descreva seu serviço")],
}


# ── CSS ───────────────────────────────────────────────────────────────────────

SETUP_STYLE = """
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:#0f1117;color:#e8eaf2;min-height:100vh;overflow-x:hidden}
.header{background:#13151f;padding:0 28px;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2d3148}
.logo{font-size:18px;font-weight:800;color:#7c7de8}
.container{max-width:680px;margin:0 auto;padding:36px 20px 60px}
.card{background:#1a1d27;border:1px solid #2d3148;border-radius:16px;padding:28px;margin-bottom:20px}
.card-title{font-size:17px;font-weight:800;margin-bottom:6px;color:#e8eaf2}
.card-sub{font-size:13px;color:#9aa0b8;margin-bottom:22px;line-height:1.6}
label{display:block;font-size:11px;font-weight:600;color:#9aa0b8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid #2d3148;border-radius:10px;background:#0f1117;color:#e8eaf2;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .2s}
input:focus,select:focus{border-color:#7c7de8;box-shadow:0 0 0 3px #23254a}
.btn{padding:10px 22px;border-radius:10px;border:none;cursor:pointer;font-size:14px;font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s;display:inline-block;text-decoration:none;text-align:center}
.btn-primary{background:#5B5BD6;color:#fff}.btn-primary:hover{background:#7c7de8}
.btn-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}.btn-success:hover{background:#243d24}
.btn-outline{background:transparent;color:#9aa0b8;border:1px solid #2d3148}.btn-outline:hover{border-color:#7c7de8;color:#7c7de8}
.btn-danger{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.btn-warn{background:#2a2200;color:#f6c90e;border:1px solid rgba(246,201,14,.2)}.btn-warn:hover{background:#3a3000}
.btn-sm{padding:6px 14px;font-size:12px;border-radius:8px}
.btn-full{width:100%;padding:13px}
.form-group{margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.divider{height:1px;background:#2d3148;margin:20px 0}
.alert{padding:12px 16px;border-radius:10px;font-size:13px;margin-bottom:16px;line-height:1.6}
.alert-success{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}
.alert-error{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.alert-info{background:#1a1d3a;color:#a29bfe;border:1px solid rgba(162,155,254,.2)}
.alert-warn{background:#2a2200;color:#f6c90e;border:1px solid rgba(246,201,14,.2)}
.steps{display:flex;align-items:center;gap:0;margin-bottom:32px}
.step-item{display:flex;flex-direction:column;align-items:center;flex:1}
.step-circle{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;border:2px solid #2d3148;background:#0f1117;color:#9aa0b8;transition:all .3s}
.step-circle.active{background:#5B5BD6;border-color:#5B5BD6;color:#fff}
.step-circle.done{background:#1a2e1a;border-color:#68d391;color:#68d391}
.step-label{font-size:10px;color:#9aa0b8;margin-top:5px;font-weight:600;text-align:center}
.step-label.active{color:#7c7de8}
.step-line{flex:1;height:2px;background:#2d3148;margin-top:-18px}
.step-line.done{background:#68d391}
.toggle-switch{position:relative;display:inline-flex;align-items:center;gap:10px;cursor:pointer}
.toggle-switch input{opacity:0;width:0;height:0}
.slider{width:44px;height:24px;background:#2d3148;border-radius:12px;position:relative;transition:background .2s;flex-shrink:0}
.slider:before{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:white;top:3px;left:3px;transition:transform .2s}
.toggle-switch input:checked + .slider{background:#5B5BD6}
.toggle-switch input:checked + .slider:before{transform:translateX(20px)}
.days-grid{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.day-btn{padding:6px 14px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#9aa0b8;cursor:pointer;font-size:12px;font-weight:700;font-family:'DM Sans',sans-serif;transition:all .15s}
.day-btn.active{background:#23254a;border-color:#7c7de8;color:#7c7de8}
.service-row{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid #2d3148;border-radius:10px;margin-bottom:8px;background:#0f1117}
.service-dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}
.conn-status{padding:14px 18px;border-radius:12px;font-size:14px;font-weight:600;text-align:center;margin-bottom:14px}
.conn-loading{background:#1a1d3a;color:#a29bfe;border:1px solid #2d3148}
.conn-ok{background:#1a2e1a;color:#68d391;border:1px solid rgba(104,211,145,.2)}
.conn-fail{background:#2d1515;color:#fc8181;border:1px solid rgba(252,129,129,.2)}
.check-row{display:flex;align-items:flex-start;gap:12px;padding:12px 0;border-bottom:1px solid #2d3148}
.check-row:last-child{border-bottom:none}
.check-icon{font-size:18px;width:28px;text-align:center;flex-shrink:0;margin-top:1px}
.check-label{font-size:14px;font-weight:600}
.check-sub{font-size:12px;color:#9aa0b8;margin-top:2px}
.pw-strength{height:4px;border-radius:2px;margin-top:6px;transition:all .3s}
.biz-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px}
.biz-card{padding:16px;border:2px solid #2d3148;border-radius:12px;background:#0f1117;cursor:pointer;text-align:center;transition:all .2s}
.biz-card:hover{border-color:#7c7de8;background:#23254a}
.biz-card.selected{border-color:#5B5BD6;background:#23254a;box-shadow:0 0 0 3px #23254a}
.biz-icon{font-size:28px;margin-bottom:8px}
.biz-label{font-size:13px;font-weight:700;color:#e8eaf2}
@media(max-width:600px){.grid2{grid-template-columns:1fr}.steps{gap:0}.step-label{display:none}.biz-grid{grid-template-columns:1fr 1fr}.card{padding:16px}.container{padding:16px 12px 40px}}
</style>
"""


def _steps_html(current: int) -> str:
    labels = ["Negócio", "Dados", "Horários", "Campos", "Serviços", "WhatsApp", "Finalizar"]
    items = ""
    for i, label in enumerate(labels, 1):
        if i < current:
            circle_cls, circle_content = "done", "✓"
        elif i == current:
            circle_cls, circle_content = "active", str(i)
        else:
            circle_cls, circle_content = "", str(i)
        label_cls = "active" if i == current else ""
        items += f'<div class="step-item"><div class="step-circle {circle_cls}">{circle_content}</div><div class="step-label {label_cls}">{label}</div></div>'
        if i < len(labels):
            line_cls = "done" if i < current else ""
            items += f'<div class="step-line {line_cls}"></div>'
    return f'<div class="steps">{items}</div>'


def _get_tenant_by_token(token: str, db: Session):
    """
    FIX: Não filtra por setup_done — permite reabrir o setup.
    O admin pode regenerar o token via /admin/tenant/{id}/resend-setup,
    que seta setup_done=False, permitindo o cliente refazer o wizard.
    """
    if not token:
        return None
    return db.query(Tenant).filter(Tenant.setup_token == token).first()


def _get_base_url(request: Request) -> str:
    if APP_URL:
        return APP_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "https")
    host  = request.headers.get("host", "")
    return f"{proto}://{host}"


def _error_page(msg: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Erro — BotGen Setup</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container" style="max-width:480px">
<div class="card" style="text-align:center;padding:40px 28px">
<div style="font-size:40px;margin-bottom:16px">⚠️</div>
<div style="font-size:18px;font-weight:800;margin-bottom:10px">Link inválido</div>
<div style="font-size:14px;color:#9aa0b8;line-height:1.7">{msg}</div>
<div style="font-size:13px;color:#9aa0b8;margin-top:16px">Se precisar de um novo link, entre em contato com o suporte.</div>
</div></div></body></html>""", status_code=400)


# ── PASSO 0 — Tipo de negócio ─────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_step0(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return _error_page("Nenhum token fornecido. Verifique o link que você recebeu.")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Este link é inválido. Entre em contato com o suporte para receber um novo link.")

    # Se já concluiu o setup, mostra aviso mas não bloqueia
    already_done = getattr(tenant, 'setup_done', False)
    done_banner  = ""
    if already_done:
        base_url      = _get_base_url(request)
        dashboard_url = f"{base_url}/dashboard?tid={tenant.id}"
        done_banner   = f"""<div class="alert alert-warn" style="margin-bottom:20px">
            ⚠️ Você já concluiu o setup anteriormente. Se quiser reconfigurar algo, pode continuar abaixo.
            Ou <a href="{dashboard_url}" style="color:#f6c90e;font-weight:700">acesse seu painel aqui</a>.
        </div>"""

    biz_cards = ""
    selected_biz = tenant.business_type or ""
    for key, info in BUSINESS_TYPES.items():
        selected_cls = "selected" if key == selected_biz else ""
        biz_cards += f"""
        <div class="biz-card {selected_cls}" id="biz-{key}" onclick="selectBiz('{key}')">
            <div class="biz-icon">{info['icon']}</div>
            <div class="biz-label">{info['label']}</div>
        </div>"""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(1)}
{done_banner}
<div class="card">
  <div class="card-title">👋 Bem-vindo ao BotGen!</div>
  <div class="card-sub">Vamos configurar seu bot em poucos minutos. Primeiro, qual é o tipo do seu negócio?</div>
  <form method="POST" action="/setup/step0?token={token}">
    <input type="hidden" name="token" value="{token}">
    <input type="hidden" name="business_type" id="biz_type_val" value="{selected_biz}">
    <div class="biz-grid">{biz_cards}</div>
    <div id="biz-error" style="display:none;margin-top:12px" class="alert alert-error">
      Por favor, selecione o tipo do seu negócio.
    </div>
    <button type="button" onclick="submitStep0()" class="btn btn-primary btn-full" style="margin-top:20px">
      Próximo →
    </button>
  </form>
</div>
</div>
<script>
function selectBiz(key) {{
  document.querySelectorAll('.biz-card').forEach(c => c.classList.remove('selected'));
  document.getElementById('biz-' + key).classList.add('selected');
  document.getElementById('biz_type_val').value = key;
  document.getElementById('biz-error').style.display = 'none';
}}
function submitStep0() {{
  const val = document.getElementById('biz_type_val').value;
  if (!val) {{ document.getElementById('biz-error').style.display = 'block'; return; }}
  document.querySelector('form').submit();
}}
</script>
</body></html>""")


@router.post("/setup/step0")
async def setup_step0_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    biz_type = form.get("business_type", "outro")
    if biz_type not in BUSINESS_TYPES:
        biz_type = "outro"

    info                        = BUSINESS_TYPES[biz_type]
    tenant.business_type        = biz_type
    tenant.tenant_icon          = info["icon"]
    tenant.subject_label        = info["subject"]
    tenant.subject_label_plural = info["subject_plural"]

    # Remove serviços anteriores e adiciona padrão do tipo
    db.query(Service).filter(Service.tenant_id == tenant.id).delete()
    for nome, dur, preco, cor, desc in SERVICOS_PADRAO.get(biz_type, SERVICOS_PADRAO["outro"]):
        db.add(Service(
            tenant_id=tenant.id, name=nome, duration_min=dur,
            price=preco, color=cor, description=desc, active=True
        ))
    db.commit()
    return RedirectResponse(f"/setup/step1?token={token}", status_code=302)


# ── PASSO 1 — Dados do negócio ────────────────────────────────────────────────

@router.get("/setup/step1", response_class=HTMLResponse)
def setup_step1(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    display   = tenant.display_name or tenant.name or ""
    attendant = getattr(tenant, 'bot_attendant_name', 'Mari') or 'Mari'
    biz_name  = getattr(tenant, 'bot_business_name', '') or display
    biz_label = BUSINESS_TYPES.get(tenant.business_type or "outro", {}).get("label", "Negócio")

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(2)}
<div class="card">
  <div class="card-title">🏢 Dados do negócio</div>
  <div class="card-sub">Tipo: <strong style="color:#7c7de8">{biz_label}</strong> — confirme as informações abaixo.</div>
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
      <label>Nome do negócio nas mensagens</label>
      <input name="bot_business_name" value="{biz_name}" placeholder="Ex: Barbearia do João">
      <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Usado pela IA: "Sou a Mari da <strong>{biz_name or 'seu negócio'}</strong>"</div>
    </div>
    <div style="display:flex;gap:10px">
      <a href="/setup?token={token}" class="btn btn-outline" style="flex:1">← Voltar</a>
      <button type="submit" class="btn btn-primary" style="flex:2">Próximo →</button>
    </div>
  </form>
</div>
</div></body></html>""")


@router.post("/setup/step1")
async def setup_step1_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    tenant.display_name       = form.get("display_name", "").strip() or tenant.display_name
    tenant.bot_attendant_name = form.get("bot_attendant_name", "Mari").strip() or "Mari"
    tenant.bot_business_name  = form.get("bot_business_name", "").strip() or tenant.display_name
    db.commit()
    return RedirectResponse(f"/setup/step2?token={token}", status_code=302)


# ── PASSO 2 — Horários e endereço ─────────────────────────────────────────────

@router.get("/setup/step2", response_class=HTMLResponse)
def setup_step2(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    open_days_list = [d.strip() for d in (getattr(tenant, 'open_days', '0,1,2,3,4,5') or '0,1,2,3,4,5').split(',')]
    days_btns      = ''.join(
        f'<button type="button" class="day-btn {"active" if str(i) in open_days_list else ""}" data-day="{i}" onclick="toggleDay(this)">{d}</button>'
        for i, d in enumerate(DAYS_PT)
    )
    open_time      = getattr(tenant, 'open_time',  '09:00') or '09:00'
    close_time     = getattr(tenant, 'close_time', '18:00') or '18:00'
    needs_address  = getattr(tenant, 'needs_address', False)
    current_label  = getattr(tenant, 'address_label', 'Endereço de busca') or 'Endereço de busca'
    na_checked     = 'checked' if needs_address else ''
    addr_display   = 'block' if needs_address else 'none'
    addr_opts      = ''.join(f'<option value="{l}" {"selected" if l == current_label else ""}>{l}</option>' for l in ADDRESS_LABELS)
    biz_type            = tenant.business_type or "outro"
    addr_suggest        = BUSINESS_TYPES.get(biz_type, {}).get("needs_address_suggest", False)
    suggest_html        = ""
    pix_key             = getattr(tenant, 'pix_key', '') or ''
    payment_note        = getattr(tenant, 'payment_note', '') or ''
    current_pay_methods = getattr(tenant, 'payment_methods', 'pix,dinheiro,cartao') or 'pix,dinheiro,cartao' 
    if addr_suggest and not needs_address:
        suggest_html = '<div class="alert alert-info" style="margin-bottom:12px">💡 Pet shops geralmente fazem busca e entrega. Ative abaixo se for o seu caso!</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(3)}
<div class="card">
  <div class="card-title">⏰ Horário de funcionamento</div>
  <div class="card-sub">Configure os dias e horários em que seu negócio atende.</div>
  <form method="POST" action="/setup/step2?token={token}">
    <input type="hidden" name="token" value="{token}">
    <div class="form-group">
      <label>Dias de atendimento</label>
      <div class="days-grid" id="days-grid">{days_btns}</div>
      <input type="hidden" name="open_days" id="open_days_val" value="{','.join(open_days_list)}">
    </div>
    <div class="grid2">
      <div class="form-group"><label>Abre às</label><input name="open_time" type="time" value="{open_time}"></div>
      <div class="form-group"><label>Fecha às</label><input name="close_time" type="time" value="{close_time}"></div>
    </div>
    <div class="divider"></div>
    <div style="font-size:13px;font-weight:700;margin-bottom:12px">📍 Coleta de endereço</div>
    {suggest_html}
    <div class="form-group">
      <label class="toggle-switch">
        <input type="checkbox" name="needs_address" value="1" id="needs_addr_cb" {na_checked} onchange="toggleAddr(this.checked)">
        <span class="slider"></span>
        <span style="font-size:13px;color:#e8eaf2;font-weight:600">Meu negócio busca ou entrega no endereço do cliente</span>
      </label>
    </div>
    <div id="addr-label-wrap" style="display:{addr_display}">
      <div class="form-group">
        <label>Como chamar o campo de endereço</label>
        <select name="address_label">{addr_opts}</select>
      </div>
    </div>
    <div class="divider"></div>
    <div style="font-size:13px;font-weight:700;margin-bottom:12px">💳 Pagamento</div>
    <div class="form-group">
      <label>Chave PIX (para o bot informar ao cliente)</label>
      <input type="text" name="pix_key" value="{pix_key}" placeholder="Ex: 11999999999 ou email@negocio.com">
      <div style="font-size:11px;color:#9aa0b8;margin-top:4px">Deixe em branco se não aceita PIX ou prefere combinar pessoalmente</div>
    </div>
    <div class="form-group">
      <label>Formas de pagamento aceitas</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#e8eaf2;cursor:pointer">
          <input type="checkbox" name="pay_pix" value="1" id="pay_pix" {"checked" if "pix" in (current_pay_methods or "pix") else ""}> PIX
        </label>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#e8eaf2;cursor:pointer">
          <input type="checkbox" name="pay_dinheiro" value="1" {"checked" if "dinheiro" in (current_pay_methods or "dinheiro") else ""}> Dinheiro
        </label>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#e8eaf2;cursor:pointer">
          <input type="checkbox" name="pay_cartao" value="1" {"checked" if "cartao" in (current_pay_methods or "cartao") else ""}> Cartão
        </label>
      </div>
    </div>
    <div class="form-group">
      <label>Observação de pagamento (opcional)</label>
      <input type="text" name="payment_note" value="{payment_note}" placeholder="Ex: Pagamento na entrega ou antecipado via PIX">
    </div>
    <div style="display:flex;gap:10px;margin-top:8px">
      <a href="/setup/step1?token={token}" class="btn btn-outline" style="flex:1">← Voltar</a>
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


@router.post("/setup/step2")
async def setup_step2_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    tenant.open_days     = form.get("open_days", "0,1,2,3,4,5")
    tenant.open_time     = form.get("open_time", "09:00")
    tenant.close_time    = form.get("close_time", "18:00")
    tenant.needs_address = form.get("needs_address") == "1"
    tenant.address_label = form.get("address_label", "Endereço de busca")
    # PIX e pagamento
    tenant.pix_key       = (form.get("pix_key") or "").strip() or None
    tenant.payment_note  = (form.get("payment_note") or "").strip() or None
    pay_methods = []
    if form.get("pay_pix"):      pay_methods.append("pix")
    if form.get("pay_dinheiro"): pay_methods.append("dinheiro")
    if form.get("pay_cartao"):   pay_methods.append("cartao")
    tenant.payment_methods = ",".join(pay_methods) if pay_methods else "pix,dinheiro,cartao"
    db.commit()
    return RedirectResponse(f"/setup/campos?token={token}", status_code=302)


# ── PASSO 2b — Campos de coleta ──────────────────────────────────────────────

@router.get("/setup/campos", response_class=HTMLResponse)
def setup_campos(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")
    import json as _j
    biz_type = tenant.business_type or "outro"
    defaults = COLLECT_DEFAULTS.get(biz_type, COLLECT_DEFAULTS["outro"]).copy()
    try:
        saved = _j.loads(tenant.collect_fields or "{}") if tenant.collect_fields else {}
        defaults.update(saved)
    except Exception:
        pass

    def _cb(key):
        return "checked" if defaults.get(key, False) else ""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(4)}
<div class="card">
  <div class="card-title">📋 O que o bot deve coletar?</div>
  <div class="card-sub">Configure quais informações a IA vai perguntar ao cliente. Os 3 primeiros são sempre coletados automaticamente.</div>
  <div style="background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:14px 16px;margin-bottom:20px">
    <div style="font-size:11px;font-weight:700;color:#9aa0b8;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px">Sempre coletados</div>
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="font-size:13px;color:#5a6172"><span style="color:#2e7d32;font-weight:800">✓</span> 👤 Nome do cliente</div>
      <div style="font-size:13px;color:#5a6172"><span style="color:#2e7d32;font-weight:800">✓</span> ✂️ Serviço</div>
      <div style="font-size:13px;color:#5a6172"><span style="color:#2e7d32;font-weight:800">✓</span> 📅 Data e horário</div>
    </div>
  </div>
  <div style="font-size:11px;font-weight:700;color:#9aa0b8;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px">Opcionais — ative o que quiser</div>
  <form method="POST" action="/setup/campos?token={token}">
    <input type="hidden" name="token" value="{token}">
    <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:24px">
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">🐾 Nome do pet/animal</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Ex: Rex, Mel, Thor</div></div>
        <input type="checkbox" name="pet_name" value="1" {_cb('pet_name')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">🦴 Raça do pet</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Ex: Labrador, Poodle</div></div>
        <input type="checkbox" name="pet_breed" value="1" {_cb('pet_breed')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">⚖️ Peso do pet</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Útil para calcular doses</div></div>
        <input type="checkbox" name="pet_weight" value="1" {_cb('pet_weight')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">🏠 Horário de busca/entrega</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Para negócios que buscam ou entregam</div></div>
        <input type="checkbox" name="pickup_time" value="1" {_cb('pickup_time')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">📍 Endereço de busca/entrega</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Para delivery ou busca em domicílio</div></div>
        <input type="checkbox" name="address" value="1" {_cb('address')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">📝 Observações do cliente</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Ex: alergias, preferências especiais</div></div>
        <input type="checkbox" name="notes" value="1" {_cb('notes')}>
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:12px 14px;cursor:pointer">
        <div><div style="font-size:13px;font-weight:600;color:#e8eaf2">📱 Telefone de contato</div><div style="font-size:11px;color:#9aa0b8;margin-top:2px">Além do WhatsApp, pede número extra</div></div>
        <input type="checkbox" name="phone" value="1" {_cb('phone')}>
      </label>
    </div>
    <div style="display:flex;gap:10px">
      <a href="/setup/step2?token={token}" class="btn btn-outline" style="flex:1">← Voltar</a>
      <button type="submit" class="btn btn-primary" style="flex:2">Próximo →</button>
    </div>
  </form>
</div>
</div>
</body></html>""")


@router.post("/setup/campos")
async def setup_campos_post(request: Request, token: str = "", db: Session = Depends(get_db)):
    import json as _j
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")
    fields = {
        "pet_name":    form.get("pet_name")    == "1",
        "pet_breed":   form.get("pet_breed")   == "1",
        "pet_weight":  form.get("pet_weight")  == "1",
        "pickup_time": form.get("pickup_time") == "1",
        "address":     form.get("address")     == "1",
        "notes":       form.get("notes")       == "1",
        "phone":       form.get("phone")       == "1",
    }
    tenant.collect_fields = _j.dumps(fields)
    tenant.needs_address  = fields["address"]
    db.commit()
    return RedirectResponse(f"/setup/step3?token={token}", status_code=302)


# ── PASSO 3 — Serviços ────────────────────────────────────────────────────────

@router.get("/setup/step3", response_class=HTMLResponse)
def setup_step3(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    services  = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).all()
    plano     = getattr(tenant, 'plan', 'basico') or 'basico'
    limite    = 7 if plano == 'basico' else 999
    qtd_atual = len(services)

    limite_html = ""
    if plano == 'basico':
        cor = "#fc8181" if qtd_atual >= limite else "#9aa0b8"
        limite_html = f'<div style="font-size:12px;color:{cor};margin-bottom:12px">Plano Básico: {qtd_atual}/{limite} serviços. {"⚠️ Limite atingido." if qtd_atual >= limite else ""}</div>'

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
        svc_rows = '<div style="color:#9aa0b8;font-size:13px;text-align:center;padding:18px 0">Nenhum serviço cadastrado.</div>'

    saved      = request.query_params.get("saved") == "1"
    alert      = '<div class="alert alert-success">✅ Serviço adicionado!</div>' if saved else ""
    limit_reached = qtd_atual >= limite
    add_display   = 'none' if limit_reached else 'block'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(4)}
<div class="card">
  <div class="card-title">✂️ Serviços oferecidos</div>
  <div class="card-sub">Cadastre os serviços que seu negócio oferece. O bot usa essas informações para apresentar opções aos clientes.</div>
  {alert}
  {limite_html}
  <div id="svc-list">{svc_rows}</div>
  <div id="add-form" style="display:{add_display}">
    <div class="divider"></div>
    <div style="font-size:13px;font-weight:700;margin-bottom:14px">Adicionar serviço</div>
    <form method="POST" action="/setup/step3/add?token={token}">
      <input type="hidden" name="token" value="{token}">
      <div class="grid2">
        <div class="form-group"><label>Nome *</label><input name="name" placeholder="Ex: Corte + Barba" required></div>
        <div class="form-group"><label>Duração (min)</label><input name="duration_min" type="number" value="60" min="5" max="480"></div>
      </div>
      <div class="grid2">
        <div class="form-group"><label>Preço (R$)</label><input name="price" type="number" step="0.01" placeholder="50.00"></div>
        <div class="form-group"><label>Descrição (opcional)</label><input name="description" placeholder="Ex: Inclui lavagem"></div>
      </div>
      <button type="submit" class="btn btn-success btn-sm">+ Adicionar serviço</button>
    </form>
  </div>
</div>
<div style="display:flex;gap:10px">
  <a href="/setup/step2?token={token}" class="btn btn-outline" style="flex:1">← Voltar</a>
  <a href="/setup/step4?token={token}" class="btn btn-primary" style="flex:2">Próximo →</a>
</div>
</div></body></html>""")


@router.post("/setup/step3/add")
async def setup_step3_add(request: Request, token: str = "", db: Session = Depends(get_db)):
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    plano = getattr(tenant, 'plan', 'basico') or 'basico'
    if plano == 'basico':
        count = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).count()
        if count >= 7:
            return RedirectResponse(f"/setup/step3?token={token}", status_code=302)

    name = form.get("name", "").strip()
    if name:
        try:    price_cents = int(float(form.get("price", "0") or "0") * 100)
        except: price_cents = 0
        try:    duration = int(form.get("duration_min", "60") or "60")
        except: duration = 60

        COLORS = ["#6C5CE7","#74b9ff","#00b894","#fd79a8","#f0a500","#a29bfe","#55efc4","#e17055"]
        count = db.query(Service).filter(Service.tenant_id == tenant.id).count()
        db.add(Service(
            tenant_id=tenant.id, name=name, duration_min=duration,
            price=price_cents, description=form.get("description", "").strip() or None,
            color=COLORS[count % len(COLORS)], active=True,
        ))
        db.commit()

    return RedirectResponse(f"/setup/step3?token={token}&saved=1", status_code=302)


@router.post("/setup/step3/delete/{service_id}")
def setup_step3_delete(service_id: str, request: Request, token: str = "", db: Session = Depends(get_db)):
    token  = token or request.query_params.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")
    svc = db.query(Service).filter(Service.id == service_id, Service.tenant_id == tenant.id).first()
    if svc:
        db.delete(svc)
        db.commit()
    return RedirectResponse(f"/setup/step3?token={token}", status_code=302)


# ── PASSO 4 — WhatsApp (OPCIONAL) ────────────────────────────────────────────

@router.get("/setup/step4", response_class=HTMLResponse)
async def setup_step4(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    # Gera nome da instância baseado no tenant — único e sem espaços
    # Formato: botgen-{primeiros 8 chars do tenant.id}
    # Só cria se ainda não tem instância configurada
    instance_name = tenant.phone_number_id or f"botgen-{tenant.id[:8]}"

    # Cria a instância automaticamente SE ainda não existir
    # Idempotente — se já existe retorna success=True sem duplicar
    if not tenant.phone_number_id and EVOLUTION_API_URL and EVOLUTION_API_KEY:
        from ..services.evolution_helper import create_instance
        result = await create_instance(instance_name)
        if result.get("success"):
            tenant.phone_number_id = instance_name
            db.commit()

    has_instance = bool(tenant.phone_number_id)
    instance_name = tenant.phone_number_id or instance_name

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}
<style>
.qr-wrap{{text-align:center;padding:20px;background:#0f1117;border-radius:12px;border:1px solid #2d3148;margin-bottom:16px}}
.qr-wrap img{{max-width:220px;width:100%;border-radius:8px}}
.qr-status{{font-size:13px;color:#9aa0b8;margin-top:10px}}
.pulse{{animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
</style>
</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(5)}
<div class="card">
  <div class="card-title">📱 Conectar WhatsApp</div>
  <div class="card-sub">Escaneie o QR Code abaixo com o <strong>WhatsApp Business</strong> do seu negócio para conectar o bot.</div>

  <div id="main-content">
    {"" if not has_instance or not EVOLUTION_API_URL else f'''
    <div class="alert alert-info" style="margin-bottom:16px">
      📱 Instância: <strong>{instance_name}</strong> — Aguardando conexão
    </div>
    <div class="qr-wrap" id="qr-wrap">
      <div class="pulse" style="font-size:13px;color:#9aa0b8">⏳ Carregando QR Code...</div>
    </div>
    '''}
    {"" if EVOLUTION_API_URL else '<div class="alert alert-warn">⚠️ Evolution API não configurada. O suporte vai conectar o WhatsApp na chamada de ativação. Pode pular esta etapa.</div>'}
  </div>

  <div id="conn-status" style="display:none" class="conn-status conn-loading">⏳ Verificando...</div>

  <div class="divider"></div>

  <div style="font-size:13px;font-weight:700;margin-bottom:10px">Como funciona:</div>
  <div style="font-size:13px;color:#9aa0b8;line-height:1.8;margin-bottom:16px">
    <div style="padding:6px 0;border-bottom:1px solid #2d3148">1. Abra o WhatsApp Business do seu negócio</div>
    <div style="padding:6px 0;border-bottom:1px solid #2d3148">2. Vá em <strong style="color:#e8eaf2">Aparelhos conectados → Conectar aparelho</strong></div>
    <div style="padding:6px 0;border-bottom:1px solid #2d3148">3. Escaneie o QR Code acima</div>
    <div style="padding:6px 0">4. Aguarde a confirmação ✅</div>
  </div>

  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <a href="/setup/step3?token={token}" class="btn btn-outline" style="flex:1;min-width:120px">← Voltar</a>
    <button onclick="skipStep()" class="btn btn-warn" style="flex:1;min-width:140px">Pular por enquanto →</button>
    <button onclick="checkAndContinue()" class="btn btn-primary" style="flex:2;min-width:160px" id="btn-continue">Já conectei →</button>
  </div>
</div>
</div>

<script>
const TOKEN   = "{token}";
const INSTANCE = "{instance_name}";
const HAS_EVO  = {"true" if EVOLUTION_API_URL else "false"};
let pollTimer   = null;
let connected   = false;
let pollAttempts = 0;
const MAX_POLL   = 60; // máx 4 minutos de polling

async function loadQR() {{
  if (!HAS_EVO) return;
  try {{
    const r = await fetch(`/setup/qrcode?token=${{TOKEN}}&instance=${{encodeURIComponent(INSTANCE)}}`);
    const d = await r.json();
    const wrap = document.getElementById('qr-wrap');
    if (!wrap) return;
    if (d.qrcode) {{
      wrap.innerHTML = `<img src="${{d.qrcode.startsWith('data:') ? d.qrcode : 'data:image/png;base64,' + d.qrcode}}" alt="QR Code"><div class="qr-status">Aponte a câmera do WhatsApp Business para este código</div>`;
    }} else {{
      wrap.innerHTML = '<div style="color:#9aa0b8;font-size:13px;padding:16px">⏳ QR Code sendo gerado... Aguarde.</div>';
      setTimeout(loadQR, 3000);
    }}
  }} catch(e) {{
    setTimeout(loadQR, 4000);
  }}
}}

async function pollConnection() {{
  if (!HAS_EVO || connected) return;
  pollAttempts++;
  // Para de fazer polling após o limite
  if (pollAttempts > MAX_POLL) {{
    const el = document.getElementById('conn-status');
    if (el) {{
      el.style.display = 'block';
      el.className = 'conn-status conn-fail';
      el.textContent = '⏱️ Tempo expirado. Clique em "Já conectei" se já escaneou o QR Code.';
    }}
    return;
  }}
  try {{
    const r = await fetch(`/setup/test-whatsapp?token=${{TOKEN}}&instance=${{encodeURIComponent(INSTANCE)}}`);
    const d = await r.json();
    if (d.status === 'connected') {{
      connected = true;
      clearTimeout(pollTimer);
      const el = document.getElementById('conn-status');
      if (el) {{
        el.style.display = 'block';
        el.className = 'conn-status conn-ok';
        el.textContent = '✅ WhatsApp conectado! Pode continuar.';
      }}
      const btn = document.getElementById('btn-continue');
      if (btn) {{
        btn.textContent = 'Continuar →';
        btn.style.background = '#2e7d32';
      }}
    }} else {{
      // Intervalo aumenta após 10 tentativas (economiza recursos)
      const interval = pollAttempts > 10 ? 8000 : 4000;
      pollTimer = setTimeout(pollConnection, interval);
    }}
  }} catch(e) {{
    pollTimer = setTimeout(pollConnection, 6000);
  }}
}}

async function checkAndContinue() {{
  if (!HAS_EVO) {{
    window.location.href = `/setup/step5?token=${{TOKEN}}`;
    return;
  }}
  const r = await fetch(`/setup/test-whatsapp?token=${{TOKEN}}&instance=${{encodeURIComponent(INSTANCE)}}`);
  const d = await r.json();
  if (d.status === 'connected') {{
    window.location.href = `/setup/step5?token=${{TOKEN}}`;
  }} else {{
    const el = document.getElementById('conn-status');
    el.style.display = 'block';
    el.className = 'conn-status conn-fail';
    el.textContent = '⚠️ Ainda não conectado. Escaneie o QR Code e tente novamente.';
  }}
}}

async function skipStep() {{
  window.location.href = `/setup/step5?token=${{TOKEN}}`;
}}

// Inicia carregamento do QR e polling
if (HAS_EVO) {{
  loadQR();
  pollTimer = setTimeout(pollConnection, 5000);
}}
</script>
</body></html>""")



@router.get("/setup/qrcode")
async def get_qrcode_route(token: str = "", instance: str = "", db: Session = Depends(get_db)):
    """Retorna o QR Code da instância para exibir no setup."""
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return JSONResponse({"error": "Token inválido"}, status_code=400)
    if not instance:
        instance = tenant.phone_number_id or ""
    if not instance:
        return JSONResponse({"error": "Instância não configurada"}, status_code=400)
    from ..services.evolution_helper import get_qrcode
    result = await get_qrcode(instance)
    return JSONResponse(result)

@router.get("/setup/test-whatsapp")
async def test_whatsapp(token: str = "", instance: str = "", db: Session = Depends(get_db)):
    """Verifica estado da conexão usando a função centralizada do evolution_helper."""
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Token inválido"}, status_code=400)
    if not instance:
        instance = tenant.phone_number_id or ""
    if not instance:
        return JSONResponse({"status": "error", "message": "Instância não informada"}, status_code=400)

    from ..services.evolution_helper import check_connection_state
    state = await check_connection_state(instance)
    return JSONResponse({"status": state})


@router.post("/setup/step4/save")
async def setup_step4_save(request: Request, token: str = "", db: Session = Depends(get_db)):
    token  = token or request.query_params.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return JSONResponse({"error": "Token inválido"}, status_code=400)

    body     = await request.json()
    instance = (body.get("instance") or "").strip()

    if instance:
        # Verifica se instância já está em uso por outro tenant
        existing = db.query(Tenant).filter(
            Tenant.phone_number_id == instance,
            Tenant.id != tenant.id
        ).first()
        if existing:
            return JSONResponse(
                {"error": f"A instância '{instance}' já está em uso. Use um nome diferente."},
                status_code=409
            )
        tenant.phone_number_id = instance
    # Se vazio, mantém o que tinha (pode ser que o admin já configurou)

    try:
        db.commit()
    except Exception:
        db.rollback()
        return JSONResponse({"error": "Erro ao salvar."}, status_code=500)

    return JSONResponse({"ok": True})


# ── PASSO 5 — Resumo e criação de senha ──────────────────────────────────────

@router.get("/setup/step5", response_class=HTMLResponse)
def setup_step5(request: Request, token: str = "", db: Session = Depends(get_db)):
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    services = db.query(Service).filter(Service.tenant_id == tenant.id, Service.active == True).count()
    has_wa   = bool(tenant.phone_number_id)
    has_svc  = services > 0

    checks = [
        (bool(tenant.display_name or tenant.name), "Nome do negócio",    tenant.display_name or tenant.name or "Não informado"),
        (bool(getattr(tenant,'open_days',None)),    "Horários",           f"{getattr(tenant,'open_time','09:00')} às {getattr(tenant,'close_time','18:00')}"),
        (has_svc,                                   "Serviços",           f"{services} serviço(s)" if has_svc else "Nenhum serviço"),
        (has_wa,                                    "WhatsApp",           tenant.phone_number_id if has_wa else "⚠️ Será configurado pelo suporte"),
    ]

    check_rows = ""
    for ok, label, sub in checks:
        icon  = "✅" if ok else ("⚠️" if label == "WhatsApp" else "⬜")
        color = "#68d391" if ok else ("#f6c90e" if label == "WhatsApp" else "#9aa0b8")
        check_rows += f"""
        <div class="check-row">
          <div class="check-icon">{icon}</div>
          <div style="flex:1">
            <div class="check-label" style="color:{color}">{label}</div>
            <div class="check-sub">{sub}</div>
          </div>
        </div>"""

    # Aviso se WhatsApp não configurado
    wa_aviso = ""
    if not has_wa:
        wa_aviso = """<div class="alert alert-warn" style="margin-bottom:16px">
            ⚠️ <strong>WhatsApp não configurado ainda.</strong> O bot vai ficar pausado até o suporte conectar o WhatsApp na chamada de ativação. Você pode finalizar o setup mesmo assim.
        </div>"""

    error    = request.query_params.get("error", "")
    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""

    # Se já tem senha (setup sendo refeito), mostra aviso
    has_pw = bool(getattr(tenant, 'dashboard_password', None))
    pw_aviso = ""
    if has_pw:
        pw_aviso = '<div class="alert alert-info" style="margin-bottom:14px">💡 Você já tem uma senha cadastrada. Crie uma nova abaixo para substituir, ou deixe em branco para manter a atual.</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup — BotGen</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container">
{_steps_html(6)}
<div class="card">
  <div class="card-title">📋 Resumo da configuração</div>
  <div class="card-sub">Verifique se tudo está correto antes de finalizar.</div>
  {check_rows}
</div>

{wa_aviso}

<div class="card">
  <div class="card-title">🔑 {"Atualizar senha" if has_pw else "Criar senha do painel"}</div>
  <div class="card-sub">{"Para acessar seu painel de agendamentos." if not has_pw else "Deixe em branco para manter a senha atual."}</div>
  {err_html}
  {pw_aviso}
  <form method="POST" action="/setup/complete?token={token}">
    <input type="hidden" name="token" value="{token}">
    <div class="form-group">
      <label>{"Nova senha" if not has_pw else "Nova senha (opcional)"} {"*" if not has_pw else ""}</label>
      <input type="password" name="password" id="pw" placeholder="Mínimo 6 caracteres" {"required minlength='6'" if not has_pw else ""} oninput="checkPw()">
      <div class="pw-strength" id="pw-bar" style="background:#2d3148;width:0%"></div>
    </div>
    <div class="form-group" id="pw2-group">
      <label>Confirmar senha {"*" if not has_pw else ""}</label>
      <input type="password" name="password2" id="pw2" placeholder="Repita a senha" {"required minlength='6'" if not has_pw else ""}>
    </div>
    <button type="submit" class="btn btn-primary btn-full" style="margin-top:8px">🚀 {"Ativar bot e finalizar" if not has_pw else "Salvar e finalizar"}</button>
  </form>
</div>

<a href="/setup/step4?token={token}" class="btn btn-outline">← Voltar</a>
</div>

<script>
function checkPw() {{
  const pw  = document.getElementById('pw').value;
  const bar = document.getElementById('pw-bar');
  let strength = 0;
  if (pw.length >= 6)   strength++;
  if (pw.length >= 10)  strength++;
  if (/[A-Z]/.test(pw)) strength++;
  if (/[0-9]/.test(pw)) strength++;
  const colors = ['#fc8181','#f6c90e','#68d391','#00b894'];
  const widths  = ['25%','50%','75%','100%'];
  bar.style.background = colors[strength-1] || '#2d3148';
  bar.style.width      = widths[strength-1]  || '0%';
}}
</script>
</body></html>""")


@router.post("/setup/complete")
async def setup_complete(request: Request, token: str = "", db: Session = Depends(get_db)):
    form   = await request.form()
    token  = token or form.get("token", "")
    tenant = _get_tenant_by_token(token, db)
    if not tenant:
        return _error_page("Link inválido.")

    pw  = form.get("password", "").strip()
    pw2 = form.get("password2", "").strip()
    has_existing_pw = bool(getattr(tenant, 'dashboard_password', None))

    # Se tem senha nova, valida
    if pw:
        if len(pw) < 6:
            return RedirectResponse(f"/setup/step5?token={token}&error=A+senha+deve+ter+ao+menos+6+caracteres.", status_code=302)
        if pw != pw2:
            return RedirectResponse(f"/setup/step5?token={token}&error=As+senhas+não+coincidem.", status_code=302)
        tenant.dashboard_password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    elif not has_existing_pw:
        # Sem senha e sem senha existente — não pode prosseguir
        return RedirectResponse(f"/setup/step5?token={token}&error=Crie+uma+senha+para+continuar.", status_code=302)

    if not tenant.dashboard_token:
        tenant.dashboard_token = secrets.token_urlsafe(32)

    # FIX: bot_active = True APENAS se WhatsApp estiver configurado
    # Se não tem instância, fica pausado até o admin ativar
    has_wa = bool(tenant.phone_number_id)
    tenant.bot_active = has_wa

    # FIX: setup_done = True mas setup_token NÃO é zerado
    # Admin precisa do token para exibir o link no painel
    # Token é regenerado apenas quando admin clica em "Reenviar Setup"
    tenant.setup_done = True

    db.commit()
    return RedirectResponse(f"/setup/done?tid={tenant.id}", status_code=302)


# ── DONE ─────────────────────────────────────────────────────────────────────

@router.get("/setup/done", response_class=HTMLResponse)
def setup_done(request: Request, tid: str = "", db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == tid, Tenant.setup_done == True).first()
    if not tenant:
        return _error_page("Página não encontrada.")

    base_url      = _get_base_url(request)
    dashboard_url = f"{base_url}/dashboard?tid={tenant.id}"
    display       = tenant.display_name or tenant.name
    has_wa        = bool(tenant.phone_number_id)

    # Mensagem diferente dependendo se WhatsApp foi configurado
    if has_wa:
        status_html = """
        <div style="background:#1a2e1a;border:1px solid rgba(104,211,145,.2);border-radius:10px;padding:14px 16px;margin-bottom:20px;font-size:13px;color:#68d391">
            ✅ Bot ativo! Seus clientes já podem agendar pelo WhatsApp. 🚀
        </div>"""
    else:
        status_html = """
        <div style="background:#2a2200;border:1px solid rgba(246,201,14,.2);border-radius:10px;padding:14px 16px;margin-bottom:20px;font-size:13px;color:#f6c90e;line-height:1.7">
            ⚠️ <strong>Quase lá!</strong> Falta só conectar o WhatsApp.<br>
            O suporte vai fazer isso na chamada de ativação — pode ficar tranquilo(a)!
        </div>"""

    return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0">
<title>Setup concluído! 🎉</title>{SETUP_STYLE}</head><body>
<div class="header"><div class="logo">⚡ BotGen Setup</div></div>
<div class="container" style="max-width:520px">
<div class="card" style="text-align:center;padding:40px 28px">
  <div style="font-size:48px;margin-bottom:16px">🎉</div>
  <div style="font-size:22px;font-weight:800;margin-bottom:8px">Configuração concluída!</div>
  <div style="font-size:14px;color:#9aa0b8;line-height:1.7;margin-bottom:20px">
    O BotGen do <strong style="color:#e8eaf2">{display}</strong> está configurado.
  </div>
  {status_html}
  <div style="background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:16px;margin-bottom:20px;text-align:left">
    <div style="font-size:11px;color:#9aa0b8;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:.4px">Seu painel de agendamentos</div>
    <div style="font-family:'DM Mono',monospace;font-size:13px;color:#7c7de8;word-break:break-all">{dashboard_url}</div>
  </div>
  <a href="{dashboard_url}" class="btn btn-primary btn-full">Acessar meu painel →</a>
  <div style="font-size:12px;color:#9aa0b8;margin-top:12px">Salve esse link nos seus favoritos!</div>
</div>
</div></body></html>""")