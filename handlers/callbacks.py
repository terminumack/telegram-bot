from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

# Imports de nuestra estructura
from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA
from database.stats import get_daily_requests_count, cast_vote

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # --- CASO 1: VOTACIÓN ---
    # Si el botón empieza por "vote_", es que el usuario pulsó Subirá o Bajará
    if data.startswith("vote_"):
        vote_type = data.split("_")[1] # Extraemos 'UP' o 'DOWN'
        
        # Guardamos el voto en la BD en un hilo aparte
        await asyncio.to_thread(cast_vote, user_id, vote_type)
        
        # Feedback rápido al usuario
        await query.answer("✅ ¡Voto registrado!")
        
        # NOTA: No hacemos return aquí porque queremos que el código siga bajando
        # para regenerar el mensaje y mostrar los resultados inmediatamente.

    # --- CASO 2: ACTUALIZAR (Refresh) O MOSTRAR RESULTADOS ---
    # AQUI ESTÁ EL CAMBIO: Aceptamos "refresh" Y TAMBIÉN "refresh_price" (del Worker)
    if data in ["refresh", "refresh_price"] or data.startswith("vote_"):
        
        if data in ["refresh", "refresh_price"]:
            await query.answer("Actualizando...")

        # 1. Obtenemos contadores frescos
        req_count = await asyncio.to_thread(get_daily_requests_count)
        
        # 2. Generamos el TEXTO NUEVO
        # IMPORTANTE: Pasamos 'user_id' para que build_price_message sepa
        # que el usuario ya votó y cambie el "👇" por los porcentajes "🚀 80%".
        text = build_price_message(MARKET_DATA, user_id=user_id, requests_count=req_count)
        
        # 3. Generamos los BOTONES NUEVOS
        # get_sentiment_keyboard sabrá que ya votó y pondrá el botón "Compartir"
        current_price = MARKET_DATA.get("price", 0)
        reply_markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, current_price)

        try:
            # 4. Editamos el mensaje con la nueva info
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except BadRequest:
            # Si el precio y los votos no han cambiado nada, Telegram da error.
            # Lo ignoramos silenciosamente.
            pass

    # ... (código anterior del bloque refresh) ...

    # --- CASO 3: VER MERCADO (O ACTUALIZAR MERCADO) ---
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
        except Exception:
            # Si los montos no cambiaron, Telegram da error. Avisamos con toast.
            await query.answer("✅ Ya está actualizado.")
    
    # --- CASO 3: BOTONES PASIVOS (Ignorar) ---
    elif data == "ignore":
        await query.answer()
