import os
import logging
import requests
import psycopg2 
import asyncio
import io 
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup 
import urllib3
from datetime import datetime, time, timedelta
import pytz 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler,     
    filters,            
    ConversationHandler,
    ContextTypes
)

# Silenciar advertencias SSL del BCV
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Configurar Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 533888411 

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 
FILTER_MIN_USD = 20

# 🔴 TUS ENLACES 🔴
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

# --- ESTADOS CONVERSACIÓN ---
ESPERANDO_INPUT_USDT, ESPERANDO_INPUT_BS, ESPERANDO_PRECIO_ALERTA = range(3)

# --- EMOJIS PREMIUM ---
EMOJI_BINANCE = '<tg-emoji emoji-id="5269277053684819725">🔶</tg-emoji>'
EMOJI_PAYPAL  = '<tg-emoji emoji-id="5364111181415996352">🅿️</tg-emoji>'
EMOJI_AMAZON  = '🎁' 
EMOJI_SUBIDA  = '<tg-emoji emoji-id="5244837092042750681">📈</tg-emoji>'
EMOJI_BAJADA  = '<tg-emoji emoji-id="5246762912428603768">📉</tg-emoji>'
EMOJI_STATS   = '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji>'
EMOJI_STORE   = '<tg-emoji emoji-id="5895288113537748673">🏪</tg-emoji>'
EMOJI_ALERTA  = '🔔'

# --- MEMORIA (Caché) ---
MARKET_DATA = {
    "price": None, 
    "bcv": {'usd': None, 'eur': None},   
    "last_updated": "Esperando...",
    "history": [] 
}
GRAPH_CACHE = {"date": None, "photo_id": None}

