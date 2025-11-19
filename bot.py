import os
import logging
import requests
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

# --- Función auxiliar para consultar Binance ---
def get_binance_price():
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
        # Retornamos el promedio
        return sum(prices) / len(prices) if prices else None
    except Exception:
        return None

# --- COMANDO /precio (Solo ve la tasa) ---
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Consultando tasa actual...")
    rate = get_binance_price()
    
    if rate:
        await update.message.reply_text(
            f"📊 **Tasa Binance:** {rate:,.2f} Bs/USDT", 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("⚠️ Error consultando Binance.")

# --- COMANDO /ves (Convierte Dólares A Bolívares) ---
async def calcular_ves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usuario escribe: /ves 50
    if not context.args:
        await update.message.reply_text("⚠️ Escribe los USDT. Ej: `/ves 50`", parse_mode='Markdown')
        return

    try:
        amount_usdt = float(context.args[0].replace(',', '.'))
        rate = get_binance_price()
        
        if rate:
            # MULTIPLICAMOS
            total_ves = amount_usdt * rate
            await update.message.reply_text(
                f"🇺🇸 {amount_usdt:,.2f} USDT son:\n"
                f"🇻🇪 **{total_ves:,.2f} Bolívares**\n"
                f"_(Tasa: {rate:,.2f})_",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Error de conexión.")
            
    except ValueError:
        await update.message.reply_text("🔢 Ingresa un número válido.")

# --- COMANDO /usdt (Convierte Bolívares A Dólares) ---
async def calcular_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usuario escribe: /usdt 2000
    if not context.args:
        await update.message.reply_text("⚠️ Escribe los Bolívares. Ej: `/usdt 2000`", parse_mode='Markdown')
        return

    try:
        amount_ves = float(context.args[0].replace(',', '.'))
        rate = get_binance_price()
        
        if rate:
            # DIVIDIMOS
            total_usdt = amount_ves / rate
            await update.message.reply_text(
                f"🇻🇪 {amount_ves:,.2f} Bs son:\n"
                f"🇺🇸 **{total_usdt:,.2f} USDT**\n"
                f"_(Tasa: {rate:,.2f})_",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Error de conexión.")
            
    except ValueError:
        await update.message.reply_text("🔢 Ingresa un número válido.")

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Calculadora Binance P2P**\n\n"
        "1️⃣ **/precio** - Ver tasa del día\n"
        "2️⃣ **/ves 50** - Convertir 50$ a Bolívares\n"
        "3️⃣ **/usdt 5000** - Convertir 5000 Bs a Dólares",
        parse_mode='Markdown'
    )

# --- BLOQUE PRINCIPAL ---
if __name__ == "__main__":
    if not TOKEN:
        print("Error: TOKEN no encontrado.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    
    # Aquí están los dos conversores:
    app.add_handler(CommandHandler("ves", calcular_ves))   # Dólar -> Bs
    app.add_handler(CommandHandler("usdt", calcular_usdt)) # Bs -> Dólar

    print("Bot Calculadora iniciando...")
    app.run_polling()
