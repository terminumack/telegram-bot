from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import exchange_db
import asyncio
import os
from telegram.constants import ParseMode 
from database.stats import get_admin_winners

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
        
        # 🔥 NUEVO: VERIFICACIÓN DE CAJERO OCUPADO
        # Antes de nada, preguntamos si ya tiene trabajo pendiente.
        active_ticket_id = await asyncio.to_thread(exchange_db.get_active_ticket_by_cashier, cashier.id)
        
        if active_ticket_id:
            # Si tiene una orden abierta, LO PARAMOS AQUÍ.
            await query.answer(
                f"⛔ ¡Alto ahí!\n\nTienes la Orden #{active_ticket_id} sin cerrar.\nTermina esa primero.", 
                show_alert=True
            )
            return
            
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

async def ganadores_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando secreto para ver a quién pagar."""
    
    # Seguridad básica: Si quieres, valida que sea tu ID
    # if update.effective_user.id != TU_ID: return

    winners = await asyncio.to_thread(get_admin_winners)
    
    if not winners:
        await update.message.reply_text("🤷‍♂️ No hay referidos todavía.")
        return

    msg = "🏆 **GANADORES PARA PAGAR (ADMIN)** 🏆\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (uid, uname, name, count) in enumerate(winners):
        medal = medals[i] if i < 3 else "🏅"
        
        # Link directo al chat del usuario
        user_link = f"tg://user?id={uid}"
        alias = f"@{uname}" if uname else "🚫 Sin Alias"
        
        msg += f"{medal} <b>{name}</b> ({alias})\n"
        msg += f"   └ 🆔 ID: <code>{uid}</code>\n"
        msg += f"   └ 👥 Refs: {count}\n"
        msg += f"   └ 💬 <a href='{user_link}'>CONTACTAR PARA PAGO</a>\n\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def ganadores_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de pagos con enlace directo al chat del usuario."""
    
    # Buscamos en la DB
    winners = await asyncio.to_thread(get_admin_winners)
    
    if not winners:
        await update.message.reply_text("🤷‍♂️ No hay datos de referidos para mostrar.")
        return

    msg = "🏆 **LISTA DE PAGOS (ADMIN)** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    # Desempaquetamos: ID, Nombre, Cantidad
    for i, (uid, name, count) in enumerate(winners):
        medal = medals[i] if i < len(medals) else "🏅"
        
        # Si el nombre viene vacío de la DB, ponemos "Usuario"
        safe_name = name if name else "Usuario"
        
        # 🔥 EL TRUCO MÁGICO: Enlace directo por ID
        # Esto abre el chat privado aunque no tenga @alias
        magic_link = f"tg://user?id={uid}"
        
        msg += f"{medal} <b>{safe_name}</b>\n"
        msg += f"   └ 🆔 ID: <code>{uid}</code>\n"
        msg += f"   └ 👥 Refs: {count}\n"
        msg += f"   └ 💬 <a href='{magic_link}'>CONTACTAR PARA PAGAR</a>\n\n"

    await update.message.reply_text(msg, parse_mode="HTML")
