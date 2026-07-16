import os
import logging
import asyncio
import urllib3
import random
from datetime import datetime, time as dt_time
import pytz
from handlers.exchange_admin import admin_actions, ganadores_mes, reiniciar_mes, confirmar_reset # <--- Agrega ganadores_mes
from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from handlers.calc import start_p2p, get_buy_price, get_sell_price, finish_p2p, cancel_p2p, COMPRA, VENTA, COMISION
from handlers.exchange_admin import campaign_stats
from handlers.calc import p2p_conv, meta_conv
from handlers.admin import comando_uso
from services.bcv_intervention import get_bcv_intervention


# --- 1. CONFIGURACIÓN DE ZONA HORARIA ---
TIMEZONE = pytz.timezone('America/Caracas')

# --- 2. IMPORTS DE MEMORIA Y BASE DE DATOS ---
from shared import MARKET_DATA
from database.users import track_user, get_user_loyalty
from database.setup import init_db
from database.stats import (
    get_daily_requests_count, 
    queue_broadcast, 
    save_mining_data, 
    save_market_state,       
    load_last_market_state,  
    save_arbitrage_snapshot,
    log_activity,
    update_daily_stats
)
from database.alerts import get_triggered_alerts
from handlers.exchange_user import exchange_conv_handler
from telegram.ext import CallbackQueryHandler  # <--- ASEGURA ESTA
from handlers import exchange_admin            # <--- Y ESTA

# --- 3. SERVICIOS ---
from services.binance_service import get_market_snapshot
from services.bcv_service import get_bcv_rates
from services.worker import background_worker 

# --- 4. UTILIDADES VISUALES ---
from utils.formatting import build_price_message, get_sentiment_keyboard

# --- 5. HANDLERS ---
# ⚠️ AQUÍ ESTABA EL ERROR: track_my_chat_member viene de commands, no de tracking
from handlers.commands import (
    start_command, help_command, grafico, referidos, 
    prediccion, stats, global_message, debug_mining, 
    stats_full, close_announcement, track_my_chat_member
)
from handlers.market import mercado
from handlers.analytics import horario
from handlers.callbacks import button_handler
from handlers.calc import conv_usdt, conv_bs 
from handlers.alerts import conv_alert, check_alerts_async
from handlers import exchange_admin
from handlers.commands import auditoria
from handlers.exchange_admin import db_diagnostic
# (Borramos la línea que decía 'from handlers.tracking import ...' porque ese archivo no existe)

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    ContextTypes, ChatMemberHandler, Application
)

# --- CONFIGURACIÓN DE LOGS ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - BOT - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TOKEN")

# ==============================================================================
#  SISTEMA: ARRANQUE SEGURO DEL WORKER (POST_INIT)
# ==============================================================================
async def post_init(application: Application):
    """
    Inicia el worker después de que el bot esté listo.
    Esto es CRÍTICO para evitar que se congele.
    """
    print("🔥 [SYSTEM] Encendiendo Worker en segundo plano...")
    asyncio.create_task(background_worker())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="🔥 Excepción atrapada:", exc_info=context.error)

