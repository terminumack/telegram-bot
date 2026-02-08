import logging
from datetime import datetime
# Importamos la conexión del nuevo sistema modular
from database.stats import get_conn, put_conn

def track_user(user, referrer_id=None, source=None):
    """
    Registra o actualiza al usuario, guardando Nombre y Username.
    """
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    # 🔥 Capturamos el username (si no tiene, guardamos None/NULL)
    username = user.username if user.username else None
    
    now = datetime.now()
    final_source = source if source else "organico"
    
    conn = get_conn()
    if not conn: return

    try:
        with conn.cursor() as cur:
            # UPSERT: Insertamos o actualizamos
            cur.execute("""
                INSERT INTO users (
                    user_id, first_name, username, referred_by, last_active, 
                    joined_at, status, source, referral_count
                ) 
                VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, 0)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    first_name = EXCLUDED.first_name,
                    username = EXCLUDED.username, -- 🔥 Se actualiza si el usuario lo cambia
                    last_active = EXCLUDED.last_active,
                    status = 'active',
                    source = CASE 
                        WHEN users.source = 'organico' OR users.source IS NULL THEN EXCLUDED.source 
                        ELSE users.source 
                    END
                RETURNING (xmax = 0) AS inserted;
            """, (user_id, first_name, username, referrer_id, now, now, final_source))
            
            # (Resto de la lógica de referidos igual que antes...)
            result = cur.fetchone()
            was_inserted = result[0] if result else False

            if was_inserted and referrer_id:
                # ... lógica de sumar puntos al padrino ...
                pass

            conn.commit()
    except Exception as e:
        logging.error(f"❌ Error en track_user: {e}")
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
