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
        logging.error(f"❌ Error conectando a DB: {e}")
        return None

def put_conn(conn):
    if conn:
        try:
            conn.close()
        except Exception:
            pass

# --- PERSISTENCIA (Argumentos: precio, bcv_usd, bcv_eur) ---
def save_market_state(price, bcv_usd, bcv_eur):
    conn = get_conn()
    if not conn: return
    try:
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
    except Exception as e: 
        logging.error(f"Error save_market_state: {e}")
    finally: 
        put_conn(conn)

def load_last_market_state():
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value_json FROM market_memory WHERE key_name = 'main_state'")
            row = cur.fetchone()
            return json.loads(row[0]) if row else None
    except Exception: 
        return None
    finally: 
        put_conn(conn)

# --- REFERIDOS VITAMINADOS (Para que /referidos no explote) ---
def get_referral_stats(user_id):
    """Devuelve count, rank y top_3."""
    conn = get_conn()
    if not conn: return 0, 0, []
    try:
        with conn.cursor() as cur:
            # 1. Conteo
            cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            count = res[0] if res else 0

            # 2. Ranking
            cur.execute("""
                SELECT position FROM (
                    SELECT user_id, RANK() OVER (ORDER BY referral_count DESC) as position 
                    FROM users
                ) AS ranking WHERE user_id = %s
            """, (user_id,))
            rank_res = cur.fetchone()
            rank = rank_res[0] if rank_res else 0

            # 3. Top 3
            cur.execute("SELECT first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 3")
            top_3 = cur.fetchall()

            return count, rank, top_3
    except Exception: return 0, 0, []
    finally: put_conn(conn)

# --- REPORTE DETALLADO (La función que faltaba) ---
def get_detailed_report_text():
    """Genera el texto para el panel de administración."""
    conn = get_conn()
    if not conn: return "❌ Sin conexión"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE")
            hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            act = cur.fetchone()[0]
            
            return (
                f"📊 <b>ESTADÍSTICAS DEL BOT</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👥 Usuarios Totales: {total}\n"
                f"🆕 Registros Hoy: {hoy}\n"
                f"📉 Actividad Hoy: {act}\n"
            )
    except Exception: return "⚠️ Error al generar reporte"
    finally: put_conn(conn)

# --- MINERÍA Y ARBITRAJE ---
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

# --- OTRAS FUNCIONES REQUERIDAS ---
def log_calc(user_id, amount, currency, result):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", (user_id, amount, currency, result))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

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

# --- VOTOS ---
def cast_vote(user_id, vote_type):
    conn = get_conn()
    if not conn: return
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO daily_votes (user_id, vote_date, vote_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (user_id, today, vote_type))
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