# ==============================================================================
#  TAREA DE FONDO: ACTUALIZADOR DE PRECIOS
# ==============================================================================
async def update_price_task(context: ContextTypes.DEFAULT_TYPE):
    logging.warning("🚀 ¡ARRANCANDO WORKER! El bot se despertó para buscar precios...")
    try:
        logging.warning("⏳ 1. Entrando al escáner masivo (Esperando a Binance y BCV)...")
        # 1. ESCANEO MASIVO (Binance Multi-banco + BCV + Intervención)
        results = await asyncio.gather(
            get_market_snapshot(), 
            get_bcv_rates(),        
            get_bcv_intervention(), # 🔥 NUEVO: Escaneamos la intervención al mismo tiempo
            return_exceptions=True
        )
        logging.warning("✅ 2. ¡Salió del escáner masivo! Descargas terminadas.")
        
        
        market_data = results[0]
        bcv_data = results[1]
        interv_data = results[2] # 🔥 NUEVO: Atrapamos el resultado
        logging.warning(f"🚨 3. RADAR CHISMOSO: La caja interv_data trajo -> {interv_data}")

        # 2. PROCESAR BINANCE
        if isinstance(market_data, dict):
            pm_buy = market_data.get("pm_buy", 0)
            pm_sell = market_data.get("pm_sell", 0)
            
            # 🔥 LA BÓVEDA: Solo actualizamos la memoria si Binance trajo oro (mayor a 0)
            if pm_buy > 0:
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
                MARKET_DATA["price"] = pm_buy
                MARKET_DATA["history"].append(pm_buy)
                
                # Alertas
                asyncio.create_task(check_alerts_async(context, pm_buy))
            
            else:
                logging.warning("🛡️ Binance trajo ceros. Usando precios de la Bóveda Segura.")
                # Rescatamos el precio principal de la bóveda por si lo necesita la Base de Datos
                pm_buy = MARKET_DATA.get("price", 0)
            
            # Guardar Snapshot Completo en la DB usando los precios protegidos
            if pm_buy > 0:
                await asyncio.to_thread(
                    save_arbitrage_snapshot,
                    pm_buy, 
                    MARKET_DATA["banks"]["pm"]["sell"],
                    MARKET_DATA["banks"]["banesco"]["buy"],
                    MARKET_DATA["banks"]["mercantil"]["buy"],
                    MARKET_DATA["banks"]["provincial"]["buy"]
                )

            # --- LÓGICA DE PROTECCIÓN BCV ---
            val_bcv_usd = 0
            val_bcv_eur = 0
            
            if isinstance(bcv_data, dict) and bcv_data.get("dolar", 0) > 0:
                val_bcv_usd = bcv_data.get("dolar")
                val_bcv_eur = bcv_data.get("euro")
                MARKET_DATA["bcv"] = bcv_data
            else:
                # Fallback memoria
                val_bcv_usd = MARKET_DATA["bcv"].get("dolar", 0)
                val_bcv_eur = MARKET_DATA["bcv"].get("euro", 0)

            # 🔥 NUEVO: CÁLCULO DE INTERVENCIÓN IMPLÍCITA 🔥
            # Calculamos la matemática solo si el BCV y la intervención respondieron bien
            if isinstance(interv_data, dict) and interv_data.get("tasa_eur", 0) > 0:
                if val_bcv_usd > 0 and val_bcv_eur > 0:
                    paridad_interna = val_bcv_eur / val_bcv_usd
                    tasa_implicita_usd = interv_data["tasa_eur"] / paridad_interna
                    
                    MARKET_DATA["intervencion"] = {
                        "fecha": interv_data["fecha"],
                        "tasa_usd": round(tasa_implicita_usd, 2),
                        "tasa_eur": interv_data["tasa_eur"]
                    }

            # Guardamos Minería y Persistencia
            if pm_buy > 0:
                await asyncio.to_thread(save_mining_data, pm_buy, val_bcv_usd, pm_sell)
            
            await asyncio.to_thread(save_market_state, pm_buy, val_bcv_usd, val_bcv_eur)

        # 🔥 RECONEXIÓN DEL GRABADOR DE HISTORIAL 🔥
            # Esto guarda el dato para que la gráfica funcione mañana
            if pm_buy > 0:
                await asyncio.to_thread(update_daily_stats, pm_buy, val_bcv_usd)

        # 4. ACTUALIZAR FECHA
        now = datetime.now(TIMEZONE)
        MARKET_DATA["last_updated"] = now.strftime("%d/%m/%Y %I:%M:%S %p")
        
        logging.info(f"🔄 Snapshot: PM={market_data.get('pm_buy'):.2f} | BCV={val_bcv_usd:.2f}")

    except Exception as e:
        logging.error(f"❌ Error Update Task: {e}")
# ==============================================================================
#  TAREA DE FONDO: REPORTE DIARIO AUTOMÁTICO
# ==============================================================================
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    print("\n" + "="*40)
    print("👀 [DEBUG BOT] ¡Hora del reporte! Iniciando función...")

    now = datetime.now(TIMEZONE)
    hour = now.hour
    
    if hour < 12:
        text = (
            "☀️ <b>Apertura de Mercado</b>\n\n"
            "Ya tenemos las referencias del día para <b>Binance</b> y <b>BCV</b>.\n"
            "¿Amaneció estable o hubo repunte? Sal de dudas ahora.\n\n"
            "👇 <i>Toca el botón para ver la tasa en vivo:</i>"
        )
    else:
        text = (
            "🌤 <b>Tendencia de la Tarde</b>\n\n"
            "El <b>mercado</b> sigue activo. Revisa si hubo variaciones en "
            "<b>Binance</b> respecto a la mañana antes de cerrar tus pagos.\n\n"
            "👇 <i>Ver Precio Actualizado:</i>"
        )
    
    print(f"📝 [DEBUG BOT] Texto generado. Guardando en DB...")

    # Encolamos el mensaje para que el Worker lo procese
    enqueued = await asyncio.to_thread(queue_broadcast, text)
    
    if enqueued:
        print("✅ [DEBUG BOT] ¡ÉXITO! Mensaje encolado.")
    else:
        print("❌ [DEBUG BOT] ERROR CRÍTICO: No se pudo encolar.")
    
    print("="*40 + "\n")
# ==============================================================================
#  COMANDO L: /calculadoradeperdidas
# ==============================================================================

