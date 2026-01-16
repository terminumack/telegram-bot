import logging
from datetime import datetime
from db_pool import get_conn, put_conn

def track_user(user, referrer_id=None, source=None):
    """Registra o actualiza un usuario."""
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    now = datetime.now()
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Verificar si existe
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()

            if not exists:
                # 2. Lógica de Referidos (Solo si es nuevo)
                valid_referrer = False
                final_referrer = None
                
                if referrer_id and referrer_id != user_id:
                    # Verificar si el padrino existe
                    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
                    if cur.fetchone():
                        valid_referrer = True
                        final_referrer = referrer_id

                # 3. Insertar Nuevo Usuario
                cur.execute("""
                    INSERT INTO users (user_id, first_name, referred_by, last_active, status, source) 
                    VALUES (%s, %s, %s, %s, 'active', %s)
                """, (user_id, first_name, final_referrer, now, source))
                
                # 4. Sumar punto al padrino
                if valid_referrer:
                    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
                
                logging.info(f"🆕 Nuevo usuario registrado: {first_name} ({user_id})")

            else:
                # 5. Actualizar Usuario Existente
                cur.execute("""
                    UPDATE users 
                    SET first_name = %s, last_active = %s, status = 'active' 
                    WHERE user_id = %s
                """, (first_name, now, user_id))

            conn.commit()

    except Exception as e:
        logging.error(f"Error track_user: {e}")
        conn.rollback()
    finally:
        put_conn(conn)

def get_user_loyalty(user_id):
    """Devuelve (días_registrado, número_referidos)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT joined_at, referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            
        if res:
            days = (datetime.now() - res[0]).days
            return (days, res[1])
        return (0, 0)
    except Exception as e:
        logging.error(f"Error loyalty: {e}")
        return (0, 0)
    finally:
        put_conn(conn)
