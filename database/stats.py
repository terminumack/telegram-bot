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
