import logging
from db_pool import get_conn, put_conn

def add_alert(user_id, target_price, condition):
    """
    Guarda una alerta nueva.
    condition: 'ABOVE' (Avísame si sube) o 'BELOW' (Avísame si baja).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Verificar cuántas alertas tiene activas (Máximo 3)
            cur.execute("SELECT COUNT(*) FROM alerts WHERE user_id = %s", (user_id,))
            count = cur.fetchone()[0]
            
            if count >= 3:
                return False # Límite alcanzado

            # 2. Insertar alerta
            cur.execute("""
                INSERT INTO alerts (user_id, target_price, condition)
                VALUES (%s, %s, %s)
            """, (user_id, target_price, condition))
            
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Error creando alerta: {e}")
        conn.rollback()
        return False
    finally:
        put_conn(conn)

def get_triggered_alerts(current_price):
    """
    Busca qué alertas se dispararon con el precio actual.
    Retorna lista de tuplas: (id, user_id, target_price)
    """
    conn = get_conn()
    triggered = []
    try:
        with conn.cursor() as cur:
            # Buscar alertas que cumplan la condición
            # 'ABOVE': El precio actual es MAYOR que el target
            # 'BELOW': El precio actual es MENOR que el target
            cur.execute("""
                SELECT id, user_id, target_price FROM alerts 
                WHERE (condition = 'ABOVE' AND %s >= target_price)
                   OR (condition = 'BELOW' AND %s <= target_price)
            """, (current_price, current_price))
            
            triggered = cur.fetchall()
            
            # Borrar las alertas disparadas (para que no suenen infinitamente)
            if triggered:
                ids = tuple([t[0] for t in triggered])
                cur.execute("DELETE FROM alerts WHERE id IN %s", (ids,))
                conn.commit()
                
        return triggered
    except Exception as e:
        logging.error(f"Error procesando alertas: {e}")
        return []
    finally:
        put_conn(conn)
