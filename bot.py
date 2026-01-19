import os
import logging
import asyncio
import urllib3
import random
from datetime import datetime, time as dt_time
from handlers.commands import close_announcement
import pytz
TIMEZONE = pytz.timezone('America/Caracas')
from telegram.constants import ChatMemberStatus

# --- 1. IMPORTS DE MEMORIA Y CONFIGURACIÓN ---
from shared import MARKET_DATA, TIMEZONE
from database.users import track_user, get_user_loyalty
from database.setup import init_db
from database.stats import (
    get_daily_requests_count, 
    queue_broadcast, 
    save_mining_data, 
    save_market_state,      
    load_last_market_state,  
    save_arbitrage_snapshot,
    log_activity
)
from database.alerts import get_triggered_alerts

# --- 2. SERVICIOS ---
from services.binance_service import get_market_snapshot
from services.bcv_service import get_bcv_rates
from services.worker import background_worker 

# --- 3. UTILIDADES VISUALES ---
from utils.formatting import build_price_message, get_sentiment_keyboard

# --- 4. HANDLERS ---
from handlers.commands import (
    start_command, 
    help_command, 
    grafico, 
    referidos, 
    prediccion,     
    stats,          
    global_message,
    debug_mining,
    track_my_chat_member
)
from handlers.commands import start_command
from handlers.market import mercado
from handlers.analytics import horario
from handlers.callbacks import button_handler
from handlers.calc import conv_usdt, conv_bs 
from handlers.alerts import conv_alert, check_alerts_async
from handlers.commands import close_announcement
from handlers.commands import stats_full
# Imports de Telegram
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    ChatMemberHandler
)

# --- CONFIGURACIÓN ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TOKEN")
# Si no usas variables de entorno, pon tu token aquí abajo:
# TOKEN = "TU_TOKEN_AQUI" 

# ==============================================================================
#  TAREA DE FONDO: ACTUALIZADOR DE PRECIOS
# ==============================================================================
async def check_time(update, context):
    now = datetime.now(TIMEZONE)
    await update.message.reply_text(f"🕒 Mi hora actual en Caracas es: {now.strftime('%I:%M:%S %p')}")



async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        # 1. ESCANEO MASIVO (Binance Multi-banco + BCV)
        results = await asyncio.gather(
            get_market_snapshot(), 
            get_bcv_rates(),       
            return_exceptions=True
        )
        
        market_data = results[0]
        bcv_data = results[1]

        # 2. PROCESAR BINANCE
        if isinstance(market_data, dict):
            pm_buy = market_data.get("pm_buy", 0)
            pm_sell = market_data.get("pm_sell", 0)
            
            # Actualizamos RAM Bancos
            MARKET_DATA["banks"]["pm"]["buy"] = pm_buy
            MARKET_DATA["banks"]["pm"]["sell"] = pm_sell
            MARKET_DATA["banks"]["banesco"]["buy"] = market_data.get("ban_buy", 0)
            MARKET_DATA["banks"]["banesco"]["sell"] = market_data.get("ban_sell", 0)
            MARKET_DATA["banks"]["mercantil"]["buy"] = market_data.get("mer_buy", 0)
            MARKET_DATA["banks"]["mercantil"]["sell"] = market_data.get("mer_sell", 0)
            MARKET_DATA["banks"]["provincial"]["buy"] = market_data.get("pro_buy", 0)
            MARKET_DATA["banks"]["provincial"]["sell"] = market_data.get("pro_sell", 0)

            # Actualizamos RAM Principal
            if pm_buy > 0:
                MARKET_DATA["price"] = pm_buy
                MARKET_DATA["history"].append(pm_buy)
                # Alertas
                asyncio.create_task(check_alerts_async(context, pm_buy))
            
            # Guardar Snapshot Completo
            await asyncio.to_thread(
                save_arbitrage_snapshot,
                pm_buy, pm_sell,
                market_data.get("ban_buy", 0),
                market_data.get("mer_buy", 0),
                market_data.get("pro_buy", 0)
            )

            # --- LÓGICA DE PROTECCIÓN BCV ---
            # Si bcv_data falló (es 0), usamos lo que ya teníamos en memoria para no borrar la DB
            val_bcv_usd = 0
            val_bcv_eur = 0
            
            if isinstance(bcv_data, dict) and bcv_data.get("dolar", 0) > 0:
                val_bcv_usd = bcv_data.get("dolar")
                val_bcv_eur = bcv_data.get("euro")
                # Actualizamos la RAM con el dato fresco
                MARKET_DATA["bcv"] = bcv_data
            else:
                # Falló la conexión al BCV, usamos memoria RAM (Fallback)
                val_bcv_usd = MARKET_DATA["bcv"].get("dolar", 0)
                val_bcv_eur = MARKET_DATA["bcv"].get("euro", 0)

            # Guardamos Minería
            if pm_buy > 0:
                await asyncio.to_thread(save_mining_data, pm_buy, val_bcv_usd, pm_sell)

            # PERSISTENCIA (Para sobrevivir reinicios)
            await asyncio.to_thread(save_market_state, pm_buy, val_bcv_usd, val_bcv_eur)

        # 4. ACTUALIZAR FECHA
        # Formato unificado para evitar conflictos
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
        
        logging.info(f"🔄 Snapshot: PM={market_data.get('pm_buy'):.2f} | BCV={val_bcv_usd:.2f}")

    except Exception as e:
        logging.error(f"❌ Error Update Task: {e}")

