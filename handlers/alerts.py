import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

from database.users import track_user
from database.stats import log_activity
from database.alerts import add_alert

# ⚠️ CAMBIO CLAVE: Importamos la memoria RAM (Velocidad de la luz)
from shared import MARKET_DATA

# Estado
ESPERANDO_PRECIO_ALERTA = 1

async def process_alert_logic(update: Update, target):
    """Lógica interna para validar y guardar la alerta."""
    
    # 1. LEER PRECIO DE MEMORIA
    current_price = MARKET_DATA["price"]
    
    # Validación de seguridad si el bot acaba de arrancar
    if not current_price:
        await update.message.reply_text("⚠️ Esperando actualización de precios... intenta en 1 minuto.")
        return ConversationHandler.END

    # 2. Lógica de Dirección (Subida/Bajada)
    if target > current_price:
        condition = "ABOVE"
        msg = f"📈 <b>ALERTA DE SUBIDA</b>\n\nTe avisaré cuando el dólar <b>SUPERE</b> los {target:,.2f} Bs."
    elif target < current_price:
        condition = "BELOW"
        msg = f"📉 <b>ALERTA DE BAJADA</b>\n\nTe avisaré cuando el dólar <b>BAJE</b> de {target:,.2f} Bs."
    else:
        await update.message.reply_text(f"⚠️ El precio actual ya es {current_price:,.2f} Bs. Define un valor distinto para que la alerta tenga sentido.")
        return ConversationHandler.END

    # 3. Guardar en DB
    success = await asyncio.to_thread(add_alert, update.effective_user.id, target, condition)
    
    if success:
        await update.message.reply_text(f"✅ {msg}", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("⛔ <b>Límite alcanzado</b>\nSolo puedes tener 3 alertas activas al mismo tiempo.", parse_mode=ParseMode.HTML)
    
    return ConversationHandler.END

# --- HANDLERS ---

async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/alerta")
    
    # Caso directo: /alerta 600
    if context.args:
        try:
            # Limpieza básica de input (cambiar comas por puntos)
            clean_arg = context.args[0].replace(',', '.')
            target = float(clean_arg)
            return await process_alert_logic(update, target)
        except ValueError:
            await update.message.reply_text("🔢 Error: Ingresa un número válido.", parse_mode=ParseMode.HTML)
            return ConversationHandler.END

    # Caso interactivo: Preguntar precio
    await update.message.reply_text(f"🔔 <b>CONFIGURAR ALERTA</b>\n\n¿A qué precio quieres que te avise?\n\n<i>Escribe el monto abajo (Ej: 75.50):</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_PRECIO_ALERTA

async def process_alert_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        clean_text = update.message.text.replace(',', '.')
        target = float(clean_text)
        return await process_alert_logic(update, target)
    except ValueError:
        await update.message.reply_text("🔢 Por favor ingresa solo números válidos.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

# --- EXPORTAR ---

conv_alert = ConversationHandler(
    entry_points=[CommandHandler("alerta", start_alert)],
    states={ESPERANDO_PRECIO_ALERTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_alert_input)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)
