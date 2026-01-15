import os
import logging
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
from datetime import datetime, time, timedelta
import pytz 
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

# Configuración Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

# Configuración
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 
FILTER_MIN_USD = 20
MAX_HISTORY_POINTS = 200

# Lista Anti-Ban
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

# Estados Conversación
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

# Memoria
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
        
        # Crear tablas si no existen
        tables = [
            """CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, first_name TEXT, referral_count INTEGER DEFAULT 0, referred_by BIGINT, last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active', source TEXT)""",
            """CREATE TABLE IF NOT EXISTS alerts (id SERIAL PRIMARY KEY, user_id BIGINT, target_price FLOAT, condition TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS activity_logs (id SERIAL PRIMARY KEY, user_id BIGINT, command TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS daily_stats (date DATE PRIMARY KEY, price_sum FLOAT DEFAULT 0, count INTEGER DEFAULT 0, bcv_price FLOAT DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS price_ticks (id SERIAL PRIMARY KEY, price_binance FLOAT, price_bcv FLOAT, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, price_sell FLOAT, spread_pct FLOAT, price_bcv_eur FLOAT)""",
            """CREATE TABLE IF NOT EXISTS calc_logs (id SERIAL PRIMARY KEY, user_id BIGINT, amount FLOAT, currency_type TEXT, result FLOAT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS daily_votes (user_id BIGINT, vote_date DATE, vote_type TEXT, PRIMARY KEY (user_id, vote_date))""",
            """CREATE TABLE IF NOT EXISTS broadcast_queue (id SERIAL PRIMARY KEY, message TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS arbitrage_data (id SERIAL PRIMARY KEY, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, buy_pm FLOAT, sell_pm FLOAT, buy_banesco FLOAT, buy_mercantil FLOAT, buy_provincial FLOAT, spread_pct FLOAT)"""
        ]
        for t in tables:
            cur.execute(t)
            
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
        # Migraciones silenciosas
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT;")
            cur.execute("ALTER TABLE daily_stats ADD COLUMN IF NOT EXISTS bcv_price FLOAT DEFAULT 0;")
            cur.execute("ALTER TABLE price_ticks ADD COLUMN IF NOT EXISTS price_sell FLOAT;")
            cur.execute("ALTER TABLE price_ticks ADD COLUMN IF NOT EXISTS spread_pct FLOAT;")
            cur.execute("ALTER TABLE price_ticks ADD COLUMN IF NOT EXISTS price_bcv_eur FLOAT;")
            cur.execute("ALTER TABLE arbitrage_data ADD COLUMN IF NOT EXISTS spread_pct FLOAT;")
            conn.commit()
        except Exception: conn.rollback()
        finally:
            cur.close()
            conn.close()
    except Exception: pass

