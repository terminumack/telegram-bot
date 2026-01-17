import logging
from datetime import datetime
from db_pool import get_conn, put_conn

# --- LOGS ---
def log_activity(user_id, command):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
        conn.commit()
    except Exception as e:
        logging.error(f"Error log_activity: {e}")
    finally:
        put_conn(conn)

def log_calc(user_id, amount, currency, result):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", 
                        (user_id, amount, currency, result))
        conn.commit()
    except Exception as e:
        logging.error(f"Error log_calc: {e}")
    finally:
        put_conn(conn)

# --- VOTOS ---
def cast_vote(user_id, vote_type):
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_votes (user_id, vote_date, vote_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, vote_date) DO NOTHING
            """, (user_id, today, vote_type))
            rows = cur.rowcount
        conn.commit()
        return rows > 0
    except Exception as e:
        logging.error(f"Error vote: {e}")
        return False
    finally:
        put_conn(conn)

def get_vote_results():
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT vote_type, COUNT(*) FROM daily_votes WHERE vote_date = %s GROUP BY vote_type", (today,))
            results = dict(cur.fetchall())
        return (results.get('UP', 0), results.get('DOWN', 0))
    except Exception:
        return (0, 0)
    finally:
        put_conn(conn)

def has_user_voted(user_id):
    conn = get_conn()
    today = datetime.now().date()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM daily_votes WHERE user_id = %s AND vote_date = %s", (user_id, today))
            return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        put_conn(conn)

def get_daily_requests_count():
    """Cuenta cuántos comandos se han usado hoy."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            count = cur.fetchone()[0]
        return count
    except Exception as e:
        logging.error(f"Error getting requests count: {e}")
        return 0
    finally:
        put_conn(conn)

def get_yesterday_close():
    """Obtiene el precio de cierre de ayer para calcular variación."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Tu query original
            cur.execute("SELECT (price_sum / NULLIF(count, 0)) FROM daily_stats WHERE date = CURRENT_DATE - 1")
            res = cur.fetchone()
        return res[0] if res else None
    except Exception as e:
        logging.error(f"Error getting yesterday close: {e}")
        return None
    finally:
        put_conn(conn)

def get_user_loyalty(user_id):
    """
    Calcula la antigüedad y referidos del usuario.
    Retorna: (días_activos, número_referidos)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Contar cuántos días distintos ha usado el bot
            cur.execute("""
                SELECT COUNT(DISTINCT DATE(timestamp)) 
                FROM activity_logs 
                WHERE user_id = %s
            """, (user_id,))
            result = cur.fetchone()
            days = result[0] if result else 0

            # 2. Obtener número de referidos
            cur.execute("SELECT count FROM referrals WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            refs = row[0] if row else 0

            return days, refs
            
    except Exception as e:
        logging.error(f"Error obteniendo loyalty para {user_id}: {e}")
        return 0, 0
    finally:
        put_conn(conn)

def get_referral_stats(user_id):
    """
    Obtiene estadísticas para el comando /referidos.
    Retorna: (count, ranking, top_3_list)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Tu conteo personal
            cur.execute("SELECT count FROM referrals WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            count = row[0] if row else 0

            # Tu ranking global
            cur.execute("""
                SELECT COUNT(*) + 1 FROM referrals 
                WHERE count > (SELECT count FROM referrals WHERE user_id = %s)
            """, (user_id,))
            rank_row = cur.fetchone()
            rank = rank_row[0] if rank_row else 9999

            # Top 3 Global
            cur.execute("""
                SELECT u.first_name, r.count 
                FROM referrals r
                JOIN users u ON r.user_id = u.user_id
                ORDER BY r.count DESC LIMIT 3
            """)
            top_3 = cur.fetchall()

            return count, rank, top_3
    except Exception as e:
        logging.error(f"Error referidos stats: {e}")
        return 0, 9999, []
    finally:
        put_conn(conn)

def queue_broadcast(message):
    """Agrega un mensaje a la cola de envíos masivos."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
            conn.commit()
    except Exception as e:
        logging.error(f"Error queue_broadcast: {e}")
    finally:
        put_conn(conn)

# --- PEGA ESTO AL FINAL DE database/stats.py ---

def save_mining_data(binance_buy, bcv_val, binance_sell):
    """
    Guarda el histórico de precios para los gráficos y calcula el spread.
    Vital para que /grafico y /ia funcionen.
    """
    conn = get_conn()
    try:
        # Importamos datetime y timezone aquí por si no están arriba
        from datetime import datetime
        import pytz
        tz = pytz.timezone('America/Caracas')
        today = datetime.now(tz).date()
        
        # Calcular Spread
        spread = 0
        if binance_buy and binance_sell:
            spread = ((binance_buy - binance_sell) / binance_buy) * 100
        
        with conn.cursor() as cur:
            # 1. Tabla daily_stats (Upsert)
            cur.execute("""
                INSERT INTO daily_stats (date, price_sum, count, bcv_price) 
                VALUES (%s, %s, 1, %s)
                ON CONFLICT (date) DO UPDATE SET 
                    price_sum = daily_stats.price_sum + %s,
                    count = daily_stats.count + 1,
                    bcv_price = GREATEST(daily_stats.bcv_price, %s)
            """, (today, binance_buy, bcv_val, binance_buy, bcv_val))
            
            # 2. Tabla arbitrage_data (Histórico detallado)
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, spread_pct, buy_banesco, buy_mercantil, buy_provincial)
                VALUES (%s, %s, %s, 0, 0, 0)
            """, (binance_buy, binance_sell, spread))
            
            conn.commit()
            
    except Exception as e:
        logging.error(f"Error guardando data de minería: {e}")
        conn.rollback()
    finally:
        put_conn(conn)

def queue_broadcast(message):
    """Agrega un mensaje a la cola de envíos masivos (/global)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
            conn.commit()
    except Exception as e:
        logging.error(f"Error queue_broadcast: {e}")
    finally:
        put_conn(conn)

