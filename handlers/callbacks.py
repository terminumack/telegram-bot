from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# Importamos la impresora nueva y la memoria compartida
from utils.formatting import build_price_message, get_sentiment_keyboard
from shared import MARKET_DATA 

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Esto quita el relojito de carga en Telegram

    if query.data == "refresh":
        # 1. Generamos el texto usando la Memoria Compartida
        text = build_price_message(MARKET_DATA)
        
        # 2. Generamos el teclado (opcional, si usas el de sentimiento)
        keyboard = get_sentiment_keyboard(MARKET_DATA["price"])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        try:
            # 3. Editamos el mensaje solo si cambió algo
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except BadRequest:
            # Si el precio es idéntico y el texto no cambia, Telegram da error. Lo ignoramos.
            pass
