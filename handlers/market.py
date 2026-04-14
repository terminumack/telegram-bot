import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Imports propios
from shared import MARKET_DATA
from database.users import track_user
from database.stats import log_activity

async def mercado_text_logic():
    """
    Genera el texto y los botones. 
    Se usa en el comando /mercado y en el botón 'Actualizar'.
    """
    banks = MARKET_DATA["banks"]
    last_update = MARKET_DATA.get("last_updated", "Reciente")
    
    # Extraemos datos
    pm_b = banks["pm"]["buy"]
    pm_s = banks["pm"]["sell"]
    ban_b = banks["banesco"]["buy"]
    ban_s = banks["banesco"]["sell"]
    mer_b = banks["mercantil"]["buy"]
    mer_s = banks["mercantil"]["sell"]
    pro_b = banks["provincial"]["buy"]
    pro_s = banks["provincial"]["sell"]
    
    # Validación de carga
    if pm_b == 0:
        return "🔄 Escaneando mercado... intenta en 30 segundos.", None

    # Cálculo de Spread (evitando división por cero)
    spread_pm = ((pm_b - pm_s)/pm_b)*100 if pm_b > 0 else 0
    spread_ban = ((ban_b - ban_s)/ban_b)*100 if ban_b > 0 else 0

    # TU TABLA ORIGINAL (Idéntica)
    table = f"""
<b>🏦 MERCADO P2P (Bidireccional)</b>

<code>{'BANCO':<8} | {'CPR':<6} | {'VTA':<6}</code>
<code>{'-'*24}</code>
<code>{'PagoMóvl':<8} | {pm_b:>6.2f} | {pm_s:>6.2f}</code>
<code>{'Banesco':<8} | {ban_b:>6.2f} | {ban_s:>6.2f}</code>
<code>{'Mercantil':<8}| {mer_b:>6.2f} | {mer_s:>6.2f}</code>
<code>{'Provincl':<8} | {pro_b:>6.2f} | {pro_s:>6.2f}</code>

📉 <b>Spread (Ganancia Dealer):</b>
• PagoMóvil: <b>{spread_pm:.2f}%</b>
• Banesco: <b>{spread_ban:.2f}%</b>

<i>CPR: Tú Compras | VTA: Tú Vendes</i>
🕐 <i>{last_update}</i>
"""

# Definición de botones con colores (API 9.4)
    kb = [
        # 🟢 Verde para la acción de refrescar datos
        [InlineKeyboardButton("🔄 Actualizar", callback_data="cmd_mercado", api_kwargs={"style": "success"})],
        
        # 🔵 Azul para volver al menú anterior
        [InlineKeyboardButton("⬅️ Volver al Promedio", callback_data="refresh_price", api_kwargs={"style": "primary"})]
    ]
    
    return table, InlineKeyboardMarkup(kb)

async def mercado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal del comando /mercado"""
    user = update.effective_user
    await asyncio.to_thread(track_user, user)
    await asyncio.to_thread(log_activity, user.id, "/mercado")
    
    # Llamamos a la lógica compartida
    text, markup = await mercado_text_logic()
    
    # Si markup es None (porque está cargando), no mandamos botones
    await update.message.reply_html(text, reply_markup=markup)