# --- RECUPERAR ESTADO ---
def recover_last_state():
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT price_binance, price_bcv, price_bcv_eur, recorded_at FROM price_ticks ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        
        if row:
            binance_db, bcv_db, bcv_eur_db, date_db = row
            if binance_db:
                MARKET_DATA["price"] = binance_db
                MARKET_DATA["history"].append(binance_db)
            MARKET_DATA["bcv"] = {'usd': bcv_db, 'eur': bcv_eur_db} 
            fecha_bonita = date_db.astimezone(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")
            MARKET_DATA["last_updated"] = fecha_bonita
            logging.info(f"💾 ESTADO RECUPERADO: Bin={binance_db} | USD={bcv_db}")
        
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error recuperando estado: {e}")

# --- DB HELPERS ---
def track_user(user, referrer_id=None, source=None):
    if not DATABASE_URL: return 
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user.id,))
        if not cur.fetchone():
            valid_ref = referrer_id if (referrer_id and referrer_id != user.id) else None
            cur.execute("INSERT INTO users (user_id, first_name, referred_by, last_active, status, source) VALUES (%s, %s, %s, %s, 'active', %s)", 
                        (user.id, user.first_name, valid_ref, datetime.now(), source))
            if valid_ref: cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s", (valid_ref,))
        else:
            cur.execute("UPDATE users SET first_name = %s, last_active = %s, status = 'active' WHERE user_id = %s", (user.first_name, datetime.now(), user.id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception: pass

async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.my_chat_member or not DATABASE_URL: return
    uid = update.my_chat_member.from_user.id
    status = 'blocked' if update.my_chat_member.new_chat_member.status in [ChatMember.KICKED, ChatMember.LEFT] else 'active'
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE users SET status = %s WHERE user_id = %s", (status, uid))
        conn.commit()
        cur.close()
        conn.close()
    except Exception: pass

def log_activity(user_id, command):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO activity_logs (user_id, command) VALUES (%s, %s)", (user_id, command))
        conn.commit()
        cur.close()
        conn.close()
    except Exception: pass

def log_calc(user_id, amount, currency, result):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO calc_logs (user_id, amount, currency_type, result) VALUES (%s, %s, %s, %s)", (user_id, amount, currency, result))
        conn.commit()
        cur.close()
        conn.close()
    except Exception: pass

def get_user_loyalty(user_id):
    if not DATABASE_URL: return (0, 0)
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT joined_at, referral_count FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        cur.close()
        conn.close()
        if res: return ((datetime.now() - res[0]).days, res[1])
        return (0, 0)
    except Exception: return (0, 0)

def get_daily_requests_count():
    if not DATABASE_URL: return 0
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at >= CURRENT_DATE")
        cnt = cur.fetchone()[0]
        cur.close()
        conn.close()
        return cnt
    except Exception: return 0

def get_yesterday_close():
    if not DATABASE_URL: return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT (price_sum / NULLIF(count, 0)) FROM daily_stats WHERE date = CURRENT_DATE - 1")
        res = cur.fetchone()
        cur.close()
        conn.close()
        return res[0] if res else None
    except Exception: return None

def cast_vote(user_id, vote_type):
    if not DATABASE_URL: return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO daily_votes (user_id, vote_date, vote_type) VALUES (%s, %s, %s) ON CONFLICT (user_id, vote_date) DO NOTHING", (user_id, datetime.now(TIMEZONE).date(), vote_type))
        rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return rows > 0
    except Exception: return False

def get_vote_results():
    if not DATABASE_URL: return (0, 0)
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT vote_type, COUNT(*) FROM daily_votes WHERE vote_date = %s GROUP BY vote_type", (datetime.now(TIMEZONE).date(),))
        res = dict(cur.fetchall())
        cur.close()
        conn.close()
        return (res.get('UP', 0), res.get('DOWN', 0))
    except Exception: return (0, 0)

def has_user_voted(user_id):
    if not DATABASE_URL: return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM daily_votes WHERE user_id = %s AND vote_date = %s", (user_id, datetime.now(TIMEZONE).date()))
        voted = cur.fetchone() is not None
        cur.close()
        conn.close()
        return voted
    except Exception: return False

def get_referral_stats(user_id):
    if not DATABASE_URL: return (0, 0, [])
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT referral_count FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        cnt = res[0] if res else 0
        cur.execute("SELECT COUNT(*) + 1 FROM users WHERE referral_count > %s", (cnt,))
        rank = cur.fetchone()[0]
        cur.execute("SELECT first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 3")
        top3 = cur.fetchall()
        cur.close()
        conn.close()
        return (cnt, rank, top3)
    except Exception: return (0, 0, [])

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
        if cur.fetchone()[0] >= 3: 
            cur.close()
            conn.close()
            return False
        cur.execute("INSERT INTO alerts (user_id, target_price, condition) VALUES (%s, %s, %s)", (user_id, target_price, condition))
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
        triggered.extend(cur.fetchall())
        cur.execute("SELECT id, user_id, target_price FROM alerts WHERE condition = 'BELOW' AND %s <= target_price", (current_price,))
        triggered.extend(cur.fetchall())
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
        spread = 0
        if binance and binance_sell: spread = ((binance - binance_sell) / binance) * 100
        cur.execute("""INSERT INTO daily_stats (date, price_sum, count, bcv_price) VALUES (%s, %s, 1, %s) ON CONFLICT (date) DO UPDATE SET price_sum = daily_stats.price_sum + %s, count = daily_stats.count + 1, bcv_price = GREATEST(daily_stats.bcv_price, %s)""", (today, binance, bcv_val, binance, bcv_val))
        cur.execute("INSERT INTO arbitrage_data (buy_pm, sell_pm, buy_banesco, buy_mercantil, buy_provincial, spread_pct) VALUES (%s, %s, 0, 0, 0, %s)", (binance, binance_sell, spread))
        eur_val = MARKET_DATA["bcv"].get("eur") if MARKET_DATA["bcv"] else 0
        cur.execute("INSERT INTO price_ticks (price_binance, price_sell, price_bcv, price_bcv_eur, spread_pct) VALUES (%s, %s, %s, %s, %s)", (binance, binance_sell, bcv_val, eur_val, spread))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: logging.error(f"Error mining: {e}")

def queue_broadcast(message):
    if not DATABASE_URL: return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO broadcast_queue (message, status) VALUES (%s, 'pending')", (message,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception: pass

# ==============================================================================
#  BACKEND PRECIOS
# ==============================================================================
def fetch_binance_price(trade_type="BUY"):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    last_known = MARKET_DATA["price"] if MARKET_DATA["price"] else 600
    dynamic_amount = int(last_known * FILTER_MIN_USD)
    payload = {"page": 1, "rows": 3, "payTypes": ["PagoMovil", "Banesco", "Mercantil", "Provincial"], "publisherType": "merchant", "transAmount": str(dynamic_amount), "asset": "USDT", "fiat": "VES", "tradeType": trade_type}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        if not data.get("data"): del payload["publisherType"]; response = requests.post(url, json=payload, headers=headers, timeout=10); data = response.json()
        if not data.get("data"): payload["payTypes"] = ["PagoMovil"]; response = requests.post(url, json=payload, headers=headers, timeout=10); data = response.json()
        if not data.get("data"): del payload["transAmount"]; response = requests.post(url, json=payload, headers=headers, timeout=10); data = response.json()
        prices = [float(item["adv"]["price"]) for item in data.get("data", [])]
        return sum(prices) / len(prices) if prices else None
    except Exception: return None

def fetch_bcv_price():
    url = "http://www.bcv.org.ve/"
    headers = {"User-Agent": "Mozilla/5.0"}
    rates = {'usd': None, 'eur': None}
    try:
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_div = soup.find('div', id='dolar'); euro_div = soup.find('div', id='euro')
            if dolar_div: rates['usd'] = float(dolar_div.find('strong').text.strip().replace(',', '.'))
            if euro_div: rates['eur'] = float(euro_div.find('strong').text.strip().replace(',', '.'))
            if rates['usd']: logging.info(f"✅ BCV ENCONTRADO: {rates['usd']} Bs")
            return rates if (rates['usd'] or rates['eur']) else None
        else: logging.error(f"❌ BCV Error HTTP: {response.status_code}"); return None
    except Exception as e: logging.error(f"❌ BCV Exception: {e}"); return None

def generate_stats_chart():
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT TO_CHAR(joined_at, 'MM-DD'), COUNT(*) FROM users WHERE joined_at >= NOW() - INTERVAL '7 DAYS' GROUP BY 1 ORDER BY 1")
        growth_data = cur.fetchall()
        cur.execute("SELECT command, COUNT(*) FROM activity_logs GROUP BY command ORDER BY 2 DESC LIMIT 5")
        cmd_data = cur.fetchall()
        plt.style.use('dark_background'); fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5)); bg_color = '#212121'; fig.patch.set_facecolor(bg_color); ax1.set_facecolor(bg_color); ax2.set_facecolor(bg_color)
        if growth_data: ax1.bar([r[0] for r in growth_data], [r[1] for r in growth_data], color='#F3BA2F')
        if cmd_data: ax2.pie([r[1] for r in cmd_data], labels=[r[0] for r in cmd_data], autopct='%1.1f%%')
        plt.tight_layout(); plt.savefig(buf, format='png', facecolor=bg_color); buf.seek(0); plt.close(); cur.close(); conn.close()
        return buf
    except Exception: return None