# ==============================================================================
#  BASE DE DATOS
# ==============================================================================
def init_db():
    if not DATABASE_URL:
        logging.warning("⚠️ Sin DATABASE_URL. Usando RAM temporal.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Tablas
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                first_name TEXT,
                referral_count INTEGER DEFAULT 0,
                referred_by BIGINT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                target_price FLOAT,
                condition TEXT, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                command TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                price_sum FLOAT DEFAULT 0,
                count INTEGER DEFAULT 0,
                bcv_price FLOAT DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_ticks (
                id SERIAL PRIMARY KEY,
                price_binance FLOAT,
                price_bcv FLOAT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calc_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount FLOAT,
                currency_type TEXT,
                result FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        migrate_db()
    except Exception as e:
        logging.error(f"❌ Error BD Init: {e}")

def migrate_db():
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
            cur.execute("ALTER TABLE daily_stats ADD COLUMN IF NOT EXISTS bcv_price FLOAT DEFAULT 0;")
            conn.commit()
        except Exception: conn.rollback()
        finally:
            cur.close()
            conn.close()
    except Exception: pass

def track_user(user, referrer_id=None):
    if not DATABASE_URL: return 
    user_id = user.id
    first_name = user.first_name[:50] if user.first_name else "Usuario"
    now = datetime.now()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        exists = cur.fetchone()
        if not exists:
            valid_referrer = False
            if referrer_id and referrer_id != user_id:
                cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
                if cur.fetchone(): valid_referrer = True
            final_referrer = referrer_id if valid_referrer else None
            cur.execute("""
                INSERT INTO users (user_id, first_name, referred_by, last_active) 
                VALUES (%s, %s, %s, %s)
            """, (user_id, first_name, final_referrer, now))
            if valid_referrer:
                cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (final_referrer,))
        else:
            cur.execute("UPDATE users SET first_name = %s, last_active = %s WHERE user_id = %s", (first_name, now, user_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error track_user: {e}")

def log_activity(user_id, command):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error log_activity: {e}")

def log_calc(user_id, amount, currency, result):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", (user_id, amount, currency, result))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error log_calc: {e}")

# ==============================================================================
#  ANALÍTICAS & GRÁFICOS
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

def generate_public_price_chart():
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price 
            FROM daily_stats ORDER BY date DESC LIMIT 7
        """)
        data = cur.fetchall()
        today_date = datetime.now(TIMEZONE).date()
        current_binance = MARKET_DATA["price"]
        current_bcv = MARKET_DATA["bcv"]["usd"] if MARKET_DATA["bcv"] else 0
        has_today = any(d[0] == today_date for d in data)
        if not has_today and current_binance:
             data.insert(0, (today_date, current_binance, current_bcv))
        data.sort(key=lambda x: x[0]) 
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        prices_bcv = [d[2] if d[2] > 0 else None for d in data]
        if not prices_bin: return None
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(8, 5))
        bg_color = '#1e1e1e'
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        
        # Fix Bug Anterior: usar prices_bin[i]
        line1, = ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=3, markersize=8, label="Binance")
        line2, = ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, markersize=6, linestyle='--', label="BCV")
        
        ax.set_title('Tendencia Semanal (Binance vs BCV)', color='white', fontsize=14, fontweight='bold', pad=20)
        ax.grid(color='#333333', linestyle='--', linewidth=0.5)
        ax.legend(loc="upper left") 
        for i, price in enumerate(prices_bin):
            ax.annotate(f"{price:.2f}", (dates[i], prices_bin[i]), textcoords="offset points", xytext=(0,10), ha='center', color='white', fontsize=9)
        fig.text(0.5, 0.5, 'Telegram: @tasabinance_bot', fontsize=20, color='white', ha='center', va='center', alpha=0.1, rotation=30)
        fig.text(0.95, 0.05, '@tasabinance_bot', fontsize=10, color='gray', ha='right', va='bottom', alpha=0.5)
        plt.tight_layout()
        plt.savefig(buf, format='png', facecolor=bg_color)
        buf.seek(0)
        plt.close()
        cur.close()
        conn.close()
        return buf
    except Exception as e:
        logging.error(f"Error Public Chart: {e}")
        return None

def get_detailed_report_text():
    if not DATABASE_URL: return "⚠️ Error DB"
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE")
        new_today = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '24 HOURS'")
        active_24h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
        requests_today = cur.fetchone()[0]
        
        # 🔥 NUEVO: Contar Alertas Activas 🔥
        cur.execute("SELECT COUNT(*) FROM alerts")
        active_alerts = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        return (
            f"📊 <b>REPORTE EJECUTIVO</b>\n\n"
            f"👥 <b>Total Histórico:</b> {total}\n"
            f"📈 <b>Nuevos Hoy:</b> +{new_today}\n"
            f"🔥 <b>Activos (24h):</b> {active_24h}\n"
            f"🔔 <b>Alertas Activas:</b> {active_alerts}\n"
            f"📥 <b>Consultas Hoy:</b> {requests_today}\n\n"
            f"<i>Sistema Operativo V27.</i> ✅"
        )
    except Exception: return "Error."

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
        cur.execute("SELECT user_id FROM users")
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

def save_mining_data(binance, bcv_val):
    if not DATABASE_URL: return
    try:
        today = datetime.now(TIMEZONE).date()
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO daily_stats (date, price_sum, count, bcv_price) 
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (date) DO UPDATE SET 
                price_sum = daily_stats.price_sum + %s,
                count = daily_stats.count + 1,
                bcv_price = GREATEST(daily_stats.bcv_price, %s)
        """, (today, binance, bcv_val, binance, bcv_val))
        cur.execute("INSERT INTO price_ticks (price_binance, price_bcv) VALUES (%s, %s)", (binance, bcv_val))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error mining: {e}")

# ==============================================================================
#  BACKEND PRECIOS
# ==============================================================================
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    last_known = MARKET_DATA["price"] if MARKET_DATA["price"] else 600
    dynamic_amount = int(last_known * FILTER_MIN_USD)
    payload = {
        "page": 1, "rows": 3, 
        "payTypes": ["PagoMovil", "Banesco", "Mercantil", "Provincial"], 
        "publisherType": "merchant", 
        "transAmount": str(dynamic_amount), 
        "asset": "USDT", "fiat": "VES", "tradeType": "BUY"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        if not data.get("data"):
            del payload["publisherType"]
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()
        if not data.get("data"):
            payload["payTypes"] = ["PagoMovil"]
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()
        if not data.get("data"):
            del payload["transAmount"]
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()
        prices = [float(item["adv"]["price"]) for item in data["data"]]
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        logging.error(f"Error Binance: {e}")
        return None

def fetch_bcv_price():
    url = "http://www.bcv.org.ve/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    rates = {'usd': None, 'eur': None}
    try:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_div = soup.find('div', id='dolar')
            if dolar_div: rates['usd'] = float(dolar_div.find('strong').text.strip().replace(',', '.'))
            euro_div = soup.find('div', id='euro')
            if euro_div: rates['eur'] = float(euro_div.find('strong').text.strip().replace(',', '.'))
            return rates if (rates['usd'] or rates['eur']) else None
    except Exception: return None
    return None

async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_binance = fetch_binance_price()
    new_bcv = fetch_bcv_price()
    
    if new_binance:
        MARKET_DATA["price"] = new_binance
        MARKET_DATA["history"].append(new_binance)
        if len(MARKET_DATA["history"]) > 30: MARKET_DATA["history"].pop(0)
        alerts = get_triggered_alerts(new_binance)
        if alerts:
            for alert in alerts:
                try:
                    await context.bot.send_message(chat_id=alert[1], text=f"{EMOJI_ALERTA} <b>¡ALERTA!</b>\nDólar en meta: <b>{alert[2]:,.2f} Bs</b>\nActual: {new_binance:,.2f} Bs", parse_mode=ParseMode.HTML)
                except Exception: pass
        
        bcv_val = new_bcv['usd'] if (new_bcv and new_bcv.get('usd')) else 0
        save_mining_data(new_binance, bcv_val)

    if new_bcv: MARKET_DATA["bcv"] = new_bcv
    if new_binance or new_bcv:
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
        logging.info(f"🔄 Actualizado - Bin: {new_binance}")

# --- FUNCIÓN GENERADORA DEL MENSAJE + MARCA DE AGUA TEXTUAL ---
def build_price_message(binance, bcv_data, time_str):
    paypal = binance * 0.90
    amazon = binance * 0.75
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n"
    text += f"{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n\n"
    
    if bcv_data:
        if bcv_data.get('usd'):
            usd_bcv = bcv_data['usd']
            text += f"🏛️ <b>BCV (Dólar):</b> {usd_bcv:,.2f} Bs\n"
            brecha = ((binance - usd_bcv) / usd_bcv) * 100
            if brecha >= 20: emoji_brecha = "🔴"
            elif brecha >= 10: emoji_brecha = "🟠"
            else: emoji_brecha = "🟢"
            text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
        if bcv_data.get('eur'):
            text += f"🇪🇺 <b>BCV (Euro):</b> {bcv_data['eur']:,.2f} Bs\n"
        text += "\n"
    else:
        text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"
        
    text += f"{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {paypal:,.2f} Bs\n"
    text += f"{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {amazon:,.2f} Bs\n\n"
    text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>\n\n"
    
    # 🔥 AQUI ESTÁ EL CAMBIO DE MARKETING 🔥
    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    return text

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    binance = MARKET_DATA["price"]
    bcv = MARKET_DATA["bcv"]
    if not binance: binance = fetch_binance_price()
    if not bcv: bcv = fetch_bcv_price()
    if not binance: return

    time_str = datetime.now(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")
    hour = datetime.now(TIMEZONE).hour
    header = "☀️ <b>¡Buenos días! Así abre el mercado:</b>" if hour < 12 else "🌤 <b>Reporte de la Tarde:</b>"

    body = build_price_message(binance, bcv, time_str)
    body = body.replace(f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n", "")
    
    text = f"{header}\n\n{body}"

    keyboard = [[InlineKeyboardButton("🔄 Ver en tiempo real", callback_data='refresh_price')]]
    users = get_all_users_ids()
    batch_size = 25
    for i in range(0, len(users), batch_size):
        batch = users[i:i + batch_size]
        for user_id in batch:
            try: await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception: pass
        await asyncio.sleep(1)

# ==============================================================================
#  COMANDOS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    referrer_id = None
    if context.args:
        try: referrer_id = int(context.args[0])
        except ValueError: referrer_id = None
    
    track_user(update.effective_user, referrer_id)
    log_activity(update.effective_user.id, "/start")
    
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
    keyboard = [
        [InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)],
        [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]
    ]
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(update.effective_user)
    log_activity(user_id, "/grafico")
    
    global GRAPH_CACHE
    today_str = datetime.now(TIMEZONE).date().isoformat()
    
    if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
        try:
            await update.message.reply_photo(photo=GRAPH_CACHE["photo_id"], caption="📉 <b>Promedio Diario (Semanal)</b>", parse_mode=ParseMode.HTML)
            return
        except Exception: GRAPH_CACHE["photo_id"] = None
            
    await update.message.reply_chat_action("upload_photo")
    img_buf = generate_public_price_chart()
    
    if img_buf:
        msg = await update.message.reply_photo(photo=img_buf, caption="📉 <b>Promedio Diario (Semanal)</b>\n\n<i>Precio promedio ponderado del día.</i>", parse_mode=ParseMode.HTML)
        if msg.photo:
            GRAPH_CACHE["date"] = today_str
            GRAPH_CACHE["photo_id"] = msg.photo[-1].file_id
    else:
        await update.message.reply_text("📉 Recopilando datos históricos. Vuelve pronto.")

async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(update.effective_user)
    log_activity(user_id, "/referidos")
    count, rank, top_3 = get_referral_stats(user_id)
    ranking_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(top_3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        clean_name = name.split()[0] if name else "Usuario"
        ranking_text += f"{medal} <b>{clean_name}</b> — {score} refs\n"
    invite_link = f"https://t.me/{context.bot.username}?start={user_id}"
    text = (f"🎁 <b>PROGRAMA DE REFERIDOS (PREMIOS USDT)</b>\n\n¡Gana dinero real invitando a tus amigos!\n📅 <b>Corte y Pago:</b> Día 30 de cada mes.\n\n🏆 <b>PREMIOS MENSUALES:</b>\n🥇 1er Lugar: <b>$10 USDT</b>\n🥈 2do Lugar: <b>$5 USDT</b>\n🥉 3er Lugar: <b>$5 USDT</b>\n\n👤 <b>TUS ESTADÍSTICAS:</b>\n👥 Invitados: <b>{count}</b>\n🏆 Tu Rango: <b>#{rank}</b>\n\n🔗 <b>TU ENLACE ÚNICO:</b>\n<code>{invite_link}</code>\n<i>(Toca para copiar y compartir)</i>\n\n📊 <b>TOP 3 LÍDERES:</b>\n{ranking_text}\n👇 <b>¡Compártelo ahora!</b>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(update.effective_user)
    log_activity(user_id, "/precio")
    binance = MARKET_DATA["price"]
    bcv = MARKET_DATA["bcv"]
    time_str = MARKET_DATA["last_updated"]
    
    if binance:
        text = build_price_message(binance, bcv, time_str)
        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(update.effective_user)
    if update.callback_query.data == 'refresh_price': log_activity(user_id, "btn_refresh")
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_price':
        binance = MARKET_DATA["price"]
        bcv = MARKET_DATA["bcv"]
        time_str = MARKET_DATA["last_updated"]
        if binance:
            text = build_price_message(binance, bcv, time_str)
            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
                await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except BadRequest: pass
            except Exception as e: logging.error(f"Error edit: {e}")

async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user)
    log_activity(update.effective_user.id, "/ia")
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
    chart = generate_stats_chart() 
    report = get_detailed_report_text()
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
    users = get_all_users_ids()
    if not users:
        await update.message.reply_text("⚠️ No hay usuarios.")
        return
    await update.message.reply_text(f"🚀 Iniciando difusión rápida a {len(users)} usuarios...")
    enviados = 0
    fallidos = 0
    batch_size = 25
    for i in range(0, len(users), batch_size):
        batch = users[i:i + batch_size]
        for user_id in batch:
            try:
                await context.bot.send_message(chat_id=user_id, text=mensaje_final, parse_mode=ParseMode.HTML)
                enviados += 1
            except Exception: fallidos += 1
        await asyncio.sleep(1)
    await update.message.reply_text(f"✅ <b>Difusión Completada</b>\n\n📨 Enviados: {enviados}\n❌ Fallidos: {fallidos}", parse_mode=ParseMode.HTML)

async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user)
    log_activity(update.effective_user.id, "/alerta")
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
    success = add_alert(update.effective_user.id, target, condition)
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
        log_calc(update.effective_user.id, amount, currency_type, 0)
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
    track_user(update.effective_user)
    log_activity(update.effective_user.id, "/calc")
    if context.args: return await calculate_conversion(update, context.args[0], "USDT")
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Cuántos Dólares?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user)
    log_activity(update.effective_user.id, "/calc")
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

if __name__ == "__main__":
    init_db()
    if not TOKEN: exit(1)
    
    app = ApplicationBuilder().token(TOKEN).build()
    
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
    app.add_handler(CallbackQueryHandler(button_handler))
    
    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)
        app.job_queue.run_daily(send_daily_report, time=time(hour=9, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
        app.job_queue.run_daily(send_daily_report, time=time(hour=13, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
    
    print("Bot V27 (Marketing + Stats + Todo V26) iniciando...")
    app.run_polling()
