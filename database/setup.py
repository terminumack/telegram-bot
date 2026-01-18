import logging
import os
import psycopg2
from urllib.parse import urlparse

DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    """Inicializa la DB usando TU esquema original + Adaptaciones V51."""
    if not DATABASE_URL:
        logging.error("❌ No DATABASE_URL found.")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # 1. TABLA USERS (Tu esquema exacto + Premium)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                first_name TEXT,
                referral_count INTEGER DEFAULT 0,
                referred_by BIGINT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                source TEXT,
                premium_until TIMESTAMP
            )
        """)

        # 2. TABLA ALERTS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                target_price FLOAT,
                condition TEXT, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. TABLA LOGS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                command TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. TABLA ESTADÍSTICAS DIARIAS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                price_sum FLOAT DEFAULT 0,
                count INTEGER DEFAULT 0,
                bcv_price FLOAT DEFAULT 0
            )
        """)

        # 5. TABLA ARBITRAJE
        cur.execute("""
            CREATE TABLE IF NOT EXISTS arbitrage_data (
                id SERIAL PRIMARY KEY,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                buy_pm FLOAT,
                sell_pm FLOAT,
                buy_banesco FLOAT,
                buy_mercantil FLOAT,
                buy_provincial FLOAT,
                spread_pct FLOAT
            )
        """)

        # 6. TABLA COLA DE MENSAJES (Broadcast)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_queue (
                id SERIAL PRIMARY KEY,
                message TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 7. TABLA VOTOS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_votes (
                user_id BIGINT,
                vote_date DATE,
                vote_type TEXT, 
                PRIMARY KEY (user_id, vote_date)
            )
        """)

        # 8. PERSISTENCIA DE MERCADO (ADAPTACIÓN HÍBRIDA)
        # Intentamos crear la tabla en formato Clave-Valor (Nuevo)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_memory (
                key_name TEXT PRIMARY KEY,
                value_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # NOTA: Si ya tenías una tabla llamada 'market_state' con otro formato,
        # la dejaremos tranquila y usaremos 'market_memory' para la V51.
        # Así evitamos choques de columnas.

        conn.commit()
        
        # Ejecutar migraciones por si faltan columnas en tablas viejas
        migrate_db(conn)
        
        cur.close()
        conn.close()
        logging.info("✅ Base de Datos Sincronizada (Modo Híbrido Seguro)")
        
    except Exception as e:
        logging.error(f"⚠️ Error en init_db: {e}")

def migrate_db(conn):
    """Asegura que las tablas viejas tengan las columnas nuevas."""
    try:
        with conn.cursor() as cur:
            # Users
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP;")
            except: conn.rollback()
            
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;")
            except: conn.rollback()
            
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT;")
            except: conn.rollback()

            # Arbitrage
            try: cur.execute("ALTER TABLE arbitrage_data ADD COLUMN IF NOT EXISTS sell_pm FLOAT;")
            except: conn.rollback()
            
            conn.commit()
    except Exception:
        pass
