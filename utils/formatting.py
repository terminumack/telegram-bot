from datetime import datetime
import pytz

# --- TUS EMOJIS ORIGINALES ---
EMOJI_STATS = "📊"
EMOJI_BINANCE = "🔶"
EMOJI_PAYPAL = "🅿️"
EMOJI_AMAZON = "📦"
EMOJI_STORE = "🏪"

def build_price_message(market_data, requests_count=0):
    """
    Reconstruye el mensaje con el diseño EXACTO de tu versión original.
    """
    # 1. Extraer datos de la memoria compartida
    binance = market_data.get("price") or 0
    bcv_raw = market_data.get("bcv", {}) or {}
    time_str = market_data.get("last_updated", "N/A")

    # Mapeo de claves (Por si bcv_service devuelve 'dolar' en vez de 'usd')
    bcv_usd = bcv_raw.get("dolar") or bcv_raw.get("usd") or 0
    bcv_eur = bcv_raw.get("euro") or bcv_raw.get("eur") or 0

    # Si no hay precio aún
    if binance <= 0:
        return "🔄 <b>Iniciando sistema...</b>\nRecopilando tasas de mercado."

    # 2. CÁLCULOS (Tu fórmula original)
    paypal = binance * 0.90
    amazon = binance * 0.75

    # 3. CONSTRUCCIÓN DEL TEXTO
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n{EMOJI_BINANCE} <b>Tasa Binance:</b> {binance:,.2f} Bs\n\n"

    # Sección BCV
    if bcv_usd > 0:
        text += f"🏛️ <b>BCV (Dólar):</b> {bcv_usd:,.2f} Bs\n"
        
        # Cálculo de Brecha
        brecha = ((binance - bcv_usd) / bcv_usd) * 100
        
        # Tu lógica de semáforo original
        emoji_brecha = "🔴" if brecha >= 20 else "🟠" if brecha >= 10 else "🟢"
        text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
        
        if bcv_eur > 0:
            text += f"🇪🇺 <b>BCV (Euro):</b> {bcv_eur:,.2f} Bs\n"
        text += "\n"
    else:
        text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"

    # Sección Otros
    text += f"{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {paypal:,.2f} Bs\n"
    text += f"{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {amazon:,.2f} Bs\n\n"
    
    # Footer
    text += f"{EMOJI_STORE} <i>Actualizado: {time_str}</i>\n"

    # Estadísticas de Visitas
    if requests_count > 100:
        text += f"👁 <b>{requests_count:,}</b> consultas hoy\n\n"
    else:
        text += "\n"

    # Comunidad / Link
    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    
    return text

def get_sentiment_keyboard(price):
    """(Opcional) Si quieres mantener la función para no romper imports"""
    return None
