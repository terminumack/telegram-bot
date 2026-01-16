import os
import logging
import psycopg2
from psycopg2 import pool

# Variable global para el Pool
_pg_pool = None

def init_db_pool():
    """Inicializa el pool de conexiones."""
    global _pg_pool
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logging.error("❌ NO DATABASE_URL found.")
        return

    try:
        # Creamos un pool que permite entre 1 y 20 conexiones simultáneas
        _pg_pool = psycopg2.pool.SimpleConnectionPool(1, 20, database_url)
        logging.info("✅ Pool de Base de Datos iniciado correctamente.")
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
        # Intenta reconectar si se cayó
        init_db_pool()
        return _pg_pool.getconn()

def put_conn(conn):
    """Devuelve la conexión al pool (importante para no saturar)."""
    global _pg_pool
    if _pg_pool and conn:
        try:
            _pg_pool.putconn(conn)
        except Exception as e:
            logging.error(f"Error devolviendo conexión: {e}")

# Inicializamos al importar
if not _pg_pool:
    init_db_pool()
