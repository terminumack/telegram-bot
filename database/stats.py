import psycopg2
import logging
import json
import os
from datetime import datetime
from contextlib import contextmanager

# Configuración
DATABASE_URL = os.getenv("DATABASE_URL")
TIMEZONE = None # Se configurará desde shared.py si hace falta, o usa UTC por defecto

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

# --- GUARDADO DE ESTADO (MEMORIA) ---
def save_market_state(state_data):
    """Guarda el estado completo de la RAM en la tabla 'market_memory' (JSON)."""
    conn = get_conn()
    if not conn: return

    try:
        # Convertimos todo el diccionario a JSON texto
        json_data = json.dumps(state_data, default=str)
        
        with conn.cursor() as cur:
            # Usamos UPSET (Insertar o Actualizar)
            cur.execute("""
                INSERT INTO market_memory (key_name, value_json, updated_at)
                VALUES ('main_state', %s, NOW())
                ON CONFLICT (key_name) 
                DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
            """, (json_data,))
            conn.commit()
    except Exception as e:
        logging.error(f"⚠️ Error guardando estado: {e}")
    finally:
        put_conn(conn)

def load_market_state():
    """Recupera el estado al iniciar el bot."""
    conn = get_conn()
    if not conn: return None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value_json FROM market_memory WHERE key_name = 'main_state'")
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        logging.error(f"⚠️ Error cargando estado: {e}")
    finally:
        put_conn(conn)
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

def get_daily_requests_count():
    conn = get_conn()
    if not conn: return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            return cur.fetchone()[0]
    except Exception: return 0
    finally: put_conn(conn)

# --- VOTOS (Sube/Baja) ---
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
