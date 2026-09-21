from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

# Imports de nuestra estructura
from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA
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
    # CASO 1 Y 2: VOTACIÓN Y REFRESH (Unificados y Sincronizados)
    # ==================================================================
    if data in ["refresh", "refresh_price"] or data.startswith("vote_"):
        
        if data.startswith("vote_"):
            vote_type = data.split("_")[1]
            
            # 🔥 CORRECCIÓN: Esperamos que el voto se guarde ANTES de generar el teclado
            # para que el porcentaje se actualice al instante en la pantalla.
            await asyncio.to_thread(cast_vote, user_id, vote_type)
            await safe_answer("✅ ¡Voto registrado!")
        else:
            await safe_answer("🔄 Consultando mercado...")
            # El refresh de botón normal sí lo mandamos al fondo porque no afecta la pantalla
            asyncio.create_task(asyncio.to_thread(log_activity, user_id, "refresh_btn"))

        # 🔥 VELOCIDAD: Pedimos el contador y el teclado actualizado AL MISMO TIEMPO
        current_price = MARKET_DATA.get("price", 0)
        req_count, reply_markup = await asyncio.gather(
            asyncio.to_thread(get_daily_requests_count),
            asyncio.to_thread(get_sentiment_keyboard, user_id, current_price)
        )
        
        # Generamos el TEXTO NUEVO
        text = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)

        try:
            if query.message.text:
                await query.edit_message_text(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
            else:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                print(f"⚠️ Error actualizando mensaje: {e}")

    # ==================================================================
    # CASO 3: VER MERCADO (CMD_MERCADO)
    # ==================================================================
    elif data == "cmd_mercado":
        await safe_answer() 
        from handlers.market import mercado_text_logic
        asyncio.create_task(asyncio.to_thread(log_activity, user_id, "mercado_btn"))
        
        text, markup = await mercado_text_logic()
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            pass 
    
    # ==================================================================
    # CASO 4: VER HORARIO (CMD_HORARIO)
    # ==================================================================
    elif data == "cmd_horario":
        await safe_answer() 
        from handlers.analytics import horario 
        asyncio.create_task(asyncio.to_thread(log_activity, user_id, "horario_btn"))
        await horario(update, context)

    # ==================================================================
    # CASO 5: REFRESH USO
    # ==================================================================
    elif data == "refresh_uso":
        await safe_answer() 
        from handlers.admin import comando_uso
        await comando_uso(update, context)

    # ==================================================================
    # CASO 6: BOTONES PASIVOS
    # ==================================================================
    elif data == "ignore":
        await safe_answer()
