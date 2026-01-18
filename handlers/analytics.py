# En handlers/commands.py

from database.stats import get_conn, put_conn
import statistics

async def horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/horario")
    
    conn = get_conn()
    if not conn: return

    try:
        msg = await update.message.reply_text("⏳ <i>Analizando patrones de mercado (7 días)...</i>", parse_mode=ParseMode.HTML)
        
        with conn.cursor() as cur:
            # SQL MAGIA: 
            # 1. Filtramos últimos 7 días.
            # 2. Convertimos la hora a Zona Vzla ('-04' horas).
            # 3. Promediamos el precio de PagoMóvil (buy_pm) por hora.
            query = """
                SELECT 
                    EXTRACT(HOUR FROM recorded_at - INTERVAL '4 hours') as hora,
                    AVG(buy_pm) as precio_promedio
                FROM arbitrage_data 
                WHERE recorded_at >= NOW() - INTERVAL '7 DAYS' 
                  AND buy_pm > 0
                GROUP BY hora 
                ORDER BY hora ASC;
            """
            cur.execute(query)
            rows = cur.fetchall() # Lista de tuplas [(8, 65.5), (9, 65.2)...]

        if not rows:
            await msg.edit_text("⚠️ Aún no tengo suficiente data histórica. Intenta en unos días.")
            return

        # --- PROCESAMIENTO DE DATOS ---
        # Convertimos a diccionario para fácil acceso
        data_by_hour = {int(r[0]): float(r[1]) for r in rows}
        
        # Encontramos la hora más barata y la más cara (excluyendo madrugada 0-6am por baja liquidez)
        valid_hours = {k:v for k,v in data_by_hour.items() if 7 <= k <= 22}
        
        if not valid_hours:
            await msg.edit_text("⚠️ Recopilando datos diurnos...")
            return

        best_buy_hour = min(valid_hours, key=valid_hours.get) # Hora con precio más bajo
        best_sell_hour = max(valid_hours, key=valid_hours.get) # Hora con precio más alto
        
        min_price = valid_hours[best_buy_hour]
        max_price = valid_hours[best_sell_hour]

        # --- GENERADOR DE GRÁFICO ASCII ---
        # Normalizamos las barras para que se vean bonitas
        def get_bar(price, min_p, max_p):
            if max_p == min_p: return "▬"
            # Escala de 0 a 8 bloques
            blocks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
            percent = (price - min_p) / (max_p - min_p)
            index = int(percent * (len(blocks) - 1))
            return blocks[index]

        # --- CONSTRUCCIÓN DEL MENSAJE EMOCIONAL ---
        text = f"🕒 <b>MEJOR HORARIO PARA OPERAR</b>\n"
        text += f"<i>Basado en el comportamiento de los últimos 7 días.</i>\n\n"
        
        # 1. El Veredicto (Lo que el usuario quiere saber ya)
        text += f"📉 <b>MEJOR COMPRA (Barato):</b>\n"
        text += f"⏰ Entre <b>{best_buy_hour:02d}:00 y {best_buy_hour+1:02d}:00</b>\n"
        text += f"💡 <i>Ahorro potencial detectado.</i>\n\n"
        
        text += f"📈 <b>MEJOR VENTA (Caro):</b>\n"
        text += f"⏰ Entre <b>{best_sell_hour:02d}:00 y {best_sell_hour+1:02d}:00</b>\n"
        text += f"💰 <i>Maximiza tus bolívares aquí.</i>\n\n"

        # 2. El Gráfico Visual (La "Tendencia")
        text += f"📊 <b>Tendencia Diaria Promedio:</b>\n"
        text += f"<code>(Hora) (Intensidad)</code>\n"
        
        # Mostramos horas clave (ej: cada 3 horas para no saturar)
        display_hours = [8, 10, 12, 14, 16, 18, 20, 22]
        
        for h in display_hours:
            if h in data_by_hour:
                price = data_by_hour[h]
                bar = get_bar(price, min_price, max_price)
                # Formato: 08:00 ▃▃▃▃▃
                # Repetimos la barra 5 veces para dar efecto visual
                text += f"<code>{h:02d}:00 {bar*6}</code>\n"

        text += "\n🧠 <i>Tip: El mercado suele tener mayor liquidez al mediodía.</i>"

        await msg.edit_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"Error horario: {e}") # Debug consola
        await msg.edit_text("⚠️ Error analizando horarios.")
    finally:
        put_conn(conn)
