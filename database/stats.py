import psycopg2
import logging
import json
import os
from datetime import datetime
import pytz

# Configuración
DATABASE_URL = os.getenv("DATABASE_URL")

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

# --- PERSISTENCIA DE MERCADO ---
def save_market_state(price, bcv_usd, bcv_eur):
    conn = get_conn()
    if not conn: return
    try:
        state_data = {
            "price": price,
            "bcv": {"dolar": bcv_usd, "euro": bcv_eur},
            "last_updated": datetime.now().isoformat()
        }
        json_data = json.dumps(state_data)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_memory (key_name, value_json)
                VALUES ('main_state', %s)
                ON CONFLICT (key_name) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
            """, (json_data,))
            conn.commit()
    except Exception as e: 
        logging.error(f"Error save_market_state: {e}")
    finally: 
        put_conn(conn)

def load_last_market_state():
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value_json FROM market_memory WHERE key_name = 'main_state'")
            row = cur.fetchone()
            return json.loads(row[0]) if row else None
    except Exception: 
        return None
    finally: 
        put_conn(conn)

# --- REFERIDOS ---
def get_referral_stats(user_id):
    conn = get_conn()
    if not conn: return 0, 0, []
    try:
        with conn.cursor() as cur:
            # 1. Conteo
            cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
            res = cur.fetchone()
            count = res[0] if res else 0

            # 2. Ranking
            cur.execute("""
                SELECT position FROM (
                    SELECT user_id, RANK() OVER (ORDER BY referral_count DESC) as position 
                    FROM users
                ) AS ranking WHERE user_id = %s
            """, (user_id,))
            rank_res = cur.fetchone()
            rank = rank_res[0] if rank_res else 0

            # 3. Top 3
            cur.execute("SELECT user_id, first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 3")
            top_3_con_id = cur.fetchall()
            
            # Limpiamos datos sensibles
            top_3_limpio = [(row[1], row[2]) for row in top_3_con_id]

            return count, rank, top_3_limpio
    except Exception: return 0, 0, []
    finally: put_conn(conn)

# --- MINERÍA Y ARBITRAJE ---
def save_arbitrage_snapshot(pm_b, pm_s, ban, mer, pro):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, buy_banesco, buy_mercantil, buy_provincial)
                VALUES (%s, %s, %s, %s, %s)
            """, (pm_b, pm_s, ban, mer, pro))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

def save_mining_data(pm_buy, bcv_usd, pm_sell):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO arbitrage_data (buy_pm, sell_pm, bcv_price) 
                VALUES (%s, %s, %s)
            """, (pm_buy, pm_sell, bcv_usd))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

# --- LOGS Y ACTIVIDAD (AQUÍ ESTÁ LA MAGIA DEL CONTADOR) ---

def log_calc(user_id, amount, currency, result):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", (user_id, amount, currency, result))
            conn.commit()
    except Exception: pass
    finally: put_conn(conn)

def log_activity(user_id, command):
    """Registra el clic o comando para las estadísticas."""
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO activity_logs (user_id, command, created_at) 
                VALUES (%s, %s, NOW())
            """, (user_id, command))
            conn.commit()
    except Exception as e:
        print(f"❌ Error log_activity: {e}") 
    finally:
        put_conn(conn)

def get_daily_requests_count():
    conn = get_conn()
    if not conn: return 0
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM activity_logs 
                WHERE created_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            return cur.fetchone()[0]
    except Exception: 
        return 0
    finally: 
        put_conn(conn)

def queue_broadcast(message):
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
            conn.commit()
        return True
    except Exception: return False
    finally: put_conn(conn)

# --- VOTOS ---
def cast_vote(user_id, vote_type):
    conn = get_conn()
    if not conn: return
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO daily_votes (user_id, vote_date, vote_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (user_id, today, vote_type))
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

def get_vote_results():
    conn = get_conn()
    if not conn: return 0, 0
    try:
        today = datetime.now().date()
        with conn.cursor() as cur:
            cur.execute("SELECT vote_type, COUNT(*) FROM daily_votes WHERE vote_date = %s GROUP BY vote_type", (today,))
            rows = dict(cur.fetchall())
            return rows.get('UP', 0), rows.get('DOWN', 0)
    except Exception: return 0, 0
    finally: put_conn(conn)