def generate_public_price_chart():
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price FROM daily_stats ORDER BY date DESC LIMIT 7")
        data = cur.fetchall()
        today = datetime.now(TIMEZONE).date()
        if not any(d[0] == today for d in data) and MARKET_DATA["price"]: data.insert(0, (today, MARKET_DATA["price"], MARKET_DATA["bcv"]["usd"] if MARKET_DATA["bcv"] else 0))
        data.sort(key=lambda x: x[0])
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        prices_bcv = [d[2] if d[2] > 0 else None for d in data]
        if not prices_bin: return None
        plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(6, 8)); bg_color = '#1e1e1e'; fig.patch.set_facecolor(bg_color); ax.set_facecolor(bg_color)
        ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=4); ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, linestyle='--')
        ax.set_title('TASA BINANCE VZLA', color='#F3BA2F', fontsize=18, fontweight='bold', pad=25)
        for i, p in enumerate(prices_bin): ax.annotate(f"{p:.2f}", (dates[i], p), textcoords="offset points", xytext=(0,15), ha='center', color='white', fontsize=11)
        for i, p in enumerate(prices_bcv): 
            if p: ax.annotate(f"{p:.2f}", (dates[i], p), textcoords="offset points", xytext=(0,-20), ha='center', color='#2979FF', fontsize=10)
        fig.text(0.5, 0.5, '@tasabinance_bot', fontsize=28, color='white', ha='center', va='center', alpha=0.08, rotation=45); plt.tight_layout(); plt.savefig(buf, format='png', facecolor=bg_color, dpi=100); buf.seek(0); plt.close(); cur.close(); conn.close()
        return buf
    except Exception: return None

