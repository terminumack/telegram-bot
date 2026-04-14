import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Importamos el motor optimizado
from database.stats import get_uso_diario_preciso

# 🔒 SEGURIDAD: Pon tu ID de Telegram aquí (puedes poner varios si tienes socios)
# Si no sabes tu ID, háblale a @userinfobot en Telegram
ADMIN_IDS = [123456789] # <--- REEMPLAZA ESTO CON TU ID REAL

async def comando_uso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Filtro de Seguridad (Si no eres tú, el bot te ignora silenciosamente)
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return 

    # 2. Mensaje de carga inicial (Solo si viene de escribir el comando)
    msg = None
    if not update.callback_query:
        msg = await update.message.reply_text("⏳ <i>Extrayendo métricas ultra rápidas...</i>", parse_mode=ParseMode.HTML)
    
    # 3. Obtener datos de la DB
    dau, total_queries, comandos_hoy = await asyncio.to_thread(get_uso_diario_preciso)
    
    # 4. Construir el reporte visual
    text = (
        f"📊 <b>MÉTRICAS DE USO (HOY)</b>\n"
        f"<i>Zona Horaria: Caracas</i>\n\n"
        f"👥 <b>DAU (Usuarios Únicos):</b> {dau:,}\n"
        f"🔄 <b>Total Interacciones:</b> {total_queries:,}\n"
    )
    
    if dau > 0:
        promedio = total_queries / dau
        text += f"⚡ <b>Promedio:</b> {promedio:.1f} acciones por usuario\n\n"
    else:
        text += "\n"

    text += "🕹️ <b>DESGLOSE DE COMANDOS:</b>\n"
    
    # Crear el gráfico de barras
    if comandos_hoy:
        max_usos = comandos_hoy[0][1] 
        for cmd, usos in comandos_hoy:
            bar_len = int((usos / max_usos) * 8) if max_usos > 0 else 0
            bar = "█" * bar_len + "░" * (8 - bar_len)
            porcentaje = (usos / total_queries) * 100 if total_queries > 0 else 0
            text += f"<code>{bar}</code> <b>{cmd}</b> ({usos:,} | {porcentaje:.1f}%)\n"
    else:
        text += "<i>Aún no hay interacciones hoy.</i>\n"

    # 5. Teclado de actualización
    kb = [[InlineKeyboardButton("🔄 Refrescar Métricas", callback_data="refresh_uso", api_kwargs={"style": "success"})]]
    markup = InlineKeyboardMarkup(kb)

    # 6. Enviar o editar
    try:
        if update.callback_query:
            await update.callback_query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            await update.callback_query.answer("Métricas actualizadas")
        else:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:
        pass # Ignorar si Telegram dice "El mensaje es igual" al refrescar rápido
