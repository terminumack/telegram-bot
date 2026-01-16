#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from datetime import datetime, time as dt_time
import pytz

# --- TELEGRAM IMPORTS ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ConversationHandler,
    ContextTypes
)

# --- SERVICIOS Y BASE DE DATOS ---
from services.bcv_service import get_bcv_rates
from services.binance_service import get_binance_price
from database.stats import save_mining_data, queue_broadcast, get_daily_requests_count
from database.alerts import get_triggered_alerts

# --- UTILIDADES VISUALES ---
from utils.formatting import build_price_message, get_sentiment_keyboard

# --- HANDLERS (Tu lógica movida) ---
from handlers.start import start_command
from handlers.callbacks import button_handler
from handlers.calc import conv_usdt, conv_bs  # Calculadora
from handlers.alerts import conv_alert        # Alertas

# Extras (Incluyendo el Bonus de global y debug si lo hiciste)
from handlers.extras import (
    grafico, 
    referidos, 
    prediccion, 
    stats, 
    global_message, 
    debug_mining
)

# --- TELEGRAM IMPORTS ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler,
    ChatMemberHandler,
    filters,            
    ConversationHandler,
    ContextTypes
)

# --- TUS MÓDULOS (La parte nueva) ---
# Servicios
from services.bcv_service import get_bcv_rates
from services.binance_service import get_binance_price

# Base de Datos
from database.users import track_user  # Usado en comandos legacy
from database.stats import log_activity, get_daily_requests_count, get_user_loyalty # Usado en /precio
from database.alerts import get_triggered_alerts # <-- IMPORTANTE: Para revisar alertas en segundo plano

# Utilidades Visuales
from utils.formatting import build_price_message, get_sentiment_keyboard

# Handlers (Comandos y Botones)
from handlers.start import start_command
from handlers.callbacks import button_handler
from handlers.calc import conv_usdt, conv_bs  # <-- Calculadora Refactorizada
from handlers.alerts import conv_alert        # <-- Alertas Refactorizadas

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL LOGGING Y VARIABLES GLOBALES
# ---------------------------------------------------------------------------

from logger_conf import logging     # importa tu configuración de logging
BOT_VERSION = "v51_dev1"
logging.info(f"🚀 Iniciando Tasabinance Bot {BOT_VERSION}")

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

# Validaciones básicas
if not TOKEN:
    raise ValueError("❌ TOKEN de Telegram no configurado.")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no configurada.")

# Silenciar el ruido de librerías externas
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING) # Opcional: silencia logs de peticiones HTTP normales

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 
FILTER_MIN_USD = 20
MAX_HISTORY_POINTS = 200

# Lista Anti‑Ban
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
]

# Links
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

# Estados de conversación
ESPERANDO_INPUT_USDT, ESPERANDO_INPUT_BS, ESPERANDO_PRECIO_ALERTA = range(3)

# Emojis
EMOJI_BINANCE = '<tg-emoji emoji-id="5269277053684819725">🔶</tg-emoji>'
EMOJI_PAYPAL  = '<tg-emoji emoji-id="5364111181415996352">🅿️</tg-emoji>'
EMOJI_AMAZON  = '🎁'
EMOJI_SUBIDA  = '<tg-emoji emoji-id="5244837092042750681">📈</tg-emoji>'
EMOJI_BAJADA  = '<tg-emoji emoji-id="5246762912428603768">📉</tg-emoji>'
EMOJI_STATS   = '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji>'
EMOJI_STORE   = '<tg-emoji emoji-id="5895288113537748673">🏪</tg-emoji>'
EMOJI_ALERTA  = '🔔'

# ---------------------------------------------------------------------------
# MEMORIA / DATOS EN TIEMPO REAL
# ---------------------------------------------------------------------------
MARKET_DATA = {
    "price": None,
    "bcv": {"usd": None, "eur": None},
    "last_updated": "Esperando...",
    "history": deque(maxlen=MAX_HISTORY_POINTS)
}

# ✅ Este diccionario sirve para cachear el gráfico diario y evitar regenerarlo muchas veces
GRAPH_CACHE = {"date": None, "photo_id": None}
# ==============================================================================
#  BASE DE DATOS
# ==============================================================================
# --- IMPORTS DE BASE DE DATOS ---
from database.setup import init_db
from database.users import track_user, get_user_loyalty
from database.stats import (
    log_activity, 
    log_calc, 
    cast_vote, 
    get_vote_results, 
    has_user_voted,
    get_daily_requests_count, # <-- ESTA FALTABA
    get_yesterday_close       # <-- Probablemente también te falte esta
)
# ==============================================================================
#  ANALÍTICAS VISUALES (DASHBOARD)
# ==============================================================================


