from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from sqlalchemy import text, inspect as sa_inspect
import asyncio, os

load_dotenv()

from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook, dashboard, whatsapp_webhook, admin, setup, billing

Base.metadata.create_all(bind=engine)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "troca-essa-senha-admin")
APP_URL      = os.getenv("APP_URL", "")

def _require_admin(request: Request):
    token = request.headers.get("X-Admin-Token") or request.cookies.get("admin_token")
    if token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Não autorizado")


# ── Migrations ────────────────────────────────────────────────────────────────

def _auto_migrate():
    novas_colunas = {
        "tenants": [
            ("bot_attendant_name", "VARCHAR DEFAULT 'Mari'"),
            ("bot_business_name",  "VARCHAR"),
            ("open_days",          "VARCHAR DEFAULT '0,1,2,3,4,5'"),
            ("open_time",          "VARCHAR DEFAULT '09:00'"),
            ("close_time",         "VARCHAR DEFAULT '18:00'"),
            ("bot_active",         "BOOLEAN DEFAULT TRUE"),
        ],
        "appointments": [
            ("payment_status",  "VARCHAR DEFAULT 'pending'"),
            ("payment_method",  "VARCHAR"),
            ("payment_amount",  "INTEGER"),
            ("payment_pix_key", "VARCHAR"),
            ("payment_paid_at", "TIMESTAMP"),
            ("payment_notes",   "TEXT"),
        ],
    }
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            for tabela, cols in novas_colunas.items():
                try:
                    existentes = {c["name"] for c in inspector.get_columns(tabela)}
                except Exception:
                    existentes = set()
                for col, tipo in cols:
                    if col not in existentes:
                        try:
                            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                        except Exception as e:
                            print(f"[migrate] skip {tabela}.{col}: {e}")
            conn.commit()
        print("[migrate] v1+v2 concluida.")
    except Exception as e:
        print(f"[migrate] erro: {e}")

_auto_migrate()


