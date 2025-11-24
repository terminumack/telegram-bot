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
    ContextTypes
)

# 1. Configurar Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# 🔴 PEGA TU ID DE ADMIN AQUÍ (Para usar /stats y /global)
ADMIN_ID = 533888411 

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 # 2 Minutos
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES REALES 🔴
LINK_CANAL = "https://t.me/tucanaloficial"
LINK_SOPORTE = "https://t.me/tuusuario"

# --- MEMORIA (Caché de precios) ---
MARKET_DATA = {
    "price": None,
    "last_updated": "Calculando...",
    "history": [] 
}

# --- GESTIÓN DE BASE DE DATOS (PostgreSQL) ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    """Crea la tabla de usuarios si no existe al iniciar"""
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
        print("✅ Base de Datos Conectada y Tabla Verificada.")
    except Exception as e:
        print(f"❌ Error Crítico en Base de Datos: {e}")

def track_user(user_id):
    """Guarda al usuario en la BD (Ignora si ya existe)"""
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
        logging.error(f"Error guardando usuario: {e}")

def count_users():
    """Cuenta total de usuarios para /stats"""
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
    """Obtiene todos los IDs para el Broadcast"""
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

# --- BACKEND BINANCE (ALGORITMO "TASA CALLEJERA") ---
def fetch_binance_price():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    # 🔥 EL SECRETO: Filtramos solo PAGO MÓVIL
    payload = {
        "page": 1, 
        "rows": 15,  # Pedimos 15 para tener margen
        "payTypes": ["PagoMovil"], 
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": "BUY" 
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        prices = []
        for item in data["data"]:
            prices.append(float(item["adv"]["price"]))

        if not prices: return None

        # 🔥 LIMPIEZA DE DATOS (Trimmed Mean)
        # Eliminamos los extremos (posibles estafas baratas o precios inflados)
        if len(prices) >= 5:
            prices.sort()
            # Quitamos el más barato y el más caro antes de promediar
            prices = prices[1:-1] 
            
        return sum(prices) / len(prices)

    except Exception as e:
        logging.error(f"Error conectando con Binance: {e}")
        return None

# --- TAREA AUTOMÁTICA (JobQueue) ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_price = fetch_binance_price()
    
    if new_price:
        MARKET_DATA["price"] = new_price
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p")
        
        # Historial para la IA
        MARKET_DATA["history"].append(new_price)
        if len(MARKET_DATA["history"]) > 30:
            MARKET_DATA["history"].pop(0)
            
        logging.info(f"🔄 Precio Real (PagoMóvil): {new_price}")
    else:
        logging.warning("⚠️ Fallo al actualizar precio.")

# --- COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id) # Guardar usuario

    mensaje = (
        "👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        "Soy tu asistente financiero conectado a <b>Binance P2P (Pago Móvil)</b>. "
        "Te doy la tasa <b>USDT/VES</b> real de la calle.\n\n"
        
        "⚡ <b>Características:</b>\n"
        "• <b>Realista:</b> Solo tasa Pago Móvil (sin estafas).\n"
        "• <b>Veloz:</b> Actualizado cada 2 minutos.\n\n"
        
        "🛠 <b>HERRAMIENTAS:</b>\n\n"
        "📊 <b>/precio</b> → Ver tasa actual.\n"
        "🧠 <b>/ia</b> → Predicción de tendencia.\n\n"
        "🧮 <b>CALCULADORA:</b>\n"
        "• <code>/usdt 50</code> → Convierte 50$ a Bs.\n"
        "• <code>/bs 2000</code> → Convierte 2000 Bs a $."
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📢 Canal Oficial", url=LINK_CANAL),
            InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    rate = MARKET_DATA["price"]
    time_str = MARKET_DATA["last_updated"]
    
    if rate:
        text = (
            f"📊 <b>Tasa Binance (Pago Móvil):</b> {rate:,.2f} Bs/USDT\n"
            f"🕒 <i>Actualizado: {time_str}</i>"
        )
        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else:
        await update.message.reply_text("🔄 Calculando tasa real... intenta en unos segundos.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    query = update.callback_query
    await query.answer()

    if query.data == 'refresh_price':
        rate = MARKET_DATA["price"]
        time_str = MARKET_DATA["last_updated"]
        
        if rate:
            new_text = (
                f"📊 <b>Tasa Binance (Pago Móvil):</b> {rate:,.2f} Bs/USDT\n"
                f"🕒 <i>Actualizado: {time_str}</i>"
            )
            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            except Exception:
                pass

async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    history = MARKET_DATA["history"]
    
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>", parse_mode=ParseMode.HTML)
        return

    start_price = history[0]
    end_price = history[-1]
    diff = end_price - start_price
    percent = (diff / start_price) * 100

    if percent > 0.5:
        emoji, status, msg = "🚀", "ALCISTA FUERTE", "Alta presión de compra."
    elif percent > 0:
        emoji, status, msg = "📈", "LIGERAMENTE ALCISTA", "Recuperación gradual."
    elif percent < -0.5:
        emoji, status, msg = "🩸", "BAJISTA FUERTE", "Alta presión de venta."
    elif percent < 0:
        emoji, status, msg = "📉", "LIGERAMENTE BAJISTA", "Corrección a la baja."
    else:
        emoji, status, msg = "⚖️", "ESTABLE", "Sin volatilidad significativa."

    text = (
        f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n"
        f"<i>Tendencia basada en historial Pago Móvil.</i>\n\n"
        f"{emoji} <b>Estado:</b> {status}\n"
        f"📊 <b>Variación (1h):</b> {percent:.2f}%\n\n"
        f"💡 <b>Conclusión:</b>\n<i>{msg}</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- CALCULADORAS ---
async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if not context.args: return
    rate = MARKET_DATA["price"]
    if not rate: return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount * rate
        await update.message.reply_text(f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>", parse_mode=ParseMode.HTML)
    except: pass

async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    if not context.args: return
    rate = MARKET_DATA["price"]
    if not rate: return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount / rate
        await update.message.reply_text(f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>", parse_mode=ParseMode.HTML)
    except: pass

# --- ADMIN COMMANDS ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return 
    total = count_users()
    await update.message.reply_text(f"📊 <b>Usuarios en BD:</b> {total}", parse_mode=ParseMode.HTML)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = ' '.join(context.args)
    if not msg: return
    
    users = get_all_users()
    await update.message.reply_text(f"📢 Enviando a {len(users)} usuarios...")
    
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 <b>AVISO:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            count += 1
        except: pass
    
    await update.message.reply_text(f"✅ Enviado a {count} usuarios.")

# --- MAIN ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("❌ Error: Faltan variables TOKEN o DATABASE_URL.")
        exit(1)

    init_db() # Iniciar BD

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Manejadores
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

    print("🚀 BOT DE ALTO TRÁFICO INICIADO...")
    app.run_polling()
