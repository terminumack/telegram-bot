# db_pool.py
import os
import logging
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    db_pool = SimpleConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
    logging.info("✅ Pool de conexiones PostgreSQL inicializado.")
except Exception as e:
    logging.error(f"❌ Error creando pool de BD: {e}")
    db_pool = None


def get_conn():
    if not db_pool:
        raise RuntimeError("El pool de conexiones no está disponible.")
    return db_pool.getconn()


def put_conn(conn):
    if db_pool and conn:
        db_pool.putconn(conn)


def exec_query(query, params=None, fetch=False):
    """Ejecuta cualquier query SQL usando el pool global."""
    conn = get_conn()
    result = None
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if fetch:
                result = cur.fetchall()
        conn.commit()
    except Exception as e:
        logging.error(f"Error SQL: {e}")
    finally:
        put_conn(conn)
    return result
