from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

# Imports de nuestra estructura
from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA
from database.stats import get_daily_requests_count, cast_vote, log_activity # <--- Agrega esto

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # --- PROTECCIÓN ANTI-CRASH (ERROR "QUERY IS TOO OLD") ---
    # Creamos una mini-función interna para responder al botón sin riesgo.
    # Si el botón es viejo (más de 48h), Telegram da error al intentar mostrar
    # el "toast" (mensajito flotante), pero no debemos dejar que eso detenga el bot.
    async def safe_answer(text=None):
        try:
            await query.answer(text)
        except BadRequest:
            # Si falla (Query too old), lo ignoramos y seguimos ejecutando la lógica
            pass

    # ==================================================================
    # CASO 1: VOTACIÓN
    # ==================================================================
    # Si el botón empieza por "vote_", es que el usuario pulsó Subirá o Bajará
    if data.startswith("vote_"):
        vote_type = data.split("_")[1] # Extraemos 'UP' o 'DOWN'
        
        # Guardamos el voto en la BD en un hilo aparte
        await asyncio.to_thread(cast_vote, user_id, vote_type)
        
        # Feedback rápido al usuario (Blindado)
        await safe_answer("✅ ¡Voto registrado!")
        
        # NOTA: No hacemos return aquí. Dejamos que el código baje al CASO 2
        # para regenerar el mensaje y mostrar los porcentajes inmediatamente.

    # ==================================================================
    # CASO 2: ACTUALIZAR (Refresh) O MOSTRAR RESULTADOS (Post-Voto)
    # ==================================================================
    # Aceptamos "refresh", "refresh_price" (del Worker) y "vote_" (flujo continuo)
    if data in ["refresh", "refresh_price"] or data.startswith("vote_"):
        
        # Solo mostramos "Actualizando..." si fue un clic de refresh directo
        if data in ["refresh", "refresh_price"]:
            await safe_answer("🔄 Consultando mercado...")
            await asyncio.to_thread(log_activity, user_id, "refresh_btn")

        # 1. Obtenemos contadores frescos (DB)
        req_count = await asyncio.to_thread(get_daily_requests_count)
        
        # 2. Generamos el TEXTO NUEVO
        # build_price_message detectará que hay un user_id y adaptará el texto
        text = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
        
        # 3. Generamos los BOTONES NUEVOS
        current_price = MARKET_DATA.get("price", 0)
        reply_markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, current_price)

        try:
            # 4. Editamos el mensaje con la nueva info
            # (Esto funciona SIEMPRE, incluso si el mensaje es de hace un año)
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except BadRequest as e:
            # Si el precio y los votos son idénticos a lo que ya hay en pantalla,
            # Telegram lanza "Message is not modified". No es grave.
            if "Message is not modified" not in str(e):
                print(f"⚠️ Error editando mensaje: {e}")

    # ==================================================================
    # CASO 3: VER MERCADO (CMD_MERCADO)
    # ==================================================================
    elif data == "cmd_mercado":
        # Importamos aquí dentro para evitar errores de importación circular
        from handlers.market import mercado_text_logic
        
        # Generamos el texto fresco
        text, markup = await mercado_text_logic()
        
        try:
            # Editamos el mensaje
            await query.edit_message_text(
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            # Confirmamos acción exitosa
            await safe_answer() 
            
        except Exception:
            # Si los montos no cambiaron, avisamos con toast (Blindado)
            await safe_answer("✅ Ya está actualizado.")
    
    # ==================================================================
    # CASO 4: BOTONES PASIVOS
    # ==================================================================
    elif data == "ignore":
        await safe_answer()
