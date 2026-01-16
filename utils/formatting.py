from datetime import datetime
from telegram import InlineKeyboardButton

# Imports de base de datos para los votos
from database.stats import get_vote_results, has_user_voted

# Constantes visuales
EMOJI_STATS = "📊"
EMOJI_BINANCE = "🔶"
EMOJI_PAYPAL = "🅿️"
EMOJI_AMAZON = "📦"
EMOJI_STORE = "🏪"
TIMEZONE_OFFSET = -4 # Ajuste para Vzla si usas UTC, o usa pytz si prefieres

def get_sentiment_keyboard(user_id, price):
    """Genera los botones de Votar o Compartir."""
    if has_user_voted(user_id):
        # Si ya votó, le dejamos compartir
        share_text = f"🔥 Dólar en {price:.2f} Bs. Revisa la tasa real aquí:"
        share_url = f"https://t.me/share/url?url=https://t.me/tasabinance_bot&text={share_text}"
        return [
            [InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')],
            [InlineKeyboardButton("📤 Compartir con Amigos", url=share_url)]
        ]
    else:
        # Si no ha votado, mostramos opciones
        return [
            [InlineKeyboardButton("🚀 Subirá", callback_data='vote_up'), 
             InlineKeyboardButton("📉 Bajará", callback_data='vote_down')],
            [InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh_price')]
        ]

def build_price_message(binance, bcv_data, time_str, user_id=None, requests_count=0):
    """Construye el texto del mensaje de precios."""
    # Cálculos simples
    paypal = binance * 0.90
    amazon = binance * 0.75
    
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n\n"
    
    # Lógica BCV
    if bcv_data:
        usd_bcv = bcv_data.get('usd', 0)
        eur_bcv = bcv_data.get('eur', 0)
        
        if usd_bcv > 0:
            text += f"🏛️ <b>BCV (Dólar):</b> {usd_bcv:,.2f} Bs\n"
            # Cálculo de brecha
            brecha = ((binance - usd_bcv) / usd_bcv) * 100
            emoji_brecha = "🔴" if brecha >= 20 else "🟠" if brecha >= 10 else "🟢"
            text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
            
        if eur_bcv > 0:
            text += f"🇪🇺 <b>BCV (Euro):</b> {eur_bcv:,.2f} Bs\n"
        text += "\n"
    else:
        text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"

    # Resto del mensaje
    text += f"{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {paypal:,.2f} Bs\n"
    text += f"{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {amazon:,.2f} Bs\n\n"
    text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>\n"

    if requests_count > 100:
        text += f"👁 <b>{requests_count:,}</b> consultas hoy\n\n"
    else:
        text += "\n"

    # Sección de comunidad (Votos)
    if user_id:
        if has_user_voted(user_id):
            up, down = get_vote_results()
            total = up + down
            if total > 0:
                up_pct = int((up / total) * 100)
                down_pct = int((down / total) * 100)
                text += f"🗣️ <b>¿Qué dice la comunidad?</b>\n🚀 {up_pct}% <b>Alcista</b> | 📉 {down_pct}% <b>Bajista</b>\n\n"
        else:
            text += "🗣️ <b>¿Qué dice la comunidad?</b> 👇\n\n"

    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    return text