# ==============================================================================
#  TASKS & LOGIC
# ==============================================================================
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_binance = await asyncio.to_thread(fetch_binance_price, "BUY")
    new_binance_sell = await asyncio.to_thread(fetch_binance_price, "SELL")
    new_bcv = await asyncio.to_thread(fetch_bcv_price)
    
    if new_binance:
        MARKET_DATA["price"] = new_binance
        MARKET_DATA["history"].append(new_binance)
        if len(MARKET_DATA["history"]) > 30: MARKET_DATA["history"].pop(0)
        alerts = await asyncio.to_thread(get_triggered_alerts, new_binance)
        if alerts:
            for alert in alerts:
                try: await context.bot.send_message(chat_id=alert[1], text=f"{EMOJI_ALERTA} <b>¡ALERTA!</b>\nDólar en meta: <b>{alert[2]:,.2f} Bs</b>\nActual: {new_binance:,.2f} Bs", parse_mode=ParseMode.HTML)
                except Exception: pass
        bcv_val = new_bcv['usd'] if (new_bcv and new_bcv.get('usd')) else 0
        await asyncio.to_thread(save_mining_data, new_binance, bcv_val, new_binance_sell)

    if new_bcv: MARKET_DATA["bcv"] = new_bcv
    if new_binance or new_bcv:
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
        logging.info(f"🔄 Actualizado - Bin: {new_binance}")

