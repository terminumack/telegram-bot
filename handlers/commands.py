import logging
import asyncio
import random
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

# Imports Propios
from shared import MARKET_DATA
from utils.formatting import build_price_message, EMOJI_SUBIDA, EMOJI_BAJADA, EMOJI_STATS
from utils.charts import generate_public_price_chart, generate_stats_chart
from database.stats import (
    log_activity, 
    get_detailed_report_text, 
    queue_broadcast, 
    get_referral_stats,
    save_mining_data
)
from database.users import track_user
from database.alerts import add_alert

ADMIN_ID = 533888411 # Asegúrate que este sea tu ID real o usa os.getenv

# --- COMANDOS BÁSICOS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    user = update.effective_user
    await update.message.reply_html(
        f"👋 ¡Hola, {user.mention_html()}!\n\n"
        f"Soy el <b>Monitor de Tasa Binance Venezuela</b>.\n\n"
        f"💡 <b>Comandos:</b>\n"
        f"/precio - Monitor en tiempo real\n"
        f"/calc - Calculadora (conversión)\n"
        f"/ia - Predicción de tendencia\n"
        f"/grafico - Historial visual\n"
        f"/alerta - Configurar aviso de precio\n"
        f"/referidos - Gana premios invitando"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🆘 <b>Ayuda:</b>\nUsa /precio para ver tasas.\nSoporte: @tasabinancesoporte", parse_mode=ParseMode.HTML)

# --- COMANDOS AVANZADOS (Rescatados de tu bot.py) ---

async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ia"""
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/ia")
    
    history = MARKET_DATA["history"]
    if len(history) < 5:
        await update.message.reply_text("🧠 <b>Calibrando IA...</b>\nNecesito más datos históricos recientes.", parse_mode=ParseMode.HTML)
        return

    start_p, end_p = history[0], history[-1]
    # Evitamos división por cero
    if start_p == 0: start_p = end_p 
    
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: emoji, status = EMOJI_SUBIDA, "ALCISTA FUERTE 🚀"
    elif percent > 0: emoji, status = EMOJI_SUBIDA, "LIGERAMENTE ALCISTA ↗️"
    elif percent < -0.5: emoji, status = EMOJI_BAJADA, "BAJISTA FUERTE 📉"
    elif percent < 0: emoji, status = EMOJI_BAJADA, "LIGERAMENTE BAJISTA ↘️"
    else: emoji, status = "⚖️", "LATERAL / ESTABLE"
    
    text = (f"🧠 <b>ANÁLISIS DE TENDENCIA (IA)</b>\n\n"
            f"{emoji} <b>Estado:</b> {status}\n"
            f"{EMOJI_STATS} <b>Variación reciente:</b> {percent:.2f}%\n\n"
            f"⚠️ <i>Basado en el historial de las últimas horas.</i>")
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /grafico"""
    msg = await update.message.reply_text("📊 <b>Generando gráfico...</b>", parse_mode=ParseMode.HTML)
    try:
        chart = await asyncio.to_thread(generate_public_price_chart)
        if chart:
            await update.message.reply_photo(chart, caption="📈 <b>Tendencia Dólar (7 Días)</b>")
            await msg.delete()
        else:
            await msg.edit_text("⚠️ No hay suficientes datos para graficar aún.")
    except Exception:
        await msg.edit_text("❌ Error generando imagen.")

async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /referidos"""
    user_id = update.effective_user.id
    count, rank, top3 = await asyncio.to_thread(get_referral_stats, user_id)
    
    text = (f"🤝 <b>SISTEMA DE REFERIDOS</b>\n\n"
            f"👥 Has invitado a: <b>{count} usuarios</b>\n"
            f"🏆 Tu Ranking Global: <b>#{rank}</b>\n\n"
            f"🔗 <b>Tu enlace de invitación:</b>\n"
            f"<code>https://t.me/{context.bot.username}?start={user_id}</code>\n\n"
            f"🏆 <b>Top 3 Líderes:</b>\n")
            
    for i, (name, cnt) in enumerate(top3, 1):
        text += f"{i}. {name}: {cnt} refs\n"
        
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- COMANDOS ADMIN ---

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /stats (Admin)"""
    if update.effective_user.id != ADMIN_ID: return
    
    report = await asyncio.to_thread(get_detailed_report_text)
    # chart = await asyncio.to_thread(generate_stats_chart) # Si tienes esta funcion actívala
    
    await update.message.reply_text(report, parse_mode=ParseMode.HTML)

async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /global mensaje"""
    if update.effective_user.id != ADMIN_ID: return
    
    text = update.message.text.replace('/global', '').strip()
    if not text:
        await update.message.reply_text("⚠️ Escribe el mensaje a difundir.")
        return
        
    await asyncio.to_thread(queue_broadcast, text)
    await update.message.reply_text(f"✅ <b>Mensaje en cola de difusión.</b>", parse_mode=ParseMode.HTML)

async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /debug"""
    if update.effective_user.id != ADMIN_ID: return
    # Aquí podrías consultar la DB para ver el último registro
    await update.message.reply_text("🕵️‍♂️ Debug: Sistema activo y guardando datos.", parse_mode=ParseMode.HTML)
