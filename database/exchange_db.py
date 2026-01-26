import logging
from datetime import datetime
from database.db_pool import get_conn, put_conn

# --- LECTURA ---
def get_menu_pairs():
    """Obtiene la lista para los botones."""
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM exchange_pairs WHERE is_active = TRUE ORDER BY id ASC")
            return cur.fetchall()
    except Exception: return []
    finally: put_conn(conn)

def get_pair_name(pair_id):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM exchange_pairs WHERE id = %s", (pair_id,))
            res = cur.fetchone()
            return res[0] if res else None
    except Exception: return None
    finally: put_conn(conn)

# --- GESTIÓN DE TICKETS ---

def create_ticket(user_id, username, pair_name, amount):
    """Crea el ticket en espera."""
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO exchange_orders (user_id, user_username, pair_name, initial_amount, status)
                VALUES (%s, %s, %s, %s, 'PENDING')
                RETURNING id
            """, (user_id, username, pair_name, amount))
            ticket_id = cur.fetchone()[0]
            conn.commit()
            return ticket_id
    except Exception as e:
        logging.error(f"Error creating ticket: {e}")
        return None
    finally: put_conn(conn)

def claim_ticket(ticket_id, cashier_id):
    """El cajero toma el ticket. (Marca el tiempo de respuesta)."""
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            # Verificar si ya está tomado
            cur.execute("SELECT cashier_id FROM exchange_orders WHERE id = %s", (ticket_id,))
            current = cur.fetchone()
            if current and current[0]: return False 

            cur.execute("""
                UPDATE exchange_orders 
                SET cashier_id = %s, status = 'IN_PROGRESS', taken_at = NOW()
                WHERE id = %s
            """, (cashier_id, ticket_id))
            conn.commit()
            return True
    except Exception: return False
    finally: put_conn(conn)

def close_ticket(ticket_id, status, final_amount=None):
    """Cierra el ticket. (Marca tiempo de resolución)."""
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            # Si no se especifica monto final, usamos el inicial como referencia
            if final_amount is None and status == 'COMPLETED':
                cur.execute("UPDATE exchange_orders SET final_amount = initial_amount WHERE id = %s", (ticket_id,))
            
            cur.execute("""
                UPDATE exchange_orders 
                SET status = %s, closed_at = NOW()
                WHERE id = %s
            """, (status, ticket_id))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)

def get_ticket_details(ticket_id):
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM exchange_orders WHERE id = %s", (ticket_id,))
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
    except Exception: return None
    finally: put_conn(conn)
