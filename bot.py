import os
import logging
import asyncio
import urllib3
import random
from datetime import datetime, time as dt_time
import pytz

# --- 1. IMPORTS DE MEMORIA Y CONFIGURACIÓN ---
from shared import MARKET_DATA, TIMEZONE
from database.setup import init_db
from database.stats import (
    get_daily_requests_count, 
    queue_broadcast, 
    save_mining_data, 
    save_market_state,      # <--- Persistencia
    load_last_market_state  # <--- Persistencia
)
from database.alerts import get_triggered_alerts

# --- 2. SERVICIOS ---
from services.binance_service import get_binance_price
from services.bcv_service import get_bcv_rates
from services.worker import background_worker  # <--- Cartero

# --- 3. UTILIDADES VISUALES ---
from utils.formatting import build_price_message

# --- 4. HANDLERS ---
from handlers.commands import (
    start_command, 
    help_command, 
    grafico, 
    referidos, 
    prediccion,    
    stats,         
    global_message,
    debug_mining   
)
from handlers.callbacks import button_handler
from handlers.calc import conv_usdt, conv_bs 
from handlers.alerts import conv_alert

# Imports de Telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    ConversationHandler
)

# --- CONFIGURACIÓN ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

# ==============================================================================
#  TAREA DE FONDO: ACTUALIZADOR DE PRECIOS
# ==============================================================================
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        current_ref = MARKET_DATA["price"] or 65.0
        
        task_buy = get_binance_price("BUY", "PagoMovil", reference_price=current_ref)
        task_sell = get_binance_price("SELL", "PagoMovil", reference_price=current_ref)
        task_bcv = get_bcv_rates()
        
        results = await asyncio.gather(task_buy, task_sell, task_bcv, return_exceptions=True)
        buy_pm, sell_pm, new_bcv = results

        if isinstance(buy_pm, float) and buy_pm > 0:
            MARKET_DATA["price"] = buy_pm
            MARKET_DATA["history"].append(buy_pm)
            asyncio.create_task(check_alerts_async(context, buy_pm))

        if isinstance(new_bcv, dict) and new_bcv:
            MARKET_DATA["bcv"] = new_bcv
        
        val_buy = MARKET_DATA["price"] or 0
        val_bcv = MARKET_DATA["bcv"].get("dolar", 0) if MARKET_DATA["bcv"] else 0
        val_sell = sell_pm if (isinstance(sell_pm, float) and sell_pm > 0) else 0
        
        if val_buy > 0:
            # 1. Guardar Histórico (Gráficos)
            await asyncio.to_thread(save_mining_data, val_buy, val_bcv, val_sell)
            
            # 2. Guardar Estado Actual (Persistencia)
            await asyncio.to_thread(save_market_state, val_buy, val_bcv, MARKET_DATA["bcv"].get("euro", 0))

        MARKET_DATA["last_updated"] = datetime.now(TIMEZONE).strftime("%d/%m %I:%M %p")
        logging.info(f"🔄 Update: Buy={val_buy:.2f} | BCV={val_bcv:.2f}")

    except Exception as e:
        logging.error(f"❌ Error Update Task: {e}")

async def check_alerts_async(context, price):
    try:
        alerts = await asyncio.to_thread(get_triggered_alerts, price)
        for alert in alerts:
            try:
                chat_id, target = alert[1], alert[2]
                await context.bot.send_message(
                    chat_id, 
                    f"🚨 <b>¡ALERTA DE PRECIO!</b>\n\nEl dólar tocó: <b>{target:,.2f} Bs</b>\nActual: <b>{price:,.2f} Bs</b>", 
                    parse_mode="HTML"
                )
            except: pass
    except: pass

# ==============================================================================
#  TAREA DE FONDO: REPORTE DIARIO AUTOMÁTICO
# ==============================================================================
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    binance = MARKET_DATA["price"]
    if not binance: return

    # Lógica de Hora
    from utils.formatting import EMOJI_STATS 
    now = datetime.now(TIMEZONE)
    hour = now.hour
    
    header = "☀️ <b>¡Buenos días! Así abre el mercado:</b>" if hour < 12 else "🌤 <b>Reporte de la Tarde:</b>"
    
    body = build_price_message(MARKET_DATA, requests_count=0)
    body = body.replace(f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n", "")
    
    text = f"{header}\n\n{body}"
    
    # Enviamos a la cola (El worker le pondrá el botón)
    await asyncio.to_thread(queue_broadcast, text)
    logging.info(f"📢 Reporte diario ({'Mañana' if hour < 12 else 'Tarde'}) encolado.")

# ==============================================================================
#  COMANDO PRINCIPAL: /PRECIO
# ==============================================================================
# Importa la nueva función arriba en bot.py
from utils.formatting import build_price_message, get_sentiment_keyboard # <--- AGREGA ESTO

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    req_count = await asyncio.to_thread(get_daily_requests_count)
    
    msg = build_price_message(MARKET_DATA, requests_count=req_count)
    
    # 👇 AQUÍ ESTÁ EL CAMBIO: Usamos el teclado dinámico
    markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, MARKET_DATA["price"])
    
    if random.random() < 0.2:
        pass 

    await update.message.reply_html(msg, reply_markup=markup)

# ==============================================================================
#  MAIN: EL CEREBRO DE ARRANQUE
# ==============================================================================
if __name__ == "__main__":
    # 1. Inicializar Base de Datos
    init_db()

    # --- CARGA SILENCIOSA DE MEMORIA ---
    # Si el bot se reinicia, recordará el precio anterior.
    try:
        last_state = load_last_market_state()
        if last_state and last_state["price"] > 0:
            MARKET_DATA["price"] = last_state["price"]
            MARKET_DATA["bcv"] = last_state["bcv"]
            MARKET_DATA["last_updated"] = last_state["last_updated"]
            print(f"🧠 Memoria restaurada: {MARKET_DATA['price']} Bs")
    except Exception as e:
        print(f"⚠️ Error cargando memoria: {e}")
    # -----------------------------------
    
    if not TOKEN:
        print("❌ Error: No hay TOKEN definido.")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).build()

    # --- REGISTRO DE COMANDOS ---
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("grafico", grafico))
    app.add_handler(CommandHandler("referidos", referidos))
    app.add_handler(CommandHandler("ia", prediccion))
    
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CommandHandler("debug", debug_mining))
    
    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    
    app.add_handler(CallbackQueryHandler(button_handler))

    # --- TAREAS AUTOMÁTICAS ---
    jq = app.job_queue
    if jq:
        jq.run_repeating(update_price_task, interval=60, first=5)
        jq.run_daily(send_daily_report, time=dt_time(hour=9, minute=0, tzinfo=TIMEZONE))
        jq.run_daily(send_daily_report, time=dt_time(hour=13, minute=0, tzinfo=TIMEZONE))

    print(f"🚀 Tasabinance Bot V51 (MODULAR + PERSISTENCIA) INICIADO")

    # 🔥 ENCENDER EL WORKER DE DIFUSIÓN 🔥
    loop = asyncio.get_event_loop()
    loop.create_task(background_worker())

    # --- MODO DE EJECUCIÓN ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL:
        # Modo Producción (Masivo)
        PORT = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        # Modo Pruebas (Local)
        print("📡 Iniciando modo POLLING...")
        app.run_polling()
