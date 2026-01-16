import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

from database.users import track_user
from database.stats import log_calc, log_activity
from services.binance_service import get_binance_price

# Estados de la conversación
ESPERANDO_INPUT_USDT = 1
ESPERANDO_INPUT_BS = 2

async def calculate_conversion(update: Update, text_amount, currency_type):
    """Función auxiliar que hace la matemática."""
    # Obtenemos precio rápido (de memoria/cache)
    rate = await get_binance_price() 
    
    if not rate:
        await update.message.reply_text("⏳ Actualizando tasas... intenta en unos segundos.")
        return ConversationHandler.END

    try:
        # Limpiar texto (cambiar comas por puntos, quitar letras)
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        amount = float(clean_text.replace(',', '.'))
        
        # Guardar en DB
        await asyncio.to_thread(log_calc, update.effective_user.id, amount, currency_type, 0)
        
        if currency_type == "USDT":
            total = amount * rate
            msg = f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>"
        else: 
            total = amount / rate
            msg = f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>"
            
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        
    except ValueError:
        await update.message.reply_text("🔢 Número inválido.")
    
    return ConversationHandler.END

# --- HANDLERS DE INICIO ---

async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    
    if context.args: 
        return await calculate_conversion(update, context.args[0], "USDT")
        
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Cuántos Dólares?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    
    if context.args: 
        return await calculate_conversion(update, context.args[0], "BS")
        
    await update.message.reply_text("🇻🇪 <b>Calculadora Bolívares:</b>\n\n¿Cuántos Bs?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_BS

async def process_usdt_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await calculate_conversion(update, update.message.text, "USDT")

async def process_bs_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await calculate_conversion(update, update.message.text, "BS")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

# --- DEFINICIÓN DE CONVERSACIONES (Para exportar al bot) ---

conv_usdt = ConversationHandler(
    entry_points=[CommandHandler("usdt", start_usdt_calc)],
    states={ESPERANDO_INPUT_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_usdt_input)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)

conv_bs = ConversationHandler(
    entry_points=[CommandHandler("bs", start_bs_calc)],
    states={ESPERANDO_INPUT_BS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bs_input)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)
