from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from urllib.parse import quote
from datetime import datetime
from database.stats import has_user_voted, get_vote_results 

# Emojis
EMOJI_STATS = "📊"
EMOJI_BINANCE = "🔶"
EMOJI_PAYPAL = "🅿️"
EMOJI_AMAZON = "🎁"
EMOJI_STORE = "🏪"

def build_price_message(market_data, user_id=None, requests_count=0):
    """
    Genera el mensaje de precios.
    Si user_id está presente, verifica si votó para mostrar la encuesta en el TEXTO.
    """
    price = market_data.get("price", 0) or 0
    bcv_data = market_data.get("bcv", {})
    last_update = market_data.get("last_updated", "Reciente")
    
    # Cálculos
    paypal = price * 0.90
    amazon = price * 0.75
    
    # 1. Encabezado y Binance
    text = f"{EMOJI_STATS} <b>MONITOR DE TASAS</b>\n\n{EMOJI_BINANCE} <b>Tasa Binance:</b> {price:,.2f} Bs\n\n"
    
    # 2. Bloque BCV
    if bcv_data and bcv_data.get('dolar'):
        bcv_usd = bcv_data['dolar']
        text += f"🏛️ <b>BCV (Dólar):</b> {bcv_usd:,.2f} Bs\n"
        
        # Cálculo de Brecha
        if bcv_usd > 0:
            brecha = ((price - bcv_usd) / bcv_usd) * 100
            emoji_brecha = "🔴" if brecha >= 20 else "🟠" if brecha >= 10 else "🟢"
            text += f"📈 <b>Brecha:</b> {brecha:.2f}% {emoji_brecha}\n"
            
        if bcv_data.get('euro'): 
            text += f"🇪🇺 <b>BCV (Euro):</b> {bcv_data['euro']:,.2f} Bs\n"
        text += "\n"
    else: 
        text += "🏛️ <b>BCV:</b> <i>No disponible</i>\n\n"
    
    # 3. Otros Mercados y Footer
    text += (f"{EMOJI_PAYPAL} <b>Tasa PayPal:</b> {paypal:,.2f} Bs\n"
             f"{EMOJI_AMAZON} <b>Giftcard Amazon:</b> {amazon:,.2f} Bs\n\n"
             f"{EMOJI_STORE} <i>Actualizado: {last_update}</i>\n")
    
    if requests_count > 100: 
        text += f"👁 <b>{requests_count:,}</b> consultas hoy\n\n"
    else: 
        text += "\n"

    # --- 4. INTEGRACIÓN DE TU ENCUESTA ---
    if user_id and has_user_voted(user_id):
        # Si YA votó: Mostramos resultados en el texto
        up, down = get_vote_results()
        total = up + down
        if total > 0:
            up_pct = int((up / total) * 100)
            down_pct = int((down / total) * 100)
            text += f"🗣️ <b>¿Qué dice la comunidad?</b>\n🚀 {up_pct}% <b>Alcista</b> | 📉 {down_pct}% <b>Bajista</b>\n\n"
        else:
            text += "🗣️ <b>¿Qué dice la comunidad?</b>\nEsperando votos...\n\n"
            
    elif user_id:
        # Si NO ha votado: Le decimos que vote abajo
        text += "🗣️ <b>¿Qué dice la comunidad?</b> 👇\n\n"

    text += "📢 <b>Síguenos:</b> @tasabinance_bot"
    return text

def get_sentiment_keyboard(user_id, current_price):
    """
    Genera los BOTONES.
    Orden ajustado para memoria muscular:
    - Si ya votó: 1. Actualizar, 2. Compartir.
    - Si no votó: 1. Votar, 2. Actualizar.
    """
    keyboard = []
    
    # Preparamos el botón de actualizar (se usa en ambos casos)
    btn_refresh = [InlineKeyboardButton("🔄 Actualizar Precio", callback_data='refresh')]

    if has_user_voted(user_id):
        # CASO 1: YA VOTÓ
        # Orden solicitado: Primero Actualizar, luego Compartir
        keyboard.append(btn_refresh)
        
        share_text = quote(f"🔥 Dólar en {current_price:,.2f} Bs. Revisa la tasa real aquí:")
        share_url = f"https://t.me/share/url?url=https://t.me/tasabinance_bot&text={share_text}"
        keyboard.append([InlineKeyboardButton("📤 Compartir con Amigos", url=share_url)])
        
    else:
        # CASO 2: NO VOTÓ
        # Orden estándar: Primero Votar, luego Actualizar
        keyboard.append([
            InlineKeyboardButton("🚀 Subirá", callback_data='vote_UP'), 
            InlineKeyboardButton("📉 Bajará", callback_data='vote_DOWN')
        ])
        keyboard.append(btn_refresh)
    
    return InlineKeyboardMarkup(keyboard)