# --- GRÁFICO VERTICAL ---

# 🔥 FIX STATS V50: REPORTE COMPLETO CON CONCATENACIÓN ROBUSTA 🔥
def get_detailed_report_text():
    if not DATABASE_URL: return "⚠️ Error DB"
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
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
        cur.execute("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '24 HOURS'")
        active_24h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM alerts")
        active_alerts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
        requests_today = cur.fetchone()[0]
        
        # 3. Listas Top (Concatenación Segura)
        cur.execute("SELECT source, COUNT(*) FROM users WHERE source IS NOT NULL GROUP BY source ORDER BY 2 DESC LIMIT 3")
        top_sources = cur.fetchall()
        cur.execute("SELECT command, COUNT(*) FROM activity_logs GROUP BY command ORDER BY 2 DESC")
        top_commands = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
        total_referrals = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        # Construcción del Mensaje
        text = (
            f"📊 <b>REPORTE EJECUTIVO</b>\n\n"
            f"👥 <b>Total Histórico:</b> {total}\n"
            f"✅ <b>Usuarios Reales:</b> {active_real}\n"
            f"🚫 <b>Bloqueados:</b> {blocked} ({churn_rate:.2f}%)\n"
            f"--------------------------\n"
            f"📈 <b>Nuevos Hoy:</b> +{new_today}\n"
            f"🔥 <b>Activos (24h):</b> {active_24h}\n"
            f"🔔 <b>Alertas Activas:</b> {active_alerts}\n"
            f"📥 <b>Consultas Hoy:</b> {requests_today}\n"
        )
        
        # Bloque Referidos
        text += f"\n🤝 <b>Referidos Totales:</b> {total_referrals}\n"
        
        # Bloque Campañas
        if top_sources:
            text += "\n🎯 <b>Top Campañas:</b>\n"
            for src, cnt in top_sources:
                text += f"• {src}: {cnt}\n"
        
        # Bloque Comandos
        if top_commands:
            text += "\n🤖 <b>Comandos Totales:</b>\n"
            for cmd, cnt in top_commands:
                text += f"• {cmd}: {cnt}\n"

        text += f"\n<i>Sistema Operativo V50 (Debug+Fix).</i> ✅"
        return text
    except Exception as e: 
        logging.error(f"Error detailed report: {e}")
        return f"Error calculando métricas: {e}"

def get_referral_stats(user_id):
    if not DATABASE_URL: return (0, 0, [])
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        my_count = res[0] if res else 0
        cur.execute("SELECT COUNT(*) + 1 FROM users WHERE referral_count > %s", (my_count,))
        my_rank = cur.fetchone()[0]
        cur.execute("SELECT first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 3")
        top_3 = cur.fetchall()
        cur.close()
        conn.close()
        return (my_count, my_rank, top_3)
    except Exception: return (0, 0, [])

def get_total_users():
    if not DATABASE_URL: return 0
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception: return 0

def get_all_users_ids():
    if not DATABASE_URL: return []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE status = 'active'")
        ids = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception: return []

# --- ALERTAS ---


def save_mining_data(binance, bcv_val, binance_sell):
    if not DATABASE_URL: return
    try:
        today = datetime.now(TIMEZONE).date()
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Spread
        spread = 0
        if binance and binance_sell:
            spread = ((binance - binance_sell) / binance) * 100
        
        cur.execute("""
            INSERT INTO daily_stats (date, price_sum, count, bcv_price) 
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (date) DO UPDATE SET 
                price_sum = daily_stats.price_sum + %s,
                count = daily_stats.count + 1,
                bcv_price = GREATEST(daily_stats.bcv_price, %s)
        """, (today, binance, bcv_val, binance, bcv_val))
        
        cur.execute("""
            INSERT INTO arbitrage_data (buy_pm, sell_pm, buy_banesco, buy_mercantil, buy_provincial, spread_pct)
            VALUES (%s, %s, 0, 0, 0, %s)
        """, (binance, binance_sell, spread))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error mining: {e}")
# ==============================================================================
#  FUNCIONES DE REINTENTO ROBUSTO
# ==============================================================================
import asyncio, time

