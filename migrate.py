"""
migrate.py — rode UMA VEZ para adicionar as colunas novas ao banco existente.
Uso: python migrate.py

Seguro para rodar em produção — usa ALTER TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL não encontrada no .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

MIGRATIONS = [
    # Tenant — auth e configuração
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS dashboard_password VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS dashboard_token VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS display_name VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subject_label VARCHAR DEFAULT 'Pet'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subject_label_plural VARCHAR DEFAULT 'Pets'",

    # Service — campos extras
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS description VARCHAR",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS color VARCHAR DEFAULT '#6C5CE7'",
]

def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            try:
                conn.execute(text(sql))
                print(f"✅ {sql[:60]}...")
            except Exception as e:
                print(f"⚠️  {sql[:60]}... → {e}")
        conn.commit()
    print("\n✅ Migração concluída!")

if __name__ == "__main__":
    run()
    