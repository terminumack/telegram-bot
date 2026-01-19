import os
import logging
import psycopg2
import asyncio
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

print("👻 FANTASMA: Soy el worker de la RAÍZ")

# Configuración
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "533888411"))

async def get_all_users():
    """Obtiene la lista de usuarios activos para el envío."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE status = 'active'")
        users = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return users
    except Exception as e:
        logging.error(f"Error obteniendo usuarios: {e}")
        return []

async def background_worker():
    """
    Función principal del Worker que corre infinitamente.
    Revisa la cola de mensajes y los envía masivamente.
    """
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
                job_id, message_text = job
                logging.info(f"🚀 Iniciando difusión #{job_id}")
                
                # 2. Marcar como procesando
                cur.execute("UPDATE broadcast_queue SET status = 'processing' WHERE id = %s", (job_id,))
                conn.commit()
                
                # --- DETECCIÓN DE CONTENIDO (Para poner botón) ---
                # Si el mensaje parece un reporte de precios, le agregamos el botón.
                reply_markup = None
                keywords = ["Binance", "BCV", "Tasa", "Precio", "Reporte"]
                
                if any(k in message_text for k in keywords):
                    # Creamos el botón "Actualizar Precio"
                    # Callback data "cmd_refresh" debe ser manejado en callbacks.py (o usa /precio si prefieres comando directo)
                    # Pero lo más seguro es usar un botón que mande "/precio" o un callback que llame a precio()
                    # Si tu handler de botones maneja "refresh", usa ese. Si no, usa una URL o simplemente texto.
                    
                    # Opción Estándar: Botón que ejecuta una acción interna
                    # Asegúrate de que tu button_handler en callbacks.py maneje "refresh_price"
                    kb = [[InlineKeyboardButton("🔄 Actualizar Precio", callback_data="refresh_price")]]
                    reply_markup = InlineKeyboardMarkup(kb)
                
                # -------------------------------------------------

                users = await get_all_users()
                enviados = 0
                fallidos = 0
                
                # 3. BATCHING (Lotes de 25 para velocidad y seguridad)
                BATCH = 25
                for i in range(0, len(users), BATCH):
                    batch = users[i:i+BATCH]
                    tasks = []
                    
                    for uid in batch:
                        tasks.append(
                            bot.send_message(
                                chat_id=uid, 
                                text=message_text, 
                                parse_mode=ParseMode.HTML, 
                                disable_notification=True,
                                reply_markup=reply_markup  # <--- AQUÍ VA EL BOTÓN
                            )
                        )
                    
                    # Enviar lote en paralelo
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for res in results:
                        if isinstance(res, Exception): 
                            fallidos += 1
                            # Opcional: Si el error es "Forbidden: bot was blocked", marcar usuario como bloqueado en DB
                        else: 
                            enviados += 1
                    
                    # Descansar 1 segundo para respetar límites de Telegram
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
            logging.error(f"Error en Worker: {e}")
            await asyncio.sleep(5) # Esperar antes de reintentar si hay error grave
        
        # Esperar 10 segundos antes de buscar trabajo de nuevo (ahorra CPU)
        await asyncio.sleep(10)
