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
    from .services.email_service import email_relatorio_semanal
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

@app.get("/planos", response_class=HTMLResponse)
async def landing_page():
    """Serve a landing page de vendas."""
    # FIX: busca em múltiplos paths para compatibilidade Railway + local
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "landing.html"),
        os.path.join(os.getcwd(), "landing.html"),
        "/app/landing.html",
        "landing.html",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    # Fallback redirect se não achar o arquivo
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <title>BotGen — Agendamento pelo WhatsApp com IA</title>
    <style>body{font-family:sans-serif;background:#0f0f1a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}</style>
    </head><body>
    <div>
        <h1 style="font-size:32px;font-weight:800;margin-bottom:12px">BotGen ⚡</h1>
        <p style="color:#94a3b8;margin-bottom:24px">Agendamento automático pelo WhatsApp com IA</p>
        <a href="https://pay.kiwify.com.br/pndpF39" style="background:#7c3aed;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:700">Ver Planos</a>
    </div>
    </body></html>""")


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