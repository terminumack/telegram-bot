import os
import logging
import requests
from datetime import datetime
import pytz 
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    ContextTypes
)

# 1. Configurar Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("TOKEN")

# --- CONFIGURACIÓN ---
# Actualizar cada 120 segundos (2 minutos)
UPDATE_INTERVAL = 120 
TIMEZONE = pytz.timezone('America/Caracas') # Hora de Venezuela

# --- MEMORIA (CACHÉ) ---
MARKET_DATA = {
    "price": None,
    "last_updated": "Esperando actualización..."
}

# --- FUNCIÓN: Consultar Binance (Backend) ---
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
        # Retornar promedio
        return sum(prices) / len(prices) if prices else None
    except Exception as e:
        logging.error(f"Error conectando con Binance: {e}")
        return None

# --- TAREA AUTOMÁTICA: Actualizar Caché ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_price = fetch_binance_price()
    
    if new_price:
        MARKET_DATA["price"] = new_price
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p")
        logging.info(f"🔄 Precio actualizado: {new_price}")
    else:
        logging.warning("⚠️ Fallo al actualizar precio.")

# --- COMANDO: /start (VERSIÓN HÍBRIDA PERFECTA) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "👋 **¡Bienvenido al Monitor P2P Inteligente!**\n\n"
        "Soy tu asistente financiero conectado en tiempo real al mercado **Binance P2P**. "
        "Mi misión es darte la tasa de cambio **USDT/VES** más precisa y rápida del mercado.\n\n"
        
        "⚡ **¿Por qué usar este bot?**\n"
        "• **Alta Precisión:** Calculo el promedio de las mejores ofertas reales.\n"
        "• **Velocidad Extrema:** Datos actualizados cada 2 minutos.\n"
        "• **Disponibilidad 24/7:** Siempre listo para sacar tus cuentas.\n\n"
        
        "🛠 **GUÍA DE USO RÁPIDO:**\n\n"
        "📊 **/precio**\n"
        "Consulta la tasa de cambio actual al instante.\n\n"
        
        "🧮 **CALCULADORA**\n\n"
        "💵 **¿Tienes Dólares y quieres Bolívares?**\n"
        "Escribe: `/usdt 50`  _(Te diré cuántos Bs son)_\n\n"
        
        "🇻🇪 **¿Tienes Bolívares y quieres Dólares?**\n"
        "Escribe: `/bs 2000`  _(Te diré cuántos $ son)_"
    )
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# --- COMANDO: /precio ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rate = MARKET_DATA["price"]
    time_str = MARKET_DATA["last_updated"]
    
    if rate:
        await update.message.reply_text(
            f"📊 **Tasa Binance:** {rate:,.2f} Bs/USDT\n"
            f"🕒 _Actualizado: {time_str}_", 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")

# --- COMANDO: /usdt (Dólar -> Bs) ---
async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Escribe el monto. Ej: `/usdt 50`", parse_mode='Markdown')
        return

    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas, espera un momento.")
        return

    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount * rate
        await update.message.reply_text(
            f"🇺🇸 {amount:,.2f} USDT son:\n"
            f"🇻🇪 **{total:,.2f} Bolívares**\n"
            f"_(Tasa: {rate:,.2f})_",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")

# --- COMANDO: /bs (Bs -> Dólar) ---
async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Escribe el monto. Ej: `/bs 1000`", parse_mode='Markdown')
        return

    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas, espera un momento.")
        return

    try:
        amount = float(context.args[0].replace(',', '.'))
        total = amount / rate
        await update.message.reply_text(
            f"🇻🇪 {amount:,.2f} Bs son:\n"
            f"🇺🇸 **{total:,.2f} USDT**\n"
            f"_(Tasa: {rate:,.2f})_",
            parse_mode='Markdown'
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
    app.add_handler(CommandHandler("usdt", usdt_to_bs))
    app.add_handler(CommandHandler("bs", bs_to_usdt))

    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot Escalable iniciando...")
    app.run_polling()
