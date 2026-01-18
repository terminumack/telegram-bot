import psycopg2
import logging
import json
import os
from datetime import datetime

# Configuración
DATABASE_URL = os.getenv("DATABASE_URL")

# --- GESTIÓN DE CONEXIÓN ---
def get_conn():
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logging.error(f"❌ Error conectando a BD: {e}")
        return None

def put_conn(conn):
    if conn:
        try:
            conn.close()
        except Exception:
            pass

# --- GUARDADO DE ESTADO (MEMORIA RAM) ---
def save_market_state(state_data):
    conn = get_conn()
    if not conn: return
    try:
        json_data = json.dumps(state_data, default=str)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_memory (key_name, value_json, updated_at)
                VALUES ('main_state', %s, NOW())
                ON CONFLICT (key_name) 
                DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
            """, (json_data,))
            conn.commit()
    except Exception as e: logging.error(f"Error save_state: {e}")
    finally: put_conn(conn)

def load_last_market_state():
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value_json FROM market_memory WHERE key_name = 'main_state'")
            row = cur.fetchone()
            if row and row[0]: return json.loads(row[0])
    except Exception: pass
    finally: put_conn(conn)
    return None

# --- ESTADÍSTICAS Y LOGS ---
def log_activity(user_id, command):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

# --- LOGS DE CALCULADORA (LA FUNCIÓN QUE FALTABA) ---
def log_calc(user_id, amount, currency, result):
    """Guarda el historial de cálculos."""
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO calc_logs (user_id, amount, currency_type, result) 
                VALUES (%s, %s, %s, %s)
            """, (user_id, amount, currency, result))
            conn.commit()
    except Exception as e:
        logging.error(f"⚠️ Error log_calc: {e}")
    finally:
        put_conn(conn)

def get_daily_requests_count():
    conn = get_conn()
    if not conn: return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            return cur.fetchone()[0]
    except Exception: return 0
    finally: put_conn(conn)

def get_referral_stats(user_id):
    conn = get_conn()
    if not conn: return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            return res[0] if res else 0
    except Exception: return 0
    finally: put_conn(conn)

# --- REPORTE DETALLADO ---
def get_detailed_report_text():
    conn = get_conn()
    if not conn: return "❌ Sin conexión a DB"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE")
            new_users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            activity = cur.fetchone()[0]
            return (
                f"📊 <b>ESTADO DEL SISTEMA</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Usuarios Totales:</b> {total}\n"
                f"🆕 <b>Nuevos Hoy:</b> {new_users}\n"
                f"📉 <b>Interacciones Hoy:</b> {activity}\n"
                f"🤖 <b>Bot Activo:</b> ✅"
            )
    except Exception as e: return f"⚠️ Error reporte: {e}"
    finally: put_conn(conn)

# --- VOTOS ---
def cast_vote(user_id, vote_type):
    conn = get_conn()
    if not conn: return
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_votes (user_id, vote_date, vote_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, vote_date) DO NOTHING
            """, (user_id, today, vote_type))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

def has_user_voted(user_id):
    conn = get_conn()
    if not conn: return False
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM daily_votes WHERE user_id = %s AND vote_date = %s", (user_id, today))
            return cur.fetchone() is not None
    except Exception: return False
    finally: put_conn(conn)

def get_vote_results():
    conn = get_conn()
    if not conn: return 0, 0
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("SELECT vote_type, COUNT(*) FROM daily_votes WHERE vote_date = %s GROUP BY vote_type", (today,))
            rows = dict(cur.fetchall())
            return rows.get('UP', 0), rows.get('DOWN', 0)
    except Exception: return 0, 0
    finally: put_conn(conn)

# --- MINERÍA ---
def save_mining_data(banks_data):
    conn = get_conn()
    if not conn: return
    try:
        pm = banks_data.get("pm", {})
        ban = banks_data.get("banesco", {})
        mer = banks_data.get("mercantil", {})
        pro = banks_data.get("provincial", {})
        buy_pm, sell_pm = pm.get("buy", 0), pm.get("sell", 0)
        spread = ((buy_pm - sell_pm) / buy_pm) * 100 if buy_pm > 0 else 0
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, buy_banesco, buy_mercantil, buy_provincial, spread_pct)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (buy_pm, sell_pm, ban.get("buy", 0), mer.get("buy", 0), pro.get("buy", 0), spread))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

save_arbitrage_snapshot = save_mining_data

def queue_broadcast(message):
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)
