from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from database import exchange_db
import asyncio

# ESTADOS DEL FLUJO
SELECT_CURRENCY, ENTER_AMOUNT = range(2)

async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 1: Muestra el menú de monedas + Otros."""
    user = update.effective_user
    
    # Buscamos las monedas activas en la DB
    pairs = await asyncio.to_thread(exchange_db.get_menu_pairs)
    
    if not pairs:
        await update.message.reply_text("🔒 El servicio de cambios está cerrado temporalmente.")
        return ConversationHandler.END

    # Construimos los botones en filas de 2
    keyboard = []
    row = []
    for p_id, p_name in pairs:
        # El callback lleva el ID y el Nombre para usarlo después
        row.append(InlineKeyboardButton(p_name, callback_data=f"sel_{p_id}_{p_name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    # 🔥 Botón Cancelar (Funcional)
    keyboard.append([InlineKeyboardButton("❌ Cancelar Operación", callback_data="cancel")])

    await update.message.reply_text(
        f"👋 Hola <b>{user.first_name}</b>,\n"
        "Selecciona qué deseas cambiar hoy:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return SELECT_CURRENCY

async def currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 2: Procesa la selección del botón."""
    query = update.callback_query
    await query.answer() # Importante para que no cargue infinito
    
    # 🔥 ARREGLO DEL BOTÓN CANCELAR
    # Verificamos esto PRIMERO, antes de intentar leer IDs
    if query.data == "cancel":
        await query.edit_message_text("❌ Operación cancelada. Puedes iniciar de nuevo con /cambio")
        return ConversationHandler.END

    # Si no es cancelar, entonces es una moneda: "sel_ID_NOMBRE"
    try:
        parts = query.data.split("_")
        # parts[0] = "sel", parts[1] = ID, parts[2] = Nombre
        pair_name = parts[2]
        context.user_data['pair_name'] = pair_name
        
        # Mensaje personalizado si eligen "Otros"
        if "Otros" in pair_name or "Consultar" in pair_name:
             msg = (
                f"✅ Has seleccionado: <b>{pair_name}</b>\n\n"
                f"✍️ Por favor escribe un <b>monto estimado</b> del valor que deseas cambiar (en USD).\n"
                f"<i>(O escribe 1 si solo quieres consultar)</i>"
            )
        else:
            msg = (
                f"✅ Has seleccionado: <b>{pair_name}</b>\n\n"
                f"✍️ Escribe el <b>monto total</b> que deseas cambiar:\n"
                f"<i>(Solo números, ejemplo: 100)</i>"
            )
        
        await query.edit_message_text(msg, parse_mode="HTML")
        return ENTER_AMOUNT
        
    except Exception as e:
        # Por si acaso ocurre un error raro al leer el botón
        print(f"Error seleccionando moneda: {e}")
        await query.edit_message_text("❌ Error en la selección. Intenta de nuevo con /cambio")
        return ConversationHandler.END

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 3: Recibe el monto y crea el ticket."""
    text = update.message.text.replace(',', '.')
    
    # Validación simple de números
    try:
        amount = float(text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Por favor escribe un número válido (ej: 50).")
        return ENTER_AMOUNT

    pair_name = context.user_data.get('pair_name', 'Desconocido')
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
            f"Estamos buscando un cajero disponible para atender tu solicitud de:\n"
            f"💰 <b>{amount} {pair_name}</b>\n\n"
            f"⏳ <i>Espera un momento, te notificaremos aquí mismo...</i>",
            parse_mode="HTML"
        )
        
        # 🔥 ALERTA A CAJEROS (Llamamos al admin)
        from handlers import exchange_admin
        asyncio.create_task(exchange_admin.notify_cashiers(context, ticket_id))
        
    else:
        await update.message.reply_text("❌ Error del sistema creando el ticket. Intenta más tarde.")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancelación por comando /cancelar."""
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# DEFINICIÓN DEL HANDLER
exchange_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('cambio', start_exchange)],
    states={
        SELECT_CURRENCY: [CallbackQueryHandler(currency_selected)], # Quitamos el patrón regex para que capture TODO, incluido "cancel"
        ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)]
    },
    fallbacks=[
        CommandHandler('cancelar', cancel),
        # Este fallback ayuda si el usuario escribe /cancelar en medio del proceso
        CallbackQueryHandler(cancel, pattern='^cancel$') 
    ]
)
