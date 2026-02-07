import os
import logging
import psycopg2
from psycopg2 import pool

# Variable global para el Pool
_pg_pool = None

def init_db_pool():
    """Inicializa el pool de conexiones (Versión Threaded para alta carga)."""
    global _pg_pool
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logging.error("❌ NO DATABASE_URL found.")
        return

    try:
        # Cambiamos a ThreadedConnectionPool para manejar 19k usuarios sin choques entre hilos
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, database_url)
        logging.info("✅ Threaded DB Pool iniciado correctamente (Capacidad: 20).")
    except Exception as e:
        logging.error(f"❌ Error conectando al pool: {e}")

def get_conn():
    """Obtiene una conexión del pool."""
    global _pg_pool
    if not _pg_pool:
        init_db_pool()
    try:
        return _pg_pool.getconn()
    except Exception as e:
        logging.error(f"Error obteniendo conexión: {e}")
        init_db_pool()
        return _pg_pool.getconn()

def put_conn(conn):
    """Devuelve la conexión al pool."""
    global _pg_pool
    if _pg_pool and conn:
        try:
            _pg_pool.putconn(conn)
        except Exception as e:
            logging.error(f"Error devolviendo conexión: {e}")

# 🔥 ESTA ES LA FUNCIÓN QUE SOLUCIONA EL ERROR DEL WORKER
def exec_query(query, params=None, fetch=False):
    """
    Ejecuta SQL, maneja el commit y devuelve la conexión al pool automáticamente.
    """
    conn = get_conn()
    if not conn:
        return None
    
    result = None
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if fetch:
                result = cur.fetchall()
        conn.commit()
    except Exception as e:
        logging.error(f"❌ Error SQL en exec_query: {e}")
        if conn: conn.rollback()
    finally:
        if conn: put_conn(conn)
    return result

# Inicializamos al importar
if not _pg_pool:
    init_db_pool()
