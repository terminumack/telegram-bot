import logging
from datetime import datetime
# Importamos la conexión del nuevo sistema modular
from database.stats import get_conn, put_conn

def track_user(user, referrer_id=None, source=None):
    """
    Registra o actualiza al usuario.
    Lógica blindada: Verifica existencia antes de insertar para asegurar referidos.
    """
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    username = user.username if user.username else None
    now = datetime.now()
    
    # Si no hay campaña, es organico
    final_source = source if source else "organico"
    
    conn = get_conn()
    if not conn: return

    try:
        with conn.cursor() as cur:
            # 1. VERIFICAMOS SI EL USUARIO YA EXISTE
            cur.execute("SELECT user_id, source FROM users WHERE user_id = %s", (user_id,))
            existing_user = cur.fetchone()

            if not existing_user:
                # --- CASO: USUARIO NUEVO (Aquí es donde se cuentan los referidos) ---
                final_referrer = None
                valid_referrer = False

                # Validamos el padrino
                if referrer_id:
                    try:
                        ref_id = int(referrer_id)
                        if ref_id != user_id:
                            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (ref_id,))
                            if cur.fetchone():
                                final_referrer = ref_id
                                valid_referrer = True
                    except:
                        pass

                # Insertamos al nuevo usuario
                cur.execute("""
                    INSERT INTO users (
                        user_id, first_name, username, referred_by, 
                        last_active, joined_at, status, source, referral_count
                    ) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, 0)
                """, (user_id, first_name, username, final_referrer, now, now, final_source))
                
                # 🔥 SUMAMOS EL PUNTO AL PADRINO (Solo si el usuario es nuevo)
                if valid_referrer:
                    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
                    logging.info(f"➕ Referido sumado con éxito al padrino: {final_referrer}")
                
                logging.info(f"🆕 Nuevo usuario registrado: {user_id} ({final_source})")

            else:
                # --- CASO: USUARIO EXISTENTE (Actualización de actividad) ---
                old_source = existing_user[1]
                
                # Solo actualizamos el origen si antes era organico/vacio
                new_source = final_source if (not old_source or old_source == 'organico') else old_source
                
                cur.execute("""
                    UPDATE users 
                    SET first_name = %s, username = %s, last_active = %s, 
                        status = 'active', source = %s
                    WHERE user_id = %s
                """, (first_name, username, now, new_source, user_id))
                
                #logging.info(f"🔄 Actividad actualizada para: {user_id}")

            conn.commit()

    except Exception as e:
        logging.error(f"❌ Error crítico en track_user: {e}")
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
def get_all_user_ids():
    """Obtiene todos los IDs de la base de datos para envíos globales."""
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE status = 'active'")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error obteniendo IDs: {e}")
        return []
    finally:
        put_conn(conn)
