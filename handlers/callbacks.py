from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

# Imports de nuestra estructura
from utils.formatting import build_price_message
from shared import MARKET_DATA
from database.stats import get_daily_requests_count

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Actualizando...") # Mensaje flotante pequeño

    if query.data == "refresh":
        # 1. Obtenemos contadores frescos de la BD (para que salga en el mensaje)
        # Usamos to_thread porque es una llamada a base de datos
        req_count = await asyncio.to_thread(get_daily_requests_count)
        
        # 2. Generamos el texto con el formato ORIGINAL
        text = build_price_message(MARKET_DATA, requests_count=req_count)
        
        # 3. Reconstruimos el botón (ESTO ES LO QUE FALTABA)
        keyboard = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # 4. Editamos texto Y botones
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup # <--- ¡Aquí está la magia!
            )
        except BadRequest:
            # Si el precio no cambió, Telegram lanza error. Lo ignoramos.
            pass

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import asyncio

from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA
from database.stats import get_daily_requests_count, cast_vote

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # --- CASO 1: VOTACIÓN ---
    if data.startswith("vote_"):
        vote_type = data.split("_")[1] # 'UP' o 'DOWN'
        
        # Guardar voto en DB
        await asyncio.to_thread(cast_vote, user_id, vote_type)
        
        await query.answer("✅ ¡Voto registrado!")
        
        # Refrescar el mensaje para mostrar resultados
        # (Esto hace que caiga en el CASO 2 automáticamente al regenerar el teclado)
        
    # --- CASO 2: ACTUALIZAR (Refresh) ---
    if data == "refresh" or data.startswith("vote_"):
        if data == "refresh":
            await query.answer("Actualizando...")

        req_count = await asyncio.to_thread(get_daily_requests_count)
        
        # Texto Nuevo
        text = build_price_message(MARKET_DATA, requests_count=req_count)
        
        # Teclado Nuevo (Ahora sabe que el usuario votó)
        reply_markup = await asyncio.to_thread(get_sentiment_keyboard, user_id, MARKET_DATA["price"])

        try:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except BadRequest:
            pass # Si el precio es idéntico, Telegram da error, lo ignoramos.
    
    # --- CASO 3: IGNORAR (Botones de adorno) ---
    elif data == "ignore":
        await query.answer()
