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
        keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')]]
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
