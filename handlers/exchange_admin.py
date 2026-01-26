async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("👉 CLICK DETECTADO") # Debug 1
    query = update.callback_query
    cashier = query.from_user
    data = query.data
    
    parts = data.split("_")
    action = parts[0]
    ticket_id = int(parts[1])
    print(f"👉 Acción: {action}, Ticket: {ticket_id}, Cajero: {cashier.first_name}") # Debug 2

    if action == "claim":
        print("👉 Intentando reclamar en DB...") # Debug 3
        success = await asyncio.to_thread(exchange_db.claim_ticket, ticket_id, cashier.id)
        print(f"👉 Resultado DB: {success}") # Debug 4
        
        if not success:
            print("👉 Falló el reclamo (Ticket ocupado o error DB)") # Debug 5
            await query.answer("⚠️ Tarde. Alguien más ya tomó esta orden.", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return

        print("👉 Reclamo exitoso. Obteniendo detalles...") # Debug 6
        ticket = await asyncio.to_thread(exchange_db.get_ticket_details, ticket_id)
        
        if not ticket:
            print("❌ ERROR: El ticket no devolvió datos (None)")
            return

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
            print("👉 Editando mensaje del grupo...") # Debug 7
            await query.edit_message_text(new_text_group, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_close))
        except Exception as e:
            print(f"❌ ERROR editando grupo: {e}")

        # Intentamos enviar al PRIVADO
        user_link = f"tg://user?id={ticket['user_id']}"
        private_msg = (
            f"✅ <b>Has tomado la Orden #{ticket_id}</b>\n"
            f"👤 <b>Cliente:</b> {ticket['user_username']}\n"
            f"💰 <b>Monto:</b> {ticket['initial_amount']} {ticket['pair_name']}\n"
        )
        kb_private = [[InlineKeyboardButton("💬 ABRIR CHAT CON CLIENTE", url=user_link)]]

        try:
            print(f"👉 Enviando DM a ID: {cashier.id}") # Debug 8
            await context.bot.send_message(
                chat_id=cashier.id,
                text=private_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb_private)
            )
            print("👉 DM Enviado OK") # Debug 9
            await query.answer("✅ Datos enviados a tu privado.")
            
        except Exception as e:
            print(f"❌ ERROR Enviando DM: {e}") # Debug 10
            await query.answer("❌ ERROR: ¡Inicia el bot en privado!", show_alert=True)

        # Avisar al usuario
        try:
            print(f"👉 Avisando al usuario {ticket['user_id']}...") # Debug 11
            cashier_link = f"tg://user?id={cashier.id}"
            await context.bot.send_message(
                chat_id=ticket['user_id'],
                text=f"🔔 <b>¡Tu cajero está listo!</b>\n👮‍♂️ <b>{cashier.first_name}</b> te atenderá.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💬 CHATEAR CON {cashier.first_name.upper()}", url=cashier_link)]])
            )
        except Exception as e:
            print(f"⚠️ No se pudo avisar al usuario (quizás bloqueó el bot): {e}")

    elif action == "done":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'COMPLETED')
        await query.edit_message_text(f"{query.message.text_html}\n\n✅ <b>FINALIZADO EXITOSAMENTE</b>", parse_mode="HTML")
        await query.answer("💰 Registrado como éxito")

    elif action == "fail":
        await asyncio.to_thread(exchange_db.close_ticket, ticket_id, 'CANCELED')
        await query.edit_message_text(f"{query.message.text_html}\n\n❌ <b>CANCELADO / NO CONCRETADO</b>", parse_mode="HTML")
        await query.answer("🗑 Cancelado")
