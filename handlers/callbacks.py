import logging
import asyncio
from datetime import datetime
import pytz 

# Imports de Telegram (ESTOS ERAN LOS QUE FALTABAN ANTES)
from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# Imports de tus Servicios y Base de Datos
from services.binance_service import get_binance_price
from services.bcv_service import get_bcv_rates
from database.users import track_user
from database.stats import log_activity, cast_vote, get_daily_requests_count
from utils.formatting import build_price_message, get_sentiment_keyboard

# Configuración de Zona Horaria
TIMEZONE = pytz.timezone('America/Caracas')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja los clicks en los botones (Actualizar, Votar, etc).
    """
    try:
        query = update.callback_query
        user = update.effective_user
        user_id = user.id
        data = query.data

        # 1. Registrar que el usuario está activo (en segundo plano)
        await asyncio.to_thread(track_user, user)

        # --- LÓGICA DE VOTOS (Subirá / Bajará) ---
        if data in ['vote_up', 'vote_down']:
            vote_type = 'UP' if data == 'vote_up' else 'DOWN'
            
            # Intentamos votar
            success = await asyncio.to_thread(cast_vote, user_id, vote_type)
            
            if success:
                await asyncio.to_thread(log_activity, user_id, f"vote_{vote_type.lower()}")
                await query.answer("✅ ¡Voto registrado!")
            else:
                await query.answer("⚠️ Ya votaste hoy.")
            
            # Después de votar, cambiamos 'data' para que el código de abajo refresque el precio automáticamente
            data = 'refresh_price'

        # --- LÓGICA DE REFRESCAR PRECIO ---
        if data == 'refresh_price':
            await asyncio.to_thread(log_activity, user_id, "btn_refresh")
            
            # Obtener precios frescos (Binance y BCV en paralelo es posible, pero aquí lo hacemos secuencial rápido)
            binance = await get_binance_price()
            bcv = await get_bcv_rates()
            
            # Hora actual bonita
            time_str = datetime.now(TIMEZONE).strftime("%d/%m/%Y %I:%M:%S %p")

            if binance:
                # Obtener cuánta gente ha consultado hoy
                req_count = await asyncio.to_thread(get_daily_requests_count)
                
                # Construir el Texto del mensaje (usando tu utilidad)
                text = build_price_message(binance, bcv, time_str, user_id, req_count)
                
                # Construir los Botones (pasando el precio para el link de compartir)
                keyboard = get_sentiment_keyboard(user_id, binance)
                
                # Editar el mensaje
                try:
                    await query.edit_message_text(
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except BadRequest:
                    # Si el precio es idéntico al anterior, Telegram lanza error "Message is not modified"
                    # Lo ignoramos para que no llene los logs de basura.
                    pass
                except Exception as e:
                    logging.error(f"Error editando mensaje: {e}")
            else:
                await query.answer("⚠️ Esperando datos del mercado... intenta de nuevo.")

        # --- CIERRE FINAL ---
        # Siempre intentamos responder al callback para que no se quede cargando
        try:
            await query.answer()
        except:
            pass

    except Exception as e:
        logging.error(f"❌ Error CRÍTICO en button_handler: {e}")
