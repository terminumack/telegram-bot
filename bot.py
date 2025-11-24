import os
import logging
import requests
import psycopg2
from datetime import datetime
import pytz 
from bs4 import BeautifulSoup 
import urllib3 

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes
)

# Silenciar advertencia de certificado SSL (BCV)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Configurar Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 123456789 # 🔴 PON TU ID REAL AQUÍ

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 # 2 Minutos
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES REALES 🔴
LINK_CANAL = "https://t.me/tucanaloficial"
LINK_SOPORTE = "https://t.me/tuusuario"

# --- MEMORIA (Caché de precios) ---
MARKET_DATA = {
    "binance_price": None,
    "bcv_price": None,
    "last_updated": "Calculando...",
    "history": [] 
}

# --- GESTIÓN DE BASE DE DATOS ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Base de Datos Conectada.")
    except Exception as e:
        print(f"❌ Error DB: {e}")

def track_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id) VALUES (%s) 
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error tracking: {e}")

def count_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception:
        return 0

def get_all_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return users
    except Exception:
        return []

# --- SCRAPING BINANCE (Tasa Real / Pago Móvil) ---
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "page": 1, "rows": 15, "payTypes": ["PagoMovil"], 
        "asset": "USDT", "fiat": "VES", "tradeType": "BUY" 
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        prices = [float(item["adv"]["price"]) for item in data["data"]]
        if not prices: return None
        
        # Trimmed Mean (Quitamos extremos para evitar estafas)
        if len(prices) >= 5:
            prices.sort()
            prices = prices[1:-1] 
            
        return sum(prices) / len(prices)
    except Exception as e:
        logging.error(f"Error Binance: {e}")
        return None

# --- SCRAPING BCV (OFICIAL) ---
def fetch_bcv_rate():
    url = "http://www.bcv.org.ve/"
    try:
        response = requests.get(url, timeout=15, verify=False)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.content, 'html.parser')
        dolar_div = soup.find('div', {'id': 'dolar'})
        if dolar_div:
            rate_text = dolar_div.find('strong').text.strip()
            return float(rate_text.replace(',', '.'))
        return None
    except Exception as e:
        logging.error(f"Error BCV: {e}")
        return None

# --- TAREA AUTOMÁTICA ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    # 1. Binance
    binance_val = fetch_binance_price()
    if binance_val:
        MARKET_DATA["binance_price"] = binance_val
        MARKET_DATA["history"].append(binance_val)
        if len(MARKET_DATA["history"]) > 30:
            MARKET_DATA["history"].pop(0)

    # 2. BCV
    bcv_val = fetch_bcv_rate()
    if bcv_val:
        MARKET_DATA["bcv_price"] = bcv_val

    # Hora
    if binance_val or bcv_val:
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p")
        logging.info(f"🔄 Datos actualizados | Binance: {binance_val} | BCV: {bcv_val}")

# --- COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    mensaje = (
        "👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        "Soy tu asistente financiero. Te doy las dos tasas más importantes de Venezuela en tiempo real.\n\n"
        "🔶 <b>Tasa Binance</b> (Pago Móvil)\n"
        "🏛️ <b>Tasa BCV</b> (Oficial)\n\n"
        "🛠 <b>HERRAMIENTAS:</b>\n"
        "📊 <b>/precio</b> → Ver tabla comparativa.\n"
        "🧠 <b>/ia</b> → Predicción de tendencia.\n"
        "🧮 <b>/usdt 50</b> → Calculadora rápida."
    )
    keyboard = [[InlineKeyboardButton("📢 Canal Oficial", url=LINK_CANAL), InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]]
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# --- COMANDO PRECIO ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    
    binance = MARKET_DATA["binance_price"]
    bcv = MARKET_DATA["bcv_price"]
    time_str = MARKET_DATA["last_updated"]
    
    if binance:
        brecha_txt = ""
        if bcv:
            diff = ((binance - bcv) / bcv) * 100
            emoji_brecha = "🔴" if diff > 5 else "🟢"
            # CAMBIO APLICADO: Icono 📈 para la brecha
            brecha_txt = f"\n📈 <b>Brecha:</b> {diff:.2f}% {emoji_brecha}"
            bcv_txt = f"{bcv:,.2f} Bs"
        else:
            bcv_txt = "⏳ Buscando..."

        text = (
            f"📊 <b>MONITOR DE TASAS</b>\n\n"
            f"🔶 <b>Tasa Binance:</b> <b>{binance:,.2f} Bs</b>\n"
            f"🏛️ <b>BCV (Oficial):</b> <b>{bcv_txt}</b>\n"
            f"{brecha_txt}\n\n"
            f"🕒 <i>Actualizado: {time_str}</i>"
        )
        
        keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data='refresh_price')]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("🔄 Iniciando sistema... espera un momento.")

