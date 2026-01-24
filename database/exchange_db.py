import logging
from datetime import datetime
import pytz
# Asegúrate de importar tu conexión correctamente.
# Si tu archivo de conexión se llama 'db_pool.py', usa esta línea:
from database.db_pool import get_conn, put_conn 

# --- CONFIGURACIÓN Y LECTURA ---

def get_active_pairs():
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, currency_in, currency_out, rate, min_amount, max_amount, instructions, required_data 
                FROM exchange_pairs 
                WHERE is_active = TRUE
                ORDER BY id ASC
            """)
            # Convertimos a diccionario para facilitar uso en el frontend
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as e:
        logging.error(f"❌ Error get_active_pairs: {e}")
        return []
    finally:
        put_conn(conn)

def get_pair_info(pair_id):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM exchange_pairs WHERE id = %s", (pair_id,))
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
    except Exception: return None
    finally: put_conn(conn)

def get_active_wallet(pair_id):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT address FROM exchange_wallets WHERE pair_id = %s AND is_active = TRUE LIMIT 1", (pair_id,))
            res = cur.fetchone()
            return res[0] if res else "Consulte al Admin"
    except Exception: return None
    finally: put_conn(conn)

# --- CREACIÓN Y GESTIÓN DE ÓRDENES ---

def create_exchange_order(user_id, pair_id, amount_in, amount_out, rate, user_data):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO exchange_orders 
                (user_id, pair_id, amount_in, amount_out, rate_snapshot, user_data, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'PENDING')
                RETURNING id
            """, (user_id, pair_id, amount_in, amount_out, rate, user_data))
            order_id = cur.fetchone()[0]
            conn.commit()
            return order_id
    except Exception as e:
        logging.error(f"❌ Error creando orden: {e}")
        return None
    finally:
        put_conn(conn)

def add_proof_to_order(order_id, file_id):
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE exchange_orders 
                SET proof_file_id = %s, status = 'PROCESSING', created_at = NOW()
                WHERE id = %s
            """, (file_id, order_id))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)

# --- GESTIÓN DE CAJEROS ---

def assign_cashier(order_id, cashier_id):
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cashier_id FROM exchange_orders WHERE id = %s", (order_id,))
            current = cur.fetchone()
            if current and current[0] is not None and current[0] != cashier_id:
                return False 
            
            cur.execute("""
                UPDATE exchange_orders 
                SET cashier_id = %s, processed_at = NOW()
                WHERE id = %s
            """, (cashier_id, order_id))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)

def close_order(order_id, status, reason=None):
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE exchange_orders 
                SET status = %s, closed_at = NOW(), rejection_reason = %s
                WHERE id = %s
            """, (status, reason, order_id))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)

def get_order_details(order_id):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.*, p.currency_in, p.currency_out 
                FROM exchange_orders o
                JOIN exchange_pairs p ON o.pair_id = p.id
                WHERE o.id = %s
            """, (order_id,))
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
    except Exception: return None
    finally: put_conn(conn)
