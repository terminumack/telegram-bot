import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from database.stats import log_activity, get_referral_stats, queue_broadcast

# Imports de BD y Servicios
from database.users import track_user
from database.stats import log_activity, get_referral_stats
from database.db_pool import get_conn, put_conn
from utils.charts import generate_public_price_chart, generate_stats_chart

# Cache simple para no generar el gráfico cada vez que alguien le da click (dura 1 día)
GRAPH_CACHE = {"date": None, "photo_id": None}
ADMIN_ID = 6870992965 # Tu ID (puedes ponerlo en config.py luego)
EMOJI_SUBIDA = "🚀"
EMOJI_BAJADA = "📉"

# --- COMANDO: /grafico ---
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/grafico")
    
    global GRAPH_CACHE
    today_str = datetime.now().date().isoformat()
    
    # 1. Intentar usar cache (para velocidad)
    if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
        try:
            await update.message.reply_photo(
                photo=GRAPH_CACHE["photo_id"], 
                caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 <i>¡Compártelo en tus estados!</i>\n\n@tasabinance_bot", 
                parse_mode=ParseMode.HTML
            )
            return
        except Exception:
            GRAPH_CACHE["photo_id"] = None # Si falla (borraron la foto), regenerar
            
    # 2. Generar gráfico nuevo
    await update.message.reply_chat_action("upload_photo")
    img_buf = await asyncio.to_thread(generate_public_price_chart)
    
    if img_buf:
        msg = await update.message.reply_photo(
            photo=img_buf, 
            caption="📉 <b>Promedio Diario (Semanal)</b>\n\n<i>Precio promedio ponderado del día.</i>", 
            parse_mode=ParseMode.HTML
        )
        # Guardar en cache
        if msg.photo:
            GRAPH_CACHE["date"] = today_str
            GRAPH_CACHE["photo_id"] = msg.photo[-1].file_id
    else:
        await update.message.reply_text("📉 Recopilando datos históricos. Vuelve pronto.")

# --- COMANDO: /referidos ---
async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/referidos")
    
    count, rank, top_3 = await asyncio.to_thread(get_referral_stats, user_id)
    
    ranking_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(top_3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        clean_name = name.split()[0] if name else "Usuario"
        ranking_text += f"{medal} <b>{clean_name}</b> — {score} refs\n"
        
    invite_link = f"https://t.me/{context.bot.username}?start={user_id}"
    share_msg = f"🎁 ¡Gana 10 USDT con este bot! Entra aquí y participa:\n\n{invite_link}"
    share_url = f"https://t.me/share/url?url={share_msg}"
    
    keyboard = [[InlineKeyboardButton("📤 Comparte y Gana $10", url=share_url)]]
    
    text = (
        f"🎁 <b>PROGRAMA DE REFERIDOS (PREMIOS USDT)</b>\n\n"
        f"¡Gana dinero real invitando a tus amigos!\n"
        f"📅 <b>Corte y Pago:</b> Día 30 de cada mes.\n\n"
        f"🏆 <b>PREMIOS MENSUALES:</b>\n"
        f"🥇 1er Lugar: <b>$10 USDT</b>\n"
        f"🥈 2do Lugar: <b>$5 USDT</b>\n"
        f"🥉 3er Lugar: <b>$5 USDT</b>\n\n"
        f"👤 <b>TUS ESTADÍSTICAS:</b>\n"
        f"👥 Invitados: <b>{count}</b>\n"
        f"🏆 Tu Rango: <b>#{rank}</b>\n\n"
        f"🔗 <b>TU ENLACE ÚNICO:</b>\n<code>{invite_link}</code>\n"
        f"<i>(Toca para copiar y compartir)</i>\n\n"
        f"📊 <b>TOP 3 LÍDERES:</b>\n{ranking_text}\n"
        f"👇 <b>¡Compártelo ahora!</b>"
    )
    
    await update.message.reply_text(
        text, 
        parse_mode=ParseMode.HTML, 
        disable_web_page_preview=True, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- COMANDO: /ia (Predicción mejorada con DB) ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/ia")
    
    # Consultar historial reciente DB (Últimos 5 registros de minería)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT buy_pm FROM arbitrage_data ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            # La query trae del más nuevo al más viejo, invertimos para tener orden cronológico
            history = [r[0] for r in rows][::-1] 
    except Exception:
        history = []
    finally:
        put_conn(conn)

    if len(history) < 2:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nRecopilando datos suficientes.", parse_mode=ParseMode.HTML)
        return

    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: emoji, status, msg = EMOJI_SUBIDA, "ALCISTA FUERTE", "Subida rápida."
    elif percent > 0: emoji, status, msg = EMOJI_SUBIDA, "LIGERAMENTE ALCISTA", "Recuperación."
    elif percent < -0.5: emoji, status, msg = EMOJI_BAJADA, "BAJISTA FUERTE", "Caída rápida."
    elif percent < 0: emoji, status, msg = EMOJI_BAJADA, "LIGERAMENTE BAJISTA", "Corrección."
    else: emoji, status, msg = "⚖️", "LATERAL / ESTABLE", "Sin cambios."
    
    text = (
        f"🧠 <b>ANÁLISIS DE MERCADO (IA)</b>\n"
        f"<i>Tendencia basada en historial reciente.</i>\n\n"
        f"{emoji} <b>Estado:</b> {status}\n"
        f"📊 <b>Variación reciente:</b> {percent:.2f}%\n\n"
        f"💡 <b>Conclusión:</b>\n<i>{msg}</i>\n\n"
        f"⚠️ <i>No es consejo financiero.</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- COMANDO: /stats (Admin) ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    chart = await asyncio.to_thread(generate_stats_chart)
    
    if chart:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=chart, caption="📊 Reporte Admin", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Error generando gráfico.")

# --- COMANDO: /global (Enviar mensaje a todos) ---
async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    mensaje_original = update.message.text_html
    if mensaje_original.startswith('/global'):
        mensaje_final = mensaje_original.replace('/global', '', 1).strip()
    else: return

    if not mensaje_final:
        await update.message.reply_text("⚠️ Escribe el mensaje.", parse_mode=ParseMode.HTML)
        return

    await asyncio.to_thread(queue_broadcast, mensaje_final)
    await update.message.reply_text(f"✅ <b>Mensaje puesto en cola.</b>", parse_mode=ParseMode.HTML)

# --- COMANDO: /debug (Ver minería técnica) ---
async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM arbitrage_data ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        
        if row:
            # Ajusta los índices [1], [2] según las columnas de tu tabla real
            msg = (
                f"🕵️‍♂️ <b>DATA MINING DEBUG</b>\n\n"
                f"🕒 Data: {row[1] if len(row) > 1 else '?'}\n"
                f"📊 Spread: {row[7] if len(row) > 7 else 0}%\n"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ No hay data de minería aún.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error Debug: {e}")
    finally:
        put_conn(conn)
