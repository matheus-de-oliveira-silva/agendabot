from fastapi import FastAPI
from dotenv import load_dotenv
from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook, dashboard
from contextlib import asynccontextmanager
from .routers import whatsapp_webhook

app.include_router(whatsapp_webhook.router)

import asyncio

load_dotenv()

Base.metadata.create_all(bind=engine)


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
            {"name": "Banho simples", "duration_min": 60, "price": 4000},
            {"name": "Banho e tosa", "duration_min": 90, "price": 7000},
            {"name": "Tosa higiênica", "duration_min": 45, "price": 3500},
        ]
        for s in services:
            service = Service(tenant_id=tenant.id, **s)
            db.add(service)
        db.commit()

        return {"tenant_id": tenant.id, "message": "criado com sucesso"}
    finally:
        db.close()
        