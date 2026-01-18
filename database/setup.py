import logging
from database.stats import get_conn, put_conn

def init_db():
    """Crea la estructura completa de la Base de Datos."""
    conn = None
    try:
        conn = get_conn()
        if not conn:
            logging.error("❌ No hay conexión a BD para init_db")
            return

        with conn.cursor() as cur:
            # 1. USUARIOS (Con soporte Premium)
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
                    premium_until TIMESTAMP -- Columna para suscripciones
                )
            """)

            # 2. LOGS DE ACTIVIDAD (Seguridad y Métricas)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    command TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. ALERTAS (Sistema Limitado 3/20)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    target_price FLOAT,
                    condition TEXT, -- 'ABOVE' o 'BELOW'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. DATA MINING (Para /mercado y /horario)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS arbitrage_data (
                    id SERIAL PRIMARY KEY,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    buy_pm FLOAT, sell_pm FLOAT,
                    buy_banesco FLOAT, buy_mercantil FLOAT, buy_provincial FLOAT,
                    spread_pct FLOAT
                )
            """)

            # 5. TABLAS LEGACY (Para no perder historial antiguo)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date DATE PRIMARY KEY,
                    price_sum FLOAT DEFAULT 0,
                    count INTEGER DEFAULT 0,
                    bcv_price FLOAT DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_ticks (
                    id SERIAL PRIMARY KEY,
                    price_binance FLOAT,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    price_sell FLOAT,
                    spread_pct FLOAT
                )
            """)

            # 6. ESTADO DEL MERCADO (Persistencia al reiniciar)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS market_state (
                    id SERIAL PRIMARY KEY,
                    price_binance FLOAT,
                    bcv_usd FLOAT,
                    bcv_eur FLOAT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 7. VOTOS DIARIOS (Sentimiento de Mercado)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_votes (
                    user_id BIGINT,
                    vote_type VARCHAR(10),
                    vote_date DATE DEFAULT CURRENT_DATE,
                    PRIMARY KEY (user_id, vote_date)
                )
            """)

            # Inicializar Market State si está vacío
            cur.execute("SELECT COUNT(*) FROM market_state")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO market_state (price_binance, bcv_usd, bcv_eur) VALUES (0, 0, 0)")

            conn.commit()
            
            # Ejecutar migraciones de columnas nuevas
            migrate_db(conn)
            
            logging.info("✅ Base de Datos inicializada correctamente.")

    except Exception as e:
        logging.error(f"❌ Error BD Init: {e}")
        if conn: conn.rollback()
    finally:
        put_conn(conn)

def migrate_db(conn):
    """
    Agrega columnas nuevas a tablas existentes sin borrar datos.
    Se llama automáticamente dentro de init_db.
    """
    try:
        with conn.cursor() as cur:
            # Migración Premium
            try:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP;")
            except Exception: conn.rollback()

            # Migración Referidos
            try:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
            except Exception: conn.rollback()

            # Migración Arbitraje (Si la tabla existía antes incompleta)
            try:
                cur.execute("ALTER TABLE arbitrage_data ADD COLUMN IF NOT EXISTS sell_pm FLOAT;")
                cur.execute("ALTER TABLE arbitrage_data ADD COLUMN IF NOT EXISTS buy_banesco FLOAT;")
            except Exception: conn.rollback()

            conn.commit()
    except Exception as e:
        logging.warning(f"⚠️ Migración no necesaria o error leve: {e}")
