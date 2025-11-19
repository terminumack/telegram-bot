import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 1. Configurar Logging (Vital para ver errores en los logs de Railway)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 2. Obtener el token de forma segura
TOKEN = os.getenv("TOKEN")

# Función de comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("¡Hola! Soy tu bot funcionando en Railway 🚀")

# Tarea periódica
async def periodic_task(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.getenv("CHAT_ID")
    if chat_id:
        try:
            await context.bot.send_message(chat_id=chat_id, text="Mensaje periódico activo.")
        except Exception as e:
            logging.error(f"Error enviando mensaje periódico: {e}")

if __name__ == "__main__":
    # Validación temprana del token
    if not TOKEN:
        print("ERROR: La variable de entorno 'TOKEN' no está definida.")
        exit(1)

    # 3. Construir la aplicación
    app = ApplicationBuilder().token(TOKEN).build()

    # 4. Añadir manejadores
    app.add_handler(CommandHandler("start", start))

    # 5. Configurar JobQueue
    if app.job_queue:
        app.job_queue.run_repeating(periodic_task, interval=300, first=10)

    print("Bot iniciando con run_polling()...")
    
    # 6. EJECUCIÓN ROBUSTA
    # run_polling() se encarga de todo: bucle async, señales de stop y reconexión.
    # No necesitas asyncio.run() ni app.idle() aquí.
    app.run_polling()
