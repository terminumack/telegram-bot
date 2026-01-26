from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import exchange_db
import asyncio
import os

# ID del Grupo de Cajeros
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID") 

# --- 1. ENVIAR ALERTA AL GRUPO ---
async def notify_cashiers(context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    if not ADMIN_GROUP_ID:
        print("⚠️ ADMIN_GROUP_ID no configurado.")
        return

    ticket = await asyncio.to_thread(exchange_db.get_ticket_details, ticket_id)
    if not ticket: return

    # 🔥 MODO ANÓNIMO
    msg = (
        f"🚨 <b>SOLICITUD #{ticket['id']}</b>\n"
        f"👤 Cliente: <b>🔒 ANÓNIMO / OCULTO</b>\n"
        f"💰 Monto: <b>{ticket['initial_amount']} {ticket['pair_name']}</b>\n"
        f"--------------------------\n"
        f"¿Quién atiende?"
    )
    
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

# --- 2. ACCIONES DEL CAJERO (CON DEBUG) ---
async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("👉 CLICK DETECTADO") # Debug 1
    query = update.callback_query
    cashier = query.from_user
    data = query.data
    
    parts = data.split("_")
    action = parts[0]
    ticket_id = int(parts[1])
    
    print(f"👉 Acción: {action}, Ticket: {ticket_id}, Cajero: {cashier.first_name}") # Debug 2

    # CASO: RECLAMAR
    if action == "claim":
        print("👉 Intentando reclamar en DB...") # Debug 3
        success = await asyncio.to_thread(exchange_db.claim_ticket, ticket_id, cashier.id)
        print(f"👉 Resultado DB: {success}") # Debug 4
        
        if not success:
            print("👉 Falló el reclamo (Ticket ocupado o error DB)") 
            await query.answer("⚠️ Tarde. Alguien más ya tomó esta orden.", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return

        print("👉 Reclamo exitoso. Obteniendo detalles...") 
        ticket = await asyncio.to_thread(exchange_db.get_ticket_details, ticket_id)
        
        if not ticket:
            print("❌ ERROR: El ticket no devolvió datos (None)")
            return

        # Actualizar Grupo
        new_text_group = (
            f"🔒 <b>TICKET #{ticket_id} EN PROCESO</b>\n"
            f"👤 Cliente: <b>🔒 CONFIDENCIAL</b>\n"
            f"💰 <b>{ticket['initial_amount']} {ticket['pair_name']}</b>\n"
            f"👮‍♂️ Atendido por: {cashier.first_name}"
        )
        
        kb_close = [
            [InlineKeyboardButton("✅ CONCRETADO", callback_data=f"done_{ticket_id}")],
            [InlineKeyboardButton("❌ CANCELADO", callback_data=f"fail_{ticket_id}")]
        ]
        
        try:
            print("👉 Editando mensaje del grupo...") 
            await query.edit_message_text(new_text_group, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_close))
        except Exception as e:
            print(f"❌ ERROR editando grupo: {e}")

        # Enviar al Privado
        user_link = f"tg://user?id={ticket['user_id']}"
        private_msg = (
            f"✅ <b>Has tomado la Orden #{ticket_id}</b>\n"
            f"👤 <b>Cliente:</b> {ticket['user_username']}\n"
            f"💰 <b>Monto:</b> {ticket['initial_amount']} {ticket['pair_name']}\n"
        )
        kb_private = [[InlineKeyboardButton("💬 ABRIR CHAT CON CLIENTE", url=user_link)]]

        try:
            print(f"👉 Enviando DM a ID: {cashier.id}") 
            await context.bot.send_message(
                chat_id=cashier.id,
                text=private_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb_private)
            )
            print("👉 DM Enviado OK") 
            await query.answer("✅ Datos enviados a tu privado.")
            
        except Exception as e:
            print(f"❌ ERROR Enviando DM: {e}") 
            await query.answer("❌ ERROR: ¡Inicia el bot en privado!", show_alert=True)

        # Avisar al usuario
        try:
            cashier_link = f"tg://user?id={cashier.id}"
            await context.bot.send_message(
                chat_id=ticket['user_id'],
                text=f"🔔 <b>¡Tu cajero está listo!</b>\n👮‍♂️ <b>{cashier.first_name}</b> te atenderá.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💬 CHATEAR CON {cashier.first_name.upper()}", url=cashier_link)]])
            )
        except Exception: pass

    # CASO: CONCRETADO
    elif action == "done":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'COMPLETED')
        await query.edit_message_text(f"{query.message.text_html}\n\n✅ <b>FINALIZADO EXITOSAMENTE</b>", parse_mode="HTML")
        await query.answer("💰 Registrado como éxito")

    # CASO: CANCELADO
    elif action == "fail":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'CANCELED')
        await query.edit_message_text(f"{query.message.text_html}\n\n❌ <b>CANCELADO / NO CONCRETADO</b>", parse_mode="HTML")
        await query.answer("🗑 Cancelado")
