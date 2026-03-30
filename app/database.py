# Importa as ferramentas do SQLAlchemy para trabalhar com banco de dados
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Carrega as variáveis do arquivo .env
load_dotenv()

# Pega a URL do banco do .env (sqlite:///./agendabot.db)
DATABASE_URL = os.getenv("DATABASE_URL")

# Cria a "conexão" com o banco
# connect_args só é necessário para SQLite
engine = create_engine(DATABASE_URL)

# Cada vez que precisar falar com o banco, abrimos uma "sessão"
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base que todos os modelos (tabelas) vão herdar
Base = declarative_base()

# Função auxiliar — abre e fecha a sessão automaticamente
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        