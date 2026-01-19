import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from urllib.parse import quote
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import pytz
from database.stats import get_daily_requests_count # Asegúrate de importar esto

# --- IMPORTS DE NUESTRA ESTRUCTURA ---
from shared import MARKET_DATA, TIMEZONE
from database.users import track_user
from database.stats import (
    log_activity, 
    get_referral_stats, 
    queue_broadcast, 
    get_conn, put_conn,
    get_detailed_report_text
)

# --- SEGURIDAD Y GRÁFICOS ---
from utils.charts import generate_public_price_chart
from utils.security import rate_limited  # <--- IMPORTANTE: El escudo Anti-Spam

# Configuración Global
ADMIN_ID = 533888411 
EMOJI_SUBIDA = "🚀"
EMOJI_BAJADA = "📉"

# Caché y Semáforo para Gráficos (Evita colapso de RAM)
GRAPH_CACHE = {"date": None, "photo_id": None}
GRAPH_LOCK = asyncio.Lock() 
# --- COMANDO /START ---
@rate_limited(2)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: >>> Entrando al comando /start")
    try:
        user = update.effective_user
        print(f"DEBUG: Usuario: {user.id} - {user.first_name}")

        # 1. Lógica de Referidos
        referrer_id = None
        if context.args:
            print(f"DEBUG: Argumentos del start: {context.args}")
            if context.args[0].isdigit():
                potential_id = int(context.args[0])
                if potential_id != user.id:
                    referrer_id = potential_id
                    print(f"DEBUG: Referido por: {referrer_id}")

        # 2. Registrar Usuario en DB
        print("DEBUG: Intentando guardar en DB (track_user)...")
        await asyncio.to_thread(track_user, user, referrer_id)
        print("DEBUG: track_user OK")
        
        await asyncio.to_thread(log_activity, user.id, "/start")
        print("DEBUG: log_activity OK")

        # 3. Enlaces
        LINK_CANAL = "https://t.me/tasabinance"
        LINK_GRUPO = "https://t.me/tasabinancegrupo"
        LINK_SOPORTE = "https://t.me/tasabinancesoporte"

        # 4. El Mensaje Completo
        msg = (
            f"👋 <b>¡Hola, {user.mention_html()}!</b>\n\n"
            f"Soy tu asistente financiero conectado a 🔶 <b>Binance P2P</b> y al <b>BCV</b>.\n\n"
            f"🚀 <b>HERRAMIENTAS PRINCIPALES:</b>\n"
            f"💵 <b>/precio</b> → Tasa Promedio Instantánea.\n"
            f"🏦 <b>/mercado</b> → Comparativa por Bancos.\n"
            f"📊 <b>/grafico</b> → Tendencia Semanal Viral.\n\n"
            f"🧠 <b>INTELIGENCIA:</b>\n"
            f"🕒 <b>/horario</b> → ¿Mejor hora para cambiar?\n"
            f"🤖 <b>/ia</b> → Predicción (Sube o Baja).\n"
            f"🔔 <b>/alerta</b> → Avisos de precio.\n\n"
            f"🎁 <b>/referidos</b> → ¡Invita y Gana!\n\n"
            f"🧮 <b>CALCULADORA:</b>\n"
            f"• <b>/usdt 100</b> → 100$ a Bs.\n"
            f"• <b>/bs 5000</b> → 5000Bs a $."
        )
        
        # 5. Botones
        keyboard = [
            [InlineKeyboardButton("📢 Canal", url=LINK_CANAL), InlineKeyboardButton("💬 Grupo", url=LINK_GRUPO)],
            [InlineKeyboardButton("🆘 Soporte", url=LINK_SOPORTE)]
        ]
        
        print("DEBUG: Enviando respuesta al usuario...")
        await update.message.reply_html(
            msg, 
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
        print("DEBUG: <<< Comando /start finalizado con éxito ✅")

    except Exception as e:
        print(f"DEBUG ERROR EN START: {str(e)}")
        # Intentamos avisar al usuario si algo falló
        try:
            await update.message.reply_text("❌ Ocurrió un error al iniciar el bot. Por favor, intenta más tarde.")
        except:
            pass

async def global_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # SEGURIDAD: Solo tú puedes usarlo
    ADMIN_ID = 533888411 
    if update.effective_user.id != ADMIN_ID:
        return

    # Extraemos el mensaje quitando el comando /global
    msg_to_send = update.message.text.replace('/global', '').strip()
    
    if not msg_to_send:
        await update.message.reply_text("❌ Formato: /global [mensaje]")
        return

    # Obtenemos la lista de IDs de la DB
    users = await asyncio.to_thread(get_all_user_ids)
    await update.message.reply_text(f"🚀 Iniciando envío a {len(users)} usuarios...")

    # Teclado con el botón de "Entendido"
    keyboard = [[InlineKeyboardButton("✅ Entendido", callback_data="delete_announcement")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    exitos = 0
    errores = 0

    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid, 
                text=msg_to_send, 
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            exitos += 1
            # Pausa obligatoria para evitar baneo de Telegram (Anti-flood)
            await asyncio.sleep(0.08) 
        except Exception:
            errores += 1

    await update.message.reply_text(f"✅ Envío finalizado.\n✨ Éxitos: {exitos}\n❌ Fallidos: {errores}")

async def close_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borra el mensaje global cuando el usuario toca 'Entendido'"""
    query = update.callback_query
    try:
        await query.answer()
        await query.message.delete()
    except Exception:
        pass

# Función para que el botón borre el mensaje
async def close_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Quita el relojito del botón
    await query.message.delete() # Borra el mensaje del chat del usuario
    
@rate_limited(2)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: Ejecutando /help")
    await update.message.reply_html(
        "🆘 <b>Ayuda Rápida:</b>\n\n"
        "• Usa /precio para ver el promedio general.\n"
        "• Usa /mercado para ver precios por banco.\n"
        "• Canal oficial: @tasabinance"
    )

# --- COMANDO /PRECIO (Velocidad de la Luz) ---
@rate_limited(1.5) # Anti-Spam rápido
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await asyncio.to_thread(track_user, user)
    await asyncio.to_thread(log_activity, user.id, "/precio")
    
    # 1. Obtenemos el conteo de consultas (con el reinicio de medianoche VE)
    consultas_hoy = await asyncio.to_thread(get_daily_requests_count)
    
    # 2. Leemos directo de la RAM
    price = MARKET_DATA["price"]
    bcv_usd = MARKET_DATA["bcv"].get("dolar", 0)
    last_upd = MARKET_DATA["last_updated"]

    if not price:
        await update.message.reply_text("🔄 Inicializando motor de precios... intenta en 30 seg.")
        return

    # 3. FORMATEO DE HORA (El "Maquillaje")
    # Si last_upd es un objeto datetime, lo convertimos a string bonito.
    # Si es un string ISO (con la T), lo transformamos.
    ve_tz = pytz.timezone('America/Caracas')
    try:
        if isinstance(last_upd, datetime):
            pretty_time = last_upd.astimezone(ve_tz).strftime("%d/%m/%Y %I:%M:%S %p")
        else:
            # Fallback por si last_upd ya es un texto o viene de otra forma
            pretty_time = datetime.now(ve_tz).strftime("%d/%m/%Y %I:%M:%S %p")
    except Exception:
        pretty_time = str(last_upd)

    # 4. Cálculo de Brecha
    brecha = 0
    if bcv_usd > 0:
        brecha = ((price - bcv_usd) / bcv_usd) * 100

    # 5. Mensaje con la estructura exacta que pediste
    msg = (
        f"🇻🇪 <b>TASA BINANCE VENEZUELA</b>\n"
        f"<i>Promedio P2P (USDT)</i>\n\n"
        f"🔥 <b>{price:,.2f} Bs</b>\n\n"
        f"🏛 <b>BCV:</b> {bcv_usd:,.2f} Bs\n"
        f"📊 <b>Brecha:</b> {brecha:.2f}%\n"
        f"🏪 <b>Actualizado:</b> {pretty_time}\n"
        f"👁 {consultas_hoy:,} consultas hoy"
    )
    
    # Botón para ir al detalle de mercado
    kb = [[InlineKeyboardButton("🏦 Ver Bancos (/mercado)", callback_data="cmd_mercado")]]
    await update.message.reply_html(msg, reply_markup=InlineKeyboardMarkup(kb))

# --- COMANDO /GRAFICO (Blindado) ---
@rate_limited(5) # Más tiempo porque consume CPU
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/grafico")
    
    global GRAPH_CACHE
    today_str = datetime.now(TIMEZONE).date().isoformat()
    
    # 1. RUTA RÁPIDA (Lectura Caché)
    if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
        try:
            await update.message.reply_photo(
                photo=GRAPH_CACHE["photo_id"], 
                caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 @tasabinance_bot", 
                parse_mode=ParseMode.HTML
            )
            return
        except Exception:
            GRAPH_CACHE["photo_id"] = None
            
    # 2. SECCIÓN CRÍTICA (Solo entra uno a la vez)
    async with GRAPH_LOCK:
        # Doble chequeo por si se generó mientras esperábamos
        if GRAPH_CACHE["date"] == today_str and GRAPH_CACHE["photo_id"]:
            await update.message.reply_photo(
                photo=GRAPH_CACHE["photo_id"], 
                caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 @tasabinance_bot", 
                parse_mode=ParseMode.HTML
            )
            return

        # Generación real
        await update.message.reply_chat_action("upload_photo")
        img_buf = await asyncio.to_thread(generate_public_price_chart)
        
        if img_buf:
            sent_msg = await update.message.reply_photo(
                photo=img_buf, 
                caption="📉 <b>Promedio Diario (Semanal)</b>\n\n📲 ¡Compártelo en tus estados!\n\n@tasabinance_bot", 
                parse_mode=ParseMode.HTML
            )
            
            if sent_msg.photo:
                GRAPH_CACHE["date"] = today_str
                GRAPH_CACHE["photo_id"] = sent_msg.photo[-1].file_id
        else:
            await update.message.reply_text("⚠️ No hay suficientes datos históricos.")

# --- COMANDO /REFERIDOS ---
@rate_limited(2)
async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 1. Registro de actividad
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/referidos")
    
    # 2. Obtener datos (Nuestra función en stats.py ya devuelve count, rank y top_3)
    count, rank, top_3 = await asyncio.to_thread(get_referral_stats, user_id)
    
    # 3. Construir el Ranking Visual
    ranking_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(top_3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        # Limpiamos el nombre para que no sea muy largo
        clean_name = name.split()[0] if name else "Usuario"
        ranking_text += f"{medal} <b>{clean_name}</b> — {score} refs\n"

    # 4. Lógica de Enlace y Compartir
    bot_username = context.bot.username
    invite_link = f"https://t.me/{bot_username}?start={user_id}"
    
    # Mensaje que se pre-escribe al darle al botón de compartir
    share_text = f"🎁 ¡Gana 10 USDT con este bot! Entra aquí y participa:\n\n{invite_link}"
    share_url = f"https://t.me/share/url?url={quote(share_text)}"
    
    # 5. Teclado y Mensaje Final (Tu diseño original)
    keyboard = [[InlineKeyboardButton("📤 Comparte y Gana $10", url=share_url)]]
    
    text = (
        f"🎁 <b>PROGRAMA DE REFERIDOS (PREMIOS USDT)</b>\n\n"
        f"¡Gana dinero real invitando a tus amigos!\n"
        f"📅 <b>Corte y Pago:</b> Día 30 de cada mes.\n\n"
        f"🏆 <b>PREMIOS MENSUALES:</b>\n"
        f"🥇 1er Lugar: <b>$10 USDT</b>\n"
        f"🥈 2do Lugar: <b>$5 USDT</b>\n"
        f"🥉 3er Lugar: <b>$5 USDT</b>\n\n"
        f"👤 <b>TUS ESTADÍSTICAS:</b>\n"
        f"👥 Invitados: <b>{count}</b>\n"
        f"🏆 Tu Rango: <b>#{rank}</b>\n\n"
        f"🔗 <b>TU ENLACE ÚNICO:</b>\n"
        f"<code>{invite_link}</code>\n"
        f"<i>(Toca para copiar y compartir)</i>\n\n"
        f"📊 <b>TOP 3 LÍDERES:</b>\n"
        f"{ranking_text}\n"
        f"👇 <b>¡Compártelo ahora!</b>"
    )

    await update.message.reply_text(
        text, 
        parse_mode=ParseMode.HTML, 
        disable_web_page_preview=True, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- COMANDO /IA ---
@rate_limited(3)
async def prediccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(track_user, update.effective_user)
    
    conn = get_conn()
    history = []
    try:
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT buy_pm FROM arbitrage_data ORDER BY id DESC LIMIT 5")
                rows = cur.fetchall()
                history = [r[0] for r in rows][::-1] 
    except Exception: pass
    finally: put_conn(conn)

    if len(history) < 2:
        await update.message.reply_text("🧠 <b>Recopilando datos para IA...</b>", parse_mode=ParseMode.HTML)
        return

    start_p, end_p = history[0], history[-1]
    percent = ((end_p - start_p) / start_p) * 100
    
    if percent > 0.5: emoji, status = EMOJI_SUBIDA, "ALCISTA FUERTE"
    elif percent > 0: emoji, status = EMOJI_SUBIDA, "LIGERAMENTE ALCISTA"
    elif percent < -0.5: emoji, status = EMOJI_BAJADA, "BAJISTA FUERTE"
    elif percent < 0: emoji, status = EMOJI_BAJADA, "LIGERAMENTE BAJISTA"
    else: emoji, status = "⚖️", "LATERAL / ESTABLE"
    
    await update.message.reply_html(
        f"🧠 <b>ANÁLISIS IA (Corto Plazo)</b>\n\n"
        f"{emoji} <b>Tendencia:</b> {status}\n"
        f"📊 <b>Variación (últimos mins):</b> {percent:.2f}%\n"
        f"⚠️ <i>No es consejo financiero.</i>"
    )

# --- COMANDOS ADMIN (Sin límites) ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ADMIN_ID = 533888411 # Tu ID
    if update.effective_user.id != ADMIN_ID:
        return

    # Mensaje de espera (opcional, pero profesional)
    status_msg = await update.message.reply_text("📊 Generando reporte ejecutivo...")

    # Ejecutamos las tareas pesadas en hilos separados
    chart = await asyncio.to_thread(generate_stats_chart)
    report_text = await asyncio.to_thread(get_detailed_report_text)

    if chart:
        # Enviamos la foto con el reporte como leyenda (caption)
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=chart,
            caption=report_text,
            parse_mode='HTML'
        )
        await status_msg.delete()
    else:
        await status_msg.edit_text(f"❌ Error al generar gráficos.\n\n{report_text}")

async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = update.message.text.replace('/global', '').strip()
    if text:
        await asyncio.to_thread(queue_broadcast, text)
        await update.message.reply_text("✅ Mensaje en cola.")

async def debug_mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM arbitrage_data ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        if row: await update.message.reply_html(f"🕵️‍♂️ <b>Debug:</b>\nData: {row}")
        else: await update.message.reply_text("❌ No data.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")
    finally: put_conn(conn)

# --- EVENTOS TÉCNICOS ---
from telegram import ChatMember

async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detecta bloqueos/desbloqueos para limpiar la DB."""
    if not update.my_chat_member: return
    
    user_id = update.my_chat_member.from_user.id
    new_status = update.my_chat_member.new_chat_member.status
    
    db_status = 'active'
    if new_status in [ChatMember.BANNED, ChatMember.LEFT, ChatMember.KICKED]:
        db_status = 'blocked'
    
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET status = %s WHERE user_id = %s", (db_status, user_id))
            conn.commit()
    except Exception as e:
        logging.error(f"Error tracking chat member: {e}")
    finally:
        put_conn(conn)
