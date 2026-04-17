# database.py — Configuração do banco de dados BotGen
#
# FIX CRITICO: timezone=America/Sao_Paulo no engine
# Sem isso o PostgreSQL interpretava datetimes naive como UTC,
# causando deslocamento de 3h nos agendamentos (horários sempre "ocupados")

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Fix timezone: garante que o PostgreSQL interprete e retorne
# todos os datetimes no horário de Brasília (UTC-3)
# Isso é essencial pois o app usa datetime naive de Brasília
if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={},
        pool_pre_ping=True,       # reconecta automaticamente se conexão cair
        pool_recycle=300,         # recicla conexões a cada 5min (evita timeout Railway)
    )

    # Configura timezone por sessão — mais confiável que connect_args
    @event.listens_for(engine, "connect")
    def set_timezone(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'America/Sao_Paulo'")
        cursor.close()

elif DATABASE_URL.startswith("sqlite"):
    # SQLite local para desenvolvimento
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Abre e fecha sessão automaticamente — use com Depends(get_db)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()