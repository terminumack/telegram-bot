import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Imports de nuestra estructura
from shared import MARKET_DATA
from database.users import track_user

# 1. AQUÍ ESTABA EL ERROR: Quitamos generate_stats_chart de aquí
from database.stats import (
    log_activity, 
    get_referral_stats, 
    queue_broadcast, 
    get_conn, put_conn,
    save_mining_data
)
from database.alerts import add_alert

# 2. Y LO PONEMOS AQUÍ (Junto con generate_public_price_chart)
from utils.charts import generate_public_price_chart, generate_stats_chart

# Configuración
ADMIN_ID = 533888411 # Tu ID real
GRAPH_CACHE = {"date": None, "photo_id": None}
EMOJI_SUBIDA = "🚀"
EMOJI_BAJADA = "📉"

# --- COMANDO /START ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    user = update.effective_user
    
    # Lógica de referidos (si viene con ?start=123)
    args = context.args
    if args and args[0].isdigit() and int(args[0]) != user.id:
        # Aquí podrías agregar la lógica para registrar el referido si track_user no lo hace automático
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

# --- COMANDO /GRAFICO (Con Caché de tu extras.py) ---
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/grafico")
    
    global GRAPH_CACHE
    today_str = datetime.now().date().isoformat()
    
    # 1. Intentar usar cache
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
            
    # 2. Generar nuevo
    msg = await update.message.reply_text("📊 Generando gráfico...")
    img_buf = await asyncio.to_thread(generate_public_price_chart)
    
    if img_buf:
        sent_msg = await update.message.reply_photo(
            photo=img_buf, 
            caption="📉 <b>Promedio Diario (Semanal)</b>\n\n<i>Precio promedio ponderado.</i>", 
            parse_mode=ParseMode.HTML
        )
        await msg.delete()
        
        if sent_msg.photo:
            GRAPH_CACHE["date"] = today_str
            GRAPH_CACHE["photo_id"] = sent_msg.photo[-1].file_id
    else:
        await msg.edit_text("⚠️ No hay suficientes datos históricos.")

# --- COMANDO /REFERIDOS (Completo de tu extras.py) ---
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

# --- COMANDO /IA (Conexión a BD Real) ---
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    
    # Consultar historial DB
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

# --- COMANDO /ALERTA (Básico, por si falla el avanzado) ---
async def alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔔 Usa el menú para configurar alertas.")

# --- COMANDOS ADMIN ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    # Asegúrate de importar generate_stats_chart desde utils.charts
    # chart = await asyncio.to_thread(generate_stats_chart)
    # if chart: await context.bot.send_photo(ADMIN_ID, chart)
    await update.message.reply_text("📊 Stats Admin (Gráfico pendiente de config).")

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
