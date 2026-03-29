from fastapi import FastAPI
from dotenv import load_dotenv
from .database import engine, Base
from .routers import webhook, appointments, telegram_webhook

load_dotenv()

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AgendaBot API",
    description="Chatbot de agendamento para negócios locais",
    version="0.1.0"
)

app.include_router(webhook.router)
app.include_router(appointments.router)
app.include_router(telegram_webhook.router)

@app.get("/")
def root():
    return {"status": "ok", "message": "AgendaBot rodando!"}

@app.get("/health")
def health():
    return {"status": "healthy"}
