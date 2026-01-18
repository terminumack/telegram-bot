# Asegúrate de tener estos imports al inicio del archivo si no los tienes:
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import asyncio

# Imports de tu base de datos
from database.users import track_user
from database.stats import log_activity

# Enlaces (Configúralos aquí o impórtalos de tu config)
LINK_CANAL = "https://t.me/tasabinance"
LINK_GRUPO = "https://t.me/tasabinancegrupo"
LINK_SOPORTE = "https://t.me/tasabinancesoporte"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Lógica de Referidos y Tracking
    referrer_id = None
    if context.args:
        try: 
            referrer_id = int(context.args[0])
        except ValueError: 
            referrer_id = None
            
    await asyncio.to_thread(track_user, update.effective_user, referrer_id)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/start")

    # 2. El Mensaje Renovado
    mensaje = (
        f"👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        f"Soy tu asistente financiero conectado a 🔶 <b>Binance P2P</b> y al <b>BCV</b>.\n\n"
        
        f"🚀 <b>HERRAMIENTAS PRINCIPALES:</b>\n"
        f"💵 <b>/precio</b> → Tasa Promedio Instantánea.\n"
        f"🏦 <b>/mercado</b> → Comparativa por Bancos.\n"
        f"📊 <b>/grafico</b> → Tendencia Semanal Viral.\n\n"
        
        f"🧠 <b>INTELIGENCIA DE MERCADO:</b>\n"
        f"🕒 <b>/horario</b> → ¿Mejor hora para cambiar?\n"
        f"🤖 <b>/ia</b> → Predicción (Sube o Baja).\n"
        f"🔔 <b>/alerta</b> → Avisos de precio.\n\n"
        
        f"🎁 <b>/referidos</b> → ¡Invita y Gana!\n\n"
        
        f"🧮 <b>CALCULADORA RÁPIDA:</b>\n"
        f"• <b>/usdt 100</b> → 100$ a Bs.\n"
        f"• <b>/bs 5000</b> → 5000Bs a $."
    )
    
    # 3. Botones de Comunidad
    keyboard = [
        [InlineKeyboardButton("📢 Canal Oficial", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo Chat", url=LINK_GRUPO)],
        [InlineKeyboardButton("🆘 Soporte / Ayuda", url=LINK_SOPORTE)]
    ]
    
    await update.message.reply_text(
        mensaje, 
        parse_mode=ParseMode.HTML, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )
