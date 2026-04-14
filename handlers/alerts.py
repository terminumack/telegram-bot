import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # 🔥 Importaciones de botones añadidas
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

from database.users import track_user
from database.stats import log_activity
# IMPORTANTE: Importamos add_alert, pero también las funciones de lectura y borrado
from database.alerts import add_alert, get_triggered_alerts, delete_alert

# Importamos la memoria RAM
from shared import MARKET_DATA

# Estado para ConversationHandler
ESPERANDO_PRECIO_ALERTA = 1

# ==============================================================================
# 1. LÓGICA DE FONDO (TAREA AUTOMÁTICA)
# ==============================================================================
async def check_alerts_async(context: ContextTypes.DEFAULT_TYPE, current_price):
    """
    Función llamada automáticamente por bot.py cada minuto.
    Revisa si hay alertas que disparar, envía el mensaje y las borra.
    """
    try:
        # 1. Consultar DB en hilo separado
        triggered = await asyncio.to_thread(get_triggered_alerts, current_price)
        
        if not triggered: return

        # 2. Procesar cada alerta disparada
        for alert in triggered:
            user_id = alert['user_id']
            target = alert['target_price']
            condition = alert['condition']
            alert_id = alert['id']
            
            # Preparar mensaje visual
            emoji = "🚀" if condition == 'ABOVE' else "🔻"
            direction = "SUBIÓ" if condition == 'ABOVE' else "BAJÓ"
            
            msg = (
                f"🚨 <b>¡ALERTA DE PRECIO!</b>\n\n"
                f"{emoji} El dólar <b>{direction}</b> y tocó tu objetivo.\n"
                f"🎯 Objetivo: <b>{target:,.2f} Bs</b>\n"
                f"💵 Actual: <b>{current_price:,.2f} Bs</b>"
            )
            
            try:
                # A. Enviar mensaje al usuario (con el botón para revisar el precio fresco)
                kb = [[InlineKeyboardButton("🔎 Ver Mercado", callback_data="refresh_price", api_kwargs={"style": "primary"})]]
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=msg, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
                
                # B. Borrar alerta (Para que no suene infinitamente)
                await asyncio.to_thread(delete_alert, alert_id)
                
            except Exception as e:
                print(f"⚠️ No se pudo notificar a {user_id} (posible bloqueo): {e}")
                # Si el usuario bloqueó el bot, igual borramos la alerta para limpiar la DB
                await asyncio.to_thread(delete_alert, alert_id)

    except Exception as e:
        print(f"❌ Error crítico en check_alerts_async: {e}")


# ==============================================================================
# 2. LÓGICA DE INTERACCIÓN (CREAR ALERTA)
# ==============================================================================

async def process_alert_logic(update: Update, target):
    """Lógica interna para validar y guardar la alerta con límites Premium."""
    
    # 1. LEER PRECIO DE MEMORIA
    current_price = MARKET_DATA["price"]
    
    # Validación de seguridad
    if not current_price:
        await update.message.reply_text("⚠️ Esperando actualización de precios... intenta en 1 minuto.")
        return ConversationHandler.END

    # 2. Lógica de Dirección (Subida/Bajada)
    if target > current_price:
        condition = "ABOVE"
        msg = f"📈 <b>ALERTA DE SUBIDA</b>\n\nTe avisaré cuando el dólar <b>SUPERE</b> los {target:,.2f} Bs."
    elif target < current_price:
        condition = "BELOW"
        msg = f"📉 <b>ALERTA DE BAJADA</b>\n\nTe avisaré cuando el dólar <b>BAJE</b> de {target:,.2f} Bs."
    else:
        await update.message.reply_text(f"⚠️ El precio actual ya es {current_price:,.2f} Bs. Define un valor distinto.")
        return ConversationHandler.END

    # 🔥 PREPARAMOS EL BOTÓN DE VOLVER 🔥
    kb_final = [[InlineKeyboardButton("⬅️ Volver al Promedio", callback_data="refresh_price", api_kwargs={"style": "primary"})]]
    markup = InlineKeyboardMarkup(kb_final)

    # 3. Guardar en DB (Manejo de estados)
    result = await asyncio.to_thread(add_alert, update.effective_user.id, target, condition)
    
    if result == "SUCCESS":
        await update.message.reply_text(f"✅ {msg}", parse_mode=ParseMode.HTML, reply_markup=markup)

    elif result == "LIMIT_REACHED":
        # --- AQUÍ ESTÁ EL MENSAJE DE VENTA PREMIUM ---
        text = (
            "🚫 <b>Límite de Alertas Alcanzado (3/3)</b>\n\n"
            "Los usuarios gratuitos solo pueden tener <b>3 alertas activas</b>.\n\n"
            "💎 <b>¡Pásate a PREMIUM!</b>\n"
            "• 🔔 Hasta <b>20 Alertas</b> simultáneas.\n"
            "• 🏦 Alertas de Arbitraje (Bancos).\n"
            "• ⚡ Soporte Prioritario.\n\n"
            "🔜 <i>Suscripción automática con Binance Pay próximamente.</i>"
        )
        await update.message.reply_html(text, reply_markup=markup)

    else:
        await update.message.reply_text("⚠️ Error de base de datos. Intenta más tarde.", reply_markup=markup)
    
    return ConversationHandler.END

# --- HANDLERS DEL COMANDO /ALERTA ---

async def start_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, update.effective_user.id, "/alerta")
    
    # Caso directo: /alerta 600
    if context.args:
        try:
            clean_arg = context.args[0].replace(',', '.')
            target = float(clean_arg)
            return await process_alert_logic(update, target)
        except ValueError:
            await update.message.reply_text("🔢 Error: Ingresa un número válido.", parse_mode=ParseMode.HTML)
            return ConversationHandler.END

    # Caso interactivo
    await update.message.reply_text(
        f"🔔 <b>CONFIGURAR ALERTA</b>\n\n¿A qué precio quieres que te avise?\n\n<i>Escribe el monto abajo (Ej: 75.50):</i>", 
        parse_mode=ParseMode.HTML
    )
    return ESPERANDO_PRECIO_ALERTA

async def process_alert_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        clean_text = update.message.text.replace(',', '.')
        target = float(clean_text)
        return await process_alert_logic(update, target)
    except ValueError:
        await update.message.reply_text("🔢 Por favor ingresa solo números válidos.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Configuración de alerta cancelada.")
    return ConversationHandler.END

# --- EXPORTAR ---

conv_alert = ConversationHandler(
    entry_points=[CommandHandler("alerta", start_alert)],
    states={ESPERANDO_PRECIO_ALERTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_alert_input)]},
    fallbacks=[
        CommandHandler("cancel", cancel),
        MessageHandler(filters.COMMAND, cancel) # Anti-traba
    ],
    allow_reentry=True # Anti-traba
)
