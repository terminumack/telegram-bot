import os
import logging
import psycopg2
import asyncio
from telegram import Bot
from telegram.constants import ParseMode

# Configuración
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

async def get_all_users():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE status = 'active'")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return users

async def background_worker():
    """Función principal del Worker que corre infinitamente"""
    logging.info("👷 Worker de Difusión: INICIADO")
    
    # Creamos una instancia del bot solo para enviar mensajes
    bot = Bot(token=TOKEN)
    
    while True:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # 1. Buscar trabajo pendiente
            cur.execute("SELECT id, message FROM broadcast_queue WHERE status = 'pending' LIMIT 1")
            job = cur.fetchone()
            
            if job:
                job_id, message = job
                logging.info(f"🚀 Iniciando difusión #{job_id}")
                
                # 2. Marcar como procesando
                cur.execute("UPDATE broadcast_queue SET status = 'processing' WHERE id = %s", (job_id,))
                conn.commit()
                
                users = await get_all_users()
                enviados = 0
                fallidos = 0
                
                # 3. BATCHING (Lotes de 25)
                BATCH = 25
                for i in range(0, len(users), BATCH):
                    batch = users[i:i+BATCH]
                    tasks = []
                    for uid in batch:
                        tasks.append(
                            bot.send_message(chat_id=uid, text=message, parse_mode=ParseMode.HTML, disable_notification=True)
                        )
                    
                    # Enviar lote en paralelo
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for res in results:
                        if isinstance(res, Exception): fallidos += 1
                        else: enviados += 1
                    
                    # Descansar 1 segundo para no enojar a Telegram
                    await asyncio.sleep(1) 
                
                # 4. Marcar como terminado
                cur.execute("UPDATE broadcast_queue SET status = 'done' WHERE id = %s", (job_id,))
                conn.commit()
                
                # 5. Reporte al Admin
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"✅ <b>Difusión Finalizada</b>\n\n📨 Enviados: {enviados}\n❌ Fallidos: {fallidos}",
                    parse_mode=ParseMode.HTML
                )
            
            cur.close()
            conn.close()
            
        except Exception as e:
            logging.error(f"⚠️ Error en worker loop: {e}")
            
        # Revisar la base de datos cada 10 segundos
        await asyncio.sleep(10)
