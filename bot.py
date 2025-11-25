import os
import logging
import requests
import psycopg2  # <--- IMPORTANTE: Librería para la Base de Datos
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
# Intenta obtener la URL de la base de datos, si falla, avisa en logs
DATABASE_URL = os.getenv("DATABASE_URL")

# ⚠️ PON TU ID DE TELEGRAM AQUÍ
ADMIN_ID = 123456789 

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES 🔴
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

# --- ESTADOS DE LA CONVERSACIÓN ---
ESPERANDO_INPUT_USDT, ESPERANDO_INPUT_BS = range(2)

# --- MEMORIA (Solo Caché de Precios) ---
MARKET_DATA = {
    "price": None,
    "last_updated": "Esperando...",
    "history": [] 
}

# ==============================================================================
#  GESTIÓN DE BASE DE DATOS (POSTGRESQL) - ¡ESTO ES LO NUEVO!
# ==============================================================================

def init_db():
    """Crea la tabla de usuarios si no existe al iniciar."""
    if not DATABASE_URL:
        logging.warning("⚠️ No se detectó DATABASE_URL. El bot usará memoria RAM (volátil).")
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
        logging.info("✅ Base de Datos conectada y tabla verificada.")
    except Exception as e:
        logging.error(f"❌ Error conectando a BD: {e}")

def track_user(user_id):
    """Guarda al usuario en PostgreSQL de forma segura."""
    if not DATABASE_URL: return 

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Intentamos insertar. Si ya existe (ON CONFLICT), no hace nada.
        cur.execute("""
            INSERT INTO users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error guardando usuario: {e}")

def get_total_users():
    """Cuenta cuántos usuarios hay en la base de datos."""
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
#  FIN LÓGICA DB
# ==============================================================================

# --- BACKEND BINANCE ---
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    payload = {
        "page": 1, "rows": 10, "payTypes": [], "asset": "USDT", "fiat": "VES", "tradeType": "BUY"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        prices = [float(item["adv"]["price"]) for item in data["data"]]
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        logging.error(f"Error conectando con Binance: {e}")
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
        logging.warning("⚠️ Fallo al actualizar precio.")

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id) # <--- Guarda en BD Real
    mensaje = (
        "👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        "Soy tu asistente financiero conectado a <b>Binance P2P</b>. "
        "Te doy la tasa <b>USDT/VES</b> más precisa y rápida del mercado.\n\n"
        
        "⚡ <b>Características:</b>\n"
        "• <b>Precisión:</b> Promedio real de ofertas.\n"
        "• <b>Velocidad:</b> Actualizado cada 2 minutos.\n\n"
        
        "🛠 <b>HERRAMIENTAS:</b>\n\n"
        "📊 <b>/precio</b> → Ver tasa actual.\n"
        "🧠 <b>/ia</b> → Predicción de tendencia.\n\n"
        "🧮 <b>CALCULADORA (Toca abajo):</b>\n"
        "• <b>/usdt</b> → Convertir Dólares a Bs.\n"
        "• <b>/bs</b> → Convertir Bs a Dólares."
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📢 Canal", url=LINK_CANAL),
            InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)
        ],
        [
            InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# --- COMANDO /precio ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    rate = MARKET_DATA["price"]
    time_str = MARKET_DATA["last_updated"]
    
    if rate:
        text = (f"📊 <b>Tasa Binance P2P:</b> {rate:,.2f} Bs/USDT\n" f"🕒 <i>Actualizado: {time_str}</i>")
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
            new_text = (f"📊 <b>Tasa Binance P2P:</b> {rate:,.2f} Bs/USDT\n" f"🕒 <i>Actualizado: {time_str}</i>")
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
    
    if percent > 0.5: emoji, status, msg = "🚀", "ALCISTA FUERTE", "El precio sube con fuerza."
    elif percent > 0: emoji, status, msg = "📈", "LIGERAMENTE ALCISTA", "Recuperación gradual."
    elif percent < -0.5: emoji, status, msg = "🩸", "BAJISTA FUERTE", "Caída rápida."
    elif percent < 0: emoji, status, msg = "📉", "LIGERAMENTE BAJISTA", "Corrección a la baja."
    else: emoji, status, msg = "⚖️", "LATERAL / ESTABLE", "Sin volatilidad."

    text = (f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n<i>Nuestro algoritmo procesa el historial.</i>\n\n"
            f"{emoji} <b>Estado:</b> {status}\n📊 <b>Variación (1h):</b> {percent:.2f}%\n\n"
            f"💡 <b>Conclusión:</b>\n<i>{msg}</i>\n\n⚠️ <i>No es consejo financiero.</i>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- ESTADÍSTICAS (LEEN LA DB) ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        count = get_total_users() # <--- Lee de la Base de Datos
        await update.message.reply_text(f"📊 <b>ESTADÍSTICAS REALES</b>\n👥 Usuarios Registrados (DB): {count}", parse_mode=ParseMode.HTML)

# --- CALCULADORA ---
async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if context.args: return await calculate_conversion(update, context.args[0], "USDT")
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Qué cantidad de Dólares quieres convertir a Bs?\n\n<i>Escribe el número abajo:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if context.args: return await calculate_conversion(update, context.args[0], "BS")
    await update.message.reply_text("🇻🇪 <b>Calculadora Bolívares:</b>\n\n¿Qué cantidad de Bs quieres convertir a Dólares?\n\n<i>Escribe el número abajo:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_BS

async def process_usdt_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "USDT")
    return ConversationHandler.END

async def process_bs_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await calculate_conversion(update, update.message.text, "BS")
    return ConversationHandler.END

async def calculate_conversion(update: Update, text_amount, currency_type):
    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas... intenta en breve.")
        return ConversationHandler.END

    try:
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        amount = float(clean_text.replace(',', '.'))
        
        if currency_type == "USDT":
            total = amount * rate
            await update.message.reply_text(
                f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>",
                parse_mode=ParseMode.HTML
            )
        else: # BS
            total = amount / rate
            await update.message.reply_text(
                f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>",
                parse_mode=ParseMode.HTML
            )
    except ValueError:
        await update.message.reply_text("🔢 Por favor ingresa solo números válidos.")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

# --- MAIN ---
if __name__ == "__main__":
    # INICIALIZAR LA DB (Esto crea la tabla si no existe)
    init_db()

    if not TOKEN:
        print("Error: TOKEN no encontrado.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler_usdt = ConversationHandler(
        entry_points=[CommandHandler("usdt", start_usdt_calc)],
        states={ESPERANDO_INPUT_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_usdt_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    conv_handler_bs = ConversationHandler(
        entry_points=[CommandHandler("bs", start_bs_calc)],
        states={ESPERANDO_INPUT_BS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bs_input)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(conv_handler_usdt)
    app.add_handler(conv_handler_bs)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot PRO (Con Base de Datos REAL) iniciando...")
    app.run_polling()