# --- REPORTES AVANZADOS ---

def get_detailed_report_text():
    conn = get_conn()
    if not conn: return "⚠️ Error: No se pudo conectar a la DB."
    
    try:
        with conn.cursor() as cur:
            # 1. KPIs Globales
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM users WHERE status = 'blocked'")
            blocked = cur.fetchone()[0]
            
            # 2. Actividad de Hoy (Caracas)
            cur.execute("""
                SELECT COUNT(*) FROM users 
                WHERE joined_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            new_today = cur.fetchone()[0]
            
            cur.execute("""
                SELECT COUNT(*) FROM activity_logs 
                WHERE created_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            queries_today = cur.fetchone()[0]

            # 3. Referidos y Alertas
            cur.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
            referrals = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM alerts")
            active_alerts = cur.fetchone()[0]

            # 4. Top 5 Comandos (Dinámico)
            cur.execute("""
                SELECT command, COUNT(*) 
                FROM activity_logs 
                GROUP BY command 
                ORDER BY 2 DESC 
                LIMIT 5
            """)
            top_commands = cur.fetchall()

        # Cálculos rápidos
        active_real = total - blocked
        churn_rate = (blocked / total * 100) if total > 0 else 0

        # Construcción del Mensaje
        report = (
            f"📊 <b>REPORTE EJECUTIVO TASABINANCE</b>\n"
            f"<i>Corte: Medianoche Caracas</i>\n\n"
            f"👥 <b>Usuarios Totales:</b> {total:,}\n"
            f"✅ <b>Usuarios Activos:</b> {active_real:,}\n"
            f"🚫 <b>Bloqueados:</b> {blocked:,} ({churn_rate:.1f}%)\n"
            f"------------------------------\n"
            f"📈 <b>Nuevos Hoy:</b> +{new_today}\n"
            f"📥 <b>Consultas Hoy:</b> {queries_today:,}\n"
            f"🤝 <b>Referidos:</b> {referrals:,}\n"
            f"🔔 <b>Alertas Activas:</b> {active_alerts:,}\n"
        )

        if top_commands:
            report += "\n🤖 <b>Top 5 Comandos:</b>\n"
            for cmd, count in top_commands:
                report += f"• <code>{cmd}</code>: {count:,}\n"

        report += f"\n<i>Sistema V51 (Estable)</i> ✅"
        return report

    except Exception as e:
        return f"❌ Error calculando métricas: {str(e)}"
    finally:
        put_conn(conn)

def get_stats_full_text():
    conn = get_conn()
    if not conn: return "⚠️ Error de conexión"
    try:
        with conn.cursor() as cur:
            # 1. Usuarios Únicos Hoy (DAU)
            cur.execute("""
                SELECT COUNT(DISTINCT user_id) FROM activity_logs 
                WHERE created_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            dau = cur.fetchone()[0]

            # 2. Total de Consultas Hoy
            cur.execute("""
                SELECT COUNT(*) FROM activity_logs 
                WHERE created_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
            """)
            queries_today = cur.fetchone()[0]

            # 3. Top 15 Comandos/Botones
            cur.execute("""
                SELECT command, COUNT(*) FROM activity_logs 
                GROUP BY 1 ORDER BY 2 DESC LIMIT 15
            """)
            top_cmds = cur.fetchall()

            # 4. Heavy Users Hoy (Top 5 usuarios más activos)
            cur.execute("""
                SELECT user_id, COUNT(*) FROM activity_logs 
                WHERE created_at >= (NOW() AT TIME ZONE 'America/Caracas')::date
                GROUP BY 1 ORDER BY 2 DESC LIMIT 5
            """)
            heavy_users = cur.fetchall()

            # 5. Métricas de Referidos
            cur.execute("SELECT COUNT(*) FROM users")
            total_users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
            total_refs = cur.fetchone()[0]

        # Cálculos de negocio
        avg_queries = (queries_today / dau) if dau > 0 else 0
        ref_percent = (total_refs / total_users * 100) if total_users > 0 else 0

        # Construcción del Reporte Full
        report = (
            f"🚀 <b>ESTADÍSTICAS FULL (ADMIN)</b>\n"
            f"<i>Análisis profundo de Tasabinance</i>\n\n"
            f"📈 <b>ACTIVIDAD HOY (Caracas)</b>\n"
            f"• Usuarios Únicos (DAU): {dau:,}\n"
            f"• Consultas Totales: {queries_today:,}\n"
            f"• Promedio consultas/frecuencia: {avg_queries:.1f}\n\n"
            f"🤝 <b>CRECIMIENTO VIRAL</b>\n"
            f"• Usuarios por Referencia: {total_refs:,}\n"
            f"• Tasa de Viralidad: {ref_percent:.1f}%\n\n"
            f"🏆 <b>HEAVY USERS (Hoy)</b>\n"
        )

        for uid, cnt in heavy_users:
            report += f"• <code>{uid}</code>: {cnt} interacciones\n"

        report += "\n🤖 <b>TOP 15 INTERACCIONES (Histórico)</b>\n"
        for cmd, cnt in top_cmds:
            report += f"• <code>{cmd}</code>: {cnt:,}\n"

        report += f"\n<i>Modo: Business Intelligence V5.1</i> 💎"
        return report

    except Exception as e:
        return f"❌ Error en Stats Full: {e}"
    finally:
        put_conn(conn)
# --- ACUMULADOR DE PROMEDIOS DIARIOS (CORREGIDO) ---
def update_daily_stats(current_price, current_bcv):
    """
    Suma el precio actual al acumulado del día e incrementa el contador.
    VERSIÓN CORREGIDA: Sin columna 'updated_at'.
    """
    conn = get_conn()
    if not conn: return
    try:
        # Usamos la hora de Venezuela
        tz_vzla = pytz.timezone('America/Caracas')
        today = datetime.now(tz_vzla).date()
        
        with conn.cursor() as cur:
            # Upsert: Si existe suma, si no crea.
            cur.execute("""
                INSERT INTO daily_stats (date, price_sum, count, bcv_price)
                VALUES (%s, %s, 1, %s)
                ON CONFLICT (date) DO UPDATE SET 
                    price_sum = daily_stats.price_sum + EXCLUDED.price_sum,
                    count = daily_stats.count + 1,
                    bcv_price = EXCLUDED.bcv_price; 
            """, (today, current_price, current_bcv))
            conn.commit()
    except Exception as e:
        print(f"❌ Error actualizando acumulado diario: {e}")
    finally:
        put_conn(conn)

def get_admin_winners():
    """Trae a los ganadores usando SOLO datos seguros (ID y Nombre)."""
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            # Seleccionamos SOLO lo que seguro tienes guardado
            cur.execute("""
                SELECT user_id, first_name, referral_count 
                FROM users 
                WHERE referral_count > 0
                ORDER BY referral_count DESC 
                LIMIT 5
            """)
            return cur.fetchall()
    except Exception as e:
        print(f"❌ Error buscando ganadores: {e}")
        return []
    finally: put_conn(conn)

def reset_referral_counts(period_name):
    """
    1. Guarda los contadores actuales en el historial.
    2. Pone a cero los contadores de la tabla users.
    period_name: Ej "Enero 2026"
    """
    conn = get_conn()
    if not conn: return False, "Error de conexión"
    
    try:
        with conn.cursor() as cur:
            # 1. ARCHIVAR (Solo guardamos los que tienen más de 0)
            cur.execute("""
                INSERT INTO referral_history (user_id, period, count)
                SELECT user_id, %s, referral_count 
                FROM users 
                WHERE referral_count > 0;
            """, (period_name,))
            
            # 2. CONTAR cuántos archivamos (para el reporte)
            archived_count = cur.rowcount
            
            # 3. REINICIAR (Poner a 0 a todos)
            cur.execute("UPDATE users SET referral_count = 0 WHERE referral_count > 0;")
            
            conn.commit()
            return True, f"✅ Cierre exitoso.\n📂 Se archivaron {archived_count} usuarios.\n🔄 Marcadores a 0."
            
    except Exception as e:
        conn.rollback() # Si algo falla, deshacemos todo para no perder datos
        return False, f"❌ Error crítico en base de datos: {e}"
    finally:
        put_conn(conn)
