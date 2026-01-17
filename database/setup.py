import logging
from db_pool import get_conn, put_conn

def init_db():
    """Crea las tablas iniciales si no existen."""
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            # --- TABLAS PRINCIPALES ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    first_name TEXT,
                    referral_count INTEGER DEFAULT 0,
                    referred_by BIGINT,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    source TEXT 
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    command TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Tabla de Votos Diarios (Encuesta)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_votes (
                user_id BIGINT,
                vote_type VARCHAR(10), -- 'UP' o 'DOWN'
                vote_date DATE DEFAULT CURRENT_DATE,
                PRIMARY KEY (user_id, vote_date)
            );
        """)
            # ... (Puedes agregar aquí el resto de tablas si quieres ser exhaustivo, 
            # pero con user y logs basta para empezar, el resto ya existen en tu DB de prod)
# ... (después de crear la tabla users, alerts, etc.) ...

        # TABLA NUEVA: Estado del Mercado (Para que no arranque en cero)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_state (
                id SERIAL PRIMARY KEY,
                price_binance FLOAT,
                bcv_usd FLOAT,
                bcv_eur FLOAT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Insertamos una fila vacía si no existe (para tener qué actualizar luego)
        cur.execute("SELECT COUNT(*) FROM market_state")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO market_state (price_binance, bcv_usd, bcv_eur) VALUES (0, 0, 0)")
            
        conn.commit()
        logging.info("✅ Tablas de Base de Datos verificadas.")
    except Exception as e:
        logging.error(f"❌ Error BD Init: {e}")
        if conn:
            conn.rollback()
    finally:
        put_conn(conn)
