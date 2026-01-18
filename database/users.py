import logging
from datetime import datetime
# Importamos la conexión del nuevo sistema modular
from database.stats import get_conn, put_conn

def track_user(user, referrer_id=None, source=None):
    """
    Registra usuario adaptado EXACTAMENTE a tu base de datos actual.
    Soporta llamadas con 1, 2 o 3 argumentos para no romper el bot.py.
    """
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    now = datetime.now()
    
    conn = get_conn()
    if not conn: return

    try:
        with conn.cursor() as cur:
            # 1. Verificar si existe
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()

            if not exists:
                # --- NUEVO USUARIO ---
                valid_referrer = False
                final_referrer = None
                
                # Lógica de Referidos
                if referrer_id and str(referrer_id).isdigit():
                    ref_id = int(referrer_id)
                    if ref_id != user_id:
                        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (ref_id,))
                        if cur.fetchone():
                            valid_referrer = True
                            final_referrer = ref_id

                # INSERT EXACTO (Respetando tus columnas originales)
                cur.execute("""
                    INSERT INTO users (user_id, first_name, referred_by, last_active, joined_at, status, source, referral_count) 
                    VALUES (%s, %s, %s, %s, %s, 'active', %s, 0)
                """, (user_id, first_name, final_referrer, now, now, source))
                
                # Sumar punto al padrino
                if valid_referrer:
                    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
                    logging.info(f"➕ Referido sumado a {final_referrer}")
                
                logging.info(f"🆕 Nuevo usuario: {user_id}")

            else:
                # --- ACTUALIZAR EXISTENTE ---
                cur.execute("""
                    UPDATE users 
                    SET first_name = %s, last_active = %s, status = 'active' 
                    WHERE user_id = %s
                """, (first_name, now, user_id))

            conn.commit()

    except Exception as e:
        logging.error(f"Error track_user: {e}")
        if conn: conn.rollback()
    finally:
        put_conn(conn)

def get_user_loyalty(user_id):
    """Devuelve antiguedad y referidos usando tus columnas originales."""
    conn = get_conn()
    if not conn: return 0, 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT joined_at, referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            if res:
                joined = res[0]
                days = (datetime.now() - joined).days if joined else 0
                refs = res[1] if res[1] else 0
                return days, refs
            return 0, 0
    except Exception:
        return 0, 0
    finally:
        put_conn(conn)
