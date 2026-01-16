import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# --- IMPORTS DE TU BASE DE DATOS NUEVA ---
from database.users import track_user
from database.stats import log_activity

# --- CONFIGURACIÓN Y CONSTANTES ---
# (Si tienes un archivo config.py, impórtalas desde ahí. Si no, déjalas aquí)
EMOJI_BINANCE = "🔶"
EMOJI_STATS = "📊"
EMOJI_ALERTA = "🔔"

# Reemplaza estos links por los tuyos reales si no los tienes en variables de entorno
LINK_CANAL = "https://t.me/tucanal"
LINK_GRUPO = "https://t.me/tugrupo"
LINK_SOPORTE = "https://t.me/tusoporte"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /start: Bienvenida y Registro de usuario.
    """
    # 1. Lógica de Referidos
    referrer_id = None
    if context.args:
        try: 
            referrer_id = int(context.args[0])
        except ValueError: 
            referrer_id = None

    # 2. Base de Datos (Ejecutado en hilo aparte para no frenar al bot)
    # track_user ahora acepta 'source' para saber de dónde vino el registro
    await asyncio.to_thread(track_user, update.effective_user, referrer_id=referrer_id, source="start_command")
    await asyncio.to_thread(log_activity, update.effective_user.id, "/start")

    # 3. Tu Mensaje Original (Intacto)
    mensaje = (
        f"👋 <b>¡Bienvenido al Monitor P2P Inteligente!</b>\n\n"
        f"Soy tu asistente financiero conectado a {EMOJI_BINANCE} <b>Binance P2P</b> y al <b>BCV</b>.\n\n"
        f"⚡ <b>Características:</b>\n"
        f"• <b>Confianza:</b> Solo monitoreamos comerciantes verificados.\n"
        f"• <b>Completo:</b> Tasa Paralela, Oficial, PayPal y Amazon.\n"
        f"• <b>Velocidad:</b> Actualizado cada 2 min.\n\n"
        f"🛠 <b>HERRAMIENTAS:</b>\n\n"
        f"{EMOJI_STATS} <b>/precio</b> → Ver tabla de tasas.\n"
        f"{EMOJI_STATS} <b>/grafico</b> → Tendencia Semanal (Promedio).\n"
        f"🧠 <b>/ia</b> → Predicción de Tendencia.\n"
        f"{EMOJI_ALERTA} <b>/alerta</b> → Avísame si sube o baja.\n"
        f"🎁 <b>/referidos</b> → ¡Invita y Gana!\n\n"
        f"🧮 <b>CALCULADORA (Toca abajo):</b>\n"
        f"• <b>/usdt</b> → Dólares a Bs.\n"
        f"• <b>/bs</b> → Bs a Dólares."
    )

    # 4. Tu Teclado Original
    keyboard = [
        [InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)], 
        [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]
    ]
    
    await update.message.reply_text(
        mensaje, 
        parse_mode=ParseMode.HTML, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
