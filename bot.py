import os
import logging
import asyncio
import urllib3
import random
from datetime import datetime, time as dt_time
import pytz
from database.users import track_user, get_user_loyalty # <--- AGREGAR AQUÍ
from services.binance_service import get_market_snapshot
from database.stats import save_arbitrage_snapshot
from handlers.market import mercado

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
# En bot.py, donde registras los handlers:

from telegram.ext import ChatMemberHandler
from handlers.commands import track_my_chat_member # <--- Impórtalo

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
        # 1. ESCANEO MASIVO (Binance Multi-banco + BCV)
        # Se ejecutan en paralelo. Total aprox: 2 a 3 segundos.
        results = await asyncio.gather(
            get_market_snapshot(), # Trae PM, Banesco, Mercantil, etc.
            get_bcv_rates(),       # Trae BCV
            return_exceptions=True
        )
        
        market_data = results[0] # Diccionario con todos los bancos
        bcv_data = results[1]    # Diccionario BCV

        # 2. PROCESAR BINANCE
        if isinstance(market_data, dict):
            pm_buy = market_data.get("pm_buy", 0)
            pm_sell = market_data.get("pm_sell", 0)
            # Actualizamos la memoria de BANCOS (Ahora con SELL)
            MARKET_DATA["banks"]["pm"]["buy"]   = market_data.get("pm_buy", 0)
            MARKET_DATA["banks"]["pm"]["sell"]  = market_data.get("pm_sell", 0)
            
            MARKET_DATA["banks"]["banesco"]["buy"]  = market_data.get("ban_buy", 0)
            MARKET_DATA["banks"]["banesco"]["sell"] = market_data.get("ban_sell", 0) # Nuevo
            
            MARKET_DATA["banks"]["mercantil"]["buy"]  = market_data.get("mer_buy", 0)
            MARKET_DATA["banks"]["mercantil"]["sell"] = market_data.get("mer_sell", 0) # Nuevo
            
            MARKET_DATA["banks"]["provincial"]["buy"]  = market_data.get("pro_buy", 0)
            MARKET_DATA["banks"]["provincial"]["sell"] = market_data.get("pro_sell", 0) # Nuevo

            # --- AQUI MANTENEMOS TU ALGORITMO ORIGINAL ---
            # La "Tasa Binance" principal sigue siendo PagoMóvil Compra
            if pm_buy > 0:
                MARKET_DATA["price"] = pm_buy
                MARKET_DATA["history"].append(pm_buy)
                # Chequeo de Alertas (Usando el precio principal)
                asyncio.create_task(check_alerts_async(context, pm_buy))
            
            # Actualizamos la memoria de BANCOS (Para el comando /mercado)
            MARKET_DATA["banks"]["pm"]["buy"] = pm_buy
            MARKET_DATA["banks"]["pm"]["sell"] = pm_sell
            MARKET_DATA["banks"]["banesco"]["buy"] = market_data.get("ban_buy", 0)
            MARKET_DATA["banks"]["mercantil"]["buy"] = market_data.get("mer_buy", 0)
            MARKET_DATA["banks"]["provincial"]["buy"] = market_data.get("pro_buy", 0)

            # Guardamos la FOTO COMPLETA en DB (Para minería de datos)
            await asyncio.to_thread(
                save_arbitrage_snapshot,
                pm_buy, pm_sell,
                market_data.get("ban_buy", 0),
                market_data.get("mer_buy", 0),
                market_data.get("pro_buy", 0)
            )
            
            # Guardamos DATA SIMPLE para gráficos históricos (Compatibilidad Legacy)
            val_bcv = MARKET_DATA["bcv"].get("dolar", 0) if MARKET_DATA["bcv"] else 0
            if pm_buy > 0:
                await asyncio.to_thread(save_mining_data, pm_buy, val_bcv, pm_sell)

        # 3. PROCESAR BCV
        if isinstance(bcv_data, dict) and bcv_data:
            MARKET_DATA["bcv"] = bcv_data

        # 4. ACTUALIZAR FECHA (Con tu formato de Año y Segundos)
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
        
        logging.info(f"🔄 Snapshot: PM={market_data.get('pm_buy'):.2f} | Ban={market_data.get('ban_buy'):.2f}")

    except Exception as e:
        logging.error(f"❌ Error Update Task: {e}")
        # --------------------------------------------------------
        
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
# 1. Asegúrate de tener estos imports arriba en bot.py
from database.users import track_user, get_user_loyalty
from database.stats import get_daily_requests_count, log_activity
from utils.formatting import build_price_message, get_sentiment_keyboard

# 2. Reemplaza tu función precio por esta:
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # --- TRACKING (Vital para tus estadísticas) ---
    # Registramos que el usuario está activo y usó el comando
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/precio")
    
    # Validamos que tengamos precio en memoria
    binance = MARKET_DATA["price"]
    if not binance:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")
        return

    # 1. Obtener contador de visitas
    req_count = await asyncio.to_thread(get_daily_requests_count)
    
    # 2. Generar el TEXTO (Pasamos user_id para que decida si muestra la encuesta)
    msg = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
    
    # 3. Generar los BOTONES (Pasamos user_id para saber si ya votó)
    markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, binance)
    
    # --- 4. ESTRATEGIA DE GROWTH HACKING (Tu código) ---
    # 20% de probabilidad de chequear lealtad
    if random.random() < 0.2:
        # Consultamos a la DB: ¿Qué tan antiguo es y cuántos referidos tiene?
        days, refs = await asyncio.to_thread(get_user_loyalty, user_id)
        
        # Si tiene más de 3 días usándote Y tiene 0 referidos:
        if days > 3 and refs == 0:
            msg += "\n\n🎁 <i>¡Gana premios invitando amigos! Toca /referidos</i>"
    
    # 5. Enviar mensaje final
    await update.message.reply_html(msg, reply_markup=markup, disable_web_page_preview=True)

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
    app.add_handler(CommandHandler("mercado", mercado))
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    
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
