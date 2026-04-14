from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

# Imports de nuestra estructura
from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA

# 🔥 CAMBIO 1: Agregamos log_activity al final de esta línea
from database.stats import get_daily_requests_count, cast_vote, log_activity

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # --- PROTECCIÓN ANTI-CRASH ---
    async def safe_answer(text=None):
        try:
            await query.answer(text)
        except BadRequest:
            pass

    # ==================================================================
    # CASO 1: VOTACIÓN
    # ==================================================================
    if data.startswith("vote_"):
        vote_type = data.split("_")[1]
        await asyncio.to_thread(cast_vote, user_id, vote_type)
        await safe_answer("✅ ¡Voto registrado!")

    # ==================================================================
    # CASO 2: ACTUALIZAR (Refresh)
    # ==================================================================
    if data in ["refresh", "refresh_price"] or data.startswith("vote_"):
        
        if data in ["refresh", "refresh_price"]:
            await safe_answer("🔄 Consultando mercado...")
            
            # 🔥 CAMBIO 2: REGISTRAMOS EL CLIC AQUÍ 🔥
            try:
                await asyncio.to_thread(log_activity, user_id, "refresh_btn")
            except Exception as e:
                print(f"⚠️ Error contando clic: {e}")

        # 1. Obtenemos contadores frescos
        req_count = await asyncio.to_thread(get_daily_requests_count)
        
        # 2. Generamos el TEXTO NUEVO
        text = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
        
        # 3. Generamos los BOTONES NUEVOS
        current_price = MARKET_DATA.get("price", 0)
        reply_markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, current_price)

        try:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                print(f"⚠️ Error editando mensaje: {e}")

    # ==================================================================
    # CASO 3: VER MERCADO (CMD_MERCADO)
    # ==================================================================
    elif data == "cmd_mercado":
        from handlers.market import mercado_text_logic
        
        # 🔥 CAMBIO 3: También contamos si ven el mercado detallado
        await asyncio.to_thread(log_activity, user_id, "mercado_btn")
        
        text, markup = await mercado_text_logic()
        
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="HTML")
            await safe_answer() 
        except Exception:
            await safe_answer("✅ Ya está actualizado.")
    
    # ==================================================================
    # CASO 4: BOTONES PASIVOS
    # ==================================================================
    elif data == "ignore":
        await safe_answer()

# ==================================================================
    # CASO: VER HORARIO (CMD_HORARIO)
    # ==================================================================
    elif data == "cmd_horario":
        # Importamos la función horario (asegúrate de poner la ruta correcta si está en otra carpeta)
        from handlers.analytics import horario 
        
        await asyncio.to_thread(log_activity, user_id, "horario_btn")
        await horario(update, context)
        await safe_answer()
