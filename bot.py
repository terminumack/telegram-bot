import os
import logging
import requests
import psycopg2 
from bs4 import BeautifulSoup 
import urllib3
from datetime import datetime
import pytz 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
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
ADMIN_ID = 533888411 # Tu ID

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES 🔴
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

# --- ESTADOS CONVERSACIÓN (¡RECUPERADO!) ---
ESPERANDO_INPUT_USDT, ESPERANDO_INPUT_BS = range(2)

# --- EMOJIS PREMIUM (IDs Personalizados) ---
EMOJI_BINANCE = '<tg-emoji emoji-id="5269277053684819725">🔶</tg-emoji>'
EMOJI_PAYPAL  = '<tg-emoji emoji-id="5364111181415996352">🅿️</tg-emoji>'
EMOJI_SUBIDA  = '<tg-emoji emoji-id="5244837092042750681">📈</tg-emoji>'
EMOJI_BAJADA  = '<tg-emoji emoji-id="5246762912428603768">📉</tg-emoji>'
EMOJI_STATS   = '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji>'
EMOJI_STORE   = '<tg-emoji emoji-id="5895288113537748673">🏪</tg-emoji>'

# --- MEMORIA (Caché) ---
MARKET_DATA = {
    "price": None, # Binance
    "bcv": None,   # BCV
    "last_updated": "Esperando...",
    "history": [] 
}

# ==============================================================================
#  BASE DE DATOS (POSTGRESQL)
# ==============================================================================
def init_db():
    if not DATABASE_URL:
        logging.warning("⚠️ Sin DATABASE_URL. Usando RAM temporal.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
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
    except Exception as e:
        logging.error(f"❌ Error BD: {e}")

def track_user(user_id):
    if not DATABASE_URL: return 
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error track_user: {e}")

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
    except Exception:
        return 0

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
    except Exception:
        return []

# ==============================================================================
#  BACKEND DE PRECIOS
# ==============================================================================
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    # Filtro Top 5 Verificados + Pago Móvil
    payload = {
        "page": 1, 
        "rows": 5, 
        "payTypes": ["PagoMovil"], 
        "publisherType": "merchant",
        "transAmount": "3600", 
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": "BUY"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        if not data.get("data"):
            del payload["publisherType"] # Fallback
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()
        prices = [float(item["adv"]["price"]) for item in data["data"]]
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        logging.error(f"Error Binance: {e}")
        return None

def fetch_bcv_price():
    url = "http://www.bcv.org.ve/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_div = soup.find('div', id='dolar')
            if dolar_div:
                rate_text = dolar_div.find('strong').text.strip()
                return float(rate_text.replace(',', '.'))
    except Exception:
        return None
    return None

# --- TAREA AUTOMÁTICA ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_binance = fetch_binance_price()
    new_bcv = fetch_bcv_price()

    if new_binance:
        MARKET_DATA["price"] = new_binance
        MARKET_DATA["history"].append(new_binance)
        if len(MARKET_DATA["history"]) > 30: MARKET_DATA["history"].pop(0)

    if new_bcv:
        MARKET_DATA["bcv"] = new_bcv

    if new_binance or new_bcv:
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p")
        logging.info(f"🔄 Actualizado - Bin: {new_binance} | BCV: {new_bcv}")

# ==============================================================================
#  COMANDOS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    mensaje = (
        f"👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        f"Soy tu asistente financiero conectado a {EMOJI_BINANCE} <b>Binance P2P</b> y al <b>BCV</b>.\n\n"
        f"⚡ <b>Características:</b>\n"
        f"• <b>Confianza:</b> Solo monitoreamos comerciantes verificados.\n"
        f"• <b>Completo:</b> Tasa Paralela, Oficial y PayPal.\n"
        f"• <b>Velocidad:</b> Actualizado cada 2 min.\n\n"
        f"🛠 <b>HERRAMIENTAS:</b>\n\n"
        f"{EMOJI_STATS} <b>/precio</b> → Ver tabla de tasas.\n"
        f"🧠 <b>/ia</b> → Predicción de Tendencia.\n\n"
        f"🧮 <b>CALCULADORA (Toca abajo):</b>\n"
        f"• <b>/usdt</b> → Dólares a Bs.\n"
        f"• <b>/bs</b> → Bs a Dólares."
    )
    keyboard = [
        [InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)],
        [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]
    ]
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    binance = MARKET_DATA["price"]
    bcv = MARKET_DATA["bcv"]
    time_str = MARKET_DATA["last_updated"]
    
    if binance:
        paypal = binance * 0.90
        
        text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n"
        text += f"{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n"
        text += f"{EMOJI_PAYPAL} <b>Tasa PayPal (Aprox):</b> {paypal:,.2f} Bs\n"
        text += f"<i>(Calculado a -10%)</i>\n\n"
        
        if bcv:
            text += f"🏛️ <b>BCV (Oficial):</b> {bcv:,.2f} Bs\n\n"
            brecha = ((binance - bcv) / bcv) * 100
            if brecha >= 20: emoji = "🔴"
            elif brecha >= 10: emoji = "🟠"
            else: emoji = "🟢"
            text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji}\n\n"
        else:
            text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"
            
        text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>"

        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    
    if query.data == 'refresh_price':
        binance = MARKET_DATA["price"]
        bcv = MARKET_DATA["bcv"]
        time_str = MARKET_DATA["last_updated"]
        
        if binance:
            paypal = binance * 0.90
            text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n"
            text += f"{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n"
            text += f"{EMOJI_PAYPAL} <b>Tasa PayPal (Aprox):</b> {paypal:,.2f} Bs\n"
            text += f"<i>(Calculado a -10%)</i>\n\n"
            
            if bcv:
                text += f"🏛️ <b>BCV (Oficial):</b> {bcv:,.2f} Bs\n\n"
                brecha = ((binance - bcv) / bcv) * 100
                if brecha >= 20: emoji = "🔴"
                elif brecha >= 10: emoji = "🟠"
                else: emoji = "🟢"
                text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji}\n\n"
            else:
                text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"
            text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>"

            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
                await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception: pass

