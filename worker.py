import os
import logging
import psycopg2
import asyncio
# 👇 IMPORTANTE: Importamos los botones aquí
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

print("👻 FANTASMA: Soy el worker de la RAÍZ")

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
    """Función principal del Worker con Botón Actualizar"""
    logging.info("👷 Worker de Difusión: INICIADO")
    
    bot = Bot(token=TOKEN)
    
    # 👇 PREPARAMOS EL BOTÓN DE UNA VEZ (Para usarlo siempre)
    keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data='refresh')]]
    markup_button = InlineKeyboardMarkup(keyboard)
    
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
                
                cur.execute("UPDATE broadcast_queue SET status = 'processing' WHERE id = %s", (job_id,))
                conn.commit()
                
                users = await get_all_users()
                enviados = 0
                fallidos = 0
                
                # BATCHING
                BATCH = 25
                for i in range(0, len(users), BATCH):
                    batch = users[i:i+BATCH]
                    tasks = []
                    for uid in batch:
                        tasks.append(
                            bot.send_message(
                                chat_id=uid, 
                                text=message, 
                                parse_mode=ParseMode.HTML, 
                                disable_notification=True,
                                reply_markup=markup_button # 👈 AQUÍ AGREGAMOS EL BOTÓN
                            )
                        )
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for res in results:
                        if isinstance(res, Exception): fallidos += 1
                        else: enviados += 1
                    
                    await asyncio.sleep(1) 
                
                cur.execute("UPDATE broadcast_queue SET status = 'done' WHERE id = %s", (job_id,))
                conn.commit()
                
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"✅ <b>Difusión Finalizada</b>\n\n📨 Enviados: {enviados}\n❌ Fallidos: {fallidos}",
                    parse_mode=ParseMode.HTML
                )
            
            cur.close()
            conn.close()
            
        except Exception as e:
            logging.error(f"⚠️ Error en worker loop: {e}")
            
        await asyncio.sleep(10)
