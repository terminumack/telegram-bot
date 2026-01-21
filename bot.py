import os
import logging
import asyncio
from datetime import datetime, time as dt_time
import pytz

# --- IMPORTS DE TELEGRAM ---
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, 
    CallbackQueryHandler, ChatMemberHandler, Application
)

# --- IMPORTS DE TU ESTRUCTURA ---
from database.db import init_db
from database.memory import load_last_market_state
from shared import MARKET_DATA, TIMEZONE
from services.worker import background_worker  # <--- IMPORTANTE: Importamos el worker nuevo

# --- IMPORTS DE COMANDOS Y HANDLERS (Asegúrate de tenerlos todos) ---
from handlers.commands import start_command, help_command, precio, grafico, referidos, stats, global_message, debug_mining, mercado, horario, stats_full, prediccion
from handlers.callbacks import button_handler, close_announcement
from handlers.tracking import track_my_chat_member
from handlers.conversations import conv_usdt, conv_bs, conv_alert
from services.scheduler import update_price_task, send_daily_report, queue_broadcast

# Configuración
TOKEN = os.getenv("TOKEN")
logging.basicConfig(format='%(asctime)s - BOT - %(levelname)s - %(message)s', level=logging.INFO)

# En bot.py, agrega esto antes de post_init

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captura cualquier error que ocurra en el bot para que no crashee en silencio."""
    logging.error(msg="🔥 Excepción atrapada por el manejador global:", exc_info=context.error)
    # Opcional: Podrías mandarte un mensaje a ti mismo avisando del error
    # await context.bot.send_message(chat_id=TU_ID_DE_TELEGRAM, text=f"⚠️ Error: {context.error}")
# ==============================================================================
# 🔌 FUNCIÓN DE ARRANQUE SEGURO (POST_INIT)
# ==============================================================================
async def post_init(application: Application):
    """
    Se ejecuta justo antes de que el bot empiece a recibir mensajes.
    Es el lugar PERFECTO para encender el Worker sin bloquear nada.
    """
    print("🔥 [SYSTEM] Encendiendo Worker en segundo plano...")
    # Creamos la tarea en el mismo bucle del bot (Evita bloqueos)
    asyncio.create_task(background_worker())

# ==============================================================================
# 🏁 MAIN
# ==============================================================================
if __name__ == "__main__":
    # 1. Inicializar Base de Datos
    init_db()

    # --- CARGA SILENCIOSA DE MEMORIA ---
    try:
        print("💾 Buscando recuerdos en la Base de Datos...")
        last_state = load_last_market_state()
        
        if last_state:
            # Restauramos PRECIO
            if last_state.get("price") and last_state["price"] > 0:
                MARKET_DATA["price"] = last_state["price"]
            
            # Restauramos BCV
            if last_state.get("bcv"):
                MARKET_DATA["bcv"] = last_state["bcv"]
            
            # Restauramos FECHA
            last_upd = last_state.get("last_updated")
            if last_upd:
                if isinstance(last_upd, datetime):
                    MARKET_DATA["last_updated"] = last_upd.strftime("%d/%m/%Y %I:%M:%S %p")
                else:
                    MARKET_DATA["last_updated"] = str(last_upd)
            
            print(f"✅ Memoria restaurada: Tasa={MARKET_DATA.get('price')} | Fecha={MARKET_DATA.get('last_updated')}")
        else:
            print("⚠️ Memoria vacía. Iniciando desde cero.")
            
    except Exception as e:
        print(f"⚠️ Error cargando memoria: {e}")

    if not TOKEN:
        print("❌ Error: No hay TOKEN definido.")
        exit(1)
        
    # 2. CONSTRUCCIÓN DEL BOT (Con post_init)
    # Aquí agregamos .post_init(post_init) para vincular el worker
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

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
    app.add_error_handler(error_handler)

    # --- TAREAS AUTOMÁTICAS ---
    jq = app.job_queue
    if jq:
        # Tarea de precios
        jq.run_repeating(update_price_task, interval=60, first=5)
        
        # Horarios de Reporte
        job_morning = jq.run_daily(send_daily_report, time=dt_time(hour=9, minute=0, tzinfo=TIMEZONE))
        job_afternoon = jq.run_daily(send_daily_report, time=dt_time(hour=13, minute=0, tzinfo=TIMEZONE))

        # Verificación visual
        print("\n📅 --- CONFIRMACIÓN DE HORARIOS ---")
        print(f"☀️ Tarea Mañana (09:00): {job_morning}")
        print(f"🌤 Tarea Tarde  (13:00): {job_afternoon}")
        print("✅ Estado: PROGRAMADO CORRECTAMENTE.")
        print("----------------------------------\n")

    print(f"🚀 Tasabinance Bot V51 (MODULAR + PERSISTENCIA) INICIADO")

    # --- MODO DE EJECUCIÓN ---
    # YA NO usamos loop.create_task aquí abajo, lo maneja post_init arriba.
    
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    
    if WEBHOOK_URL:
        PORT = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Iniciando modo WEBHOOK en puerto {PORT}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{WEBHOOK_URL}/{TOKEN}")
    else:
        print("📡 Iniciando modo POLLING...")
        app.run_polling()