def _auto_migrate_v3():
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            try:
                existentes = {c["name"] for c in inspector.get_columns("tenants")}
            except Exception:
                existentes = set()
            for col, tipo in [
                ("tenant_icon",     "VARCHAR DEFAULT '🐾'"),
                ("owner_phone",     "VARCHAR"),
                ("notify_new_appt", "BOOLEAN DEFAULT TRUE"),
            ]:
                if col not in existentes:
                    try:
                        conn.execute(text(f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                    except Exception as e:
                        print(f"[migrate-v3] skip: {e}")
            try:
                conn.execute(text("""CREATE TABLE IF NOT EXISTS blocked_slots (
                    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL,
                    date VARCHAR NOT NULL, time VARCHAR, reason VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW())"""))
                print("[migrate-v3] blocked_slots ok")
            except Exception as e:
                print(f"[migrate-v3] blocked_slots: {e}")
            conn.commit()
        print("[migrate-v3] v3 concluida.")
    except Exception as e:
        print(f"[migrate-v3] erro: {e}")

_auto_migrate_v3()


def _auto_migrate_v4():
    novas = {
        "tenants": [
            ("needs_address", "BOOLEAN DEFAULT FALSE"),
            ("address_label", "VARCHAR DEFAULT 'Endereço de busca'"),
            ("setup_token",   "VARCHAR"),
            ("setup_done",    "BOOLEAN DEFAULT FALSE"),
            ("plan",          "VARCHAR DEFAULT 'basico'"),
            ("plan_active",   "BOOLEAN DEFAULT TRUE"),
            ("billing_email", "VARCHAR"),
        ],
        "appointments": [("pickup_address", "VARCHAR")],
    }
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            for tabela, cols in novas.items():
                try:
                    existentes = {c["name"] for c in inspector.get_columns(tabela)}
                except Exception:
                    existentes = set()
                for col, tipo in cols:
                    if col not in existentes:
                        try:
                            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                        except Exception as e:
                            print(f"[migrate-v4] skip {tabela}.{col}: {e}")
            conn.commit()
        print("[migrate-v4] concluida.")
    except Exception as e:
        print(f"[migrate-v4] erro: {e}")

_auto_migrate_v4()


def _auto_migrate_v5():
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan_tenant_group VARCHAR"))
            conn.commit()
        print("[migrate-v5] concluida.")
    except Exception as e:
        print(f"[migrate-v5] erro: {e}")

_auto_migrate_v5()


def _auto_migrate_v6():
    try:
        with engine.connect() as conn:
            for col in ["evolution_url", "evolution_key"]:
                conn.execute(text(f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
            conn.commit()
        print("[migrate-v6] concluida.")
    except Exception as e:
        print(f"[migrate-v6] erro: {e}")

_auto_migrate_v6()


def _auto_migrate_v7():
    """next_billing_date para aviso de vencimento."""
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS next_billing_date DATE"))
            conn.commit()
        print("[migrate-v7] concluida.")
    except Exception as e:
        print(f"[migrate-v7] erro: {e}")

_auto_migrate_v7()


# ── Scheduler loops ───────────────────────────────────────────────────────────

def _segundos_ate(hora: int, minuto: int = 0) -> float:
    from datetime import datetime
    import pytz
    BRASILIA = pytz.timezone("America/Sao_Paulo")
    agora    = datetime.now(BRASILIA).replace(tzinfo=None)
    target   = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if agora >= target:
        from datetime import timedelta
        target = target + timedelta(days=1)
    return (target - agora).total_seconds()


async def reminder_loop():
    """Lembretes — diariamente às 18h."""
    from .services.reminder import send_daily_reminders
    while True:
        segundos = _segundos_ate(18, 0)
        print(f"[Lembretes] Proximo envio em {int(segundos/3600)}h {int((segundos%3600)/60)}min")
        await asyncio.sleep(segundos)
        await send_daily_reminders()


async def weekly_report_loop():
    """Relatório semanal — toda segunda às 8h."""
    # FIX: import direto de email_service + scheduler, sem conflito
    from .services.scheduler import send_weekly_reports
    from datetime import datetime, timedelta
    import pytz
    BRASILIA = pytz.timezone("America/Sao_Paulo")
    while True:
        agora = datetime.now(BRASILIA).replace(tzinfo=None)
        dias_ate_seg = (7 - agora.weekday()) % 7
        if dias_ate_seg == 0 and agora.hour >= 8:
            dias_ate_seg = 7
        target   = (agora + timedelta(days=dias_ate_seg)).replace(hour=8, minute=0, second=0, microsecond=0)
        segundos = (target - agora).total_seconds()
        print(f"[Relatorio] Proximo envio em {int(segundos/3600)}h")
        await asyncio.sleep(segundos)
        await send_weekly_reports()


async def expiry_warning_loop():
    """Aviso de vencimento — diariamente às 9h."""
    from .services.scheduler import send_expiry_warnings
    while True:
        await asyncio.sleep(_segundos_ate(9, 0))
        await send_expiry_warnings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(reminder_loop()),
        asyncio.create_task(weekly_report_loop()),
        asyncio.create_task(expiry_warning_loop()),
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(
    title="BotGen API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ENVIRONMENT") == "production" else "/docs",
    redoc_url=None,
)

app.include_router(webhook.router)
app.include_router(appointments.router)
app.include_router(telegram_webhook.router)
app.include_router(dashboard.router)
app.include_router(whatsapp_webhook.router)
app.include_router(admin.router)
app.include_router(setup.router)
app.include_router(billing.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "BotGen", "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Página de vendas ──────────────────────────────────────────────────────────

_LANDING_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BotGen — Seu WhatsApp agendando sozinho com IA</title>
  <meta name="description" content="Automatize os agendamentos do seu negócio pelo WhatsApp com inteligência artificial. Sem app, sem complicação. Ativo em 15 minutos.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,700;0,800;0,900;1,800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

    :root {
      --purple: #7c3aed;
      --purple2: #6d28d9;
      --glow: rgba(124,58,237,0.4);
      --green: #10b981;
      --bg: #080810;
      --card: #0e0e1c;
      --border: rgba(255,255,255,0.07);
      --text: #f1f5f9;
      --muted: #64748b;
      --muted2: #94a3b8;
    }

    html { scroll-behavior: smooth; }
    body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); overflow-x: hidden; }

    /* ── NAV ── */
    nav {
      position: fixed; top: 0; left: 0; right: 0; z-index: 100;
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 5%; height: 60px;
      background: rgba(8,8,16,0.85); backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
    }
    .nav-logo { font-size: 20px; font-weight: 900; letter-spacing: -0.5px; }
    .nav-logo span { color: #a78bfa; }
    .nav-cta {
      background: var(--purple); color: #fff; text-decoration: none;
      padding: 8px 20px; border-radius: 8px; font-weight: 700; font-size: 13px;
      transition: background .2s;
    }
    .nav-cta:hover { background: var(--purple2); }

    /* ── HERO ── */
    .hero {
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
      text-align: center; padding: 100px 5% 60px;
      position: relative;
    }
    .hero::before {
      content: ''; position: absolute; inset: 0; z-index: 0;
      background: radial-gradient(ellipse 80% 60% at 50% 0%, rgba(124,58,237,0.18) 0%, transparent 70%);
    }
    .hero-inner { position: relative; z-index: 1; max-width: 780px; margin: 0 auto; }
    .hero-badge {
      display: inline-block; background: rgba(124,58,237,0.12);
      border: 1px solid rgba(124,58,237,0.35); color: #a78bfa;
      padding: 5px 16px; border-radius: 20px; font-size: 12px; font-weight: 700;
      letter-spacing: 1px; text-transform: uppercase; margin-bottom: 28px;
    }
    h1 {
      font-size: clamp(40px, 7vw, 80px); font-weight: 900; line-height: 1.05;
      letter-spacing: -2px; color: #fff; margin-bottom: 22px;
    }
    h1 em { font-style: italic; color: #a78bfa; }
    .hero-sub {
      font-size: clamp(16px, 2.5vw, 19px); color: var(--muted2);
      max-width: 540px; margin: 0 auto 40px; line-height: 1.7;
    }
    .hero-ctas { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-bottom: 48px; }
    .btn-big {
      padding: 16px 36px; border-radius: 12px; font-weight: 800;
      font-size: 16px; text-decoration: none; transition: all .2s; display: inline-block;
    }
    .btn-big-primary { background: var(--purple); color: #fff; box-shadow: 0 0 30px var(--glow); }
    .btn-big-primary:hover { background: var(--purple2); transform: translateY(-2px); box-shadow: 0 0 40px var(--glow); }
    .btn-big-ghost { background: rgba(255,255,255,0.05); color: var(--text); border: 1px solid var(--border); }
    .btn-big-ghost:hover { background: rgba(255,255,255,0.1); }
    .hero-social { font-size: 14px; color: var(--muted); }
    .hero-social strong { color: var(--muted2); }

    /* ── STATS ── */
    .stats-strip {
      display: flex; justify-content: center; gap: 0;
      border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
      overflow-x: auto;
    }
    .stat-item {
      flex: 1; min-width: 160px; padding: 28px 20px; text-align: center;
      border-right: 1px solid var(--border);
    }
    .stat-item:last-child { border-right: none; }
    .stat-num { font-size: 36px; font-weight: 900; color: #fff; letter-spacing: -1px; }
    .stat-num span { color: var(--purple); }
    .stat-label { font-size: 13px; color: var(--muted); margin-top: 4px; }

    /* ── SECTIONS ── */
    section { padding: 80px 5%; }
    .container { max-width: 1100px; margin: 0 auto; }
    .section-eyebrow {
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px;
      color: #a78bfa; margin-bottom: 12px;
    }
    h2 { font-size: clamp(28px, 4vw, 46px); font-weight: 900; color: #fff; letter-spacing: -1px; line-height: 1.1; margin-bottom: 14px; }
    .section-sub { font-size: 17px; color: var(--muted2); margin-bottom: 52px; max-width: 520px; }

    /* ── NEGÓCIOS ── */
    .biz-grid { display: flex; gap: 10px; flex-wrap: wrap; }
    .biz-chip {
      display: flex; align-items: center; gap: 8px;
      background: var(--card); border: 1px solid var(--border);
      padding: 10px 16px; border-radius: 30px; font-size: 14px; font-weight: 500;
      transition: border-color .2s;
    }
    .biz-chip:hover { border-color: rgba(124,58,237,0.4); }

    /* ── CHAT DEMO ── */
    .demo-section { background: linear-gradient(180deg, var(--bg) 0%, rgba(124,58,237,0.05) 50%, var(--bg) 100%); }
    .demo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 60px; align-items: center; }
    @media(max-width:768px) { .demo-grid { grid-template-columns: 1fr; } }
    .chat-wrap {
      background: #0a0a14; border-radius: 20px; overflow: hidden;
      border: 1px solid var(--border); max-width: 360px; margin: 0 auto;
      box-shadow: 0 0 60px rgba(124,58,237,0.15);
    }
    .chat-top {
      background: #13131f; padding: 14px 16px;
      display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--border);
    }
    .chat-av {
      width: 36px; height: 36px; background: var(--purple);
      border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px;
    }
    .chat-av-name { font-size: 14px; font-weight: 700; }
    .chat-av-status { font-size: 11px; color: #4ade80; }
    .chat-body { padding: 16px; display: flex; flex-direction: column; gap: 10px; background: #0d0d1a; }
    .msg { max-width: 82%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.55; }
    .msg-in  { background: #1a1a2e; color: var(--text); align-self: flex-start; border-radius: 4px 12px 12px 12px; }
    .msg-out { background: var(--purple); color: #fff; align-self: flex-end; border-radius: 12px 4px 12px 12px; }
    .msg-time { font-size: 10px; color: var(--muted); text-align: right; margin-top: 4px; opacity: .6; }

    /* ── FEATURES ── */
    .features-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap: 18px; }
    .feature-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 28px;
      transition: border-color .2s, transform .2s;
    }
    .feature-card:hover { border-color: rgba(124,58,237,0.35); transform: translateY(-3px); }
    .feature-icon {
      width: 46px; height: 46px; background: rgba(124,58,237,0.12);
      border-radius: 12px; display: flex; align-items: center; justify-content: center;
      font-size: 22px; margin-bottom: 16px;
    }
    .feature-card h3 { font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 8px; }
    .feature-card p { font-size: 14px; color: var(--muted2); line-height: 1.7; }

    /* ── PLANOS ── */
    .plans-section { background: rgba(124,58,237,0.03); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
    .plans-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap: 20px; }
    .plan-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 32px 26px;
      position: relative; transition: transform .2s, border-color .2s;
    }
    .plan-card:hover { transform: translateY(-4px); }
    .plan-card.best { border-color: var(--purple); box-shadow: 0 0 40px rgba(124,58,237,0.2); }
    .plan-pill {
      position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
      background: var(--purple); color: #fff; font-size: 11px; font-weight: 800;
      padding: 4px 14px; border-radius: 20px; white-space: nowrap; text-transform: uppercase; letter-spacing: .5px;
    }
    .plan-name { font-size: 18px; font-weight: 800; color: #fff; margin-bottom: 6px; }
    .plan-price { font-size: 46px; font-weight: 900; color: #fff; line-height: 1; letter-spacing: -2px; }
    .plan-price sup { font-size: 20px; font-weight: 700; vertical-align: top; margin-top: 10px; }
    .plan-price sub { font-size: 15px; font-weight: 400; color: var(--muted); letter-spacing: 0; }
    .plan-desc { font-size: 14px; color: var(--muted2); margin: 12px 0 24px; line-height: 1.6; }
    .plan-features { list-style: none; margin-bottom: 28px; }
    .plan-features li {
      font-size: 13px; color: var(--text); padding: 8px 0;
      border-bottom: 1px solid var(--border); display: flex; align-items: flex-start; gap: 10px;
    }
    .plan-features li:last-child { border-bottom: none; }
    .plan-features li .ok  { color: var(--green); font-weight: 800; flex-shrink: 0; }
    .plan-features li .no  { color: var(--muted); flex-shrink: 0; }
    .plan-features li.off  { color: var(--muted); }
    .plan-btn {
      display: block; text-align: center; text-decoration: none;
      padding: 14px; border-radius: 12px; font-weight: 800; font-size: 15px; transition: all .2s;
    }
    .plan-btn-purple { background: var(--purple); color: #fff; }
    .plan-btn-purple:hover { background: var(--purple2); }
    .plan-card.best .plan-btn { background: #fff; color: var(--purple2); }
    .plan-card.best .plan-btn:hover { background: #f0f0ff; }
    .plan-btn-outline { background: transparent; color: var(--muted2); border: 1px solid var(--border); }
    .plan-btn-outline:hover { border-color: rgba(124,58,237,0.4); color: #a78bfa; }
    .guarantee {
      display: inline-flex; align-items: center; gap: 10px;
      background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25);
      border-radius: 10px; padding: 10px 20px; font-size: 13px; color: #34d399;
      margin-top: 28px;
    }

    /* ── COMO FUNCIONA ── */
    .steps-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 20px; }
    .step-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 26px;
    }
    .step-num {
      width: 36px; height: 36px; background: var(--purple); border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 900; font-size: 16px; margin-bottom: 14px;
    }
    .step-card h3 { font-size: 15px; font-weight: 700; color: #fff; margin-bottom: 8px; }
    .step-card p { font-size: 13px; color: var(--muted2); line-height: 1.7; }

    /* ── FAQ ── */
    .faq-list { max-width: 700px; margin: 0 auto; }
    .faq-item { border-bottom: 1px solid var(--border); }
    .faq-q {
      width: 100%; background: none; border: none; color: var(--text);
      font-family: 'Inter',sans-serif; font-size: 15px; font-weight: 600;
      padding: 20px 0; text-align: left; cursor: pointer; display: flex;
      justify-content: space-between; align-items: center; gap: 16px;
    }
    .faq-q .ico { color: #a78bfa; font-size: 20px; transition: transform .2s; flex-shrink: 0; }
    .faq-a { font-size: 14px; color: var(--muted2); line-height: 1.8; padding-bottom: 18px; display: none; }
    .faq-item.open .faq-a { display: block; }
    .faq-item.open .faq-q .ico { transform: rotate(45deg); }

    /* ── CTA FINAL ── */
    .cta-section {
      text-align: center; padding: 100px 5%;
      background: radial-gradient(ellipse 80% 60% at 50% 100%, rgba(124,58,237,0.2) 0%, transparent 70%);
    }
    .cta-section h2 { margin-bottom: 14px; }
    .cta-section p { color: var(--muted2); font-size: 18px; margin-bottom: 40px; max-width: 500px; margin-left: auto; margin-right: auto; }

    /* ── FOOTER ── */
    footer {
      border-top: 1px solid var(--border); padding: 28px 5%;
      display: flex; justify-content: space-between; align-items: center;
      flex-wrap: wrap; gap: 12px;
    }
    footer .logo { font-size: 16px; font-weight: 900; }
    footer .logo span { color: #a78bfa; }
    footer p { font-size: 12px; color: var(--muted); }
    footer a { color: var(--muted); text-decoration: none; }
    footer a:hover { color: #a78bfa; }

    @media(max-width:600px) {
      .stats-strip { flex-direction: column; }
      .stat-item { border-right: none; border-bottom: 1px solid var(--border); }
      footer { flex-direction: column; text-align: center; }
    }
  </style>
</head>
<body>

<!-- NAV -->
<nav>
  <div class="nav-logo">Bot<span>Gen</span></div>
  <a href="#planos" class="nav-cta">Ver planos →</a>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-inner">
    <div class="hero-badge">⚡ powered by gpt-4o</div>
    <h1>Seu WhatsApp<br>agendando <em>sozinho</em></h1>
    <p class="hero-sub">
      IA que fala como atendente de verdade, verifica horários em tempo real e confirma agendamentos — 24h por dia, sem você precisar responder nada.
    </p>
    <div class="hero-ctas">
      <a href="#planos" class="btn-big btn-big-primary">Quero ativar agora →</a>
      <a href="#como-funciona" class="btn-big btn-big-ghost">Ver como funciona</a>
    </div>
    <div class="hero-social">
      Usado por <strong>barbearias, pet shops, salões</strong> e mais de <strong>50 outros negócios</strong>
    </div>
  </div>
</section>

<!-- STATS -->
<div class="stats-strip">
  <div class="stat-item">
    <div class="stat-num">+<span>200</span></div>
    <div class="stat-label">Negócios atendidos</div>
  </div>
  <div class="stat-item">
    <div class="stat-num">+<span>15k</span></div>
    <div class="stat-label">Agendamentos realizados</div>
  </div>
  <div class="stat-item">
    <div class="stat-num"><span>15</span>min</div>
    <div class="stat-label">Para ativar o bot</div>
  </div>
  <div class="stat-item">
    <div class="stat-num"><span>24</span>h</div>
    <div class="stat-label">Por dia, 7 dias por semana</div>
  </div>
</div>

<!-- NEGÓCIOS -->
<section>
  <div class="container">
    <div class="section-eyebrow">Compatível com</div>
    <h2 style="margin-bottom:24px">Funciona para qualquer<br>negócio de agendamento</h2>
    <div class="biz-grid">
      <div class="biz-chip">💈 Barbearia</div>
      <div class="biz-chip">🐾 Pet Shop</div>
      <div class="biz-chip">💅 Salão de Beleza</div>
      <div class="biz-chip">✨ Estética</div>
      <div class="biz-chip">🏥 Clínica Veterinária</div>
      <div class="biz-chip">🦷 Odontologia</div>
      <div class="biz-chip">💆 Spa & Massagem</div>
      <div class="biz-chip">⚙️ Outros</div>
    </div>
  </div>
</section>

<!-- DEMO -->
<section class="demo-section">
  <div class="container">
    <div class="demo-grid">
      <div>
        <div class="section-eyebrow">Experiência real</div>
        <h2>Seus clientes vão achar que é uma atendente de verdade</h2>
        <p style="color:var(--muted2);font-size:16px;line-height:1.7;margin:16px 0 28px">
          A IA foi treinada para falar de forma natural — usa o nome do cliente, lembra de agendamentos anteriores e trata cada tipo de negócio com o tom certo.
        </p>
        <div style="display:flex;flex-direction:column;gap:10px">
          <div style="display:flex;gap:10px;font-size:14px;color:var(--text)"><span style="color:var(--green);font-weight:800">✓</span> Personalidade adaptada ao seu tipo de negócio</div>
          <div style="display:flex;gap:10px;font-size:14px;color:var(--text)"><span style="color:var(--green);font-weight:800">✓</span> Verifica disponibilidade em tempo real</div>
          <div style="display:flex;gap:10px;font-size:14px;color:var(--text)"><span style="color:var(--green);font-weight:800">✓</span> Nunca agenda em feriados</div>
          <div style="display:flex;gap:10px;font-size:14px;color:var(--text)"><span style="color:var(--green);font-weight:800">✓</span> Lembra clientes recorrentes e seus pets</div>
          <div style="display:flex;gap:10px;font-size:14px;color:var(--text)"><span style="color:var(--green);font-weight:800">✓</span> Notifica você a cada agendamento confirmado</div>
        </div>
      </div>
      <div>
        <div class="chat-wrap">
          <div class="chat-top">
            <div class="chat-av">🐾</div>
            <div>
              <div class="chat-av-name">Mari — PetShop BotGen</div>
              <div class="chat-av-status">● online agora</div>
            </div>
          </div>
          <div class="chat-body">
            <div class="msg msg-in">oi! queria marcar banho pro meu cachorro</div>
            <div class="msg msg-out">Oi! 😊 Me fala seu nome pra eu anotar aqui?</div>
            <div class="msg msg-in">Lucas</div>
            <div class="msg msg-out">Oi Lucas! Qual o nome e raça do seu bichinho? 🐾</div>
            <div class="msg msg-in">Thor, labrador</div>
            <div class="msg msg-out">Que gracinha! 🐶 Peso aproximado do Thor?</div>
            <div class="msg msg-in">uns 30kg</div>
            <div class="msg msg-out">Perfeito! Sexta tem horário às 10h — tá bom?</div>
            <div class="msg msg-in">sim!</div>
            <div class="msg msg-out">
              Confirmado! 🐾✨<br><br>
              ✂️ Banho — R$60,00<br>
              📅 Sexta, 18/04 às 10:00<br><br>
              Thor vai ficar um princesinho! Até lá 😄
            </div>
            <div class="msg-time">hoje</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- COMO FUNCIONA -->
<section id="como-funciona">
  <div class="container">
    <div style="text-align:center;margin-bottom:48px">
      <div class="section-eyebrow">Processo</div>
      <h2>Do pagamento ao bot ativo<br>em menos de 15 minutos</h2>
    </div>
    <div class="steps-grid">
      <div class="step-card">
        <div class="step-num">1</div>
        <h3>Você escolhe o plano</h3>
        <p>Paga pelo checkout seguro da Kiwify e recebe confirmação imediata por WhatsApp e email.</p>
      </div>
      <div class="step-card">
        <div class="step-num">2</div>
        <h3>Chamada de 15 min</h3>
        <p>Nossa equipe liga, conecta seu WhatsApp Business e configura o bot ao vivo com você.</p>
      </div>
      <div class="step-card">
        <div class="step-num">3</div>
        <h3>Bot no ar</h3>
        <p>Seus clientes já agendam. Você recebe notificação de cada agendamento confirmado.</p>
      </div>
      <div class="step-card">
        <div class="step-num">4</div>
        <h3>Acompanhe no painel</h3>
        <p>Dashboard com todos os agendamentos, histórico de clientes e relatórios. Acesse pelo celular.</p>
      </div>
    </div>
  </div>
</section>

<!-- FEATURES -->
<section style="background:var(--card);border-top:1px solid var(--border);border-bottom:1px solid var(--border)">
  <div class="container">
    <div style="text-align:center;margin-bottom:48px">
      <div class="section-eyebrow">Recursos</div>
      <h2>Tudo incluso em todos os planos</h2>
    </div>
    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon">🤖</div>
        <h3>IA com personalidade</h3>
        <p>Barbearia fala de forma descontraída, clínica com tom profissional. A IA se adapta ao seu negócio.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📅</div>
        <h3>Agenda em tempo real</h3>
        <p>Verifica disponibilidade, bloqueia horários e nunca marca dois clientes no mesmo horário.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔔</div>
        <h3>Notificação imediata</h3>
        <p>WhatsApp para você a cada agendamento confirmado, com nome do cliente, serviço e horário.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📊</div>
        <h3>Dashboard completo</h3>
        <p>Agenda do dia, histórico, clientes, faturamento e controle de pagamentos em um lugar só.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">⏰</div>
        <h3>Lembretes automáticos</h3>
        <p>Bot lembra seus clientes um dia antes. Reduz faltas e aumenta a receita. (Pro e Agência)</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔒</div>
        <h3>Seguro e na lei</h3>
        <p>HTTPS obrigatório, dados isolados por negócio, sem logs de mensagens. 100% LGPD.</p>
      </div>
    </div>
  </div>
</section>

<!-- PLANOS -->
<section id="planos" class="plans-section">
  <div class="container">
    <div style="text-align:center;margin-bottom:52px">
      <div class="section-eyebrow">Preços</div>
      <h2>Planos simples e transparentes</h2>
      <p style="color:var(--muted2);font-size:17px;margin-top:10px">Todos incluem ativação gratuita e suporte pelo WhatsApp.</p>
    </div>

    <div class="plans-grid">

      <!-- BÁSICO -->
      <div class="plan-card">
        <div class="plan-name">Básico</div>
        <div class="plan-price"><sup>R$</sup>97<sub>,90/mês</sub></div>
        <div class="plan-desc">Para quem quer começar a automatizar sem complicação.</div>
        <ul class="plan-features">
          <li><span class="ok">✓</span> Bot de agendamento pelo WhatsApp</li>
          <li><span class="ok">✓</span> Até 7 serviços cadastrados</li>
          <li><span class="ok">✓</span> Painel de agendamentos</li>
          <li><span class="ok">✓</span> Notificação de cada agendamento</li>
          <li><span class="ok">✓</span> Ativação em até 2 horas</li>
          <li class="off"><span class="no">✗</span> Lembretes automáticos</li>
          <li class="off"><span class="no">✗</span> Exportação CSV</li>
          <li class="off"><span class="no">✗</span> Relatório semanal por email</li>
        </ul>
        <a href="https://pay.kiwify.com.br/ypIXFRM" class="plan-btn plan-btn-outline" target="_blank">Assinar Básico →</a>
      </div>

      <!-- PRO (destaque) -->
      <div class="plan-card best">
        <div class="plan-pill">⭐ MAIS POPULAR</div>
        <div class="plan-name">Pro</div>
        <div class="plan-price"><sup>R$</sup>197<sub>,90/mês</sub></div>
        <div class="plan-desc">Para negócios que querem escalar com automação completa.</div>
        <ul class="plan-features">
          <li><span class="ok">✓</span> Tudo do Básico</li>
          <li><span class="ok">✓</span> Serviços ilimitados</li>
          <li><span class="ok">✓</span> Lembretes automáticos no dia anterior</li>
          <li><span class="ok">✓</span> Exportação de agendamentos CSV</li>
          <li><span class="ok">✓</span> Relatório semanal por email</li>
          <li><span class="ok">✓</span> Suporte prioritário</li>
        </ul>
        <a href="https://pay.kiwify.com.br/pndpF39" class="plan-btn" target="_blank">Assinar Pro →</a>
      </div>

      <!-- AGÊNCIA -->
      <div class="plan-card">
        <div class="plan-name">Agência</div>
        <div class="plan-price"><sup>R$</sup>497<sub>,90/mês</sub></div>
        <div class="plan-desc">Para quem gerencia múltiplos negócios ou quer revender.</div>
        <ul class="plan-features">
          <li><span class="ok">✓</span> Tudo do Pro</li>
          <li><span class="ok">✓</span> Até 3 negócios no mesmo plano</li>
          <li><span class="ok">✓</span> Painel separado por negócio</li>
          <li><span class="ok">✓</span> Ideal para revendedores</li>
          <li><span class="ok">✓</span> Suporte VIP pelo WhatsApp</li>
        </ul>
        <a href="https://pay.kiwify.com.br/O0oUFkt" class="plan-btn plan-btn-purple" target="_blank">Assinar Agência →</a>
      </div>

    </div>

    <div style="text-align:center">
      <div class="guarantee">🛡️ Satisfação garantida — se não funcionar na sua operação, devolvemos</div>
    </div>
  </div>
</section>

<!-- FAQ -->
<section>
  <div class="container">
    <div style="text-align:center;margin-bottom:48px">
      <div class="section-eyebrow">Dúvidas</div>
      <h2>Perguntas frequentes</h2>
    </div>
    <div class="faq-list">

      <div class="faq-item">
        <button class="faq-q">Preciso ter WhatsApp Business? <span class="ico">+</span></button>
        <div class="faq-a">Sim, você precisa do WhatsApp Business instalado no celular do seu negócio. É gratuito e funciona no mesmo número que você já usa. Na chamada de ativação a gente te ajuda a configurar tudo.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">Meus clientes precisam instalar algum app? <span class="ico">+</span></button>
        <div class="faq-a">Não. Seus clientes agendam pelo WhatsApp normal — o que todo mundo já tem. É só mandar mensagem para o número do seu negócio e o bot responde automaticamente.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">O bot funciona 24 horas por dia? <span class="ico">+</span></button>
        <div class="faq-a">Sim! O bot atende e agenda 24h por dia, 7 dias por semana. Você configura os horários de funcionamento e o bot só aceita agendamentos dentro desses horários — mas responde dúvidas a qualquer hora.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">Posso cancelar quando quiser? <span class="ico">+</span></button>
        <div class="faq-a">Sim. Cancele a qualquer momento pela Kiwify. Seu bot continua ativo até o fim do período pago e seus dados ficam preservados por 30 dias após o cancelamento.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">Meus dados e dos clientes estão seguros? <span class="ico">+</span></button>
        <div class="faq-a">Sim. HTTPS obrigatório em todas as rotas, senhas criptografadas com bcrypt, webhook com assinatura HMAC-SHA1 e isolamento total por negócio. Desenvolvido em conformidade com a LGPD.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">E se eu tiver mais de um negócio? <span class="ico">+</span></button>
        <div class="faq-a">O Plano Agência (R$497,90/mês) inclui até 3 negócios diferentes no mesmo plano — cada um com seu próprio bot, painel e número de WhatsApp.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">Quanto tempo demora para ativar? <span class="ico">+</span></button>
        <div class="faq-a">Nossa equipe entra em contato em até 2 horas após a compra. A ativação em si leva apenas 15 minutos numa chamada rápida.</div>
      </div>

      <div class="faq-item">
        <button class="faq-q">Como é feito o processo de entrega? <span class="ico">+</span></button>
        <div class="faq-a">Imediatamente após a compra você recebe um WhatsApp e um email de boas-vindas. Nossa equipe entra em contato em até 2 horas para agendar a chamada de ativação. Não há nada para baixar — tudo é configurado ao vivo pela nossa equipe diretamente no seu WhatsApp Business.</div>
      </div>

    </div>
  </div>
</section>

<!-- CTA FINAL -->
<section class="cta-section">
  <div class="container">
    <div class="section-eyebrow">Comece hoje</div>
    <h2>Pare de responder<br>agendamentos à mão</h2>
    <p>Ative o BotGen em 15 minutos e tenha uma atendente que nunca dorme, nunca erra e nunca reclama.</p>
    <div style="display:flex;gap:14px;justify-content:center;flex-wrap:wrap">
      <a href="https://pay.kiwify.com.br/ypIXFRM" class="btn-big btn-big-ghost" target="_blank">Básico — R$97,90</a>
      <a href="https://pay.kiwify.com.br/pndpF39" class="btn-big btn-big-primary" target="_blank">Pro — R$197,90 ⭐</a>
    </div>
    <div class="guarantee" style="margin-top:28px">🛡️ Satisfação garantida — sem letras miúdas</div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="logo">Bot<span>Gen</span></div>
  <p>
    © 2026 BotGen · Agendamento inteligente pelo WhatsApp ·
    <a href="mailto:mtdnvendas@gmail.com">mtdnvendas@gmail.com</a> ·
    <a href="/privacidade">Política de Privacidade</a> ·
    <a href="/termos">Termos de Uso</a>
  </p>
  <p style="font-size:11px;color:var(--muted)">Conforme LGPD (Lei 13.709/2018)</p>
</footer>

<script>
  document.querySelectorAll('.faq-item .faq-q').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.faq-item').classList.toggle('open');
    });
  });
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      const t = document.querySelector(a.getAttribute('href'));
      if (t) { e.preventDefault(); t.scrollIntoView({behavior:'smooth'}); }
    });
  });
</script>
</body>
</html>

"""

@app.get("/planos", response_class=HTMLResponse)
async def landing_page():
    """Página de vendas BotGen — HTML embutido para funcionar em qualquer ambiente."""
    return HTMLResponse(content=_LANDING_HTML)




# ── Política de Privacidade ───────────────────────────────────────────────────

_PRIVACIDADE_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Política de Privacidade — BotGen</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0f0f1a;color:#e2e8f0;line-height:1.8}
.header{background:#13151f;padding:0 5%;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.07);position:sticky;top:0;z-index:10}
.logo{font-size:18px;font-weight:800;color:#fff}.logo span{color:#a78bfa}
.back{color:#94a3b8;text-decoration:none;font-size:13px}.back:hover{color:#a78bfa}
.container{max-width:780px;margin:0 auto;padding:48px 5% 80px}
h1{font-size:28px;font-weight:800;color:#fff;margin-bottom:8px}
.updated{font-size:13px;color:#64748b;margin-bottom:40px}
h2{font-size:18px;font-weight:700;color:#a78bfa;margin:36px 0 12px}
p{color:#94a3b8;margin-bottom:14px;font-size:15px}
ul{color:#94a3b8;padding-left:20px;margin-bottom:14px;font-size:15px}
li{margin-bottom:6px}
strong{color:#e2e8f0}
a{color:#a78bfa}
.box{background:#1a1a2e;border:1px solid rgba(124,58,237,0.2);border-radius:12px;padding:20px 24px;margin:20px 0}
footer{text-align:center;padding:32px 5%;border-top:1px solid rgba(255,255,255,0.07);font-size:13px;color:#475569}
footer a{color:#64748b;text-decoration:none;margin:0 8px}
footer a:hover{color:#a78bfa}
</style>
</head><body>
<div class="header">
  <div class="logo">Bot<span>Gen</span></div>
  <a href="/planos" class="back">← Voltar</a>
</div>
<div class="container">
  <h1>Política de Privacidade</h1>
  <div class="updated">Última atualização: abril de 2026</div>

  <p>A BotGen ("nós", "nosso") está comprometida com a proteção dos seus dados pessoais em conformidade com a <strong>Lei Geral de Proteção de Dados (LGPD — Lei nº 13.709/2018)</strong>. Esta política explica como coletamos, usamos e protegemos suas informações.</p>

  <h2>1. Quem somos</h2>
  <p>A BotGen é um serviço de automação de agendamentos pelo WhatsApp com inteligência artificial, voltado para pequenos negócios brasileiros. Nosso contato: <a href="mailto:mtdnvendas@gmail.com">mtdnvendas@gmail.com</a>.</p>

  <h2>2. Dados que coletamos</h2>
  <p><strong>Dados dos nossos clientes (donos de negócio):</strong></p>
  <ul>
    <li>Nome e email fornecidos na compra (via Kiwify)</li>
    <li>Número de WhatsApp para notificações</li>
    <li>Dados do negócio: nome, horários, serviços</li>
  </ul>
  <p><strong>Dados dos clientes finais (usuários do WhatsApp):</strong></p>
  <ul>
    <li>Nome e número de telefone (fornecidos voluntariamente no chat)</li>
    <li>Dados dos agendamentos: data, serviço, informações do pet (quando aplicável)</li>
    <li>Histórico de conversa (limitado a 20 mensagens, resetado após 24h de inatividade)</li>
  </ul>

  <h2>3. Como usamos os dados</h2>
  <ul>
    <li>Realizar e gerenciar agendamentos pelo WhatsApp</li>
    <li>Enviar lembretes de agendamento (planos Pro e Agência)</li>
    <li>Notificar o dono do negócio sobre novos agendamentos</li>
    <li>Enviar emails transacionais (confirmação de compra, relatórios)</li>
    <li>Melhorar a qualidade do serviço</li>
  </ul>

  <h2>4. Base legal (LGPD)</h2>
  <ul>
    <li><strong>Execução de contrato</strong> (Art. 7º, V): processamento necessário para prestação do serviço</li>
    <li><strong>Legítimo interesse</strong> (Art. 7º, IX): notificações operacionais do serviço</li>
    <li><strong>Consentimento</strong> (Art. 7º, I): ao iniciar uma conversa com o bot, o usuário consente com o processamento para fins de agendamento</li>
  </ul>

  <h2>5. Compartilhamento de dados</h2>
  <p>Não vendemos nem compartilhamos seus dados com terceiros, exceto:</p>
  <ul>
    <li><strong>Kiwify</strong>: processamento de pagamentos</li>
    <li><strong>OpenAI</strong>: processamento das mensagens de chat para geração de respostas (sem armazenamento pela OpenAI)</li>
    <li><strong>SendGrid</strong>: envio de emails transacionais</li>
    <li><strong>Railway</strong>: infraestrutura de hospedagem</li>
  </ul>
  <p>Todos os parceiros são contratualmente obrigados a proteger seus dados.</p>

  <h2>6. Segurança</h2>
  <div class="box">
    <ul>
      <li>Comunicação criptografada via HTTPS em todas as rotas</li>
      <li>Senhas armazenadas com bcrypt (hash irreversível)</li>
      <li>Isolamento total entre clientes — nenhum negócio acessa dados de outro</li>
      <li>Mensagens do WhatsApp nunca armazenadas em texto plano nos logs</li>
      <li>Tokens de acesso gerados com entropia criptográfica</li>
    </ul>
  </div>

  <h2>7. Seus direitos (LGPD)</h2>
  <p>Como titular dos dados, você tem direito a:</p>
  <ul>
    <li><strong>Acesso</strong>: solicitar cópia dos seus dados</li>
    <li><strong>Correção</strong>: corrigir dados incompletos ou incorretos</li>
    <li><strong>Exclusão</strong>: solicitar a exclusão dos seus dados</li>
    <li><strong>Portabilidade</strong>: receber seus dados em formato estruturado</li>
    <li><strong>Revogação do consentimento</strong>: a qualquer momento</li>
    <li><strong>Oposição</strong>: opor-se ao tratamento em determinadas circunstâncias</li>
  </ul>
  <p>Para exercer seus direitos, entre em contato: <a href="mailto:mtdnvendas@gmail.com">mtdnvendas@gmail.com</a></p>

  <h2>8. Retenção de dados</h2>
  <ul>
    <li>Histórico de conversa: resetado após 24h de inatividade</li>
    <li>Dados de agendamento: mantidos enquanto a conta estiver ativa</li>
    <li>Dados pessoais: excluídos em até 30 dias após cancelamento da conta</li>
  </ul>

  <h2>9. Cookies</h2>
  <p>Usamos apenas cookies essenciais para autenticação no painel (cookie de sessão httpOnly). Não usamos cookies de rastreamento ou publicidade.</p>

  <h2>10. Contato e DPO</h2>
  <p>Para dúvidas sobre privacidade ou para exercer seus direitos:<br>
  <strong>Email:</strong> <a href="mailto:mtdnvendas@gmail.com">mtdnvendas@gmail.com</a><br>
  Responderemos em até 15 dias úteis.</p>

  <h2>11. Alterações</h2>
  <p>Podemos atualizar esta política periodicamente. Notificaremos clientes sobre mudanças significativas por email.</p>
</div>
<footer>
  © 2026 BotGen ·
  <a href="/planos">Página inicial</a> ·
  <a href="/termos">Termos de Uso</a> ·
  <a href="mailto:mtdnvendas@gmail.com">Contato</a>
</footer>
</body></html>"""

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade():
    return HTMLResponse(content=_PRIVACIDADE_HTML)


# ── Termos de Uso ─────────────────────────────────────────────────────────────

_TERMOS_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Termos de Uso — BotGen</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0f0f1a;color:#e2e8f0;line-height:1.8}
.header{background:#13151f;padding:0 5%;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.07);position:sticky;top:0;z-index:10}
.logo{font-size:18px;font-weight:800;color:#fff}.logo span{color:#a78bfa}
.back{color:#94a3b8;text-decoration:none;font-size:13px}.back:hover{color:#a78bfa}
.container{max-width:780px;margin:0 auto;padding:48px 5% 80px}
h1{font-size:28px;font-weight:800;color:#fff;margin-bottom:8px}
.updated{font-size:13px;color:#64748b;margin-bottom:40px}
h2{font-size:18px;font-weight:700;color:#a78bfa;margin:36px 0 12px}
p{color:#94a3b8;margin-bottom:14px;font-size:15px}
ul{color:#94a3b8;padding-left:20px;margin-bottom:14px;font-size:15px}
li{margin-bottom:6px}
strong{color:#e2e8f0}
a{color:#a78bfa}
.box{background:#1a1a2e;border:1px solid rgba(124,58,237,0.2);border-radius:12px;padding:20px 24px;margin:20px 0}
footer{text-align:center;padding:32px 5%;border-top:1px solid rgba(255,255,255,0.07);font-size:13px;color:#475569}
footer a{color:#64748b;text-decoration:none;margin:0 8px}
footer a:hover{color:#a78bfa}
</style>
</head><body>
<div class="header">
  <div class="logo">Bot<span>Gen</span></div>
  <a href="/planos" class="back">← Voltar</a>
</div>
<div class="container">
  <h1>Termos de Uso</h1>
  <div class="updated">Última atualização: abril de 2026</div>

  <p>Ao contratar ou utilizar os serviços da BotGen, você concorda com os termos abaixo. Leia atentamente antes de prosseguir.</p>

  <h2>1. O serviço</h2>
  <p>A BotGen oferece uma plataforma SaaS de automação de agendamentos pelo WhatsApp com inteligência artificial. O serviço é prestado mediante assinatura mensal nos planos Básico, Pro e Agência.</p>

  <h2>2. Cadastro e conta</h2>
  <ul>
    <li>Você deve fornecer informações verdadeiras no cadastro</li>
    <li>É responsável por manter a confidencialidade da sua senha</li>
    <li>Deve ter ao menos 18 anos ou representar legalmente uma empresa</li>
    <li>Uma conta por pessoa/empresa, salvo no Plano Agência (até 3 negócios)</li>
  </ul>

  <h2>3. Uso aceitável</h2>
  <p>É <strong>proibido</strong> usar a BotGen para:</p>
  <ul>
    <li>Enviar spam ou mensagens não solicitadas em massa</li>
    <li>Atividades ilegais ou que violem direitos de terceiros</li>
    <li>Vender, revender ou sublicenciar o serviço sem autorização</li>
    <li>Tentar acessar dados de outros clientes</li>
    <li>Sobrecarregar intencionalmente a infraestrutura</li>
  </ul>

  <h2>4. Pagamento e cancelamento</h2>
  <ul>
    <li>Cobrança mensal antecipada via Kiwify</li>
    <li>Cancelamento a qualquer momento — sem multa</li>
    <li>O serviço permanece ativo até o fim do período pago</li>
    <li>Não há reembolso proporcional por cancelamento no meio do período</li>
    <li>Em caso de inadimplência, o bot é pausado automaticamente</li>
  </ul>

  <h2>5. Planos e limites</h2>
  <div class="box">
    <ul>
      <li><strong>Básico:</strong> até 7 serviços, sem lembretes automáticos, sem CSV</li>
      <li><strong>Pro:</strong> serviços ilimitados, lembretes, CSV, relatório semanal</li>
      <li><strong>Agência:</strong> tudo do Pro + até 3 negócios no mesmo plano</li>
    </ul>
  </div>

  <h2>6. Disponibilidade</h2>
  <p>Buscamos 99% de disponibilidade, mas não garantimos funcionamento ininterrupto. Manutenções programadas serão comunicadas com antecedência. Não nos responsabilizamos por indisponibilidades da Evolution API, WhatsApp ou OpenAI.</p>

  <h2>7. Responsabilidade</h2>
  <ul>
    <li>Você é responsável pelo conteúdo enviado pelo bot</li>
    <li>A BotGen não se responsabiliza por agendamentos perdidos por falha do WhatsApp</li>
    <li>Nossa responsabilidade máxima é limitada ao valor pago no último mês</li>
    <li>Não nos responsabilizamos por danos indiretos ou lucros cessantes</li>
  </ul>

  <h2>8. Propriedade intelectual</h2>
  <p>A plataforma BotGen, seu código e design são de propriedade exclusiva da BotGen. Você retém a propriedade dos seus dados e do conteúdo do seu negócio.</p>

  <h2>9. Rescisão</h2>
  <p>Podemos suspender ou encerrar sua conta sem aviso prévio em caso de violação destes termos. Em cancelamentos normais, seus dados ficam disponíveis por 30 dias após o encerramento.</p>

  <h2>10. Alterações nos termos</h2>
  <p>Podemos alterar estes termos com aviso de 15 dias por email. O uso continuado do serviço após esse prazo implica aceitação das mudanças.</p>

  <h2>11. Lei aplicável</h2>
  <p>Estes termos são regidos pelas leis brasileiras. Foro eleito: comarca de São Gonçalo do Pará, MG, com renúncia a qualquer outro.</p>

  <h2>12. Contato</h2>
  <p><a href="mailto:mtdnvendas@gmail.com">mtdnvendas@gmail.com</a></p>
</div>
<footer>
  © 2026 BotGen ·
  <a href="/planos">Página inicial</a> ·
  <a href="/privacidade">Política de Privacidade</a> ·
  <a href="mailto:mtdnvendas@gmail.com">Contato</a>
</footer>
</body></html>"""

@app.get("/termos", response_class=HTMLResponse)
async def termos():
    return HTMLResponse(content=_TERMOS_HTML)

# ── Rotas de teste (admin only) ───────────────────────────────────────────────

@app.post("/test/reminders")
async def test_reminders(request: Request):
    _require_admin(request)
    from .services.reminder import send_daily_reminders
    await send_daily_reminders()
    return {"status": "ok"}

@app.post("/test/weekly-report")
async def test_weekly_report(request: Request):
    _require_admin(request)
    from .services.scheduler import send_weekly_reports
    await send_weekly_reports()
    return {"status": "ok"}

@app.post("/test/expiry-warnings")
async def test_expiry_warnings(request: Request):
    _require_admin(request)
    from .services.scheduler import send_expiry_warnings
    await send_expiry_warnings()
    return {"status": "ok"}