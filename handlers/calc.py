import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

# Imports de base de datos
from database.users import track_user
from database.stats import log_calc, log_activity

# ⚠️ CAMBIO CLAVE: Importamos la memoria RAM, no el servicio
from shared import MARKET_DATA

# Estados de la conversación
ESPERANDO_INPUT_USDT = 1
ESPERANDO_INPUT_BS = 2

async def calculate_conversion(update: Update, text_amount, currency_type):
    """Función auxiliar que hace la matemática usando memoria RAM."""
    
    # 1. LEER PRECIO DE MEMORIA (Instantáneo)
    rate = MARKET_DATA["price"]
    
    if not rate:
        await update.message.reply_text("⏳ Iniciando sistema... intenta en 5 segundos.")
        return ConversationHandler.END

    try:
        # Limpiar texto (Soporta formatos como "1.200,50" o "1200.50")
        clean_text = ''.join(c for c in text_amount if c.isdigit() or c in '.,')
        
        # Normalizar coma a punto para Python
        if ',' in clean_text and '.' in clean_text:
            # Caso complejo: 1.500,50 -> Quitamos punto, cambiamos coma
            clean_text = clean_text.replace('.', '').replace(',', '.')
        elif ',' in clean_text:
            clean_text = clean_text.replace(',', '.')
            
        amount = float(clean_text)
        
        # Guardar en DB (Log de uso)
        await asyncio.to_thread(log_calc, update.effective_user.id, amount, currency_type, 0)
        
        if currency_type == "USDT":
            total = amount * rate
            msg = f"🇺🇸 {amount:,.2f} USDT son:\n🇻🇪 <b>{total:,.2f} Bolívares</b>\n<i>(Tasa: {rate:,.2f})</i>"
        else: 
            total = amount / rate
            msg = f"🇻🇪 {amount:,.2f} Bs son:\n🇺🇸 <b>{total:,.2f} USDT</b>\n<i>(Tasa: {rate:,.2f})</i>"
            
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        
    except ValueError:
        await update.message.reply_text("🔢 Número inválido. Usa solo números (ej: 100 o 50.5)")
    
    return ConversationHandler.END

# --- HANDLERS DE INICIO ---

async def start_usdt_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    
    # Si el usuario escribió "/usdt 100"
    if context.args: 
        return await calculate_conversion(update, context.args[0], "USDT")
        
    await update.message.reply_text("🇺🇸 <b>Calculadora USDT:</b>\n\n¿Cuántos Dólares?\n<i>Escribe el número:</i>", parse_mode=ParseMode.HTML)
    return ESPERANDO_INPUT_USDT

async def start_bs_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/calc")
    
    # Si el usuario escribió "/bs 5000"
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

# --- DEFINICIÓN DE CONVERSACIONES ---

conv_usdt = ConversationHandler(
    entry_points=[CommandHandler("usdt", start_usdt_calc), CommandHandler("calc", start_usdt_calc)], # Alias /calc
    states={ESPERANDO_INPUT_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_usdt_input)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)

conv_bs = ConversationHandler(
    entry_points=[CommandHandler("bs", start_bs_calc)],
    states={ESPERANDO_INPUT_BS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bs_input)]},
    fallbacks=[CommandHandler("cancel", cancel)]
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
import logging

# Estados de la conversación
COMPRA, VENTA, COMISION = range(3)

async def start_p2p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso pidiendo el precio de compra."""
    # Limpiamos datos previos del usuario
    context.user_data.clear()
    
    await update.message.reply_text(
        "📊 <b>CALCULADORA P2P PRO</b>\n\n"
        "1️⃣ ¿A qué precio <b>COMPRASTE</b> los USDT? (en Bs)\n"
        "<i>Ejemplo: 54.50</i>",
        parse_mode=ParseMode.HTML
    )
    return COMPRA

async def get_buy_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el precio de compra."""
    try:
        # Limpieza de entrada (acepta comas y puntos)
        val = update.message.text.replace(',', '.')
        buy_p = float(val)
        context.user_data['buy_p'] = buy_p
        
        await update.message.reply_text(
            f"✅ Compra: <b>{buy_p:,.2f} Bs</b>\n\n"
            "2️⃣ ¿A qué precio vas a <b>VENDER</b>? (en Bs)\n"
            "<i>Ejemplo: 55.80</i>",
            parse_mode=ParseMode.HTML
        )
        return VENTA
    except ValueError:
        await update.message.reply_text("❌ Envía un número válido. Ejemplo: 54.50")
        return COMPRA

