import os
import logging
import asyncio
import psycopg2
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden

# Configuración
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Configurar Logging
logging.basicConfig(format='%(asctime)s - WORKER - %(levelname)s - %(message)s', level=logging.INFO)

async def get_active_users():
    print("   🔍 [DEBUG WORKER] Consultando usuarios activos en DB...")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE status = 'active'")
        users = [row[0] for row in cur.fetchall()]
        print(f"   👥 [DEBUG WORKER] ¡Encontrados {len(users)} usuarios!")
        return users
    except Exception as e:
        print(f"   ❌ [DEBUG WORKER] Error SQL: {e}")
        return []
    finally:
        if conn: conn.close()

async def mark_job_status(job_id, status):
    print(f"   🖊️ [DEBUG WORKER] Actualizando trabajo #{job_id} a estado: '{status}'")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE broadcast_queue SET status = %s WHERE id = %s", (status, job_id))
        conn.commit()
    except Exception as e:
        print(f"   ❌ [DEBUG WORKER] Error actualizando estado: {e}")
    finally:
        if conn: conn.close()

async def background_worker():
    print("\n👷 [DEBUG WORKER] Worker INICIADO. Esperando trabajos en la DB...")
    
    if not TOKEN or not DATABASE_URL:
        print("⛔ [DEBUG WORKER] Faltan variables de entorno.")
        return

    bot = Bot(token=TOKEN)

    while True:
        conn = None
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # Buscar trabajo pendiente
            # print("💤 [DEBUG WORKER] Buscando tareas...") # Comentado para no llenar la consola, descomenta si quieres ver el latido
            
            cur.execute("SELECT id, message FROM broadcast_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
            job = cur.fetchone()
            cur.close()
            conn.close()

            if job:
                job_id, text = job
                print(f"\n🚀 [DEBUG WORKER] ¡NUEVA TAREA ENCONTRADA! ID: {job_id}")
                
                await mark_job_status(job_id, 'processing')

                users = await get_active_users()
                if not users:
                    print("⚠️ [DEBUG WORKER] No hay usuarios. Terminando tarea.")
                    await mark_job_status(job_id, 'done')
                    continue

                # Preparar botón
                reply_markup = None
                if "Binance" in text or "Tasa" in text:
                    kb = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data="refresh_price")]]
                    reply_markup = InlineKeyboardMarkup(kb)

                # Envío Masivo
                success = 0
                blocked = 0
                total = len(users)
                BATCH_SIZE = 25 

                print(f"📨 [DEBUG WORKER] Iniciando envío a {total} personas...")

                for i in range(0, total, BATCH_SIZE):
                    batch = users[i:i + BATCH_SIZE]
                    print(f"   📦 [DEBUG WORKER] Enviando lote {i} - {i + len(batch)}...")
                    
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

                    for res in results:
                        if isinstance(res, Exception):
                            if isinstance(res, Forbidden):
                                blocked += 1
                            else:
                                print(f"   ❌ [DEBUG WORKER] Error de envío: {res}")
                        else:
                            success += 1
                    
                    await asyncio.sleep(1.5)

                print(f"✅ [DEBUG WORKER] Tarea #{job_id} COMPLETADA.")
                print(f"📊 [DEBUG WORKER] Resultados: {success} enviados | {blocked} bloqueados")
                
                await mark_job_status(job_id, 'done')

            else:
                # Si no hay trabajo, esperar 10 segundos
                await asyncio.sleep(10)

        except Exception as e:
            print(f"⚠️ [DEBUG WORKER] Error general en el bucle: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(background_worker())