async def retry_request(func, *args, retries=3, delay=3, **kwargs):
    """
    Ejecuta una función (sincrónica o asíncrona) con reintentos automáticos.
    Retorna None si todos los intentos fallan.
    """
    for attempt in range(1, retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            logging.warning(f"⚠️ Intento {attempt}/{retries} falló en {func.__name__}: {e}")
            if attempt < retries:
                await asyncio.sleep(delay * attempt)
    logging.error(f"❌ Todos los intentos fallaron en {func.__name__}")
    return None
# ==============================================================================
#  BACKEND PRECIOS
# ==============================================================================
# --- IMPORTS NECESARIOS (Asegúrate de tenerlos arriba) ---
# from services.bcv_service import get_bcv_rates
# from services.binance_service import get_binance_price
# from telegram.constants import ParseMode

async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    """
    Tarea Maestra:
    1. Obtiene tasas (Binance Buy/Sell y BCV) en PARALELO.
    2. Actualiza variables globales y memoria.
    3. Gestiona Alertas y Mining.
    """
    try:
        # 1. PREPARAR LAS TAREAS (No se ejecutan aún, solo se definen)
        # Usamos el precio actual como referencia para el filtro de seguridad
        current_ref = MARKET_DATA["price"] or 60.0
        
        task_buy = get_binance_price("BUY", "PagoMovil", reference_price=current_ref)
        task_sell = get_binance_price("SELL", "PagoMovil", reference_price=current_ref)
        task_bcv = get_bcv_rates()

        # 2. EJECUTAR TODO A LA VEZ (Aquí ocurre la magia de la velocidad)
        # El bot espera solo lo que tarde la más lenta, no la suma de todas.
        buy_pm, sell_pm, new_bcv = await asyncio.gather(task_buy, task_sell, task_bcv)

        # 3. PROCESAR BINANCE (COMPRA - El precio principal)
        if buy_pm:
            MARKET_DATA["price"] = buy_pm
            
            # Lógica de Historial (Deque)
            MARKET_DATA["history"].append(buy_pm)
            if len(MARKET_DATA["history"]) > MAX_HISTORY_POINTS:
                MARKET_DATA["history"].popleft()

            # --- GESTIÓN DE ALERTAS ---
            # Nota: get_triggered_alerts sigue siendo síncrona (SQL), así que usamos to_thread
            # Más adelante moveremos esto a database/alerts.py
            try:
                alerts = await asyncio.to_thread(get_triggered_alerts, buy_pm)
                for alert in alerts:
                    chat_id, target_price = alert[1], alert[2]
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=(f"{EMOJI_ALERTA} <b>¡ALERTA!</b>\n"
                                  f"Dólar meta: <b>{target_price:,.2f} Bs</b>\n"
                                  f"Actual: {buy_pm:,.2f} Bs"),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as err_msg:
                        logging.warning(f"No se pudo enviar alerta a {chat_id}: {err_msg}")
            except Exception as e_alerts:
                logging.error(f"Error procesando alertas: {e_alerts}")

        # 4. PROCESAR BCV
        if new_bcv:
            MARKET_DATA["bcv"] = new_bcv

        # 5. DATA MINING (Guardar en DB)
        # Usamos el dato nuevo si existe, sino el viejo de memoria
        val_buy = buy_pm if buy_pm else MARKET_DATA["price"]
        val_bcv = new_bcv["usd"] if (new_bcv and new_bcv.get("usd")) else MARKET_DATA["bcv"].get("usd", 0)
        val_sell = sell_pm if sell_pm else 0 # Si falló el sell, guardamos 0 o el anterior según prefieras

        # Ejecutamos la query de guardado en hilo aparte para no frenar
        await asyncio.to_thread(save_mining_data, val_buy, val_bcv, val_sell)

        # 6. ACTUALIZAR TIMESTAMP
        if buy_pm or new_bcv:
            now = datetime.now(TIMEZONE)
            MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
            logging.info(f"🔄 Mercado Actualizado: Buy={val_buy:.2f} | Sell={val_sell:.2f} | BCV={val_bcv:.2f}")

    except Exception as e:
        logging.error(f"❌ Error CRÍTICO en update_price_task: {e}")

# --- NEW: COMANDO DEBUG ---
async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT * FROM arbitrage_data ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        
        if row:
            msg = (
                f"🕵️‍♂️ <b>DATA MINING DEBUG</b>\n\n"
                f"🕒 Time: {row[1]}\n"
                f"🟢 Buy PM: {row[2]}\n"
                f"🔴 Sell PM: {row[3]}\n"
                f"📉 Spread: {row[7]:.2f}%\n"
                f"🏦 Ban: {row[4]} | Mer: {row[5]} | Pro: {row[6]}"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ No hay data de minería aún.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error Debug: {e}")

# ... (El resto de comandos precio, start, etc. se mantienen igual a la V49) ...
# (Para no hacer el mensaje muy largo, asegúrate de mantener las funciones build_price_message, etc.)

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    binance = MARKET_DATA["price"]
    bcv = MARKET_DATA["bcv"]
    if not binance: binance = await asyncio.to_thread(fetch_binance_price)
    if not bcv: bcv = await asyncio.to_thread(fetch_bcv_price)
    if not binance: return

    time_str = datetime.now(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")
    hour = datetime.now(TIMEZONE).hour
    header = "☀️ <b>¡Buenos días! Así abre el mercado:</b>" if hour < 12 else "🌤 <b>Reporte de la Tarde:</b>"
    body = build_price_message(binance, bcv, time_str)
    body = body.replace(f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n", "")
    text = f"{header}\n\n{body}"
    
    await asyncio.to_thread(queue_broadcast, text)

def queue_broadcast(message):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
        conn.commit(); cur.close(); conn.close()
    except Exception: pass

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/precio")
    binance = MARKET_DATA["price"]
    bcv = MARKET_DATA["bcv"]
    time_str = MARKET_DATA["last_updated"]
    if binance:
        req_count = await asyncio.to_thread(get_daily_requests_count)
        text = build_price_message(binance, bcv, time_str, user_id, req_count)
        keyboard = get_sentiment_keyboard(user_id, binance)
        if random.random() < 0.2:
            days, refs = await asyncio.to_thread(get_user_loyalty, user_id)
            if days > 3 and refs == 0: text += "\n\n🎁 <i>¡Gana $10 USDT invitando amigos! Toca /referidos</i>"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/ia")
    history = MARKET_DATA["history"]
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nRecopilando datos.", parse_mode=ParseMode.HTML)
        return
    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    if percent > 0.5: emoji, status, msg = EMOJI_SUBIDA, "ALCISTA FUERTE", "Subida rápida."
    elif percent > 0: emoji, status, msg = EMOJI_SUBIDA, "LIGERAMENTE ALCISTA", "Recuperación."
    elif percent < -0.5: emoji, status, msg = EMOJI_BAJADA, "BAJISTA FUERTE", "Caída rápida."
    elif percent < 0: emoji, status, msg = EMOJI_BAJADA, "LIGERAMENTE BAJISTA", "Corrección."
    else: emoji, status, msg = "⚖️", "LATERAL / ESTABLE", "Sin cambios."
    text = (f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n<i>Tendencia basada en historial reciente.</i>\n\n"
            f"{emoji} <b>Estado:</b> {status}\n{EMOJI_STATS} <b>Variación (1h):</b> {percent:.2f}%\n\n"
            f"💡 <b>Conclusión:</b>\n<i>{msg}</i>\n\n⚠️ <i>No es consejo financiero.</i>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    chart = await asyncio.to_thread(generate_stats_chart)
    report = await asyncio.to_thread(get_detailed_report_text)
    if chart: await context.bot.send_photo(chat_id=ADMIN_ID, photo=chart, caption=report, parse_mode=ParseMode.HTML)
    else: await update.message.reply_text("❌ Error generando gráfico.")

async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    mensaje_original = update.message.text_html
    if mensaje_original.startswith('/global'):
        mensaje_final = mensaje_original.replace('/global', '', 1).strip()
    else: return
    if not mensaje_final:
        await update.message.reply_text("⚠️ Escribe el mensaje.", parse_mode=ParseMode.HTML)
        return
    await asyncio.to_thread(queue_broadcast, mensaje_final)
    await update.message.reply_text(f"✅ <b>Mensaje puesto en cola.</b>", parse_mode=ParseMode.HTML)


async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT * FROM arbitrage_data ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            msg = (f"🕵️‍♂️ <b>DATA MINING DEBUG</b>\n\n🕒 Time: {row[1]}\n🟢 Buy PM: {row[2]}\n🔴 Sell PM: {row[3]}\n📉 Spread: {row[7]:.2f}%\n🏦 Ban: {row[4]} | Mer: {row[5]} | Pro: {row[6]}")
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        else: await update.message.reply_text("❌ No hay data.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

if __name__ == "__main__":
    init_db()
    if not TOKEN: exit(1)
    
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.environ.get("PORT", "8080"))

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_error_handler(error_handler)


    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    
    # 👇 ESTA ES LA LÍNEA QUE CAMBIÓ
    app.add_handler(CommandHandler("start", start_command))
    
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CommandHandler("referidos", referidos)) 
    app.add_handler(CommandHandler("grafico", grafico)) 
    app.add_handler(CommandHandler("debug", debug_mining))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)
        # Asegúrate de que dt_time está siendo usado aquí
        app.job_queue.run_daily(send_daily_report, time=dt_time(hour=9, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
        app.job_queue.run_daily(send_daily_report, time=dt_time(hour=13, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
    
    if WEBHOOK_URL:
        print(f"🚀 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        print("⚠️ Sin WEBHOOK_URL. Iniciando Polling...")
        app.run_polling()
