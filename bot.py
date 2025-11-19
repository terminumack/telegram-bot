import os
import logging
import requests
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

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120 # 2 Minutos
TIMEZONE = pytz.timezone('America/Caracas') 

# 🔴 TUS ENLACES (Configúralos aquí) 🔴
LINK_CANAL = "https://t.me/tucanaloficial"
LINK_SOPORTE = "https://t.me/tuusuario"

# --- MEMORIA (CACHÉ + HISTORIAL PARA IA) ---
MARKET_DATA = {
    "price": None,
    "last_updated": "Esperando...",
    "history": [] 
}

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
        
        # IA: Guardar historial
        MARKET_DATA["history"].append(new_price)
        if len(MARKET_DATA["history"]) > 30:
            MARKET_DATA["history"].pop(0)
            
        logging.info(f"🔄 Precio: {new_price} | Datos IA: {len(MARKET_DATA['history'])}")
    else:
        logging.warning("⚠️ Fallo al actualizar precio.")

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        "Soy tu asistente financiero conectado a <b>Binance P2P</b>. "
        "Te doy la tasa <b>USDT/VES</b> más precisa y rápida del mercado.\n\n"
        
        "⚡ <b>Características:</b>\n"
        "• <b>Precisión:</b> Promedio real de ofertas.\n"
        "• <b>Velocidad:</b> Actualizado cada 2 minutos.\n\n"
        
        "🛠 <b>HERRAMIENTAS:</b>\n\n"
        "📊 <b>/precio</b> → Ver tasa actual.\n"
        "🧠 <b>/ia</b> → <b>¡NUEVO!</b> Predicción de tendencia.\n\n"
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

# --- COMANDO /precio ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rate = MARKET_DATA["price"]
    time_str = MARKET_DATA["last_updated"]
    
    if rate:
        text = (
            f"📊 <b>Tasa Binance P2P:</b> {rate:,.2f} Bs/USDT\n"
            f"🕒 <i>Actualizado: {time_str}</i>"
        )
        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

# --- MANEJADOR BOTÓN REFRESH ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'refresh_price':
        rate = MARKET_DATA["price"]
        time_str = MARKET_DATA["last_updated"]
        
        if rate:
            new_text = (
                f"📊 <b>Tasa Binance P2P:</b> {rate:,.2f} Bs/USDT\n"
                f"🕒 <i>Actualizado: {time_str}</i>"
            )
            try:
                keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            except Exception:
                pass

# --- COMANDO /ia (REDACCIÓN MEJORADA) ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = MARKET_DATA["history"]
    
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nRecopilando datos del mercado para generar la predicción. Intenta en unos minutos.", parse_mode=ParseMode.HTML)
        return

    start_price = history[0]
    end_price = history[-1]
    diff = end_price - start_price
    percent = (diff / start_price) * 100

    if percent > 0.5:
        emoji = "🚀"
        status = "ALCISTA FUERTE"
        msg = "El precio sube con fuerza. Alta presión de compra."
    elif percent > 0:
        emoji = "📈"
        status = "LIGERAMENTE ALCISTA"
        msg = "El mercado muestra una recuperación gradual."
    elif percent < -0.5:
        emoji = "🩸"
        status = "BAJISTA FUERTE"
        msg = "El precio cae rápidamente. Alta presión de venta."
    elif percent < 0:
        emoji = "📉"
        status = "LIGERAMENTE BAJISTA"
        msg = "El mercado está corrigiendo a la baja."
    else:
        emoji = "⚖️"
        status = "LATERAL / ESTABLE"
        msg = "El precio se mantiene estable sin volatilidad."

    text = (
        f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n"
        f"<i>Nuestra Inteligencia Artificial procesa el historial de precios en tiempo real para proyectar la dirección del mercado.</i>\n\n"
        f"{emoji} <b>Estado:</b> {status}\n"
        f"📊 <b>Variación (1h):</b> {percent:.2f}%\n\n"
        f"💡 <b>Conclusión:</b>\n<i>{msg}</i>\n\n"
        f"⚠️ <i>Análisis estadístico, no consejo financiero.</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- COMANDOS CALCULADORA ---
async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ej: <code>/usdt 50</code>", parse_mode=ParseMode.HTML)
        return
    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas...")
        return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount * rate
        await update.message.reply_text(
            f"🇺🇸 {amount:,.2f} USDT son:\n"
            f"🇻🇪 <b>{total:,.2f} Bolívares</b>\n"
            f"<i>(Tasa: {rate:,.2f})</i>",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")

async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ej: <code>/bs 1000</code>", parse_mode=ParseMode.HTML)
        return
    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas...")
        return
    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount / rate
        await update.message.reply_text(
            f"🇻🇪 {amount:,.2f} Bs son:\n"
            f"🇺🇸 <b>{total:,.2f} USDT</b>\n"
            f"<i>(Tasa: {rate:,.2f})</i>",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")

# --- MAIN ---
if __name__ == "__main__":
    if not TOKEN:
        print("Error: TOKEN no encontrado.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("ia", prediccion))
    app.add_handler(CommandHandler("usdt", usdt_to_bs))
    app.add_handler(CommandHandler("bs", bs_to_usdt))
    app.add_handler(CallbackQueryHandler(button_handler))

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot FINAL LISTO iniciando...")
    app.run_polling()
