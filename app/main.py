from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from sqlalchemy import text, inspect as sa_inspect
import asyncio, os

load_dotenv()

from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook, dashboard, whatsapp_webhook, admin, setup, billing

Base.metadata.create_all(bind=engine)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "troca-essa-senha-admin")

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
                        print(f"[migrate-v3] ok tenants.{col}")
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
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            try:
                existentes = {c["name"] for c in inspector.get_columns("tenants")}
            except Exception:
                existentes = set()
            if "plan_tenant_group" not in existentes:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan_tenant_group VARCHAR"))
            conn.commit()
        print("[migrate-v5] concluida.")
    except Exception as e:
        print(f"[migrate-v5] erro: {e}")

_auto_migrate_v5()


def _auto_migrate_v6():
    """Evolution por tenant — escalabilidade multi-servidor."""
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            try:
                existentes = {c["name"] for c in inspector.get_columns("tenants")}
            except Exception:
                existentes = set()
            for col in ["evolution_url", "evolution_key"]:
                if col not in existentes:
                    try:
                        conn.execute(text(f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
                        print(f"[migrate-v6] ok tenants.{col}")
                    except Exception as e:
                        print(f"[migrate-v6] skip {col}: {e}")
            conn.commit()
        print("[migrate-v6] concluida.")
    except Exception as e:
        print(f"[migrate-v6] erro: {e}")

_auto_migrate_v6()


def _auto_migrate_v7():
    """next_billing_date — para aviso de vencimento."""
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:
            try:
                existentes = {c["name"] for c in inspector.get_columns("tenants")}
            except Exception:
                existentes = set()
            if "next_billing_date" not in existentes:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS next_billing_date DATE"))
                print("[migrate-v7] ok tenants.next_billing_date")
            conn.commit()
        print("[migrate-v7] concluida.")
    except Exception as e:
        print(f"[migrate-v7] erro: {e}")

_auto_migrate_v7()


# ── Scheduler loops ───────────────────────────────────────────────────────────

def _segundos_ate(hora: int, minuto: int = 0) -> float:
    """Segundos até o próximo HH:MM (hoje ou amanhã)."""
    from datetime import datetime
    import pytz
    BRASILIA = pytz.timezone("America/Sao_Paulo")
    agora    = datetime.now(BRASILIA).replace(tzinfo=None)
    target   = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if agora >= target:
        target = target.replace(day=target.day + 1)
    return (target - agora).total_seconds()


async def reminder_loop():
    """Lembretes de agendamento — todo dia às 18h."""
    from .services.reminder import send_daily_reminders
    while True:
        segundos = _segundos_ate(18, 0)
        print(f"[Lembretes] Próximo envio em {int(segundos/3600)}h {int((segundos%3600)/60)}min")
        await asyncio.sleep(segundos)
        await send_daily_reminders()


async def weekly_report_loop():
    """Relatório semanal — toda segunda-feira às 8h."""
    from .services.scheduler import send_weekly_reports
    from datetime import datetime
    import pytz
    BRASILIA = pytz.timezone("America/Sao_Paulo")
    while True:
        agora    = datetime.now(BRASILIA).replace(tzinfo=None)
        # Dias até segunda (weekday 0)
        dias_ate_seg = (7 - agora.weekday()) % 7
        if dias_ate_seg == 0 and agora.hour >= 8:
            dias_ate_seg = 7  # já passou das 8h de segunda, espera a próxima
        target = (agora + __import__('datetime').timedelta(days=dias_ate_seg)).replace(
            hour=8, minute=0, second=0, microsecond=0
        )
        segundos = (target - agora).total_seconds()
        print(f"[Relatorio] Próximo envio em {int(segundos/3600)}h")
        await asyncio.sleep(segundos)
        await send_weekly_reports()


async def expiry_warning_loop():
    """Aviso de vencimento — todo dia às 9h."""
    from .services.scheduler import send_expiry_warnings
    while True:
        segundos = _segundos_ate(9, 0)
        await asyncio.sleep(segundos)
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
    title="AgendaBot API",
    version="1.0.0",
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
    return {"status": "ok", "message": "AgendaBot rodando!"}

@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Página de vendas ──────────────────────────────────────────────────────────

@app.get("/planos", response_class=HTMLResponse)
async def landing_page():
    """Serve a landing page de vendas."""
    landing_path = os.path.join(os.path.dirname(__file__), "..", "landing.html")
    if os.path.exists(landing_path):
        with open(landing_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>AgendaBot</h1><p>Página em construção.</p>")


# ── Rotas utilitárias ─────────────────────────────────────────────────────────

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