import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from shared import MARKET_DATA
from database.users import track_user
from database.stats import log_activity

async def mercado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra una tabla comparativa de bancos en tiempo real."""
    user = update.effective_user
    await asyncio.to_thread(track_user, user)
    await asyncio.to_thread(log_activity, user.id, "/mercado")
    
    # Leemos de RAM (Instantáneo)
    banks = MARKET_DATA["banks"]
    pm_buy = banks["pm"]["buy"]
    pm_sell = banks["pm"]["sell"]
    ban = banks["banesco"]["buy"]
    mer = banks["mercantil"]["buy"]
    pro = banks["provincial"]["buy"]
    
    if pm_buy == 0:
        await update.message.reply_text("🔄 Recopilando datos del mercado... intenta en 1 minuto.")
        return

    # Cálculos de diferencias (Spread vs PagoMóvil)
    def get_diff_icon(price, ref):
        if price == 0: return ""
        diff = price - ref
        if diff < -0.05: return "🟢" # Más barato
        if diff > 0.05: return "🔴"  # Más caro
        return "⚪️"

    # Construimos la tabla usando Code Block para alineación
    table = f"""
<b>🏦 MERCADO P2P (En Vivo)</b>
<i>Precios de referencia (Compra):</i>

<code>{'BANCO':<9} | {'PRECIO':<7} | </code>
<code>{'-'*24}</code>
<code>{'PagoMóvil':<9} | {pm_buy:>7.2f} | 📱</code>
<code>{'Banesco':<9} | {ban:>7.2f} | {get_diff_icon(ban, pm_buy)}</code>
<code>{'Mercantil':<9} | {mer:>7.2f} | {get_diff_icon(mer, pm_buy)}</code>
<code>{'Provincl':<9} | {pro:>7.2f} | {get_diff_icon(pro, pm_buy)}</code>

📉 <b>Arbitraje / Spread:</b>
• Venta Rápida: <b>{pm_sell:.2f} Bs</b>
• Brecha: <b>{((pm_buy - pm_sell)/pm_buy)*100:.2f}%</b> (Ganancia Dealer)

🕐 <i>Actualizado: {MARKET_DATA['last_updated']}</i>
"""
    await update.message.reply_html(table)
