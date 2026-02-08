import logging
import os
import asyncio
import psycopg2
from database.db_pool import get_conn, put_conn

def init_db():
    """Inicializa y sincroniza todo el ecosistema de la DB V51."""
    conn = get_conn()
    if not conn:
        logging.error("❌ No se pudo conectar a la DB.")
        return

    try:
        with conn.cursor() as cur:
            # 1. TABLA PRINCIPAL: USERS (Incluye 'source' para campañas)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    first_name TEXT,
                    referral_count INTEGER DEFAULT 0,
                    referred_by BIGINT,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    source TEXT DEFAULT 'organico',
                    premium_until TIMESTAMP
                )
            """)

            # 2. COLA DE MENSAJES (Para el Worker de 19k usuarios)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_queue (
                    id SERIAL PRIMARY KEY,
                    message TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. TABLA EXCHANGE (Pares y Órdenes)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exchange_pairs (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(50) UNIQUE NOT NULL,
                    type VARCHAR(20) DEFAULT 'FIAT',
                    is_active BOOLEAN DEFAULT TRUE,
                    min_amount DECIMAL(10, 2) DEFAULT 10
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS exchange_orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    user_username TEXT,
                    pair_name VARCHAR(50) NOT NULL,
                    initial_amount DECIMAL(10, 2) NOT NULL,
                    final_amount DECIMAL(10, 2),
                    status VARCHAR(20) DEFAULT 'PENDING',
                    cashier_id BIGINT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    taken_at TIMESTAMP WITH TIME ZONE,
                    closed_at TIMESTAMP WITH TIME ZONE
                )
            """)

            # 4. TABLAS DE INTELIGENCIA Y LOGS
            cur.execute("CREATE TABLE IF NOT EXISTS alerts (id SERIAL PRIMARY KEY, user_id BIGINT, target_price FLOAT, condition TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS activity_logs (id SERIAL PRIMARY KEY, user_id BIGINT, command TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS daily_stats (date DATE PRIMARY KEY, price_sum FLOAT DEFAULT 0, count INTEGER DEFAULT 0, bcv_price FLOAT DEFAULT 0)")
            cur.execute("CREATE TABLE IF NOT EXISTS arbitrage_data (id SERIAL PRIMARY KEY, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, buy_pm FLOAT, sell_pm FLOAT, buy_banesco FLOAT, buy_mercantil FLOAT, buy_provincial FLOAT, spread_pct FLOAT)")
            cur.execute("CREATE TABLE IF NOT EXISTS market_memory (key_name TEXT PRIMARY KEY, value_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS referral_history (id SERIAL PRIMARY KEY, user_id BIGINT, period VARCHAR(20), count INTEGER, archived_at TIMESTAMP DEFAULT NOW())")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;") # Dentro de tu función init_db, en la parte de migraciones:

            # 5. INYECCIÓN DE MONEDAS (Seed Data)
            target_pairs = [
                ('USDT', 'CRYPTO', 10), ('PayPal', 'FIAT', 20), ('Zelle', 'FIAT', 20),
                ('Zinli', 'FIAT', 15), ('Revolut', 'FIAT', 20), ('Wise', 'FIAT', 20),
                ('Bolívares', 'FIAT', 500)
            ]
            for name, p_type, min_amt in target_pairs:
                cur.execute("INSERT INTO exchange_pairs (name, type, is_active, min_amount) VALUES (%s, %s, TRUE, %s) ON CONFLICT (name) DO NOTHING", (name, p_type, min_amt))

            # 6. MIGRACIONES (Asegura columnas en DBs viejas)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'organico'")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0")

            # 7. ÍNDICES DE VELOCIDAD (Críticos para 19k+ usuarios)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_source ON users (source)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs (user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON broadcast_queue (status)")

            conn.commit()
            logging.info("✅ Base de Datos V51 Sincronizada y Optimizada.")

    except Exception as e:
        logging.error(f"⚠️ Error crítico en init_db: {e}")
        conn.rollback()
    finally:
        put_conn(conn)
