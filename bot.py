import os
import logging
import requests
from datetime import datetime
import pytz # Para la hora correcta
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

# --- MEMORIA GLOBAL (CACHÉ) ---
# Aquí guardaremos el precio para no molestar a Binance todo el tiempo
MARKET_DATA = {
    "price": None,
    "last_updated": None
}

# --- CONFIGURACIÓN ---
UPDATE_INTERVAL = 120  # 120 segundos = 2 Minutos

# --- Función que consulta a Binance (Backend) ---
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

# --- TAREA AUTOMÁTICA (Se ejecuta sola cada 20 min) ---
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    new_price = fetch_binance_price()
    
    if new_price:
        # Guardamos en memoria
        MARKET_DATA["price"] = new_price
        # Guardamos la hora actual (Ajusta 'America/Caracas' si quieres hora Vzla)
        now = datetime.now(pytz.timezone('America/Caracas'))
        MARKET_DATA["last_updated"] = now.strftime("%I:%M %p") # Ej: 02:30 PM
        
        logging.info(f"🔄 Precio actualizado en caché: {new_price}")
    else:
        logging.warning("⚠️ No se pudo actualizar el precio. Se mantiene el anterior.")

# --- COMANDO /precio ---
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
        await update.message.reply_text("🔄 Iniciando sistema... intenta en 1 minuto.")

# --- COMANDO /usdt (Dólar -> Bs) ---
async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ej: `/usdt 50`", parse_mode='Markdown')
        return

    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ El bot está actualizando tasas, espera un momento.")
        return

    try:
        amount_usdt = float(context.args[0].replace(',', '.'))
        total_ves = amount_usdt * rate
        await update.message.reply_text(
            f"🇺🇸 {amount_usdt:,.2f} USDT son:\n"
            f"🇻🇪 **{total_ves:,.2f} Bolívares**",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")

# --- COMANDO /bs (Bs -> Dólar) ---
async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ej: `/bs 2000`", parse_mode='Markdown')
        return

    rate = MARKET_DATA["price"]
    if not rate:
        await update.message.reply_text("⏳ El bot está actualizando tasas, espera un momento.")
        return

    try:
        amount_ves = float(context.args[0].replace(',', '.'))
        total_usdt = amount_ves / rate
        await update.message.reply_text(
            f"🇻🇪 {amount_ves:,.2f} Bs son:\n"
            f"🇺🇸 **{total_usdt:,.2f} USDT**",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")

# --- START ACTUALIZADO Y PROFESIONAL ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "👋 **¡Bienvenido al Monitor P2P Inteligente!**\n\n"
        "Soy tu asistente financiero conectado en tiempo real al mercado **Binance P2P**. "
        "Mi misión es darte la tasa de cambio **USDT/VES** más precisa y rápida del mercado.\n\n"
        
        "⚡ **¿Por qué usar este bot?**\n"
        "• **Alta Precisión:** Calculo el promedio de las mejores ofertas reales.\n"
        "• **Velocidad Extrema:** Datos actualizados automáticamente cada 2 minutos.\n"
        "• **Disponibilidad 24/7:** Siempre listo para sacar tus cuentas.\n\n"
        
        "🛠 **GUÍA DE USO RÁPIDO:**\n\n"
        "📊 **/precio**\n"
        "Consulta la tasa de cambio actual al instante.\n\n"
        
        "🇺🇸 **Tengo Dólares** (Quiero saber cuántos Bs son)\n"
        "Escribe: `/usdt 50`  _(Ejemplo para 50 USDT)_\n\n"
        
        "🇻🇪 **Tengo Bolívares** (Quiero saber cuántos $ son)\n"
        "Escribe: `/bs 2000`  _(Ejemplo para 2000 Bs)_"
    )
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("usdt", usdt_to_bs))
    app.add_handler(CommandHandler("bs", bs_to_usdt))

    # --- AQUÍ ESTÁ LA MAGIA ---
    # Programamos la actualización automática cada 1200 segundos (20 min)
    # 'first=1' significa que la primera vez corre al segundo 1 de encenderse.
    if app.job_queue:
        app.job_queue.run_repeating(update_price_task, interval=UPDATE_INTERVAL, first=1)

    print("Bot Escalable iniciando...")
    app.run_polling()
