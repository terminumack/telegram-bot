from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import exchange_db
import asyncio

# --- CONFIGURACIÓN ---
# ⚠️ IMPORTANTE: Aquí debes poner el ID de tu grupo privado de cajeros.
# Si no lo tienes, el bot intentará enviar el mensaje pero fallará si no está en el grupo.
# Puedes ponerlo en una variable de entorno o "hardcodearlo" aquí temporalmente.
import os
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID") 

# --- NOTIFICACIÓN (Se llama desde exchange_user.py) ---

async def notify_new_order(context: ContextTypes.DEFAULT_TYPE, order_id: int):
    """Envía la alerta al grupo de cajeros."""
    if not ADMIN_GROUP_ID:
        print("⚠️ ADMIN_GROUP_ID no configurado. No se envió alerta.")
        return

    # 1. Buscamos datos de la orden
    order = await asyncio.to_thread(exchange_db.get_order_details, order_id)
    if not order: return

    # 2. Preparamos el mensaje
    msg = (
        f"🔔 <b>NUEVA ORDEN #{order['id']}</b>\n"
        f"👤 Usuario: {order['user_data']}\n"
        f"-----------------------------\n"
        f"📉 Vende: <b>{order['amount_in']} {order['currency_in']}</b>\n"
        f"📈 Recibe: <b>{order['amount_out']} {order['currency_out']}</b>\n"
        f"-----------------------------\n"
        f"⚠️ Estado: <b>PENDIENTE DE REVISIÓN</b>"
    )

    # 3. Botón para reclamar (Locking)
    keyboard = [[InlineKeyboardButton("👮‍♂️ ATENDER ORDEN", callback_data=f"adm_claim_{order_id}")]]

    # 4. Enviamos la foto al grupo
    try:
        if order['proof_file_id']:
            await context.bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=order['proof_file_id'],
                caption=msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        print(f"❌ Error enviando alerta a admins: {e}")

# --- MANEJO DE BOTONES (Handlers) ---

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los clics en el grupo de cajeros."""
    query = update.callback_query
    cashier = query.from_user
    data = query.data
    
    # adm_claim_1050 -> action="claim", order_id="1050"
    parts = data.split("_")
    action = parts[1]
    order_id = int(parts[2])

    # 1. ACCIÓN: RECLAMAR (ATENDER)
    if action == "claim":
        success = await asyncio.to_thread(exchange_db.assign_cashier, order_id, cashier.id)
        
        if success:
            # Editamos el mensaje para mostrar botones de decisión
            new_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ APROBAR", callback_data=f"adm_approve_{order_id}"),
                    InlineKeyboardButton("❌ RECHAZAR", callback_data=f"adm_reject_{order_id}")
                ]
            ])
            # Actualizamos el caption conservando la foto
            current_caption = query.message.caption_html if query.message.caption else query.message.text_html
            new_caption = current_caption.replace("PENDIENTE DE REVISIÓN", f"🔒 EN PROCESO por {cashier.first_name}")
            
            await query.edit_message_caption(caption=new_caption, reply_markup=new_markup, parse_mode="HTML")
            await query.answer(f"🔒 Orden asignada a ti, {cashier.first_name}")
        else:
            await query.answer("⚠️ Esta orden ya fue tomada por otro cajero.", show_alert=True)
            # Quitamos el botón si ya fue tomada
            await query.edit_message_reply_markup(reply_markup=None)

    # 2. ACCIÓN: APROBAR
    elif action == "approve":
        # Marcamos en DB
        await asyncio.to_thread(exchange_db.close_order, order_id, "COMPLETED")
        
        # Editamos mensaje del grupo
        final_caption = query.message.caption_html.split("-----------------------------")[0]
        final_caption += f"\n✅ <b>FINALIZADA por {cashier.first_name}</b>"
        
        await query.edit_message_caption(caption=final_caption, reply_markup=None, parse_mode="HTML")
        await query.answer("✅ Orden completada.")
        
        # 🔥 NOTIFICAR AL USUARIO ORIGINAL
        # Necesitamos el ID del usuario. Lo buscamos en la DB.
        order_details = await asyncio.to_thread(exchange_db.get_order_details, order_id)
        if order_details:
            try:
                await context.bot.send_message(
                    chat_id=order_details['user_id'],
                    text=f"✅ <b>¡TU ORDEN #{order_id} HA SIDO COMPLETADA!</b>\n\n"
                         f"Hemos enviado tus fondos ({order_details['amount_out']} {order_details['currency_out']}).\n"
                         f"Gracias por confiar en nosotros.",
                    parse_mode="HTML"
                )
            except Exception:
                pass # El usuario quizás bloqueó el bot, no podemos hacer nada.

    # 3. ACCIÓN: RECHAZAR
    elif action == "reject":
        # Marcamos en DB
        await asyncio.to_thread(exchange_db.close_order, order_id, "REJECTED", "Rechazada por Admin")
        
        final_caption = query.message.caption_html.split("-----------------------------")[0]
        final_caption += f"\n❌ <b>RECHAZADA por {cashier.first_name}</b>"
        
        await query.edit_message_caption(caption=final_caption, reply_markup=None, parse_mode="HTML")
        await query.answer("❌ Orden rechazada.")
        
        # Notificar usuario
        order_details = await asyncio.to_thread(exchange_db.get_order_details, order_id)
        if order_details:
            try:
                await context.bot.send_message(
                    chat_id=order_details['user_id'],
                    text=f"❌ <b>ORDEN #{order_id} RECHAZADA</b>\n\n"
                         f"El comprobante no es válido o no se recibió el pago.\n"
                         f"Si crees que es un error, contacta a soporte.",
                    parse_mode="HTML"
                )
            except Exception: pass
