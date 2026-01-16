async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🔘 ¡CLICK RECIBIDO! Entrando al handler...") # <--- AGREGA ESTO
    """Maneja los clicks en los botones."""
    query = update.callback_query
    # ... resto del código ...

import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# Imports Modulares
from services.binance_service import get_binance_price
from services.bcv_service import get_bcv_rates
from database.users import track_user
from database.stats import log_activity, cast_vote, get_daily_requests_count
from utils.formatting import build_price_message, get_sentiment_keyboard

# Zona horaria (ajusta si usas pytz)
import pytz
TIMEZONE = pytz.timezone('America/Caracas')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los clicks en los botones."""
    query = update.callback_query
    user = update.effective_user
    user_id = user.id
    data = query.data

    # Registrar actividad en segundo plano
    await asyncio.to_thread(track_user, user)

    # --- LÓGICA DE VOTOS ---
    if data in ['vote_up', 'vote_down']:
        vote_type = 'UP' if data == 'vote_up' else 'DOWN'
        
        success = await asyncio.to_thread(cast_vote, user_id, vote_type)
        if success:
            await asyncio.to_thread(log_activity, user_id, f"vote_{vote_type.lower()}")
            await query.answer("✅ ¡Voto registrado!")
        else:
            await query.answer("⚠️ Ya votaste hoy.")
        
        # Después de votar, forzamos que entre en la lógica de refrescar precio
        data = 'refresh_price'

    # --- LÓGICA DE REFRESCAR PRECIO ---
    if data == 'refresh_price':
        await asyncio.to_thread(log_activity, user_id, "btn_refresh")
        
        # 1. Obtener datos frescos (Usando cache inteligente de servicios)
        # Esto reemplaza a MARKET_DATA global, es más robusto
        binance = await get_binance_price()
        bcv = await get_bcv_rates()
        
        # Hora actual
        time_str = datetime.now(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")

        if binance:
            # Obtener contador de visitas
            req_count = await asyncio.to_thread(get_daily_requests_count)
            
            # Construir mensaje usando la utilidad que creamos
            text = build_price_message(binance, bcv, time_str, user_id, req_count)
            
            # Construir teclado
            keyboard = get_sentiment_keyboard(user_id, binance)
            
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest:
                # Si el precio no cambió, Telegram da error al editar. Lo ignoramos.
                pass
            except Exception as e:
                logging.error(f"Error editando mensaje: {e}")
        else:
            await query.answer("🔄 Iniciando sistema... intenta en unos segundos.")

    # Siempre responder al final para quitar el relojito
    try:
        await query.answer()
    except:
        pass