# 1. Creamos el manejador de la conversación
p2p_conv = ConversationHandler(
    entry_points=[
        CommandHandler('p2p', start_p2p),
        CallbackQueryHandler(start_p2p, pattern="p2p_retry") # Para que el botón de repetir funcione
    ],
    states={
        COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_buy_price)],
        VENTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sell_price)],
        COMISION: [CallbackQueryHandler(finish_p2p, pattern="^p2pfee_|^p2p_cancel")]
    },
    fallbacks=[CommandHandler('cancelar', cancel_p2p)],
    allow_reentry=True
)
# ==============================================================================
#  COMANDO PRINCIPAL: /PRECIO
# ==============================================================================
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🚀 VELOCIDAD 1: "Dispara y olvida" (Background tasks)
    # Mandamos a registrar al usuario y su actividad en segundo plano.
    # Al NO poner 'await' aquí, el bot NO se detiene a esperar a la base de datos.
    asyncio.create_task(asyncio.to_thread(track_user, update.effective_user))
    asyncio.create_task(asyncio.to_thread(log_activity, user_id, "/precio"))
    
    binance = MARKET_DATA["price"]
    if not binance:
        await update.message.reply_text("🔄 Iniciando sistema... intenta en unos segundos.")
        return

    # 🚀 VELOCIDAD 2: Paralelismo real
    # Mandamos a buscar los datos que sí necesitamos para armar el mensaje AL MISMO TIEMPO.
    req_count, markup = await asyncio.gather(
        asyncio.to_thread(get_daily_requests_count),
        asyncio.to_thread(get_sentiment_keyboard, user_id, binance)
    )
    
    # Texto (Asegúrate de que esta función no esconda peticiones a la DB por dentro)
    msg = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
    
    # Growth Hacking
    if random.random() < 0.2:
        # Esto queda igual, se ejecuta rápido solo el 20% de las veces
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
    try:
        print("💾 Buscando recuerdos en la Base de Datos...")
        last_state = load_last_market_state()
        
        if last_state:
            if last_state.get("price") and last_state["price"] > 0:
                MARKET_DATA["price"] = last_state["price"]
            if last_state.get("bcv"):
                MARKET_DATA["bcv"] = last_state["bcv"]
            last_upd = last_state.get("last_updated")
            if last_upd:
                if isinstance(last_upd, datetime):
                    MARKET_DATA["last_updated"] = last_upd.strftime("%d/%m/%Y %I:%M:%S %p")
                else:
                    MARKET_DATA["last_updated"] = str(last_upd)
            
            print(f"✅ Memoria restaurada: Tasa={MARKET_DATA.get('price')}")
        else:
            print("⚠️ Memoria vacía. Iniciando desde cero.")
            
    except Exception as e:
        print(f"⚠️ Error cargando memoria: {e}")
    
    if not TOKEN:
        print("❌ Error: No hay TOKEN definido.")
        exit(1)
        
    # 2. CONSTRUCCIÓN DEL BOT
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # --- REGISTRO DE COMANDOS ---
    app.add_handler(exchange_conv_handler)
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
    app.add_handler(CommandHandler("auditoria", auditoria))
    app.add_handler(CommandHandler("ganadores", ganadores_mes))
    app.add_handler(CommandHandler("reset_mes", reiniciar_mes))
    app.add_handler(CommandHandler("confirmar_reset", confirmar_reset))
    app.add_handler(CommandHandler("db_test", db_diagnostic))
    app.add_handler(p2p_conv)
    app.add_handler(CommandHandler('stats_mkt', campaign_stats))
    app.add_handler(meta_conv)
    app.add_handler(CommandHandler("uso", comando_uso))
    
    app.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(close_announcement, pattern="^delete_announcement$"))
    app.add_handler(CallbackQueryHandler(exchange_admin.admin_actions, pattern="^(claim|done|fail)_"))
    # En bot.py, agrega el import si hace falta:
# from handlers.exchange_admin import admin_notify_winner

# Y agrega el manejador:
    app.add_handler(CallbackQueryHandler(exchange_admin.admin_notify_winner, pattern="^notify_"))
    
    app.add_handler(conv_usdt)
    app.add_handler(conv_bs)
    app.add_handler(conv_alert)
    
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

   # --- TAREAS AUTOMÁTICAS ---
    jq = app.job_queue
    if jq:
        # 1. Tarea de precios
        jq.run_repeating(update_price_task, interval=60, first=5)
        
        # 2. Reportes Diarios (USAMOS TIMEZONE AQUÍ)
        jq.run_daily(send_daily_report, time=dt_time(hour=8, minute=00, tzinfo=TIMEZONE))
        jq.run_daily(send_daily_report, time=dt_time(hour=13, minute=0, tzinfo=TIMEZONE))

        print("\n📅 --- CONFIRMACIÓN DE HORARIOS ---")
        print("✅ Tareas de reporte programadas (08:00 y 13:00)")

    print(f"🚀 Tasabinance Bot V51 (RESTAURADO + ASÍNCRONO) INICIADO")

    # --- MODO DE EJECUCIÓN ---
  WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL:
        PORT = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(
            listen="0.0.0.0", 
            port=PORT, 
            url_path=TOKEN, 
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
            drop_pending_updates=True # 🔥 ESCUDO ACTIVADO PARA WEBHOOK
        )
    else:
        print("📡 Iniciando modo POLLING...")
        app.run_polling(drop_pending_updates=True) # 🔥 ESCUDO ACTIVADO PARA POLLING
