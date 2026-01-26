from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from database import exchange_db
import asyncio

# ESTADOS
SELECT_CURRENCY, ENTER_AMOUNT = range(2)

async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los botones de monedas disponibles."""
    pairs = await asyncio.to_thread(exchange_db.get_menu_pairs)
    
    if not pairs:
        await update.message.reply_text("🔒 Servicio cerrado temporalmente.")
        return ConversationHandler.END

    # Creamos botones en filas de 2
    keyboard = []
    row = []
    for p_id, p_name in pairs:
        row.append(InlineKeyboardButton(p_name, callback_data=f"sel_{p_id}_{p_name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])

    await update.message.reply_text(
        "👋 <b>Mesa de Cambio OTC</b>\n"
        "Selecciona la moneda que deseas cambiar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return SELECT_CURRENCY

async def currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda la selección y pide monto."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END

    # Data viene como: sel_1_PayPal
    parts = query.data.split("_")
    pair_name = parts[2]
    context.user_data['pair_name'] = pair_name
    
    await query.edit_message_text(
        f"✅ Elegiste: <b>{pair_name}</b>\n\n"
        f"✍️ Escribe el monto total que deseas cambiar:\n"
        f"<i>(Solo números, ejemplo: 100)</i>",
        parse_mode="HTML"
    )
    return ENTER_AMOUNT

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Valida monto y crea el ticket."""
    text = update.message.text.replace(',', '.')
    try:
        amount = float(text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Por favor escribe un número válido (ej: 50).")
        return ENTER_AMOUNT

    pair_name = context.user_data['pair_name']
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name

    # CREAR TICKET EN DB
    ticket_id = await asyncio.to_thread(
        exchange_db.create_ticket, 
        user.id, username, pair_name, amount
    )

    if ticket_id:
        await update.message.reply_text(
            f"🎫 <b>Ticket #{ticket_id} Creado</b>\n\n"
            f"Estamos buscando un cajero disponible para procesar tus <b>{amount} {pair_name}</b>.\n"
            f"⏳ <i>Espera un momento, te notificaremos aquí mismo...</i>",
            parse_mode="HTML"
        )
        
        # 🔥 ALERTA A CAJEROS
        from handlers import exchange_admin
        asyncio.create_task(exchange_admin.notify_cashiers(context, ticket_id))
        
    else:
        await update.message.reply_text("❌ Error creando ticket.")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.")
    return ConversationHandler.END

exchange_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('cambio', start_exchange)],
    states={
        SELECT_CURRENCY: [CallbackQueryHandler(currency_selected, pattern='^sel_')],
        ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)]
    },
    fallbacks=[CommandHandler('cancelar', cancel), CallbackQueryHandler(cancel, pattern='^cancel$')]
)
