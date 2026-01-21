import os
import logging
import asyncio
import psycopg2
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter

# Configuración
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Configurar Logging
logging.basicConfig(format='%(asctime)s - WORKER - %(levelname)s - %(message)s', level=logging.INFO)

# ==============================================================================
# 🧱 CAPA DE BASE DE DATOS (SÍNCRONA - SE EJECUTA EN HILOS APARTE)
# ==============================================================================

def db_get_active_users():
    """Función bloqueante que busca usuarios (se ejecutará en un hilo)."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE status = 'active'")
        users = [row[0] for row in cur.fetchall()]
        return users
    except Exception as e:
        print(f"   ❌ [DEBUG WORKER] Error SQL (Get Users): {e}")
        return []
    finally:
        if conn: conn.close()

def db_update_job_status(job_id, status):
    """Función bloqueante que actualiza estado."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE broadcast_queue SET status = %s WHERE id = %s", (status, job_id))
        conn.commit()
    except Exception as e:
        print(f"   ❌ [DEBUG WORKER] Error SQL (Update Status): {e}")
    finally:
        if conn: conn.close()

def db_check_pending_job():
    """Busca si hay trabajo pendiente."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT id, message FROM broadcast_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
        job = cur.fetchone()
        return job
    except Exception as e:
        print(f"   ❌ [DEBUG WORKER] Error SQL (Check Job): {e}")
        return None
    finally:
        if conn: conn.close()

# ==============================================================================
# 🚀 WORKER PRINCIPAL (ASÍNCRONO)
# ==============================================================================

async def background_worker():
    print("\n👷 [DEBUG WORKER] Worker INICIADO. Esperando trabajos en la DB...")
    
    if not TOKEN or not DATABASE_URL:
        print("⛔ [DEBUG WORKER] Faltan variables de entorno.")
        return

    bot = Bot(token=TOKEN)

    while True:
        try:
            # 1. BUSCAR TRABAJO (En un hilo aparte para no bloquear al bot)
            # Usamos asyncio.to_thread para que psycopg2 no congele el bot
            job = await asyncio.to_thread(db_check_pending_job)

            if job:
                job_id, text = job
                print(f"\n🚀 [DEBUG WORKER] ¡NUEVA TAREA ENCONTRADA! ID: {job_id}")
                
                # Marcar como procesando (en hilo aparte)
                await asyncio.to_thread(db_update_job_status, job_id, 'processing')

                # Obtener usuarios (en hilo aparte - ESTO ERA LO QUE CONGELABA ANTES)
                users = await asyncio.to_thread(db_get_active_users)
                
                if not users:
                    print("⚠️ [DEBUG WORKER] No hay usuarios. Terminando tarea.")
                    await asyncio.to_thread(db_update_job_status, job_id, 'done')
                    continue

                # Preparar botón
                keywords = ["Binance", "BCV", "Mercado", "mercado", "Apertura", "Tendencia"]
                reply_markup = None
                
                if any(k in text for k in keywords):
                    kb = [[InlineKeyboardButton("🔎 Ver Precio en Vivo", callback_data="refresh_price")]]
                    reply_markup = InlineKeyboardMarkup(kb)

                # Variables
                success = 0
                blocked = 0
                total = len(users)

                # CONFIGURACIÓN DE ENVÍO
                BATCH_SIZE = 50   
                SLEEP_TIME = 2.0  

                print(f"📨 [DEBUG WORKER] Iniciando envío a {total} personas...")

                # BUCLE PRINCIPAL DE ENVÍO
                for i in range(0, total, BATCH_SIZE):
                    batch = users[i:i + BATCH_SIZE]
                    
                    # Progreso visual
                    progress = (i / total) * 100
                    # Comentamos el print por lote para no saturar consola, descomenta si quieres ver
                    # print(f"   📦 [DEBUG WORKER] Procesando {i}-{i+len(batch)} | {progress:.1f}%")
                    
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
                    
                    pause_extra = 0

                    try:
                        # 🔥 FUEGO: Enviamos el lote en paralelo
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        for res in results:
                            if isinstance(res, Exception):
                                if isinstance(res, Forbidden):
                                    blocked += 1 
                                elif isinstance(res, RetryAfter):
                                    # 🛑 PROTECCIÓN ANTI-FLOOD
                                    print(f"   ⚠️ [ALERTA] Telegram pide esperar {res.retry_after}s")
                                    if res.retry_after > pause_extra:
                                        pause_extra = res.retry_after
                            else:
                                success += 1
                        
                    except Exception as e:
                        print(f"   ❌ Error grave en lote: {e}")

                    # DESCANSO
                    if pause_extra > 0:
                        await asyncio.sleep(pause_extra + 1)
                    else:
                        await asyncio.sleep(SLEEP_TIME)

                # FIN DE LA TAREA
                print(f"✅ [DEBUG WORKER] Tarea #{job_id} COMPLETADA.")
                print(f"📊 [DEBUG WORKER] Resultados: {success} enviados | {blocked} bloqueados")
                
                # Marcar como terminado (en hilo aparte)
                await asyncio.to_thread(db_update_job_status, job_id, 'done')

            else:
                # Si no hay trabajo, esperar 10 segundos
                # (Esto no bloquea, es un sleep asíncrono real)
                await asyncio.sleep(10)

        except Exception as e:
            print(f"⚠️ [DEBUG WORKER] Error general en el bucle: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(background_worker())
