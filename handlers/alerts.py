import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

from database.users import track_user
from database.stats import log_activity
from database.alerts import add_alert # Asegúrate de haber creado este archivo con la lógica nueva

# Importamos la memoria RAM
from shared import MARKET_DATA

# Estado para ConversationHandler
ESPERANDO_PRECIO_ALERTA = 1

async def process_alert_logic(update: Update, target):
    """Lógica interna para validar y guardar la alerta con límites Premium."""
    
    # 1. LEER PRECIO DE MEMORIA
    current_price = MARKET_DATA["price"]
    
    # Validación de seguridad
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
        await update.message.reply_text(f"⚠️ El precio actual ya es {current_price:,.2f} Bs. Define un valor distinto.")
        return ConversationHandler.END

    # 3. Guardar en DB (Manejo de estados)
    # add_alert ahora devuelve: "SUCCESS", "LIMIT_REACHED" o "ERROR"
    result = await asyncio.to_thread(add_alert, update.effective_user.id, target, condition)
    
    if result == "SUCCESS":
        await update.message.reply_text(f"✅ {msg}", parse_mode=ParseMode.HTML)

    elif result == "LIMIT_REACHED":
        # --- AQUÍ ESTÁ EL MENSAJE DE VENTA PREMIUM ---
        text = (
            "🚫 <b>Límite de Alertas Alcanzado (3/3)</b>\n\n"
            "Los usuarios gratuitos solo pueden tener <b>3 alertas activas</b>.\n\n"
            "💎 <b>¡Pásate a PREMIUM!</b>\n"
            "• 🔔 Hasta <b>20 Alertas</b> simultáneas.\n"
            "• 🏦 Alertas de Arbitraje (Bancos).\n"
            "• ⚡ Soporte Prioritario.\n\n"
            "🔜 <i>Suscripción automática con Binance Pay próximamente.</i>"
        )
        await update.message.reply_html(text)

    else:
        await update.message.reply_text("⚠️ Error de base de datos. Intenta más tarde.")
    
    return ConversationHandler.END

# --- HANDLERS ---

async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/alerta")
    
    # Caso directo: /alerta 600
    if context.args:
        try:
            clean_arg = context.args[0].replace(',', '.')
            target = float(clean_arg)
            return await process_alert_logic(update, target)
        except ValueError:
            await update.message.reply_text("🔢 Error: Ingresa un número válido.", parse_mode=ParseMode.HTML)
            return ConversationHandler.END

    # Caso interactivo
    await update.message.reply_text(
        f"🔔 <b>CONFIGURAR ALERTA</b>\n\n¿A qué precio quieres que te avise?\n\n<i>Escribe el monto abajo (Ej: 75.50):</i>", 
        parse_mode=ParseMode.HTML
    )
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