# --- MANEJADOR BOTÓN ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    query = update.callback_query
    await query.answer()

    if query.data == 'refresh_price':
        binance = MARKET_DATA["binance_price"]
        bcv = MARKET_DATA["bcv_price"]
        time_str = MARKET_DATA["last_updated"]
        
        if binance:
            brecha_txt = ""
            if bcv:
                diff = ((binance - bcv) / bcv) * 100
                emoji_brecha = "🔴" if diff > 5 else "🟢"
                # CAMBIO APLICADO AQUÍ TAMBIÉN
                brecha_txt = f"\n📈 <b>Brecha:</b> {diff:.2f}% {emoji_brecha}"
                bcv_txt = f"{bcv:,.2f} Bs"
            else:
                bcv_txt = "⏳ Buscando..."

            new_text = (
                f"📊 <b>MONITOR DE TASAS</b>\n\n"
                f"🔶 <b>Tasa Binance:</b> <b>{binance:,.2f} Bs</b>\n"
                f"🏛️ <b>BCV (Oficial):</b> <b>{bcv_txt}</b>\n"
                f"{brecha_txt}\n\n"
                f"🕒 <i>Actualizado: {time_str}</i>"
            )
            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data='refresh_price')]]
                await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except: pass

# --- OTROS ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    history = MARKET_DATA["history"]
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>", parse_mode=ParseMode.HTML); return
    
    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: s, e, m = "ALCISTA FUERTE", "🚀", "Alta presión de compra."
    elif percent > 0: s, e, m = "LIGERAMENTE ALCISTA", "📈", "Recuperación gradual."
    elif percent < -0.5: s, e, m = "BAJISTA FUERTE", "🩸", "Fuerte presión de venta."
    elif percent < 0: s, e, m = "LIGERAMENTE BAJISTA", "📉", "Corrección a la baja."
    else: s, e, m = "ESTABLE", "⚖️", "Sin volatilidad."
    
    text = (
        f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n"
        f"<i>Tendencia Binance (1h)</i>\n\n"
        f"{e} <b>Estado:</b> {s}\n"
        f"📊 <b>Variación:</b> {percent:.2f}%\n\n"
        f"💡 <b>Conclusión:</b>\n<i>{m}</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if not context.args: return
    rate = MARKET_DATA["binance_price"]
    if not rate: return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount * rate
        await update.message.reply_text(f"🇺🇸 {amount:,.2f} USDT = 🇻🇪 <b>{total:,.2f} Bs</b>", parse_mode=ParseMode.HTML)
    except: pass

async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if not context.args: return
    rate = MARKET_DATA["binance_price"]
    if not rate: return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount / rate
        await update.message.reply_text(f"🇻🇪 {amount:,.2f} Bs = 🇺🇸 <b>{total:,.2f} USDT</b>", parse_mode=ParseMode.HTML)
    except: pass

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return 
    total = count_users()
    await update.message.reply_text(f"📊 <b>Usuarios BD:</b> {total}", parse_mode=ParseMode.HTML)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = ' '.join(context.args)
    if not msg: return
    users = get_all_users()
    await update.message.reply_text(f"📢 Enviando a {len(users)}...")
    c = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 <b>AVISO:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            c+=1
        except: pass
    await update.message.reply_text(f"✅ Enviados: {c}")

if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("❌ Error: Faltan variables.")
        exit(1)
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("usdt", usdt_to_bs))
    app.add_handler(CommandHandler("bs", bs_to_usdt))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)
    
    print("🚀 BOT OFICIAL LISTO PARA LANZAMIENTO...")
    app.run_polling()
