from fastapi import FastAPI
from dotenv import load_dotenv
from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook, dashboard
from contextlib import asynccontextmanager
import asyncio

load_dotenv()

Base.metadata.create_all(bind=engine)


async def reminder_loop():
    """Roda os lembretes uma vez por dia às 18h."""
    from .services.reminder import send_daily_reminders
    from datetime import datetime

    while True:
        agora = datetime.now()

        # Calcula quantos segundos faltam para as 18h de hoje
        target = agora.replace(hour=18, minute=0, second=0, microsecond=0)

        if agora >= target:
            # Se já passou das 18h, agenda para amanhã
            target = target.replace(day=target.day + 1)

        segundos = (target - agora).total_seconds()
        print(f"[Lembretes] Próximo envio em {int(segundos/3600)}h {int((segundos%3600)/60)}min")

        await asyncio.sleep(segundos)
        await send_daily_reminders()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia o loop de lembretes em background
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
    """Rota para testar lembretes manualmente."""
    from .services.reminder import send_daily_reminders
    await send_daily_reminders()
    return {"status": "ok", "message": "Lembretes enviados!"}