# --- FUNCIONES DE REPORTE Y ADMIN (Mudadas desde bot.py) ---

def get_detailed_report_text():
    """Genera el reporte ejecutivo para el Admin."""
    conn = get_conn()
    if not conn: return "⚠️ Error de conexión DB"
    try:
        with conn.cursor() as cur:
            # 1. KPI Principales
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE status = 'blocked'")
            blocked = cur.fetchone()[0]
            active_real = total - blocked
            churn_rate = (blocked / total * 100) if total > 0 else 0
            
            # 2. Actividad Reciente
            cur.execute("SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE")
            new_today = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
            requests_today = cur.fetchone()[0]
            
            # 3. Listas Top
            cur.execute("SELECT command, COUNT(*) FROM activity_logs GROUP BY command ORDER BY 2 DESC LIMIT 5")
            top_commands = cur.fetchall()

        text = (
            f"📊 <b>REPORTE EJECUTIVO</b>\n\n"
            f"👥 <b>Total:</b> {total} | ✅ <b>Activos:</b> {active_real}\n"
            f"🚫 <b>Bloqueados:</b> {blocked} ({churn_rate:.1f}%)\n"
            f"📈 <b>Nuevos Hoy:</b> +{new_today}\n"
            f"📥 <b>Consultas Hoy:</b> {requests_today}\n\n"
        )
        
        if top_commands:
            text += "🤖 <b>Top Comandos:</b>\n"
            for cmd, cnt in top_commands:
                text += f"• {cmd}: {cnt}\n"
                
        return text
    except Exception as e:
        logging.error(f"Error reporte detallado: {e}")
        return "❌ Error calculando métricas."
    finally:
        put_conn(conn)

def get_referral_stats(user_id):
    """Obtiene estadísticas de referidos de un usuario."""
    conn = get_conn()
    if not conn: return (0, 0, [])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            my_count = res[0] if res else 0
            
            # Ranking
            cur.execute("SELECT COUNT(*) + 1 FROM users WHERE referral_count > %s", (my_count,))
            my_rank = cur.fetchone()[0]
            
            # Top 3 Global
            cur.execute("SELECT first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 3")
            top_3 = cur.fetchall()
            
        return (my_count, my_rank, top_3)
    except Exception as e:
        logging.error(f"Error referidos: {e}")
        return (0, 0, [])
    finally:
        put_conn(conn)
