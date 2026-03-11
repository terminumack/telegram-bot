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
    """Inicia el proceso. Maneja tanto el comando /p2p como el botón de reintento."""
    context.user_data.clear()
    
    texto_bienvenida = (
        "📊 <b>CALCULADORA DE GANANCIAS P2P</b>\n\n"
        "Esta herramienta calcula cuánto dinero real queda en tu bolsillo después de las comisiones de Binance.\n\n"
        "1️⃣ ¿A qué precio <b>COMPRASTE</b> los USDT?\n"
        "<i>Ejemplo: 54.50</i>"
    )

    # Si viene del botón "Nuevo Cálculo"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.edit_text(texto_bienvenida, parse_mode=ParseMode.HTML)
    else:
        # Si viene del comando /p2p escrito
        await update.message.reply_html(texto_bienvenida)
        
    return COMPRA

async def get_buy_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el precio de compra."""
    try:
        val = update.message.text.replace(',', '.')
        buy_p = float(val)
        context.user_data['buy_p'] = buy_p
        
        await update.message.reply_html(
            f"✅ Compraste a: <b>{buy_p:,.2f} Bs</b>\n\n"
            "2️⃣ ¿A qué precio vas a <b>VENDER</b>?\n"
            "<i>Ejemplo: 55.80</i>"
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
        
        await update.message.reply_html(
            f"✅ Vas a vender a: <b>{sell_p:,.2f} Bs</b>\n\n"
            "3️⃣ <b>¿Qué tipo de anuncio vas a usar?</b>\n"
            "Selecciona tu comisión de Binance para finalizar:"
            , reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return COMISION
    except ValueError:
        await update.message.reply_text("❌ Envía un número válido. Ejemplo: 55.80")
        return VENTA

async def finish_p2p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calcula el resultado final con el nuevo diseño limpio."""
    query = update.callback_query
    await query.answer()

    if query.data == "p2p_cancel":
        await query.message.edit_text("❌ Operación cancelada.")
        return ConversationHandler.END

    # Datos base
    fee_rate = float(query.data.split('_')[1])
    buy_p = context.user_data['buy_p']
    sell_p = context.user_data['sell_p']

    # Cálculos financieros
    comision_bs = sell_p * fee_rate
    ganancia_neta = sell_p - comision_bs - buy_p
    roi = (ganancia_neta / buy_p) * 100
    ganancia_1000 = ganancia_neta * 1000

    # Determinar salud de la operación
    if roi <= 0:
        status_text = "¡OPERACIÓN EN PÉRDIDA!"
        emoji = "🔴"
        nota = "No vendas a este precio, estarías perdiendo dinero."
    elif roi < 0.5:
        status_text = "RENTABILIDAD BAJA"
        emoji = "🟡"
        nota = "El margen es muy pequeño. Considera subir el precio."
    else:
        status_text = "¡OPERACIÓN EXITOSA!"
        emoji = "🟢"
        nota = "Tienes un excelente margen de ganancia."

    # --- NUEVO DISEÑO LIMPIO Y ENTENDIBLE ---
    res_text = (
        f"{emoji} <b>{status_text}</b>\n"
        f"----------------------------------\n"
        f"📥 <b>Compraste a:</b> <code>{buy_p:,.2f} Bs</code>\n"
        f"📤 <b>Vendiste a:</b> <code>{sell_p:,.2f} Bs</code>\n"
        f"💸 <b>Comisión de Binance:</b> <code>-{comision_bs:,.2f} Bs</code>\n"
        f"----------------------------------\n"
        f"💵 <b>TU GANANCIA REAL:</b>\n"
        f"👉 <b>{ganancia_neta:,.2f} Bs</b> por cada USDT\n\n"
        f"📈 <b>Rentabilidad:</b> <code>{roi:.2f}%</code>\n"
        f"💰 <b>Si mueves 1.000 USDT ganas:</b>\n"
        f"✨ <code>{ganancia_1000:,.2f} Bolívares</code>\n"
        f"----------------------------------\n"
        f"💡 <i>{nota}</i>"
    )

    kb_final = [[InlineKeyboardButton("🔄 Nuevo Cálculo", callback_data="p2p_retry")]]
    
    await query.message.edit_text(
        res_text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=InlineKeyboardMarkup(kb_final)
    )
    return ConversationHandler.END

async def cancel_p2p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la conversación."""
    # Como cancel_p2p puede venir del botón (CallbackQuery), lo validamos:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text("🔄 Calculadora cerrada.")
    else:
        await update.message.reply_text("🔄 Calculadora cerrada.")
    return ConversationHandler.END
