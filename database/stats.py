import logging
from datetime import datetime
from db_pool import get_conn, put_conn

# --- LOGS ---
def log_activity(user_id, command):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
        conn.commit()
    except Exception as e:
        logging.error(f"Error log_activity: {e}")
    finally:
        put_conn(conn)

def log_calc(user_id, amount, currency, result):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", 
                        (user_id, amount, currency, result))
        conn.commit()
    except Exception as e:
        logging.error(f"Error log_calc: {e}")
    finally:
        put_conn(conn)

# --- VOTOS ---
def cast_vote(user_id, vote_type):
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_votes (user_id, vote_date, vote_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, vote_date) DO NOTHING
            """, (user_id, today, vote_type))
            rows = cur.rowcount
        conn.commit()
        return rows > 0
    except Exception as e:
        logging.error(f"Error vote: {e}")
        return False
    finally:
        put_conn(conn)

def get_vote_results():
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT vote_type, COUNT(*) FROM daily_votes WHERE vote_date = %s GROUP BY vote_type", (today,))
            results = dict(cur.fetchall())
        return (results.get('UP', 0), results.get('DOWN', 0))
    except Exception:
        return (0, 0)
    finally:
        put_conn(conn)

def has_user_voted(user_id):
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM daily_votes WHERE user_id = %s AND vote_date = %s", (user_id, today))
            return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        put_conn(conn)

def get_daily_requests_count():
    """Cuenta cuántos comandos se han usado hoy."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            count = cur.fetchone()[0]
        return count
    except Exception as e:
        logging.error(f"Error getting requests count: {e}")
        return 0
    finally:
        put_conn(conn)

def get_yesterday_close():
    """Obtiene el precio de cierre de ayer para calcular variación."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Tu query original
            cur.execute("SELECT (price_sum / NULLIF(count, 0)) FROM daily_stats WHERE date = CURRENT_DATE - 1")
            res = cur.fetchone()
        return res[0] if res else None
    except Exception as e:
        logging.error(f"Error getting yesterday close: {e}")
        return None
    finally:
        put_conn(conn)

def get_user_loyalty(user_id):
    """
    Calcula la antigüedad y referidos del usuario.
    Retorna: (días_activos, número_referidos)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Contar cuántos días distintos ha usado el bot
            cur.execute("""
                SELECT COUNT(DISTINCT DATE(timestamp)) 
                FROM activity_logs 
                WHERE user_id = %s
            """, (user_id,))
            result = cur.fetchone()
            days = result[0] if result else 0

            # 2. Obtener número de referidos
            cur.execute("SELECT count FROM referrals WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            refs = row[0] if row else 0

            return days, refs
            
    except Exception as e:
        logging.error(f"Error obteniendo loyalty para {user_id}: {e}")
        return 0, 0
    finally:
        put_conn(conn)

def get_referral_stats(user_id):
    """
    Obtiene estadísticas para el comando /referidos.
    Retorna: (count, ranking, top_3_list)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Tu conteo personal
            cur.execute("SELECT count FROM referrals WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            count = row[0] if row else 0

            # Tu ranking global
            cur.execute("""
                SELECT COUNT(*) + 1 FROM referrals 
                WHERE count > (SELECT count FROM referrals WHERE user_id = %s)
            """, (user_id,))
            rank_row = cur.fetchone()
            rank = rank_row[0] if rank_row else 9999

            # Top 3 Global
            cur.execute("""
                SELECT u.first_name, r.count 
                FROM referrals r
                JOIN users u ON r.user_id = u.user_id
                ORDER BY r.count DESC LIMIT 3
            """)
            top_3 = cur.fetchall()

            return count, rank, top_3
    except Exception as e:
        logging.error(f"Error referidos stats: {e}")
        return 0, 9999, []
    finally:
        put_conn(conn)
