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
        return sum(prices) / len(prices) if prices else None
    except Exception:
        return None

# --- COMANDO /precio ---
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

# --- COMANDO /usdt (TENGO Dólares -> QUIERO Bolívares) ---
async def usdt_to_bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Lógica: Usuario tiene USDT, quiere saber cuántos Bs son.
    # Ejemplo: /usdt 50
    if not context.args:
        await update.message.reply_text("⚠️ Escribe la cantidad de USDT que tienes. Ej: `/usdt 50`", parse_mode='Markdown')
        return

    try:
        amount_usdt = float(context.args[0].replace(',', '.'))
        rate = get_binance_price()
        
        if rate:
            total_ves = amount_usdt * rate  # Multiplicamos
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

# --- COMANDO /bs (TENGO Bolívares -> QUIERO Dólares) ---
async def bs_to_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Lógica: Usuario tiene Bolívares, quiere saber cuántos USDT son.
    # Ejemplo: /bs 5000
    if not context.args:
        await update.message.reply_text("⚠️ Escribe la cantidad de Bolívares que tienes. Ej: `/bs 2000`", parse_mode='Markdown')
        return

    try:
        amount_ves = float(context.args[0].replace(',', '.'))
        rate = get_binance_price()
        
        if rate:
            total_usdt = amount_ves / rate  # Dividimos
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
        "🤖 **Calculadora P2P**\n\n"
        "1️⃣ **/precio** - Ver tasa del día\n"
        "2️⃣ **/usdt 50** - Tienes 50$ 👉 Te dice cuántos Bs son\n"
        "3️⃣ **/bs 1000** - Tienes 1000 Bs 👉 Te dice cuántos $ son",
        parse_mode='Markdown'
    )

# --- MAIN ---
if __name__ == "__main__":
    if not TOKEN:
        print("Error: TOKEN no encontrado.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))
    
    # Nuevos comandos intuitivos
    app.add_handler(CommandHandler("usdt", usdt_to_bs)) 
    app.add_handler(CommandHandler("bs", bs_to_usdt))

    print("Bot iniciando...")
    app.run_polling()
