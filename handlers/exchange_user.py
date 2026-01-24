import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from database import exchange_db

# ESTADOS DE LA CONVERSACIÓN
SELECT_PAIR, ENTER_AMOUNT, CONFIRM_ORDER, UPLOAD_PROOF = range(4)

# ID del Grupo de Cajeros (Lo configuraremos después, por ahora pon tu ID o 0)
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0")) 

async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 1: El usuario escribe /cambio y ve los pares disponibles."""
    user = update.effective_user
    
    # Buscamos pares activos en la DB
    pairs = await asyncio.to_thread(exchange_db.get_active_pairs)
    
    if not pairs:
        await update.message.reply_text("⚠️ El servicio de cambios está cerrado o en mantenimiento.")
        return ConversationHandler.END

    keyboard = []
    for p in pairs:
        text = f"{p['currency_in']} ➡️ {p['currency_out']} (Tasa: {p['rate']})"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"pair_{p['id']}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    await update.message.reply_text(
        f"👋 Hola {user.first_name}, bienvenido al Exchange OTC.\n"
        "Selecciona qué deseas cambiar hoy:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_PAIR

async def pair_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 2: El usuario tocó un botón. Pedimos el monto."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Operación cancelada.")
        return ConversationHandler.END
    
    # Guardamos el ID del par seleccionado en memoria temporal
    pair_id = int(query.data.split("_")[1])
    context.user_data['pair_id'] = pair_id
    
    # Traemos info del par para mostrar límites
    pair_info = await asyncio.to_thread(exchange_db.get_pair_info, pair_id)
    context.user_data['pair_info'] = pair_info # Guardamos toda la info
    
    await query.edit_message_text(
        f"✅ Has seleccionado: <b>{pair_info['currency_in']} ➡️ {pair_info['currency_out']}</b>\n"
        f"💵 Tasa: {pair_info['rate']}\n"
        f"📉 Mínimo: {pair_info['min_amount']} | 📈 Máximo: {pair_info['max_amount']}\n\n"
        f"✍️ <b>Ingresa la cantidad de {pair_info['currency_in']} que deseas enviar:</b>\n"
        "(Solo el número, ejemplo: 100)",
        parse_mode="HTML"
    )
    return ENTER_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 3: Validamos el monto y mostramos la cotización."""
    try:
        amount_in = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("⚠️ Por favor ingresa un número válido (Ejemplo: 50.5)")
        return ENTER_AMOUNT

    pair = context.user_data['pair_info']
    
    # Validar límites
    if amount_in < float(pair['min_amount']) or amount_in > float(pair['max_amount']):
        await update.message.reply_text(
            f"⚠️ El monto debe estar entre {pair['min_amount']} y {pair['max_amount']}.\n"
            "Intenta de nuevo:"
        )
        return ENTER_AMOUNT

    # Calcular Salida
    # Lógica: Si Tasa es 0.90 y envías 100, recibes 90.
    amount_out = amount_in * float(pair['rate'])
    
    # Guardamos en memoria
    context.user_data['amount_in'] = amount_in
    context.user_data['amount_out'] = amount_out
    
    # Mostrar resumen y pedir confirmación
    keyboard = [
        [InlineKeyboardButton("✅ Confirmar y Pagar", callback_data="confirm")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ]
    
    await update.message.reply_text(
        f"🧮 <b>Cotización:</b>\n\n"
        f"📤 Envías: <b>{amount_in} {pair['currency_in']}</b>\n"
        f"📥 Recibes: <b>{amount_out:.2f} {pair['currency_out']}</b>\n\n"
        "¿Deseas proceder con esta operación?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CONFIRM_ORDER

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 4: Usuario aceptó. Mostramos cuenta y pedimos foto."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Operación cancelada.")
        return ConversationHandler.END

    pair_id = context.user_data['pair_id']
    
    # Buscamos dónde debe pagar el usuario
    wallet = await asyncio.to_thread(exchange_db.get_active_wallet, pair_id)
    
    msg = (
        f"🔒 <b>DATOS DE PAGO</b>\n"
        f"--------------------------\n"
        f"🏦 Destino: <code>{wallet}</code>\n"
        f"💰 Monto exacto: <b>{context.user_data['amount_in']}</b>\n"
        f"📝 Notas: {context.user_data['pair_info'].get('instructions', 'Sin notas')}\n"
        f"--------------------------\n\n"
        "📸 <b>Por favor, envía AHORA la captura de pantalla del pago.</b>\n"
        "O escribe /cancelar para salir."
    )
    
    await query.edit_message_text(msg, parse_mode="HTML")
    
    # AQUÍ CREAMOS LA ORDEN EN DB (Estado PENDING)
    # Pedimos el dato del usuario (email/wallet) después de la foto o asumimos username
    # Para simplificar V1, creamos la orden ya.
    user = query.from_user
    order_id = await asyncio.to_thread(
        exchange_db.create_exchange_order,
        user_id=user.id,
        pair_id=pair_id,
        amount_in=context.user_data['amount_in'],
        amount_out=context.user_data['amount_out'],
        rate=context.user_data['pair_info']['rate'],
        user_data=f"@{user.username}" if user.username else "Sin Alias"
    )
    
    context.user_data['current_order_id'] = order_id
    
    return UPLOAD_PROOF

import asyncio # Import necesario arriba, o asegúrate de que esté

async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 5: Recibimos la foto y notificamos al admin."""
    photo = update.message.photo[-1] # La foto más grande
    file_id = photo.file_id
    order_id = context.user_data.get('current_order_id')
    
    if not order_id:
        await update.message.reply_text("⚠️ Error de sesión. Inicia de nuevo.")
        return ConversationHandler.END

    # Actualizamos DB con la foto
    success = await asyncio.to_thread(exchange_db.add_proof_to_order, order_id, file_id)
    
    if success:
        await update.message.reply_text(
            f"✅ <b>¡Comprobante Recibido!</b>\n\n"
            f"Orden #{order_id} está en revisión.\n"
            "Te notificaremos en cuanto sea validada."
        , parse_mode="HTML")
        
        # --- AQUÍ NOTIFICARÍAMOS AL GRUPO DE ADMINS ---
        # (Lo implementaremos en el siguiente paso para no sobrecargar este archivo)
        # Por ahora solo imprime en consola
        print(f"🔔 NUEVA ORDEN #{order_id} LISTA PARA REVISIÓN")
        
    else:
        await update.message.reply_text("❌ Error guardando el comprobante. Contacta soporte.")

    return ConversationHandler.END

async def cancel_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancelación por comando."""
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# DEFINICIÓN DEL HANDLER PRINCIPAL
exchange_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('cambio', start_exchange)],
    states={
        SELECT_PAIR: [CallbackQueryHandler(pair_selected, pattern='^pair_')],
        ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        CONFIRM_ORDER: [CallbackQueryHandler(confirm_order)],
        UPLOAD_PROOF: [MessageHandler(filters.PHOTO, receive_proof)]
    },
    fallbacks=[
        CommandHandler('cancelar', cancel_exchange),
        CallbackQueryHandler(cancel_exchange, pattern='^cancel$')
    ]
)