async def get_sell_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el precio de venta y muestra botones de comisión."""
    try:
        val = update.message.text.replace(',', '.')
        sell_p = float(val)
        context.user_data['sell_p'] = sell_p
        
        keyboard = [
            [
                InlineKeyboardButton("👤 0.10% (Normal)", callback_data="p2pfee_0.001"),
                InlineKeyboardButton("💎 0.35% (Verificado)", callback_data="p2pfee_0.0035")
            ],
            [InlineKeyboardButton("❌ Cancelar", callback_data="p2p_cancel")]
        ]
        
        await update.message.reply_text(
            f"✅ Venta: <b>{sell_p:,.2f} Bs</b>\n\n"
            "3️⃣ <b>Selecciona tu comisión de Binance:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return COMISION
    except ValueError:
        await update.message.reply_text("❌ Envía un número válido. Ejemplo: 55.80")
        return VENTA

async def finish_p2p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calcula el ROI final con lógica de alertas."""
    query = update.callback_query
    await query.answer()

    if query.data == "p2p_cancel":
        await query.message.edit_text("❌ Operación cancelada.")
        return ConversationHandler.END

    # Datos
    fee_rate = float(query.data.split('_')[1])
    buy_p = context.user_data['buy_p']
    sell_p = context.user_data['sell_p']

    # Lógica financiera en Bolívares
    comision_bs = sell_p * fee_rate
    venta_neta = sell_p - comision_bs
    ganancia_bs = venta_neta - buy_p
    roi = (ganancia_bs / buy_p) * 100

    # Determinar salud de la operación
    if roi <= 0:
        status = "⚠️ <b>ALERTA: OPERACIÓN EN PÉRDIDA</b>"
        emoji = "🔴"
        nota = "No es recomendable vender a este precio, pierdes dinero tras comisiones."
    elif roi < 0.4:
        status = "⚠️ <b>RENTABILIDAD BAJA</b>"
        emoji = "🟡"
        nota = "El margen es muy estrecho. Considera subir el precio de venta."
    else:
        status = "✅ <b>OPERACIÓN RENTABLE</b>"
        emoji = "🟢"
        nota = "Buen margen de ganancia para P2P."

    res_text = (
        f"{emoji} {status}\n"
        f"----------------------------------\n"
        f"📥 <b>Compra:</b> {buy_p:,.2f} Bs\n"
        f"📤 <b>Venta:</b> {sell_p:,.2f} Bs\n"
        f"💸 <b>Comisión:</b> -{comision_bs:,.4f} Bs\n"
        f"----------------------------------\n"
        f"✨ <b>Ganancia:</b> {ganancia_bs:,.4f} Bs/USDT\n"
        f"📈 <b>ROI Real:</b> {roi:.2f}%\n\n"
        f"💰 <b>Ganancia en 1.000$:</b> {ganancia_bs * 1000:,.2f} Bs\n"
        f"----------------------------------\n"
        f"💡 <i>{nota}</i>"
    )

    # Botón para repetir
    kb_final = [[InlineKeyboardButton("🔄 Nuevo Cálculo", callback_data="p2p_retry")]]
    
    await query.message.edit_text(
        res_text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=InlineKeyboardMarkup(kb_final)
    )
    return ConversationHandler.END

async def cancel_p2p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la conversación."""
    await update.message.reply_text("🔄 Calculadora cerrada.")
    return ConversationHandler.END
