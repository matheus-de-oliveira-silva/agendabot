from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from sqlalchemy import text, inspect as sa_inspect
import asyncio

load_dotenv()

from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook, dashboard, whatsapp_webhook, admin

# Cria tabelas novas (se não existirem)
Base.metadata.create_all(bind=engine)

# ── Migração automática de colunas ────────────────────────────────────────────
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
                            print(f"[migrate] ✅ {tabela}.{col} adicionado")
                        except Exception as e:
                            print(f"[migrate] ⚠️  {tabela}.{col}: {e}")
            conn.commit()
        print("[migrate] ✅ Migração concluída.")
    except Exception as e:
        print(f"[migrate] ❌ Erro geral na migração: {e}")

_auto_migrate()
@app.post("/admin/migrate-v3")
def migrate_v3_http(request: Request):
    from .database import engine
    from migrate_v3 import run_migration
    results = run_migration(engine)
    return {"results": results}
# ─────────────────────────────────────────────────────────────────────────────


async def reminder_loop():
    from .services.reminder import send_daily_reminders
    from datetime import datetime

    while True:
        agora = datetime.now()
        target = agora.replace(hour=18, minute=0, second=0, microsecond=0)

        if agora >= target:
            target = target.replace(day=target.day + 1)

        segundos = (target - agora).total_seconds()
        print(f"[Lembretes] Próximo envio em {int(segundos/3600)}h {int((segundos%3600)/60)}min")

        await asyncio.sleep(segundos)
        await send_daily_reminders()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()


app = FastAPI(
    title="AgendaBot API",
    description="Chatbot de agendamento para negócios locais",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(webhook.router)
app.include_router(appointments.router)
app.include_router(telegram_webhook.router)
app.include_router(dashboard.router)
app.include_router(whatsapp_webhook.router)
app.include_router(admin.router)


@app.get("/")
def root():
    return {"status": "ok", "message": "AgendaBot rodando!"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/test/reminders")
async def test_reminders():
    from .services.reminder import send_daily_reminders
    await send_daily_reminders()
    return {"status": "ok", "message": "Lembretes enviados!"}


@app.post("/setup/tenant")
def setup_tenant(data: dict):
    from .database import SessionLocal
    from .models import Tenant, Service

    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.name == data["name"]).first()
        if existing:
            return {"tenant_id": existing.id, "message": "já existe"}

        tenant = Tenant(
            name=data["name"],
            business_type=data.get("business_type", "petshop"),
            phone_number_id=data.get("phone_number_id", "TEST123"),
            wa_access_token=data.get("wa_access_token", "TOKEN_TESTE")
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        services = [
            {"name": "Banho simples",    "duration_min": 60, "price": 4000},
            {"name": "Banho e tosa",     "duration_min": 90, "price": 7000},
            {"name": "Tosa higiênica",   "duration_min": 45, "price": 3500},
        ]
        for s in services:
            service = Service(tenant_id=tenant.id, **s)
            db.add(service)
        db.commit()

        return {"tenant_id": tenant.id, "message": "criado com sucesso"}
    finally:
        db.close()


@app.post("/admin/migrate")
def migrate_legacy():
    """Rota legada — mantida por compatibilidade."""
    from .database import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE appointments
            ADD COLUMN IF NOT EXISTS pet_id VARCHAR,
            ADD COLUMN IF NOT EXISTS pet_name VARCHAR,
            ADD COLUMN IF NOT EXISTS pet_breed VARCHAR,
            ADD COLUMN IF NOT EXISTS pet_weight FLOAT,
            ADD COLUMN IF NOT EXISTS pickup_time VARCHAR;
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pets (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL,
                customer_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                breed VARCHAR,
                weight FLOAT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))
        conn.commit()
    return {"success": True, "message": "Migration legada concluída!"}


@app.post("/admin/rename-tenant")
def rename_tenant(data: dict):
    from .database import SessionLocal
    from .models import Tenant
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if not tenant:
            return {"error": "Tenant não encontrado"}
        tenant.name = data["name"]
        db.commit()
        return {"success": True, "name": tenant.name}
    finally:
        db.close()