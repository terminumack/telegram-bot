import os
import logging
import asyncio
# 🔥 Importamos el pool que ya tenemos listo
from database.db_pool import get_conn, put_conn, exec_query
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter

# Configuración
TOKEN = os.getenv("TOKEN")

logging.basicConfig(format='%(asctime)s - WORKER - %(levelname)s - %(message)s', level=logging.INFO)

# ==============================================================================
# 🧱 CAPA DE BASE DE DATOS (USANDO EL POOL)
# ==============================================================================

def db_get_active_users():
    """Usa el pool para obtener usuarios activos rápidamente."""
    # Obtenemos solo los activos para no perder tiempo con bloqueados
    rows = exec_query("SELECT user_id FROM users WHERE status = 'active'", fetch=True)
    return [row[0] for row in rows] if rows else []

def db_mark_user_blocked(user_id):
    """Marca al usuario como blocked para no volver a intentar enviarle."""
    exec_query("UPDATE users SET status = 'blocked' WHERE user_id = %s", (user_id,))
    logging.info(f"🚫 Usuario {user_id} marcado como bloqueado.")

def db_update_job_status(job_id, status):
    exec_query("UPDATE broadcast_queue SET status = %s WHERE id = %s", (status, job_id))

def db_check_pending_job():
    res = exec_query(
        "SELECT id, message FROM broadcast_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1", 
        fetch=True
    )
    return res[0] if res else None

# ==============================================================================
# 🚀 WORKER PRINCIPAL
# ==============================================================================

async def background_worker():
    logging.info("👷 Worker INICIADO con soporte para 19K+ usuarios.")
    
    if not TOKEN:
        logging.error("⛔ TOKEN no encontrado.")
        return

    bot = Bot(token=TOKEN)

    while True:
        try:
            # 1. BUSCAR TRABAJO (Súper rápido gracias al pool)
            job = await asyncio.to_thread(db_check_pending_job)

            if job:
                job_id, text = job
                logging.info(f"🚀 TAREA ENCONTRADA! ID: {job_id}")
                
                await asyncio.to_thread(db_update_job_status, job_id, 'processing')
                users = await asyncio.to_thread(db_get_active_users)
                # --- AQUÍ COLOCAS EL CÓDIGO DEL BOTÓN ---
                # Lo preparamos UNA SOLA VEZ antes del bucle para ahorrar procesador
                kb_anuncio = [[InlineKeyboardButton("✅ Entendido", callback_data="delete_announcement")]]
                reply_markup = InlineKeyboardMarkup(kb_anuncio)
                
                if not users:
                    await asyncio.to_thread(db_update_job_status, job_id, 'done')
                    continue

                # Preparar teclado
                reply_markup = None
                if any(k in text.lower() for k in ["binance", "bcv", "mercado", "apertura"]):
                    kb = [[InlineKeyboardButton("🔎 Ver Precio en Vivo", callback_data="refresh_price")]]
                    reply_markup = InlineKeyboardMarkup(kb)

                success, blocked_count, total = 0, 0, len(users)
                
                # CONFIGURACIÓN ÓPTIMA PARA 19K
                BATCH_SIZE = 25   # Bajamos un poco el lote para ser más "amables" con Telegram
                SLEEP_TIME = 1.2  # Ritmo constante: ~20 msgs por segundo (Límite oficial es 30)

                logging.info(f"📨 Enviando a {total} usuarios...")

                for i in range(0, total, BATCH_SIZE):
                    batch = users[i:i + BATCH_SIZE]
                    tasks = []
                    
                    for user_id in batch:
                        tasks.append(
                            bot.send_message(
                                chat_id=user_id,
                                text=text,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                                reply_markup=reply_markup
                            )
                        )
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for idx, res in enumerate(results):
                        if isinstance(res, Exception):
                            if isinstance(res, Forbidden):
                                # 🔥 CRÍTICO: Si nos bloqueó, lo quitamos de la lista para el futuro
                                blocked_count += 1
                                await asyncio.to_thread(db_mark_user_blocked, batch[idx])
                            elif isinstance(res, RetryAfter):
                                logging.warning(f"⚠️ Flood control: esperando {res.retry_after}s")
                                await asyncio.sleep(res.retry_after)
                        else:
                            success += 1
                    
                    await asyncio.sleep(SLEEP_TIME)

                logging.info(f"✅ Tarea #{job_id} FIN: {success} OK | {blocked_count} Bloqueados.")
                await asyncio.to_thread(db_update_job_status, job_id, 'done')

            else:
                await asyncio.sleep(15) # Esperar más si no hay trabajo

        except Exception as e:
            logging.error(f"⚠️ Error en bucle worker: {e}")
            await asyncio.sleep(10)
