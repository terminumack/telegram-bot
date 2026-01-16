#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from services.bcv_service import get_bcv_rates
from services.binance_service import get_binance_price
import requests
import psycopg2
import asyncio
import io
import random
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup
import urllib3
from urllib.parse import quote
from datetime import datetime, time as dt_time, timedelta
import pytz
from collections import deque   # ✅ correcto: import fuera de cualquier bloque

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

# Silenciar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
from database.stats import log_activity, log_calc, cast_vote, get_vote_results, has_user_voted
# ==============================================================================
#  ANALÍTICAS VISUALES (DASHBOARD)
# ==============================================================================
def generate_stats_chart():
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT TO_CHAR(joined_at, 'MM-DD'), COUNT(*) 
            FROM users WHERE joined_at >= NOW() - INTERVAL '7 DAYS'
            GROUP BY 1 ORDER BY 1
        """)
        growth_data = cur.fetchall()
        cur.execute("""
            SELECT command, COUNT(*) FROM activity_logs 
            GROUP BY command ORDER BY 2 DESC LIMIT 5
        """)
        cmd_data = cur.fetchall()
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
        bg_color = '#212121'
        fig.patch.set_facecolor(bg_color)
        ax1.set_facecolor(bg_color)
        ax2.set_facecolor(bg_color)
        if growth_data:
            dates = [row[0] for row in growth_data]
            counts = [row[1] for row in growth_data]
            bars = ax1.bar(dates, counts, color='#F3BA2F') 
            ax1.set_title('Nuevos Usuarios (7 Días)', color='white', fontsize=12)
            ax1.bar_label(bars, color='white')
        else: ax1.text(0.5, 0.5, "Sin datos", ha='center', color='gray')
        if cmd_data:
            labels = [row[0] for row in cmd_data]
            sizes = [row[1] for row in cmd_data]
            ax2.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, textprops={'color':"white"})
            ax2.set_title('Comandos Favoritos', color='white', fontsize=12)
        else: ax2.text(0.5, 0.5, "Esperando data", ha='center', color='gray')
        plt.tight_layout()
        plt.savefig(buf, format='png', facecolor=bg_color)
        buf.seek(0)
        plt.close()
        cur.close()
        conn.close()
        return buf
    except Exception: return None

# --- GRÁFICO VERTICAL ---
def generate_public_price_chart():
    # (Código V44 - Se mantiene igual)
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price FROM daily_stats ORDER BY date DESC LIMIT 7")
        data = cur.fetchall()
        today_date = datetime.now(TIMEZONE).date()
        current_binance = MARKET_DATA["price"]
        current_bcv = MARKET_DATA["bcv"]["usd"] if MARKET_DATA["bcv"] else 0
        has_today = any(d[0] == today_date for d in data)
        if not has_today and current_binance: data.insert(0, (today_date, current_binance, current_bcv))
        data.sort(key=lambda x: x[0]) 
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        prices_bcv = [d[2] if d[2] > 0 else None for d in data]
        if not prices_bin: return None
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(6, 8)) 
        bg_color = '#1e1e1e'
        fig.patch.set_facecolor(bg_color); ax.set_facecolor(bg_color)
        ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=4, label="Binance")
        ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, linestyle='--', label="BCV")
        ax.set_title('TASA BINANCE VZLA', color='#F3BA2F', fontsize=18, fontweight='bold', pad=25)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=2, frameon=False)
        for i, price in enumerate(prices_bin):
            ax.annotate(f"{price:.2f}", (dates[i], prices_bin[i]), textcoords="offset points", xytext=(0,15), ha='center', color='white', fontsize=11, fontweight='bold')
        for i, price in enumerate(prices_bcv):
            if price: ax.annotate(f"{price:.2f}", (dates[i], prices_bcv[i]), textcoords="offset points", xytext=(0,-20), ha='center', color='#2979FF', fontsize=10, fontweight='bold')
        fig.text(0.5, 0.5, '@tasabinance_bot', fontsize=28, color='white', ha='center', va='center', alpha=0.08, rotation=45, fontweight='bold')
        plt.tight_layout()
        plt.savefig(buf, format='png', facecolor=bg_color, dpi=100)
        buf.seek(0); plt.close(); cur.close(); conn.close()
        return buf
    except Exception: return None

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
def add_alert(user_id, target_price, condition):
    if not DATABASE_URL: return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM alerts WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]
        if count >= 3:
            cur.close()
            conn.close()
            return False
        cur.execute("INSERT INTO alerts (user_id, target_price, condition) VALUES (%s, %s, %s)", 
                    (user_id, target_price, condition))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception: return False

def get_triggered_alerts(current_price):
    if not DATABASE_URL: return []
    triggered = []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, target_price FROM alerts WHERE condition = 'ABOVE' AND %s >= target_price", (current_price,))
        above = cur.fetchall()
        cur.execute("SELECT id, user_id, target_price FROM alerts WHERE condition = 'BELOW' AND %s <= target_price", (current_price,))
        below = cur.fetchall()
        triggered = above + below
        if triggered:
            ids = tuple([t[0] for t in triggered])
            cur.execute(f"DELETE FROM alerts WHERE id IN {ids}")
            conn.commit()
        cur.close()
        conn.close()
    except Exception: pass
    return triggered

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

def get_sentiment_keyboard(user_id):
    if has_user_voted(user_id):
        up, down = get_vote_results()
        share_text = quote(f"🔥 Dólar en {MARKET_DATA['price']:.2f} Bs. Revisa la tasa real aquí:")
        share_url = f"https://t.me/share/url?url=https://t.me/tasabinance_bot&text={share_text}"
        return [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')], [InlineKeyboardButton("📤 Compartir con Amigos", url=share_url)]]
    else:
        return [[InlineKeyboardButton("🚀 Subirá", callback_data='vote_up'), InlineKeyboardButton("📉 Bajará", callback_data='vote_down')], [InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]

def build_price_message(binance, bcv_data, time_str, user_id=None, requests_count=0):
    paypal = binance * 0.90
    amazon = binance * 0.75
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n\n"
    if bcv_data:
        if bcv_data.get('usd'):
            text += f"🏛️ <b>BCV (Dólar):</b> {bcv_data['usd']:,.2f} Bs\n"
            brecha = ((binance - bcv_data['usd']) / bcv_data['usd']) * 100
            emoji_brecha = "🔴" if brecha >= 20 else "🟠" if brecha >= 10 else "🟢"
            text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
        if bcv_data.get('eur'): text += f"🇪🇺 <b>BCV (Euro):</b> {bcv_data['eur']:,.2f} Bs\n"
        text += "\n"
    else: text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"
    text += f"{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {paypal:,.2f} Bs\n{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {amazon:,.2f} Bs\n\n{EMOJI_STORE} <i>Actualizado: {time_str}</i>\n"
    if requests_count > 100: text += f"👁 <b>{requests_count:,}</b> consultas hoy\n\n"
    else: text += "\n"
    if user_id and has_user_voted(user_id):
        up, down = get_vote_results()
        total = up + down
        if total > 0:
            up_pct = int((up / total) * 100)
            down_pct = int((down / total) * 100)
            text += f"🗣️ <b>¿Qué dice la comunidad?</b>\n🚀 {up_pct}% <b>Alcista</b> | 📉 {down_pct}% <b>Bajista</b>\n\n"
    elif user_id: text += "🗣️ <b>¿Qué dice la comunidad?</b> 👇\n\n"
    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    return text

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    referrer_id = None
    if context.args:
        try: referrer_id = int(context.args[0])
        except ValueError: referrer_id = None
    await asyncio.to_thread(track_user, update.effective_user, referrer_id)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/start")
    mensaje = (
        f"👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        f"Soy tu asistente financiero conectado a {EMOJI_BINANCE} <b>Binance P2P</b> y al <b>BCV</b>.\n\n"
        f"⚡ <b>Características:</b>\n"
        f"• <b>Confianza:</b> Solo monitoreamos comerciantes verificados.\n"
        f"• <b>Completo:</b> Tasa Paralela, Oficial, PayPal y Amazon.\n"
        f"• <b>Velocidad:</b> Actualizado cada 2 min.\n\n"
        f"🛠 <b>HERRAMIENTAS:</b>\n\n"
        f"{EMOJI_STATS} <b>/precio</b> → Ver tabla de tasas.\n"
        f"{EMOJI_STATS} <b>/grafico</b> → Tendencia Semanal (Promedio).\n"
        f"🧠 <b>/ia</b> → Predicción de Tendencia.\n"
        f"{EMOJI_ALERTA} <b>/alerta</b> → Avísame si sube o baja.\n"
        f"🎁 <b>/referidos</b> → ¡Invita y Gana!\n\n"
        f"🧮 <b>CALCULADORA (Toca abajo):</b>\n"
        f"• <b>/usdt</b> → Dólares a Bs.\n"
        f"• <b>/bs</b> → Bs a Dólares."
    )
    keyboard = [[InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)], [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]]
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/grafico")
    global GRAPH_CACHE
    today_str = datetime.now(TIMEZONE).date().isoformat()
    if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
        try:
            await update.message.reply_photo(photo=GRAPH_CACHE["photo_id"], caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 <i>¡Compártelo en tus estados!</i>\n\n@tasabinance_bot", parse_mode=ParseMode.HTML)
            return
        except Exception: GRAPH_CACHE["photo_id"] = None
    await update.message.reply_chat_action("upload_photo")
    img_buf = await asyncio.to_thread(generate_public_price_chart)
    if img_buf:
        msg = await update.message.reply_photo(photo=img_buf, caption="📉 <b>Promedio Diario (Semanal)</b>\n\n<i>Precio promedio ponderado del día.</i>", parse_mode=ParseMode.HTML)
        if msg.photo:
            GRAPH_CACHE["date"] = today_str
            GRAPH_CACHE["photo_id"] = msg.photo[-1].file_id
    else:
        await update.message.reply_text("📉 Recopilando datos históricos. Vuelve pronto.")

async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/referidos")
    count, rank, top_3 = await asyncio.to_thread(get_referral_stats, user_id)
    ranking_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(top_3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        clean_name = name.split()[0] if name else "Usuario"
        ranking_text += f"{medal} <b>{clean_name}</b> — {score} refs\n"
    invite_link = f"https://t.me/{context.bot.username}?start={user_id}"
    share_msg = quote(f"🎁 ¡Gana 10 USDT con este bot! Entra aquí y participa:\n\n{invite_link}")
    share_url = f"https://t.me/share/url?url={share_msg}"
    keyboard = [[InlineKeyboardButton("📤 Comparte y Gana $10", url=share_url)]]
    text = (f"🎁 <b>PROGRAMA DE REFERIDOS (PREMIOS USDT)</b>\n\n¡Gana dinero real invitando a tus amigos!\n📅 <b>Corte y Pago:</b> Día 30 de cada mes.\n\n🏆 <b>PREMIOS MENSUALES:</b>\n🥇 1er Lugar: <b>$10 USDT</b>\n🥈 2do Lugar: <b>$5 USDT</b>\n🥉 3er Lugar: <b>$5 USDT</b>\n\n👤 <b>TUS ESTADÍSTICAS:</b>\n👥 Invitados: <b>{count}</b>\n🏆 Tu Rango: <b>#{rank}</b>\n\n🔗 <b>TU ENLACE ÚNICO:</b>\n<code>{invite_link}</code>\n<i>(Toca para copiar y compartir)</i>\n\n📊 <b>TOP 3 LÍDERES:</b>\n{ranking_text}\n👇 <b>¡Compártelo ahora!</b>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard))

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
        keyboard = get_sentiment_keyboard(user_id)
        if random.random() < 0.2:
            days, refs = await asyncio.to_thread(get_user_loyalty, user_id)
            if days > 3 and refs == 0: text += "\n\n🎁 <i>¡Gana $10 USDT invitando amigos! Toca /referidos</i>"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    query = update.callback_query
    data = query.data
    if data in ['vote_up', 'vote_down']:
        vote_type = 'UP' if data == 'vote_up' else 'DOWN'
        if await asyncio.to_thread(cast_vote, user_id, vote_type):
            await asyncio.to_thread(log_activity, user_id, f"vote_{vote_type.lower()}")
            await query.answer("✅ ¡Voto registrado!")
        else: await query.answer("⚠️ Ya votaste hoy.")
        data = 'refresh_price'
    if data == 'refresh_price':
        await asyncio.to_thread(log_activity, user_id, "btn_refresh")
        binance = MARKET_DATA["price"]
        bcv = MARKET_DATA["bcv"]
        time_str = MARKET_DATA["last_updated"]
        if binance:
            req_count = await asyncio.to_thread(get_daily_requests_count)
            text = build_price_message(binance, bcv, time_str, user_id, req_count)
            keyboard = get_sentiment_keyboard(user_id)
            try: await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except BadRequest: pass
            except Exception as e: logging.error(f"Error edit: {e}")
    try: await query.answer()
    except: pass

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

async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/alerta")
    if context.args:
        try:
            target = float(context.args[0].replace(',', '.'))
            return await process_alert_logic(update, target)
        except ValueError:
            await update.message.reply_text("🔢 Error: Ingresa un número válido.", parse_mode=ParseMode.HTML)
            return ConversationHandler.END
    await update.message.reply_text(f"{EMOJI_ALERTA} <b>CONFIGURAR ALERTA</b>\n\n¿A qué precio quieres que te avise?\n\n<i>Escribe el monto abajo (Ej: 600):</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_PRECIO_ALERTA

async def process_alert_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = float(update.message.text.replace(',', '.'))
        await process_alert_logic(update, target)
    except ValueError:
        await update.message.reply_text("🔢 Por favor ingresa solo números válidos.", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def process_alert_logic(update: Update, target):
    current_price = MARKET_DATA["price"]
    if not current_price:
        await update.message.reply_text("⚠️ Esperando actualización de precios... intenta en 1 minuto.")
        return
    if target > current_price:
        condition = "ABOVE"
        msg = f"📈 <b>ALERTA DE SUBIDA</b>\n\nTe avisaré cuando el dólar <b>SUPERE</b> los {target} Bs."
    elif target < current_price:
        condition = "BELOW"
        msg = f"📉 <b>ALERTA DE BAJADA</b>\n\nTe avisaré cuando el dólar <b>BAJE</b> de {target} Bs."
    else:
        await update.message.reply_text(f"⚠️ El precio actual ya es {current_price}. Define un valor distinto.")
        return
    success = await asyncio.to_thread(add_alert, update.effective_user.id, target, condition)
    if success:
        await update.message.reply_text(f"✅ {msg}", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("⛔ <b>Límite alcanzado</b>\nSolo puedes tener 3 alertas activas al mismo tiempo.", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def calculate_conversion(update: Update, text_amount, currency_type):
    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas...")
        return ConversationHandler.END
    try:
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        amount = float(clean_text.replace(',', '.'))
        await asyncio.to_thread(log_calc, update.effective_user.id, amount, currency_type, 0)
        if currency_type == "USDT":
            total = amount * rate
            await update.message.reply_text(f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>", parse_mode=ParseMode.HTML)
        else: 
            total = amount / rate
            await update.message.reply_text(f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")
    return ConversationHandler.END

async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    if context.args: return await calculate_conversion(update, context.args[0], "USDT")
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Cuántos Dólares?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    if context.args: return await calculate_conversion(update, context.args[0], "BS")
    await update.message.reply_text("🇻🇪 <b>Calculadora Bolívares:</b>\n\n¿Cuántos Bs?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_BS

async def process_usdt_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "USDT")
    return ConversationHandler.END

async def process_bs_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "BS")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

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
    
    conv_usdt = ConversationHandler(
        entry_points=[CommandHandler("usdt", start_usdt_calc)],
        states={ESPERANDO_INPUT_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_usdt_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    conv_bs = ConversationHandler(
        entry_points=[CommandHandler("bs", start_bs_calc)],
        states={ESPERANDO_INPUT_BS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bs_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    conv_alert = ConversationHandler(
        entry_points=[CommandHandler("alerta", start_alert)],
        states={ESPERANDO_PRECIO_ALERTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_alert_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    app.add_handler(CommandHandler("start", start))
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
