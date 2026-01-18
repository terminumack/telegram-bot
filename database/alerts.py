import logging
from datetime import datetime
# Asumo que tu conexión viene de database.stats como en el resto de archivos
from database.stats import get_conn, put_conn 

def add_alert(user_id, target_price, condition):
    """
    Guarda una alerta nueva respetando los límites.
    Retorna: "SUCCESS", "LIMIT_REACHED" o "ERROR".
    """
    conn = get_conn()
    if not conn: return "ERROR"
    
    try:
        with conn.cursor() as cur:
            # 1. VERIFICAR SI ES PREMIUM
            # Si la fecha 'premium_until' es futura, el límite es 20, si no, es 3.
            cur.execute("SELECT premium_until FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            
            is_premium = False
            if row and row[0]:
                if row[0] > datetime.now():
                    is_premium = True
            
            limit = 20 if is_premium else 3

            # 2. CONTAR ALERTAS ACTUALES
            cur.execute("SELECT COUNT(*) FROM alerts WHERE user_id = %s", (user_id,))
            count = cur.fetchone()[0]
            
            if count >= limit:
                return "LIMIT_REACHED" # Código especial para vender Premium

            # 3. INSERTAR ALERTA
            cur.execute("""
                INSERT INTO alerts (user_id, target_price, condition)
                VALUES (%s, %s, %s)
            """, (user_id, target_price, condition))
            
            conn.commit()
            return "SUCCESS"

    except Exception as e:
        logging.error(f"Error creando alerta: {e}")
        conn.rollback()
        return "ERROR"
    finally:
        put_conn(conn)

def get_triggered_alerts(current_price):
    """
    Busca qué alertas se dispararon con el precio actual.
    Retorna una lista de diccionarios con los datos.
    NO BORRA las alertas aquí (se borran una por una en el handler tras enviar el mensaje).
    """
    conn = get_conn()
    triggered = []
    
    if not conn: return []

    try:
        with conn.cursor() as cur:
            # 'ABOVE': El precio SUBIÓ y pasó el target (Precio Actual >= Target)
            # 'BELOW': El precio BAJÓ y pasó el target (Precio Actual <= Target)
            query = """
                SELECT id, user_id, target_price, condition 
                FROM alerts 
                WHERE (condition = 'ABOVE' AND %s >= target_price)
                   OR (condition = 'BELOW' AND %s <= target_price)
            """
            cur.execute(query, (current_price, current_price))
            rows = cur.fetchall()
            
            # Convertimos a diccionarios para que sea fácil usar en el handler
            for r in rows:
                triggered.append({
                    "id": r[0],
                    "user_id": r[1],
                    "target_price": r[2],
                    "condition": r[3]
                })
                
        return triggered

    except Exception as e:
        logging.error(f"Error buscando alertas disparadas: {e}")
        return []
    finally:
        put_conn(conn)

def delete_alert(alert_id):
    """
    Borra una alerta específica por ID.
    Se usa después de enviarle el mensaje al usuario.
    """
    conn = get_conn()
    if not conn: return

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
            conn.commit()
    except Exception as e:
        logging.error(f"Error borrando alerta {alert_id}: {e}")
    finally:
        put_conn(conn)
