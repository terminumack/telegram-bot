import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from shared import MARKET_DATA
from database.users import track_user
from database.stats import log_activity

async def mercado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await asyncio.to_thread(track_user, user)
    await asyncio.to_thread(log_activity, user.id, "/mercado")
    
    banks = MARKET_DATA["banks"]
    
    # Extraemos datos para escribir menos código abajo
    pm_b, pm_s = banks["pm"]["buy"], banks["pm"]["sell"]
    ban_b, ban_s = banks["banesco"]["buy"], banks["banesco"]["sell"]
    mer_b, mer_s = banks["mercantil"]["buy"], banks["mercantil"]["sell"]
    pro_b, pro_s = banks["provincial"]["buy"], banks["provincial"]["sell"]
    
    if pm_b == 0:
        await update.message.reply_text("🔄 Escaneando mercado... intenta en 30 segundos.")
        return

    # Icono de Spread (Diferencia entre Compra y Venta del mismo banco)
    def get_spread_icon(buy, sell):
        if buy == 0 or sell == 0: return ""
        spread = ((buy - sell) / buy) * 100
        # Si hay mucha ganancia (>5%) o poca (<1%)
        if spread > 5: return "🔥"
        return ""

    # Tabla compacta para móviles
    # CPR = A cuanto venden ellos (Tú compras)
    # VTA = A cuanto compran ellos (Tú vendes)
    table = f"""
<b>🏦 MERCADO P2P (Bidireccional)</b>

<code>{'BANCO':<8} | {'CPR':<6} | {'VTA':<6}</code>
<code>{'-'*24}</code>
<code>{'PagoMóvl':<8} | {pm_b:>6.2f} | {pm_s:>6.2f}</code>
<code>{'Banesco':<8} | {ban_b:>6.2f} | {ban_s:>6.2f}</code>
<code>{'Mercantil':<8}| {mer_b:>6.2f} | {mer_s:>6.2f}</code>
<code>{'Provincl':<8} | {pro_b:>6.2f} | {pro_s:>6.2f}</code>

📉 <b>Spread (Ganancia Dealer):</b>
• PagoMóvil: <b>{((pm_b - pm_s)/pm_b)*100:.2f}%</b>
• Banesco: <b>{((ban_b - ban_s)/ban_b)*100:.2f}%</b>

<i>CPR: Tú Compras | VTA: Tú Vendes</i>
🕐 <i>{MARKET_DATA['last_updated']}</i>
"""
    await update.message.reply_html(table)