async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    history = MARKET_DATA["history"]
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nRecopilando datos. Intenta en unos minutos.", parse_mode=ParseMode.HTML)
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
    if update.effective_user.id == ADMIN_ID:
        count = get_total_users()
        await update.message.reply_text(f"{EMOJI_STATS} <b>ESTADÍSTICAS (DB)</b>\n👥 Usuarios: {count}", parse_mode=ParseMode.HTML)

# --- COMANDO GLOBAL ---
async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("⚠️ Escribe el mensaje.", parse_mode=ParseMode.HTML)
        return
    mensaje = " ".join(context.args)
    users = get_all_users_ids()
    if not users:
        await update.message.reply_text("⚠️ No hay usuarios.")
        return
    await update.message.reply_text(f"🚀 Iniciando difusión a {len(users)} usuarios...")
    enviados = 0
    fallidos = 0
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=mensaje)
            enviados += 1
        except Exception:
            fallidos += 1
    await update.message.reply_text(f"✅ <b>Terminado</b>\n\n📨 Enviados: {enviados}\n❌ Fallidos: {fallidos}", parse_mode=ParseMode.HTML)

# --- CALCULADORA ---
async def calculate_conversion(update: Update, text_amount, currency_type):
    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas...")
        return ConversationHandler.END
    try:
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        amount = float(clean_text.replace(',', '.'))
        if currency_type == "USDT":
            total = amount * rate
            await update.message.reply_text(f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>", parse_mode=ParseMode.HTML)
        else: 
            total = amount / rate
            await update.message.reply_text(f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")
    return ConversationHandler.END

# --- MANEJADORES CONVERSACIÓN ---
async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if context.args: return await calculate_conversion(update, context.args[0], "USDT")
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Cuántos Dólares?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
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

# --- MAIN ---
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

    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot PREMIUM VISUAL iniciando...")
    app.run_polling()
