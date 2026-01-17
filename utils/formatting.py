from datetime import datetime
import pytz

# Emojis
EMOJI_SUBIDA = "🚀"
EMOJI_BAJADA = "📉"
EMOJI_IGUAL = "⚖️"
EMOJI_CALENDARIO = "📅"

def get_sentiment_keyboard(price):
    """(Opcional) Retorna el teclado si lo usas"""
    return None

def build_price_message(market_data):
    """
    Construye el mensaje visual con:
    1. Precio Binance (Paralelo)
    2. Tasa BCV (Dólar y Euro)
    3. Brecha Cambiaria (Diferencia %)
    """
    # 1. Extraer datos de la memoria
    price_now = market_data.get("price")
    bcv_data = market_data.get("bcv", {}) or {}
    last_update = market_data.get("last_updated", "N/A")
    
    bcv_usd = bcv_data.get("dolar", 0)
    bcv_eur = bcv_data.get("euro", 0)

    # Si no hay precio de Binance aún
    if not price_now:
        return "🔄 <b>Iniciando sistema...</b>\nRecopilando tasas de mercado."

    # 2. Calcular Tendencia (Flecha)
    # Comparamos el precio actual con el promedio de los últimos 5 (si existen)
    history = market_data.get("history", [])
    if len(history) >= 2:
        avg_hist = sum(history) / len(history)
        if price_now > avg_hist: arrow = EMOJI_SUBIDA
        elif price_now < avg_hist: arrow = EMOJI_BAJADA
        else: arrow = EMOJI_IGUAL
    else:
        arrow = EMOJI_IGUAL

    # 3. CALCULAR BRECHA (SPREAD) 📊
    # (Paralelo - BCV) / BCV * 100
    brecha_str = ""
    if bcv_usd > 0:
        brecha = ((price_now - bcv_usd) / bcv_usd) * 100
        icon_brecha = "🔴" if brecha > 10 else "🟡" if brecha > 5 else "🟢"
        brecha_str = f"{icon_brecha} <b>Brecha:</b> {brecha:.2f}%"

    # 4. Construir Mensaje Final
    msg = (
        f"🇻🇪 <b>TASA BINANCE VENEZUELA</b>\n"
        f"<i>Promedio P2P (PagoMóvil)</i>\n\n"
        
        f"{arrow} <b>{price_now:,.2f} VES</b> / USDT\n"
        f"{brecha_str}\n\n"
        
        f"🏛 <b>TASAS OFICIALES (BCV)</b>\n"
        f"💵 Dólar: <b>{bcv_usd:,.2f} VES</b>\n"
    )

    # Solo mostramos Euro si el BCV lo reportó
    if bcv_eur > 0:
        msg += f"💶 Euro: <b>{bcv_eur:,.2f} VES</b>\n"
        
    msg += f"\n{EMOJI_CALENDARIO} <i>Act: {last_update}</i>"
    
    return msg
