"""
migrate.py — rode UMA VEZ para adicionar as colunas novas ao banco.
Uso: python migrate.py
"""
import os, sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL não encontrada")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

MIGRATIONS = [
    # Tenant — campos novos
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS dashboard_password VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS dashboard_token VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS display_name VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subject_label VARCHAR DEFAULT 'Pet'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subject_label_plural VARCHAR DEFAULT 'Pets'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bot_attendant_name VARCHAR DEFAULT 'Mari'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bot_business_name VARCHAR",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS open_days VARCHAR DEFAULT '0,1,2,3,4,5'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS open_time VARCHAR DEFAULT '09:00'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS close_time VARCHAR DEFAULT '18:00'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bot_active BOOLEAN DEFAULT TRUE",
    # Service — campos extras
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS description VARCHAR",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS color VARCHAR DEFAULT '#6C5CE7'",
]

def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            try:
                conn.execute(text(sql))
                print(f"✅ {sql[:70]}...")
            except Exception as e:
                print(f"⚠️  {sql[:70]}... → {e}")
        conn.commit()
    print("\n✅ Migração concluída!")

if __name__ == "__main__":
    run()
    