# ==============================================================================
#  TAREA DE FONDO: REPORTE DIARIO AUTOMÁTICO
# ==============================================================================
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    # 1. Datos de la RAM
    price = MARKET_DATA.get("price")
    bcv_usd = MARKET_DATA.get("bcv", {}).get("dolar", 0)
    last_upd = MARKET_DATA.get("last_updated")

    if not price: return

    # 2. Conteo de hoy
    from database.stats import get_daily_requests_count
    consultas_hoy = await asyncio.to_thread(get_daily_requests_count)

    # 3. Elegir saludo según la hora de Caracas
    now = datetime.now(TIMEZONE)
    header = "☀️ <b>¡Buenos días! Así abre el mercado:</b>" if now.hour < 12 else "🌤 <b>Reporte de la Tarde:</b>"

    # 4. Formatear hora (Tu estilo de /precio)
    try:
        pretty_time = last_upd.astimezone(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p") if isinstance(last_upd, datetime) else str(last_upd)
    except:
        pretty_time = datetime.now(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")

    # 5. Construir mensaje
    brecha = ((price - bcv_usd) / bcv_usd) * 100 if bcv_usd > 0 else 0
    body = (
        f"<i>Promedio P2P (USDT)</i>\n\n🔥 <b>{price:,.2f} Bs</b>\n\n"
        f"🏛 <b>BCV:</b> {bcv_usd:,.2f} Bs\n📊 <b>Brecha:</b> {brecha:.2f}%\n"
        f"🏪 <b>Actualizado:</b> {pretty_time}\n👁 {consultas_hoy:,} consultas hoy"
    )

    # 6. Enviar a la cola del Worker
    from services.worker import queue_broadcast
    await asyncio.to_thread(queue_broadcast, f"{header}\n\n{body}")

# ==============================================================================
#  COMANDO PRINCIPAL: /PRECIO
# ==============================================================================
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/precio")
    
    binance = MARKET_DATA["price"]
    if not binance:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")
        return

    req_count = await asyncio.to_thread(get_daily_requests_count)
    
    # Texto
    msg = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
    
    # Botones
    markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, binance)
    
    # Growth Hacking
    if random.random() < 0.2:
        days, refs = await asyncio.to_thread(get_user_loyalty, user_id)
        if days > 3 and refs == 0:
            msg += "\n\n🎁 <i>¡Gana premios invitando amigos! Toca /referidos</i>"
    
    await update.message.reply_html(msg, reply_markup=markup, disable_web_page_preview=True)

# ==============================================================================
#  MAIN: EL CEREBRO DE ARRANQUE
# ==============================================================================
if __name__ == "__main__":
    # 1. Inicializar Base de Datos
    init_db()

    # --- CARGA SILENCIOSA DE MEMORIA ---
    # Recuperamos el último estado conocido antes de conectarnos
    try:
        print("💾 Buscando recuerdos en la Base de Datos...")
        last_state = load_last_market_state()
        
        if last_state:
            # Restauramos PRECIO
            if last_state.get("price") and last_state["price"] > 0:
                MARKET_DATA["price"] = last_state["price"]
            
            # Restauramos BCV (Vital para que no salga "No disponible")
            if last_state.get("bcv"):
                MARKET_DATA["bcv"] = last_state["bcv"]
            
            # Restauramos FECHA (Si es un objeto datetime, lo convertimos a string bonito)
            last_upd = last_state.get("last_updated")
            if last_upd:
                if isinstance(last_upd, datetime):
                    MARKET_DATA["last_updated"] = last_upd.strftime("%d/%m/%Y %I:%M:%S %p")
                else:
                    MARKET_DATA["last_updated"] = str(last_upd)
            
            print(f"✅ Memoria restaurada: Tasa={MARKET_DATA['price']} | BCV={MARKET_DATA['bcv'].get('dolar')} | Fecha={MARKET_DATA['last_updated']}")
        else:
            print("⚠️ Memoria vacía. Iniciando desde cero.")
            
    except Exception as e:
        print(f"⚠️ Error cargando memoria: {e}")
    # --- 1. VERIFICACIÓN DE TOKEN ---
    if not TOKEN:
        print("❌ Error: No hay TOKEN definido en las variables de entorno.")
        exit(1)
        
    # --- 2. CONSTRUCCIÓN DE LA APP ---
    # Esto crea la base del bot y el motor de alarmas (JobQueue)
    app = ApplicationBuilder().token(TOKEN).build()

    # --- 3. REGISTRO DE COMANDOS (Handlers) ---
    # Asegúrate de tener todos tus handlers aquí
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("precio", precio))
    app.add_handler(CommandHandler("mercado", mercado))
    # ... (añade aquí el resto de tus handlers como 'ia', 'stats', etc.)
    app.add_handler(CallbackQueryHandler(button_handler))

    # ==========================================================================
    # 4. CONFIGURACIÓN DEL RELOJ (JOB QUEUE) - LA CORRECCIÓN
    # ==========================================================================
    job_queue = app.job_queue  # <--- Aquí es donde se define 'job_queue' correctamente

    if job_queue:
        print("⏰ Configurando tareas programadas...")
        
        # Latido del corazón: para ver en logs que el bot sigue despierto
        job_queue.run_repeating(lambda ctx: logging.info("⏰ [RELOJ VIVO]"), interval=60, first=10)
        
        # Actualizador de precios: Refresca MARKET_DATA cada 5 minutos
        job_queue.run_repeating(update_price_task, interval=300, first=5)

        # REPORTE DIARIO: 09:00 AM
        job_queue.run_daily(
            send_daily_report, 
            time=dt_time(hour=9, minute=0, tzinfo=TIMEZONE),
            name="reporte_manana"
        )
        
        # REPORTE DIARIO: 01:00 PM (13:00)
        job_queue.run_daily(
            send_daily_report, 
            time=dt_time(hour=14, minute=25, tzinfo=TIMEZONE),
            name="reporte_tarde"
        )
        print("✅ Alarmas de las 09:00 AM y 13:00 PM activadas.")

    # --- 5. ENCENDER EL TRABAJADOR (WORKER) ---
    # Esto activa el archivo 'services/worker.py' para mandar mensajes masivos
    from services.worker import background_worker
    loop = asyncio.get_event_loop()
    loop.create_task(background_worker())

    # --- 6. INICIAR EL BOT ---
    print(f"🚀 Tasabinance Bot V51 INICIADO")
    
    # Si usas Webhook en Railway, aquí iría la lógica de run_webhook
    app.run_polling()
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
    app.add_handler(CommandHandler("horario", horario))
    app.add_handler(CommandHandler("stats_full", stats_full))
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(close_announcement, pattern="^delete_announcement$"))
    
    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    
    app.add_handler(CallbackQueryHandler(button_handler))


    print(f"🚀 Tasabinance Bot V51 (MODULAR + PERSISTENCIA) INICIADO")

    # 🔥 ENCENDER EL WORKER DE DIFUSIÓN 🔥
    loop = asyncio.get_event_loop()
    loop.create_task(background_worker())

    # --- MODO DE EJECUCIÓN ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL:
        PORT = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        print("📡 Iniciando modo POLLING...")
        app.run_polling()
