"""
migrate_v3.py — Adiciona colunas novas sem perder dados.
Execute UMA VEZ após o deploy: python migrate_v3.py
Ou chame POST /admin/migrate-v3 pelo navegador.
"""
from sqlalchemy import text, inspect as sa_inspect
import os, sys

def run_migration(engine):
    migrations = {
        "tenants": [
            ("tenant_icon",      "VARCHAR DEFAULT '🐾'"),
            ("owner_phone",      "VARCHAR"),
            ("notify_new_appt",  "BOOLEAN DEFAULT TRUE"),
        ],
    }
    # Cria tabela blocked_slots se não existir
    create_blocked = """
    CREATE TABLE IF NOT EXISTS blocked_slots (
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL,
        date VARCHAR NOT NULL,
        time VARCHAR,
        reason VARCHAR,
        created_at TIMESTAMP DEFAULT NOW()
    )"""

    results = []
    inspector = sa_inspect(engine)
    with engine.connect() as conn:
        for table, cols in migrations.items():
            try:
                existing = {c["name"] for c in inspector.get_columns(table)}
            except Exception:
                existing = set()
            for col, tipo in cols:
                if col not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                        results.append(f"✅ {table}.{col} adicionado")
                    except Exception as e:
                        results.append(f"❌ {table}.{col}: {e}")
                else:
                    results.append(f"⏭  {table}.{col} já existe")
        try:
            conn.execute(text(create_blocked))
            results.append("✅ Tabela blocked_slots criada/verificada")
        except Exception as e:
            results.append(f"❌ blocked_slots: {e}")
        conn.commit()
    return results

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.database import engine
    for r in run_migration(engine):
        print(r)