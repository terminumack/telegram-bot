import os
import logging
import requests
import psycopg2 
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

# 1. Configurar Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 123456789  # <--- ⚠️ PON TU ID REAL AQUÍ

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES 🔴
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

# --- ESTADOS DE LA CONVERSACIÓN ---
ESPERANDO_INPUT_USDT, ESPERANDO_INPUT_BS = range(2)

# --- MEMORIA (Caché) ---
MARKET_DATA = {
    "price": None,
    "last_updated": "Esperando...",
    "history": [] 
}

# ==============================================================================
#  GESTIÓN DE BASE DE DATOS
# ==============================================================================

def init_db():
    if not DATABASE_URL:
        logging.warning("⚠️ Sin DATABASE_URL. Usando RAM.")
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

# ==============================================================================
#  BACKEND BINANCE (OPTIMIZADO PARA USUARIO COMÚN)
# ==============================================================================
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    # 🔥 AQUÍ ESTÁ EL CAMBIO CLAVE 🔥
    payload = {
        "page": 1, 
        "rows": 10, 
        # Filtramos por PagoMovil específico para Venezuela
        "payTypes": ["PagoMovil"], 
        # Filtro de monto: 3600 VES (~10 USD) para evitar ballenas y dar precio real
        "transAmount": "3600", 
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": "BUY"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        # Filtramos resultados vacíos o errores (Fallback si falla PagoMovil)
        if not data.get("data"):
            payload["payTypes"] = [] # Intentar sin filtro de pago
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()

        prices = [float(item["adv"]["price"]) for item in data["data"]]
        
        # Promedio simple de los primeros resultados (ya filtrados por monto humano)
        return sum(prices) / len(prices) if prices else None

    except Exception as e:
        logging.error(f"Error Binance: {e}")
        return None

# --- TAREA AUTOMÁTICA ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_price = fetch_binance_price()
    if new_price:
        MARKET_DATA["price"] = new_price
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p")
        MARKET_DATA["history"].append(new_price)
        if len(MARKET_DATA["history"]) > 30:
            MARKET_DATA["history"].pop(0)
        logging.info(f"🔄 Precio: {new_price}")
    else:
        logging.warning("⚠️ Fallo actualización precio.")

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    mensaje = (
        "👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        "Soy tu asistente financiero conectado a <b>Binance P2P</b>. "
        "Te doy la tasa <b>USDT/VES</b> más precisa (Pago Móvil) del mercado.\n\n"
        
        "⚡ <b>Características:</b>\n"
        "• <b>Realidad:</b> Filtramos precios mayoristas falsos.\n"
        "• <b>Velocidad:</b> Actualizado cada 2 minutos.\n\n"
        
        "🛠 <b>HERRAMIENTAS:</b>\n\n"
        "📊 <b>/precio</b> → Ver tasa actual.\n"
        "🧠 <b>/ia</b> → Predicción de tendencia.\n\n"
        "🧮 <b>CALCULADORA (Toca abajo):</b>\n"
        "• <b>/usdt</b> → Convertir Dólares a Bs.\n"
        "• <b>/bs</b> → Convertir Bs a Dólares."
    )
    keyboard = [
        [InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)],
        [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]
    ]
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# --- COMANDO /precio ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    rate = MARKET_DATA["price"]
    time_str = MARKET_DATA["last_updated"]
    
    if rate:
        text = (f"📊 <b>Tasa Binance (Pago Móvil):</b> {rate:,.2f} Bs/USDT\n" f"🕒 <i>Actualizado: {time_str}</i>")
        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

# --- BOTÓN REFRESH ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_price':
        rate = MARKET_DATA["price"]
        time_str = MARKET_DATA["last_updated"]
        if rate:
            new_text = (f"📊 <b>Tasa Binance (Pago Móvil):</b> {rate:,.2f} Bs/USDT\n" f"🕒 <i>Actualizado: {time_str}</i>")
            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
                await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception: pass

# --- IA PREDICCIÓN ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    history = MARKET_DATA["history"]
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nRecopilando datos. Intenta en unos minutos.", parse_mode=ParseMode.HTML)
        return
    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: emoji, status, msg = "🚀", "ALCISTA FUERTE", "Subida rápida."
    elif percent > 0: emoji, status, msg = "📈", "LIGERAMENTE ALCISTA", "Recuperación."
    elif percent < -0.5: emoji, status, msg = "🩸", "BAJISTA FUERTE", "Caída rápida."
    elif percent < 0: emoji, status, msg = "📉", "LIGERAMENTE BAJISTA", "Corrección."
    else: emoji, status, msg = "⚖️", "LATERAL / ESTABLE", "Sin cambios."

    text = (f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n<i>Tendencia basada en historial reciente.</i>\n\n"
            f"{emoji} <b>Estado:</b> {status}\n📊 <b>Variación (1h):</b> {percent:.2f}%\n\n"
            f"💡 <b>Conclusión:</b>\n<i>{msg}</i>\n\n⚠️ <i>No es consejo financiero.</i>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- ESTADÍSTICAS ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        count = get_total_users()
        await update.message.reply_text(f"📊 <b>ESTADÍSTICAS (DB)</b>\n👥 Usuarios: {count}", parse_mode=ParseMode.HTML)

# --- CALCULADORA (Lógica Común) ---
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
            # Muestra la tasa usada
            await update.message.reply_text(
                f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>",
                parse_mode=ParseMode.HTML
            )
        else: 
            total = amount / rate
            # Muestra la tasa usada
            await update.message.reply_text(
                f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>",
                parse_mode=ParseMode.HTML
            )
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
    app.add_handler(CallbackQueryHandler(button_handler))

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot REALISTA (Pago Movil + Anti-Ballenas) iniciando...")
    app.run_polling()
