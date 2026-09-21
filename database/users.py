import logging
from datetime import datetime

# 🔥 CAMBIO CRÍTICO: Ahora apuntamos al Pool blindado real, no a stats.py
from database.db_pool import get_conn, put_conn

def track_user(user, referrer_id=None, source=None):
    """
    Registra o actualiza al usuario. (Versión estándar para comandos secundarios)
    """
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    username = user.username if user.username else None
    now = datetime.now()
    final_source = source if source else "organico"
    
    conn = get_conn()
    if not conn: return

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, source FROM users WHERE user_id = %s", (user_id,))
            existing_user = cur.fetchone()

            if not existing_user:
                final_referrer = None
                valid_referrer = False
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

                cur.execute("""
                    INSERT INTO users (user_id, first_name, username, referred_by, last_active, joined_at, status, source, referral_count) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, 0)
                """, (user_id, first_name, username, final_referrer, now, now, final_source))
                
                if valid_referrer:
                    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
            else:
                old_source = existing_user[1]
                new_source = final_source if (not old_source or old_source == 'organico') else old_source
                cur.execute("""
                    UPDATE users SET first_name = %s, username = %s, last_active = %s, status = 'active', source = %s
                    WHERE user_id = %s
                """, (first_name, username, now, new_source, user_id))
            conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        import logging
        logging.error(f"❌ Error en track_user: {e}")
    finally:
        if conn: put_conn(conn)

def get_user_loyalty(user_id):
    """Devuelve antiguedad y referidos usando tus columnas originales."""
    conn = get_conn()
    if not conn: return 0, 0
    try:
        from datetime import datetime
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
        if conn: conn.rollback()
        return 0, 0
    finally:
        if conn: put_conn(conn)

def process_core_interaction(user, command, referrer_id=None, source=None):
    """
    Súper-función 4 en 1 para alto tráfico.
    Hace tracking, lealtad, contador híbrido y métricas en un solo viaje a la DB.
    """
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    username = user.username if user.username else None
    now = datetime.now()
    final_source = source if source else "organico"

    conn = get_conn()
    if not conn: 
        return 0, 0, 0  # daily_count, loyalty_days, refs

    try:
        with conn.cursor() as cur:
            # ==========================================
            # 1. TRACK USER & LOYALTY (Fusionados)
            # ==========================================
            cur.execute("SELECT user_id, source, joined_at, referral_count FROM users WHERE user_id = %s", (user_id,))
            existing_user = cur.fetchone()

            loyalty_days = 0
            refs = 0

            if not existing_user:
                # Nuevo usuario
                final_referrer = None
                valid_referrer = False
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

                cur.execute("""
                    INSERT INTO users (user_id, first_name, username, referred_by, last_active, joined_at, status, source, referral_count) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, 0)
                """, (user_id, first_name, username, final_referrer, now, now, final_source))
                
                if valid_referrer:
                    cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
            else:
                # Usuario existente
                old_source = existing_user[1]
                joined_at = existing_user[2]
                refs = existing_user[3] if existing_user[3] else 0
                
                loyalty_days = (now - joined_at).days if joined_at else 0
                new_source = final_source if (not old_source or old_source == 'organico') else old_source
                
                cur.execute("""
                    UPDATE users SET first_name = %s, username = %s, last_active = %s, status = 'active', source = %s
                    WHERE user_id = %s
                """, (first_name, username, now, new_source, user_id))

            # ==========================================
            # 2. LOG ACTIVITY (Sistema Híbrido Rápido)
            # ==========================================
            cur.execute("""
                INSERT INTO daily_command_counts (stat_date, command, uses)
                VALUES ((NOW() AT TIME ZONE 'America/Caracas')::date, %s, 1)
                ON CONFLICT (stat_date, command) DO UPDATE SET uses = daily_command_counts.uses + 1
            """, (command,))

            # Solo va al "diario" si NO es un refresh
            if command not in ['refresh_btn', 'btn_refresh']:
                cur.execute("""
                    INSERT INTO activity_logs (user_id, command, created_at) 
                    VALUES (%s, %s, NOW())
                """, (user_id, command))

            # ==========================================
            # 3. GET DAILY REQUESTS COUNT
            # ==========================================
            cur.execute("""
                SELECT SUM(uses) FROM daily_command_counts 
                WHERE stat_date = (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            res = cur.fetchone()[0]
            daily_count = int(res) if res else 0

            # 🔥 CONFIRMAMOS TODO EN UN SOLO BLOQUE
            conn.commit()

            return daily_count, loyalty_days, refs

    except Exception as e:
        if conn: conn.rollback()
        logging.error(f"❌ Error en process_core_interaction: {e}")
        return 0, 0, 0
    finally:
        if conn: put_conn(conn)
def get_all_user_ids():
    """Obtiene todos los IDs de la base de datos para envíos globales."""
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE status = 'active'")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        # 🔥 EL ANTÍDOTO APLICADO
        if conn: conn.rollback()
        print(f"Error obteniendo IDs: {e}")
        return []
    finally:
        if conn: put_conn(conn)
