import os
import logging
import asyncio
import urllib3
import random
from datetime import datetime, time as dt_time
from services.worker import background_worker
import pytz

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    ConversationHandler
)

# --- 1. IMPORTS DE MEMORIA Y CONFIGURACIÓN ---
from shared import MARKET_DATA, TIMEZONE
from database.setup import init_db
from database.stats import get_daily_requests_count, queue_broadcast, save_mining_data
from database.alerts import get_triggered_alerts

# --- 2. SERVICIOS (Conexión a Binance y BCV) ---
from services.binance_service import get_binance_price
from services.bcv_service import get_bcv_rates

# --- 3. UTILIDADES VISUALES ---
from utils.formatting import build_price_message

# --- 4. HANDLERS (Aquí conectamos tu lógica vieja y nueva) ---
# A. Comandos Generales (Mudados a commands.py)
from handlers.commands import (
    start_command, 
    help_command, 
    grafico, 
    referidos, 
    prediccion,    # Comando /ia
    stats,         # Admin
    global_message,# Admin
    debug_mining   # Admin
)
# B. Botones (Actualizar precio)
from handlers.callbacks import button_handler
# C. Módulos Complejos (Calculadora y Alertas - Archivos originales)
from handlers.calc import conv_usdt, conv_bs 
from handlers.alerts import conv_alert

# --- CONFIGURACIÓN ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

# ==============================================================================
#  TAREA DE FONDO: ACTUALIZADOR DE PRECIOS (EL CORAZÓN DEL BOT)
# ==============================================================================
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        # 1. Definir Referencia (Evita precios locos)
        current_ref = MARKET_DATA["price"] or 65.0
        
        # 2. Obtener Datos en Paralelo (Binance y BCV a la vez)
        task_buy = get_binance_price("BUY", "PagoMovil", reference_price=current_ref)
        task_sell = get_binance_price("SELL", "PagoMovil", reference_price=current_ref)
        task_bcv = get_bcv_rates()
        
        results = await asyncio.gather(task_buy, task_sell, task_bcv, return_exceptions=True)
        buy_pm, sell_pm, new_bcv = results

        # 3. Procesar Binance (Compra)
        if isinstance(buy_pm, float) and buy_pm > 0:
            MARKET_DATA["price"] = buy_pm
            MARKET_DATA["history"].append(buy_pm)
            # Chequear alertas en segundo plano
            asyncio.create_task(check_alerts_async(context, buy_pm))

        # 4. Procesar BCV (Defensivo: Si falla, mantiene el anterior)
        if isinstance(new_bcv, dict) and new_bcv:
            MARKET_DATA["bcv"] = new_bcv
        
        # 5. Guardar en Base de Datos (Data Mining)
        val_buy = MARKET_DATA["price"] or 0
        val_bcv = MARKET_DATA["bcv"].get("dolar", 0) if MARKET_DATA["bcv"] else 0
        val_sell = sell_pm if (isinstance(sell_pm, float) and sell_pm > 0) else 0
        
        if val_buy > 0:
            await asyncio.to_thread(save_mining_data, val_buy, val_bcv, val_sell)

        # 6. Actualizar Timestamp
        MARKET_DATA["last_updated"] = datetime.now(TIMEZONE).strftime("%d/%m %I:%M %p")
        logging.info(f"🔄 Update: Buy={val_buy:.2f} | BCV={val_bcv:.2f}")

    except Exception as e:
        logging.error(f"❌ Error Update Task: {e}")

async def check_alerts_async(context, price):
    """Revisa si alguna alerta se activó y envía el mensaje."""
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
    
    msg = build_price_message(MARKET_DATA)
    header = "☀️ <b>Reporte del Día:</b>\n\n"
    # Lo enviamos a la cola de difusión (Broadcast)
    await asyncio.to_thread(queue_broadcast, header + msg)

# ==============================================================================
#  COMANDO PRINCIPAL: /PRECIO (Se mantiene aquí para acceso rápido a memoria)
# ==============================================================================
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Obtener contador de visitas
    req_count = await asyncio.to_thread(get_daily_requests_count)
    
    # 2. Construir mensaje
    msg = build_price_message(MARKET_DATA, requests_count=req_count)
    
    # 3. Botón de refrescar
    kb = [[InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')]]
    
    # 4. Publicidad aleatoria (20% de probabilidad)
    if random.random() < 0.2:
        # Aquí puedes insertar tu lógica de publicidad si la tienes
        pass 

    await update.message.reply_html(msg, reply_markup=InlineKeyboardMarkup(kb))

# ==============================================================================
#  MAIN: EL CEREBRO DE ARRANQUE
# ==============================================================================
if __name__ == "__main__":
    # 1. Inicializar Base de Datos
    init_db()
    
    # 2. Construir Aplicación
    if not TOKEN:
        print("❌ Error: No hay TOKEN definido.")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).build()

    # --- REGISTRO DE COMANDOS (Conectando los cables) ---
    
    # Comandos Básicos
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("grafico", grafico))
    app.add_handler(CommandHandler("referidos", referidos))
    app.add_handler(CommandHandler("ia", prediccion))
    
    # Comandos Admin
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CommandHandler("debug", debug_mining))
    
    # Conversaciones (Calculadora y Alertas avanzadas)
    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    
    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))

    # --- TAREAS AUTOMÁTICAS (JobQueue) ---
    jq = app.job_queue
    if jq:
        # Actualizar precios cada 60 segundos
        jq.run_repeating(update_price_task, interval=60, first=5)
        
        # Reportes diarios (9:00 AM y 1:00 PM hora Venezuela)
        jq.run_daily(send_daily_report, time=dt_time(hour=9, minute=0, tzinfo=TIMEZONE))
        jq.run_daily(send_daily_report, time=dt_time(hour=13, minute=0, tzinfo=TIMEZONE))

    print(f"🚀 Tasabinance Bot V51 (MODULAR) INICIADO CORRECTAMENTE")
    # ... (código anterior de job_queue) ...

    print(f"🚀 Tasabinance Bot V51 (MODULAR) INICIADO CORRECTAMENTE")

    # 🔥 ENCENDER EL WORKER DE DIFUSIÓN EN SEGUNDO PLANO 🔥
    loop = asyncio.get_event_loop()
    loop.create_task(background_worker())

    # --- MODO DE EJECUCIÓN ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        # ... (código webhook) ...
    else:
        print("📡 Iniciando modo POLLING...")
        app.run_polling()
        
    # --- MODO DE EJECUCIÓN (Polling vs Webhook) ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        PORT = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        print("📡 Iniciando modo POLLING...")
        app.run_polling()
