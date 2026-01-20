import os
import logging
import asyncio
import psycopg2
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter  # <--- IMPORTANTE: RetryAfter importado

# Configuración
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Configurar Logging
logging.basicConfig(format='%(asctime)s - WORKER - %(levelname)s - %(message)s', level=logging.INFO)

async def get_active_users():
    # print("   🔍 [DEBUG WORKER] Consultando usuarios activos en DB...") 
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE status = 'active'")
        users = [row[0] for row in cur.fetchall()]
        # print(f"   👥 [DEBUG WORKER] ¡Encontrados {len(users)} usuarios!")
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
                keywords = ["Binance", "BCV", "Mercado", "mercado"]
                
                reply_markup = None
                
                # Si el mensaje tiene esas palabras, pegamos el botón
                if any(k in text for k in keywords):
                    kb = [[InlineKeyboardButton("🔎 Ver Precio en Vivo", callback_data="refresh_price")]]
                    reply_markup = InlineKeyboardMarkup(kb)

                # Variables de conteo
                success = 0
                blocked = 0
                total = len(users)

                # =======================================================
                # ⚙️ CONFIGURACIÓN SEGURA (ZONA VERDE)
                # =======================================================
                BATCH_SIZE = 50   # 50 usuarios por golpe
                SLEEP_TIME = 2.0  # 2 segundos de descanso
                # Resultado: ~25 mensajes/segundo (Telegram permite 30)

                print(f"📨 [DEBUG WORKER] Iniciando envío a {total} personas...")
                print(f"🛡️ Modo: Seguro (Lotes de {BATCH_SIZE})")

                # BUCLE PRINCIPAL DE ENVÍO
                for i in range(0, total, BATCH_SIZE):
                    batch = users[i:i + BATCH_SIZE]
                    
                    # Barra de progreso en consola
                    progress = (i / total) * 100
                    print(f"   📦 [DEBUG WORKER] Procesando {i}-{i+len(batch)} | {progress:.1f}%")
                    
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
                    
                    # Variable para saber si Telegram nos pidió frenar
                    pause_extra = 0

                    try:
                        # 🔥 FUEGO: Enviamos el lote en paralelo
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        for res in results:
                            if isinstance(res, Exception):
                                # Manejo de errores
                                if isinstance(res, Forbidden):
                                    blocked += 1 # Usuario bloqueó el bot
                                elif isinstance(res, RetryAfter):
                                    # 🛑 PROTECCIÓN ANTI-FLOOD ACTIVA
                                    print(f"   ⚠️ [ALERTA] Telegram pide esperar {res.retry_after}s")
                                    # Tomamos el tiempo de espera más largo que nos pidan
                                    if res.retry_after > pause_extra:
                                        pause_extra = res.retry_after
                            else:
                                success += 1
                        
                    except Exception as e:
                        print(f"   ❌ Error grave en lote: {e}")

                    # LÓGICA DE DESCANSO INTELIGENTE
                    if pause_extra > 0:
                        print(f"   ⏳ Pausando {pause_extra + 1}s por orden de Telegram...")
                        await asyncio.sleep(pause_extra + 1)
                    else:
                        # Si todo va bien, descansamos lo normal
                        await asyncio.sleep(SLEEP_TIME)

                # =======================================================
                
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
