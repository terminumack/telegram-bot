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
            # ... (Puedes agregar aquí el resto de tablas si quieres ser exhaustivo, 
            # pero con user y logs basta para empezar, el resto ya existen en tu DB de prod)
            
        conn.commit()
        logging.info("✅ Tablas de Base de Datos verificadas.")
    except Exception as e:
        logging.error(f"❌ Error BD Init: {e}")
        if conn:
            conn.rollback()
    finally:
        put_conn(conn)
