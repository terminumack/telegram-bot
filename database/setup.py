import logging
import os
import psycopg2
from urllib.parse import urlparse

DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    """Inicializa la DB usando TU esquema original + Adaptaciones V51."""
    if not DATABASE_URL:
        logging.error("❌ No DATABASE_URL found.")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # 1. TABLA USERS (Tu esquema exacto + Premium)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                first_name TEXT,
                referral_count INTEGER DEFAULT 0,
                referred_by BIGINT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                source TEXT,
                premium_until TIMESTAMP
            )
        """)

        # 2. TABLA ALERTS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                target_price FLOAT,
                condition TEXT, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. TABLA LOGS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                command TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. TABLA ESTADÍSTICAS DIARIAS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                price_sum FLOAT DEFAULT 0,
                count INTEGER DEFAULT 0,
                bcv_price FLOAT DEFAULT 0
            )
        """)

        # 5. TABLA ARBITRAJE
        cur.execute("""
            CREATE TABLE IF NOT EXISTS arbitrage_data (
                id SERIAL PRIMARY KEY,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                buy_pm FLOAT,
                sell_pm FLOAT,
                buy_banesco FLOAT,
                buy_mercantil FLOAT,
                buy_provincial FLOAT,
                spread_pct FLOAT
            )
        """)

        # 6. TABLA COLA DE MENSAJES (Broadcast)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_queue (
                id SERIAL PRIMARY KEY,
                message TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 7. TABLA VOTOS
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_votes (
                user_id BIGINT,
                vote_date DATE,
                vote_type TEXT, 
                PRIMARY KEY (user_id, vote_date)
            )
        """)

        # 8. PERSISTENCIA DE MERCADO (ADAPTACIÓN HÍBRIDA)
        # Intentamos crear la tabla en formato Clave-Valor (Nuevo)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_memory (
                key_name TEXT PRIMARY KEY,
                value_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # NOTA: Si ya tenías una tabla llamada 'market_state' con otro formato,
        # la dejaremos tranquila y usaremos 'market_memory' para la V51.
        # Así evitamos choques de columnas.
        # =================================================================
        # 9. MÓDULO EXCHANGE (OTC) - ¡NUEVO! 🔥
        # =================================================================
        
        # 9.1 Tabla de Pares (Configuración)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exchange_pairs (
                id SERIAL PRIMARY KEY,
                currency_in VARCHAR(50) NOT NULL,
                currency_out VARCHAR(50) NOT NULL,
                rate DECIMAL(10, 4) NOT NULL,
                min_amount DECIMAL(10, 2) DEFAULT 10,
                max_amount DECIMAL(10, 2) DEFAULT 500,
                is_active BOOLEAN DEFAULT TRUE,
                instructions TEXT,
                required_data TEXT DEFAULT 'email'
            );
        """)

        # 9.2 Tabla de Billeteras (Tus cuentas)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exchange_wallets (
                id SERIAL PRIMARY KEY,
                pair_id INTEGER REFERENCES exchange_pairs(id),
                address TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                daily_limit DECIMAL(10, 2) DEFAULT 1000,
                current_volume DECIMAL(10, 2) DEFAULT 0,
                last_reset DATE DEFAULT CURRENT_DATE
            );
        """)

        # 9.3 Tabla de Órdenes (Historial)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exchange_orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                pair_id INTEGER REFERENCES exchange_pairs(id),
                amount_in DECIMAL(10, 2) NOT NULL,
                amount_out DECIMAL(10, 2) NOT NULL,
                rate_snapshot DECIMAL(10, 4) NOT NULL,
                status VARCHAR(20) DEFAULT 'PENDING',
                user_data TEXT,
                proof_file_id TEXT,
                cashier_id BIGINT,
                rejection_reason TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                processed_at TIMESTAMP WITH TIME ZONE,
                closed_at TIMESTAMP WITH TIME ZONE
            );
        """)

        # 9.4 Datos de Prueba (Seed Data)
        # Solo insertamos si la tabla está vacía para no duplicar
        cur.execute("SELECT COUNT(*) FROM exchange_pairs")
        if cur.fetchone()[0] == 0:
            print("🌱 Insertando datos base del Exchange...")
            # Insertar Par: PayPal -> USDT (Tasa 0.90)
            cur.execute("""
                INSERT INTO exchange_pairs (currency_in, currency_out, rate, instructions)
                VALUES ('PayPal', 'USDT', 0.90, '⚠️ Enviar solo como "Amigos y Familiares". Adjuntar captura completa.')
            """)
            # Insertar Wallet de prueba para el ID 1
            cur.execute("""
                INSERT INTO exchange_wallets (pair_id, address)
                VALUES (1, 'tucorreo@gmail.com')
            """)

        conn.commit()
        
        # Ejecutar migraciones por si faltan columnas en tablas viejas
        migrate_db(conn)
        
        cur.close()
        conn.close()
        logging.info("✅ Base de Datos Sincronizada (Modo Híbrido Seguro)")
        
    except Exception as e:
        logging.error(f"⚠️ Error en init_db: {e}")

def migrate_db(conn):
    """Asegura que las tablas viejas tengan las columnas nuevas."""
    try:
        with conn.cursor() as cur:
            # Users
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP;")
            except: conn.rollback()
            
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;")
            except: conn.rollback()
            
            try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT;")
            except: conn.rollback()

            # Arbitrage
            try: cur.execute("ALTER TABLE arbitrage_data ADD COLUMN IF NOT EXISTS sell_pm FLOAT;")
            except: conn.rollback()
            
            conn.commit()
    except Exception:
        pass
