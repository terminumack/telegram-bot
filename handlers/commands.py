import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Imports de nuestra estructura
from shared import MARKET_DATA, TIMEZONE # <--- AGREGAR TIMEZONE
from database.users import track_user
from database.stats import (
    log_activity, 
    get_referral_stats, 
    queue_broadcast, 
    get_conn, put_conn,
    save_mining_data
)
from database.alerts import add_alert

# Importamos la lógica de gráficos (que crearemos en el paso 2)
from utils.charts import generate_public_price_chart, generate_stats_chart

# Configuración
ADMIN_ID = 533888411 
GRAPH_CACHE = {"date": None, "photo_id": None}
EMOJI_SUBIDA = "🚀"
EMOJI_BAJADA = "📉"

# --- COMANDO /START ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    user = update.effective_user
    
    args = context.args
    if args and args[0].isdigit() and int(args[0]) != user.id:
        pass

    await update.message.reply_html(
        f"👋 ¡Hola, {user.mention_html()}!\n\n"
        f"Soy el <b>Monitor de Tasa Binance Venezuela</b>.\n\n"
        f"💡 <b>Comandos:</b>\n"
        f"/precio - Monitor en tiempo real\n"
        f"/calc - Calculadora\n"
        f"/grafico - Tendencia semanal\n"
        f"/referidos - Gana premios\n"
        f"/ia - Predicción inteligente\n"
        f"/alerta - Avisos de precio"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 <b>Ayuda:</b>\n"
        "Usa /precio para ver tasas.\n"
        "Canal: @tasabinance_channel", 
        parse_mode=ParseMode.HTML
    )

# --- COMANDO /GRAFICO (Con Caché y Timezone) ---
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/grafico")
    
    global GRAPH_CACHE
    # USA TIMEZONE PARA QUE COINCIDA CON VENEZUELA
    today_str = datetime.now(TIMEZONE).date().isoformat()
    
    # 1. Intentar usar cache (Ruta Rápida)
    if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
        try:
            await update.message.reply_photo(
                photo=GRAPH_CACHE["photo_id"], 
                caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 @tasabinance_bot", 
                parse_mode=ParseMode.HTML
            )
            return
        except Exception:
            GRAPH_CACHE["photo_id"] = None
            
    # 2. Generar nuevo (Ruta Lenta)
    # Usamos chat_action en lugar de texto para que se vea "enviando foto..."
    await update.message.reply_chat_action("upload_photo")
    
    img_buf = await asyncio.to_thread(generate_public_price_chart)
    
    if img_buf:
        sent_msg = await update.message.reply_photo(
            photo=img_buf, 
            caption="📉 <b>Promedio Diario (Semanal)</b>\n\n<i>Precio promedio ponderado.</i>", 
            parse_mode=ParseMode.HTML
        )
        
        if sent_msg.photo:
            GRAPH_CACHE["date"] = today_str
            GRAPH_CACHE["photo_id"] = sent_msg.photo[-1].file_id
    else:
        await update.message.reply_text("⚠️ No hay suficientes datos históricos.")

# --- COMANDO /REFERIDOS ---
async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    
    count, rank, top_3 = await asyncio.to_thread(get_referral_stats, user_id)
    
    ranking_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(top_3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        clean_name = name.split()[0] if name else "Usuario"
        ranking_text += f"{medal} <b>{clean_name}</b> — {score} refs\n"
        
    invite_link = f"https://t.me/{context.bot.username}?start={user_id}"
    share_url = f"https://t.me/share/url?url={invite_link}"
    
    text = (
        f"🎁 <b>PROGRAMA DE REFERIDOS</b>\n\n"
        f"👥 Invitados: <b>{count}</b> | 🏆 Rango: <b>#{rank}</b>\n\n"
        f"🔗 <b>TU ENLACE:</b>\n<code>{invite_link}</code>\n\n"
        f"📊 <b>TOP LÍDERES:</b>\n{ranking_text}"
    )
    
    kb = [[InlineKeyboardButton("📤 Compartir Enlace", url=share_url)]]
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)

# --- COMANDO /IA ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    
    conn = get_conn()
    history = []
    try:
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT buy_pm FROM arbitrage_data ORDER BY id DESC LIMIT 5")
                rows = cur.fetchall()
                history = [r[0] for r in rows][::-1] 
    except Exception: pass
    finally: put_conn(conn)

    if len(history) < 2:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>", parse_mode=ParseMode.HTML)
        return

    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: emoji, status = EMOJI_SUBIDA, "ALCISTA FUERTE"
    elif percent > 0: emoji, status = EMOJI_SUBIDA, "LIGERAMENTE ALCISTA"
    elif percent < -0.5: emoji, status = EMOJI_BAJADA, "BAJISTA FUERTE"
    elif percent < 0: emoji, status = EMOJI_BAJADA, "LIGERAMENTE BAJISTA"
    else: emoji, status = "⚖️", "LATERAL / ESTABLE"
    
    await update.message.reply_html(
        f"🧠 <b>ANÁLISIS IA</b>\n\n"
        f"{emoji} <b>Estado:</b> {status}\n"
        f"📊 <b>Variación:</b> {percent:.2f}%\n"
        f"⚠️ <i>No es consejo financiero.</i>"
    )

async def alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔔 Usa el menú para configurar alertas.")

# --- COMANDOS ADMIN ---
# En handlers/commands.py
from database.stats import get_detailed_report_text # <--- IMPORTA LA NUEVA FUNCION

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    # Usamos la función poderosa que acabamos de crear
    report = await asyncio.to_thread(get_detailed_report_text)
    
    # Si tienes el gráfico de stats activo, úsalo, si no, solo manda el texto
    await update.message.reply_html(report)

async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = update.message.text.replace('/global', '').strip()
    if text:
        await asyncio.to_thread(queue_broadcast, text)
        await update.message.reply_text("✅ Mensaje en cola.")

async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM arbitrage_data ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        if row: await update.message.reply_html(f"🕵️‍♂️ <b>Debug:</b>\nData: {row}")
        else: await update.message.reply_text("❌ No data.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")
    finally: put_conn(conn)

# --- EVENTOS DE USUARIO ---
from telegram import ChatMember

async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Detecta cuando un usuario bloquea o desbloquea el bot.
    Actualiza el estado en la base de datos para métricas reales.
    """
    if not update.my_chat_member: return
    
    user_id = update.my_chat_member.from_user.id
    new_status = update.my_chat_member.new_chat_member.status
    
    # Definir estado
    db_status = 'active'
    if new_status in [ChatMember.BANNED, ChatMember.LEFT, ChatMember.KICKED]:
        db_status = 'blocked'
    
    # Actualizar DB
    conn = get_conn() # Asegúrate de tener get_conn importado arriba
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET status = %s WHERE user_id = %s", (db_status, user_id))
            conn.commit()
    except Exception as e:
        logging.error(f"Error tracking chat member: {e}")
    finally:
        put_conn(conn)
