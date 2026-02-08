from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import exchange_db
import asyncio
import os
from telegram.constants import ParseMode 
from database.stats import get_admin_winners
from database.db_pool import get_conn, put_conn

# ID del Grupo de Cajeros
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID") 

def exec_query(query, params=None, fetch=False):
    """Función auxiliar para ejecutar queries rápidamente."""
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if fetch:
                return cur.fetchall()
            conn.commit()
            return True
    except Exception as e:
        print(f"Error en exec_query: {e}")
        return None
    finally:
        put_conn(conn)

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
    """
    Envía una tarjeta individual por cada ganador.
    Permite 'Notificar' automáticamente si el enlace manual falla.
    """
    winners = await asyncio.to_thread(get_admin_winners) # Asegúrate de importar get_admin_winners
    
    if not winners:
        await update.message.reply_text("🤷‍♂️ No hay ganadores para mostrar.")
        return

    await update.message.reply_text("🏆 **PANEL DE PAGOS (ADMIN)** 🏆\n<i>Enviando fichas de los Top 5...</i>", parse_mode="HTML")

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    for i, (uid, name, count) in enumerate(winners):
        medal = medals[i] if i < len(medals) else "🏅"
        safe_name = name if name else "Usuario"
        
        # Texto de la tarjeta
        msg = (
            f"{medal} <b>{safe_name}</b>\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"👥 Referidos: {count}"
        )
        
        # Botones de Acción
        # 1. Enlace manual (El que ya tenías)
        # 2. Botón "🔔 AVISARLE" (Para que el bot le escriba)
        kb = [
            [InlineKeyboardButton("💬 INTENTAR ABRIR CHAT", url=f"tg://user?id={uid}")],
            [InlineKeyboardButton("🔔 ENVIAR NOTIFICACIÓN", callback_data=f"notify_{uid}")]
        ]

        if uid < 0: # Si es un grupo
             msg += "\n⚠️ <b>ES UN GRUPO/CANAL</b>"
             kb = [] # Sin botones

        await update.message.reply_text(
            msg, 
            parse_mode="HTML", 
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def admin_notify_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Envía un mensaje al ganador con un botón para que TE escriba a ti.
    """
    query = update.callback_query
    await query.answer() # Detenemos el reloj de carga

    # 1. Obtenemos el ID del ganador del botón (notify_12345)
    target_user_id = int(query.data.split("_")[1])
    
    # ⚠️ CONFIGURACIÓN IMPORTANTE ⚠️
    # Escribe aquí TU usuario personal (sin el @) para que te escriban a ti.
    # Ejemplo: Si eres @CarlosCrypto, pon "CarlosCrypto"
    ADMIN_USERNAME = "@tasabinancesoporte" 

    # 2. Mensaje que recibirá el Ganador
    msg_to_winner = (
        f"🎉 <b>¡FELICIDADES!</b> 🎉\n\n"
        f"Has ganado uno de los premios mensuales por referidos de <b>TasaBinance</b>.\n\n"
        f"👇 <b>IMPORTANTE:</b>\n"
        f"Toca el botón de abajo para escribirme directamente y coordinar la entrega de tu premio en USDT."
    )
    
    # 3. El botón mágico (Abre tu chat privado)
    kb_winner = [
        [InlineKeyboardButton("💬 RECLAMAR PREMIO AHORA", url=f"https://t.me/tasabinancesoporte")]
    ]

    # 4. Intentamos enviar el mensaje
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=msg_to_winner,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb_winner)
        )
        
        # Si funciona: Actualizamos tu panel de admin con ✅
        await query.edit_message_text(
            text=f"{query.message.text_html}\n\n✅ <b>NOTIFICACIÓN ENVIADA</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        # Si falla (Bot bloqueado o usuario eliminado): Actualizamos con ❌
        print(f"❌ Error notificando ganador {target_user_id}: {e}")
        await query.edit_message_text(
            text=f"{query.message.text_html}\n\n❌ <b>FALLÓ EL ENVÍO</b>\n(El usuario bloqueó al bot)",
            parse_mode="HTML"
        )

from database.stats import reset_referral_counts # Importar arriba

async def reiniciar_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando peligroso: Reinicia los referidos."""
    user_id = update.effective_user.id
    
    # ⚠️ SEGURIDAD: Pon aquí TU ID para que nadie más pueda usarlo
    MY_ADMIN_ID = 533888411  # <--- CAMBIA ESTO POR TU ID
    
    if user_id != MY_ADMIN_ID:
        return # Ignoramos a los curiosos

    # Obtenemos el argumento (Ej: /reset_mes Enero-2026)
    # Si no escribe nada, usamos el mes pasado automático
    args = context.args
    if args:
        periodo = args[0]
    else:
        # Calculamos el mes anterior automáticamente (para el nombre del archivo)
        hoy = datetime.now()
        mes_anterior = hoy.replace(day=1) - timedelta(days=1)
        periodo = mes_anterior.strftime("%B-%Y") # Ej: January-2026

    await update.message.reply_text(f"⚠️ **ATENCIÓN** ⚠️\n\nEstás a punto de reiniciar los contadores de referidos para el periodo: **{periodo}**.\n\nLos datos actuales se guardarán en el historial y los usuarios volverán a 0.\n\nEscribe `/confirmar_reset {periodo}` para proceder.")

async def confirmar_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ejecuta el reseteo real."""
    user_id = update.effective_user.id
    MY_ADMIN_ID = 533888411 # <--- CAMBIA ESTO POR TU ID
    
    if user_id != MY_ADMIN_ID: return

    try:
        periodo = context.args[0]
    except IndexError:
        await update.message.reply_text("❌ Falta el nombre del periodo.")
        return

    # EJECUTAMOS LA FUNCIÓN DE LA DB
    success, msg = await asyncio.to_thread(reset_referral_counts, periodo)
    
    await update.message.reply_text(msg)

import time
from telegram import Update
from telegram.ext import ContextTypes
from database.stats import get_conn, put_conn # Usa tus funciones actuales

async def db_diagnostic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mide el rendimiento real de la base de datos."""
    user_id = update.effective_user.id
    # Tu ID de seguridad
    if user_id != 533888411: return 

    status_msg = await update.message.reply_text("⏳ Iniciando diagnóstico de alto rendimiento...")

    try:
        # --- 1. TEST DE CONEXIÓN ---
        start_conn = time.perf_counter()
        conn = get_conn()
        end_conn = time.perf_counter()
        conn_time = (end_conn - start_conn) * 1000 # Convertir a ms

        if not conn:
            await status_msg.edit_text("❌ Error: No se pudo establecer conexión.")
            return

        # --- 2. TEST DE BÚSQUEDA (Buscando entre 19k) ---
        start_query = time.perf_counter()
        with conn.cursor() as cur:
            # Buscamos al propio admin para ver cuánto tarda en hallarlo
            cur.execute("SELECT first_name FROM users WHERE user_id = %s", (user_id,))
            cur.fetchone()
        end_query = time.perf_counter()
        query_time = (end_query - start_query) * 1000

        put_conn(conn)

        # --- 3. RESULTADOS ---
        total_time = conn_time + query_time
        
        # Interpretación de salud
        salud = "🟢 EXCELENTE" if total_time < 150 else "🟡 NORMAL" if total_time < 500 else "🔴 LENTO"

        reporte = (
            f"🖥 **DIAGNÓSTICO DE BASE DE DATOS**\n\n"
            f"🔌 **Conexión:** `{conn_time:.2f} ms`\n"
            f"🔍 **Consulta (19k filas):** `{query_time:.2f} ms`\n"
            f"⏱ **Latencia Total:** `{total_time:.2f} ms`\n\n"
            f"📊 **Estado:** {salud}\n\n"
            f"💡 _Tip: Si la conexión supera los 300ms, el Pool es obligatorio._"
        )
        await status_msg.edit_text(reporte, parse_mode="Markdown")

    except Exception as e:
        await status_msg.edit_text(f"❌ Fallo en el test: {e}")

async def campaign_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # SEGURIDAD: Solo tu ID
    if update.effective_user.id != 533888411: return

    # Consulta que clasifica a los 19,105 usuarios según su origen real
    query = """
        SELECT 
            CASE 
                WHEN referred_by IS NOT NULL THEN 'Sistema de Referidos 👥'
                WHEN source IS NOT NULL AND source != 'organico' THEN UPPER(source) || ' 📢'
                ELSE 'Búsqueda Orgánica 🏠'
            END as canal,
            COUNT(*) as total 
        FROM users 
        GROUP BY canal 
        ORDER BY total DESC;
    """
    
    results = exec_query(query, fetch=True)

    # Consulta extra para los nuevos de hoy (Opcional, pero muy útil)
    query_today = "SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE;"
    res_today = exec_query(query_today, fetch=True)
    hoy = res_today[0][0] if res_today else 0

    text = "📊 <b>REPORTE ESTRATÉGICO DE CRECIMIENTO</b>\n"
    text += "----------------------------------\n"
    
    total_general = 0
    if results:
        for canal, count in results:
            text += f"🔹 <b>{canal}</b>: <code>{count:,}</code>\n"
            total_general += count
    
    text += "----------------------------------\n"
    text += f"✨ <b>Nuevos hoy:</b> <code>+{hoy} usuarios</code>\n"
    text += f"📈 <b>Total registrado:</b> <code>{total_general:,}</code>"

    await update.message.reply_html(text)
