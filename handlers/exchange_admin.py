from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import exchange_db
import asyncio
import os

ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID") 

async def notify_cashiers(context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    # ... validaciones anteriores igual ...

    ticket = await asyncio.to_thread(exchange_db.get_ticket_details, ticket_id)
    if not ticket: return

    # 🔥 CAMBIO: Ocultamos el username
    msg = (
        f"🚨 <b>SOLICITUD #{ticket['id']}</b>\n"
        f"👤 Cliente: <b>🔒 ANÓNIMO</b>\n"  # <--- YA NO MOSTRAMOS EL NOMBRE
        f"💰 Monto: <b>{ticket['initial_amount']} {ticket['pair_name']}</b>\n"
        f"--------------------------\n"
        f"¿Quién atiende?"
    )
    
    # Botón para reclamar
    kb = [[InlineKeyboardButton("🙋‍♂️ YO ATIENDO", callback_data=f"claim_{ticket_id}")]]
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=msg,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        print(f"❌ Error enviando a admins: {e}")

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja Claim y Cierre."""
    query = update.callback_query
    cashier = query.from_user
    data = query.data
    
    parts = data.split("_")
    action = parts[0]
    ticket_id = int(parts[1])

    # 1. RECLAMAR
    if action == "claim":
        success = await asyncio.to_thread(exchange_db.claim_ticket, ticket_id, cashier.id)
        if not success:
            await query.answer("⚠️ Ya fue tomado.", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return

        # Buscamos datos para el link
        ticket = await asyncio.to_thread(exchange_db.get_ticket_details, ticket_id)
        
        # Botones de Cierre (Para después de hablar)
        kb_close = [
            [InlineKeyboardButton("✅ CONCRETADO", callback_data=f"done_{ticket_id}")],
            [InlineKeyboardButton("❌ CANCELADO", callback_data=f"fail_{ticket_id}")]
        ]

        # Editamos mensaje del grupo
        new_text = (
            f"🔒 <b>TICKET #{ticket_id} EN PROCESO</b>\n"
            f"👤 Cliente: {ticket['user_username']}\n"
            f"💰 <b>{ticket['initial_amount']} {ticket['pair_name']}</b>\n"
            f"👮‍♂️ Cajero: {cashier.first_name} (@{cashier.username})"
        )
        await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_close))
        
        # NOTIFICAMOS AL CLIENTE CON EL LINK DEL CAJERO
        # Construimos link seguro: tg://user?id=123 (Funciona en móvil y desktop)
        cashier_link = f"tg://user?id={cashier.id}"
        
        kb_user = [[InlineKeyboardButton(f"💬 CHATEAR CON {cashier.first_name.upper()}", url=cashier_link)]]
        
        try:
            await context.bot.send_message(
                chat_id=ticket['user_id'],
                text=f"🔔 <b>¡Tu cajero está listo!</b>\n\n"
                     f"👮‍♂️ <b>{cashier.first_name}</b> ha tomado tu orden.\n"
                     f"Toca el botón abajo para enviarle tus datos y coordinar el pago.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb_user)
            )
        except Exception: pass
        
        await query.answer("✅ Asignado. Cliente notificado.")

    # 2. CONCRETADO
    elif action == "done":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'COMPLETED')
        await query.edit_message_text(f"{query.message.text_html}\n\n✅ <b>FINALIZADO EXITOSAMENTE</b>", parse_mode="HTML")
        await query.answer("💰 Registrado como éxito")

    # 3. CANCELADO
    elif action == "fail":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'CANCELED')
        await query.edit_message_text(f"{query.message.text_html}\n\n❌ <b>CANCELADO / NO CONCRETADO</b>", parse_mode="HTML")
        await query.answer("🗑 Cancelado")