def get_sentiment_keyboard(user_id):
    share_url = f"https://t.me/share/url?url=https://t.me/tasabinance_bot&text={quote('🔥 Tasa Binance')}"
    if has_user_voted(user_id):
        return [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')], [InlineKeyboardButton("📤 Compartir con Amigos", url=share_url)]]
    else:
        return [[InlineKeyboardButton("🚀 Subirá", callback_data='vote_up'), InlineKeyboardButton("📉 Bajará", callback_data='vote_down')], [InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]

def build_price_message(binance, bcv_data, time_str, user_id=None, requests_count=0):
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n\n"
    if bcv_data:
        if bcv_data.get('usd'):
            brecha = ((binance - bcv_data['usd']) / bcv_data['usd']) * 100
            emoji_brecha = "🔴" if brecha >= 20 else "🟠" if brecha >= 10 else "🟢"
            text += f"🏛️ <b>BCV (Dólar):</b> {bcv_data['usd']:,.2f} Bs\n📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
        else: text += "🏛️ <b>BCV (Dólar):</b> <i>Esperando datos...</i> ⏳\n"
        if bcv_data.get('eur'): text += f"🇪🇺 <b>BCV (Euro):</b> {bcv_data['eur']:,.2f} Bs\n"
        else: text += "🇪🇺 <b>BCV (Euro):</b> <i>Esperando datos...</i> ⏳\n"
    else: text += "🏛️ <b>BCV:</b> <i>Esperando datos...</i> ⏳\n"
    
    text += f"\n{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {binance * 0.90:,.2f} Bs\n{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {binance * 0.75:,.2f} Bs\n\n"
    
    if user_id and has_user_voted(user_id):
        up, down = get_vote_results()
        total = up + down
        if total > 0:
            up_pct = int((up / total) * 100)
            down_pct = int((down / total) * 100)
            text += f"🗣️ <b>¿Qué dice la comunidad?</b>\n🚀 {up_pct}% <b>Alcista</b> | 📉 {down_pct}% <b>Bajista</b>\n\n"
    elif user_id: text += "🗣️ <b>¿Qué dice la comunidad?</b> 👇\n\n"
    
    text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>\n"
    if requests_count > 100: text += f"👁 <b>{requests_count:,}</b> consultas hoy\n\n"
    else: text += "\n"
    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    return text

# ==============================================================================
#  CONVERSATION & COMMAND HANDLERS
# ==============================================================================
async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/alerta")
    if context.args:
        try:
            target = float(context.args[0].replace(',', '.'))
            return await process_alert_logic(update, target)
        except ValueError:
            await update.message.reply_text("🔢 Error: Ingresa un número válido.")
            return ConversationHandler.END
    await update.message.reply_text(f"{EMOJI_ALERTA} <b>CONFIGURAR ALERTA</b>\n\n¿A qué precio quieres que te avise?", parse_mode=ParseMode.HTML)
    return ESPERANDO_PRECIO_ALERTA

async def process_alert_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = float(update.message.text.replace(',', '.'))
        await process_alert_logic(update, target)
    except ValueError: await update.message.reply_text("🔢 Solo números.")
    return ConversationHandler.END

async def process_alert_logic(update: Update, target):
    current_price = MARKET_DATA["price"]
    if not current_price:
        await update.message.reply_text("⚠️ Esperando actualización...")
        return
    condition = "ABOVE" if target > current_price else "BELOW"
    msg = "SUBIDA" if condition == "ABOVE" else "BAJADA"
    success = await asyncio.to_thread(add_alert, update.effective_user.id, target, condition)
    if success: await update.message.reply_text(f"✅ Alerta de {msg} configurada en {target}")
    else: await update.message.reply_text("⛔ Límite de alertas alcanzado.")
    return ConversationHandler.END

async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    if context.args: return await calculate_conversion(update, context.args[0], "USDT")
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n¿Cuántos Dólares?", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    if context.args: return await calculate_conversion(update, context.args[0], "BS")
    await update.message.reply_text("🇻🇪 <b>Calculadora Bolívares:</b>\n¿Cuántos Bs?", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_BS

async def process_usdt_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "USDT")
    return ConversationHandler.END

async def process_bs_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "BS")
    return ConversationHandler.END

async def calculate_conversion(update: Update, text_amount, currency_type):
    rate_binance = MARKET_DATA["price"]
    rate_bcv = MARKET_DATA["bcv"]["usd"] if MARKET_DATA["bcv"] else None
    if not rate_binance:
        await update.message.reply_text("⏳ Actualizando tasas...")
        return ConversationHandler.END
    try:
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        if not clean_text:
             await update.message.reply_text("🔢 Número inválido.")
             return ConversationHandler.END
        amount = float(clean_text.replace(',', '.'))
        await asyncio.to_thread(log_calc, update.effective_user.id, amount, currency_type, 0)
        
        extra_msg = "\n\n🔔 <i>¿Esperas una tasa mejor? Configura una /alerta</i>" if random.random() < 0.3 else ""

        if currency_type == "USDT":
            total_binance = amount * rate_binance
            text = f"🇺🇸 <b>{amount:,.2f} (USDT / Dólares) son:</b>\n\n🔶 <b>{total_binance:,.2f} Bs</b> (Binance)\n└ <i>Tasa: {rate_binance:,.2f}</i>\n\n"
            if rate_bcv:
                total_bcv = amount * rate_bcv
                diff = abs(total_binance - total_bcv)
                text += f"🏛️ <b>{total_bcv:,.2f} Bs</b> (Tasa BCV)\n└ <i>Tasa: {rate_bcv:,.2f}</i>\n\n💸 <b>Diferencia:</b> {diff:,.2f} Bs"
            else: text += "🏛️ <b>BCV:</b> No disponible"
        else: 
            total_binance = amount / rate_binance
            text = f"🇻🇪 <b>{amount:,.2f} Bs equivalen a:</b>\n\n🔶 <b>{total_binance:,.2f} USDT</b> (Binance)\n└ <i>Tasa: {rate_binance:,.2f}</i>\n\n"
            if rate_bcv and rate_bcv > 0:
                total_bcv = amount / rate_bcv
                diff = abs(total_binance - total_bcv)
                text += f"🏛️ <b>{total_bcv:,.2f} $</b> (Dólar Oficial)\n└ <i>Tasa: {rate_bcv:,.2f}</i>\n\n💸 <b>Diferencia:</b> {diff:,.2f} USD"
            else: text += "🏛️ <b>BCV:</b> No disponible"
            
        await update.message.reply_text(text + extra_msg, parse_mode=ParseMode.HTML)
    except ValueError: await update.message.reply_text("🔢 Número inválido.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

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
    try: await query.answer()
    except: pass

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

if __name__ == "__main__":
    init_db()
    if not TOKEN: exit(1)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.environ.get("PORT", "8080"))
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    
    # Handlers
    conv_usdt = ConversationHandler(entry_points=[CommandHandler("usdt", start_usdt_calc)], states={ESPERANDO_INPUT_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_usdt_input)]}, fallbacks=[CommandHandler("cancel", cancel)])
    conv_bs = ConversationHandler(entry_points=[CommandHandler("bs", start_bs_calc)], states={ESPERANDO_INPUT_BS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bs_input)]}, fallbacks=[CommandHandler("cancel", cancel)])
    conv_alert = ConversationHandler(entry_points=[CommandHandler("alerta", start_alert)], states={ESPERANDO_PRECIO_ALERTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_alert_input)]}, fallbacks=[CommandHandler("cancel", cancel)])

    app.add_handler(conv_usdt); app.add_handler(conv_bs); app.add_handler(conv_alert)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CommandHandler("referidos", referidos)) 
    app.add_handler(CommandHandler("grafico", grafico)) 
    app.add_handler(CommandHandler("debug", debug_mining))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # 🔥 RECUPERACIÓN DE ESTADO 🔥
    if MARKET_DATA["price"] is None:
        recover_last_state()

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)
        app.job_queue.run_daily(send_daily_report, time=time(hour=9, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
        app.job_queue.run_daily(send_daily_report, time=time(hour=13, minute=0, tzinfo=TIMEZONE), days=(0, 1, 2, 3, 4, 5, 6))
    
    if WEBHOOK_URL:
        print(f"🚀 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        print("⚠️ Sin WEBHOOK_URL. Iniciando Polling...")
        app.run_polling()
