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

# 2. Obtener TOKEN (El mismo nombre que tienes en Railway)
TOKEN = os.getenv("TOKEN")

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    
    # HEADERS CRÍTICOS: Disfrazamos al bot como un navegador Chrome
    # Sin esto, Binance bloqueará la conexión desde Railway.
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    payload = {
        "page": 1,
        "rows": 10,            # Promedio de las primeras 10 ofertas
        "payTypes": [],
        "asset": "USDT",
        "fiat": "VES",
        "tradeType": "BUY"     # "BUY" es a cuánto lo venden los anunciantes
    }

    await update.message.reply_text("🔎 Consultando Binance P2P...")

    try:
        # Hacemos la petición
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()

        if not data.get("data"):
            await update.message.reply_text("⚠️ Binance no devolvió datos. Intenta más tarde.")
            return

        # Extraemos precios
        prices = [float(item["adv"]["price"]) for item in data["data"]]
        
        if not prices:
            await update.message.reply_text("⚠️ No hay ofertas disponibles ahora.")
            return

        # Cálculo del promedio
        average_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)

        # Formateamos el mensaje de respuesta
        mensaje = (
            f"🇻🇪 **Tasa Binance P2P (USDT > VES)**\n\n"
            f"💵 **Promedio:** {average_price:,.2f} Bs\n"
            f"📉 **Mínimo:** {min_price:,.2f} Bs\n"
            f"📈 **Máximo:** {max_price:,.2f} Bs\n\n"
            f"_(Basado en las primeras {len(prices)} ofertas)_"
        )

        # parse_mode='Markdown' permite usar negritas con **texto**
        await update.message.reply_text(mensaje, parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error consultando Binance: {e}")
        await update.message.reply_text(f"❌ Ocurrió un error al conectar con Binance.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola! Soy tu Monitor de Cambios 🤖.\n\nUsa /precio para ver la tasa actual del USDT en Binance.")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: TOKEN no encontrado.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("precio", precio))

    print("Bot de Precios iniciando...")
    app.run_polling()
    # 6. EJECUCIÓN ROBUSTA
    # run_polling() se encarga de todo: bucle async, señales de stop y reconexión.
    # No necesitas asyncio.run() ni app.idle() aquí.
    app.run_polling()
