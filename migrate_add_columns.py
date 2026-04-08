"""
migrate_add_columns.py
Execute UMA VEZ para adicionar as colunas faltantes no banco existente.

Uso:
    python migrate_add_columns.py
"""

import sqlite3
import os

DB_PATH = os.getenv("DATABASE_URL", "agendabot.db").replace("sqlite:///", "")

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    migrations = [
        # Tenant — colunas que faltavam
        ("tenants", "bot_attendant_name", "TEXT DEFAULT 'Mari'"),
        ("tenants", "bot_business_name",  "TEXT"),
        ("tenants", "open_days",          "TEXT DEFAULT '0,1,2,3,4,5'"),
        ("tenants", "open_time",          "TEXT DEFAULT '09:00'"),
        ("tenants", "close_time",         "TEXT DEFAULT '18:00'"),
        ("tenants", "bot_active",         "INTEGER DEFAULT 1"),

        # Appointment — colunas de pagamento
        ("appointments", "payment_status",  "TEXT DEFAULT 'pending'"),
        ("appointments", "payment_method",  "TEXT"),
        ("appointments", "payment_amount",  "INTEGER"),
        ("appointments", "payment_pix_key", "TEXT"),
        ("appointments", "payment_paid_at", "DATETIME"),
        ("appointments", "payment_notes",   "TEXT"),
    ]

    added = []
    for table, col, definition in migrations:
        if not column_exists(cur, table, col):
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            added.append(f"{table}.{col}")
            print(f"  ✅ Adicionado: {table}.{col}")
        else:
            print(f"  ⏭  Já existe: {table}.{col}")

    conn.commit()
    conn.close()

    if added:
        print(f"\n✅ Migração concluída! {len(added)} coluna(s) adicionada(s).")
    else:
        print("\n✅ Banco já estava atualizado. Nenhuma alteração necessária.")

if __name__ == "__main__":
    migrate()
    