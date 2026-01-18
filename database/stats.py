import psycopg2
import logging
import json
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    if not DATABASE_URL: return None
    try: return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logging.error(f"❌ Error DB: {e}")
        return None

def put_conn(conn):
    if conn: conn.close()

# --- PERSISTENCIA (Argumentos: precio, bcv_usd, bcv_eur) ---
def save_market_state(price, bcv_usd, bcv_eur):
    conn = get_conn()
    if not conn: return
    try:
        # Creamos el diccionario que tu bot espera recuperar luego
        state_data = {
            "price": price,
            "bcv": {"dolar": bcv_usd, "euro": bcv_eur},
            "last_updated": datetime.now().isoformat()
        }
        json_data = json.dumps(state_data)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_memory (key_name, value_json)
                VALUES ('main_state', %s)
                ON CONFLICT (key_name) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
            """, (json_data,))
            conn.commit()
    except Exception as e: logging.error(f"Error save_market_state: {e}")
    finally: put_conn(conn)

def load_last_market_state():
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value_json FROM market_memory WHERE key_name = 'main_state'")
            row = cur.fetchone()
            return json.loads(row[0]) if row else None
    except Exception: return None
    finally: put_conn(conn)

# --- MINERÍA (Argumentos: pm_buy, bcv_usd, pm_sell) ---
def save_mining_data(pm_buy, bcv_usd, pm_sell):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, bcv_price) 
                VALUES (%s, %s, %s)
            """, (pm_buy, pm_sell, bcv_usd))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

# --- ARBITRAJE (Argumentos: pm_b, pm_s, ban, mer, pro) ---
def save_arbitrage_snapshot(pm_b, pm_s, ban, mer, pro):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, buy_banesco, buy_mercantil, buy_provincial)
                VALUES (%s, %s, %s, %s, %s)
            """, (pm_b, pm_s, ban, mer, pro))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

# --- OTRAS FUNCIONES ---
def log_activity(user_id, command):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

def get_daily_requests_count():
    conn = get_conn()
    if not conn: return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            return cur.fetchone()[0]
    except Exception: return 0
    finally: put_conn(conn)

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

# Para evitar errores en handlers que busquen estas funciones
def get_referral_stats(user_id): return 0
def get_detailed_report_text(): return "Reporte activo"
