import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from database.stats import get_conn, put_conn, log_activity
from database.users import track_user

async def horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/horario")
    
    conn = get_conn()
    if not conn: return

    try:
        msg = await update.message.reply_text("⏳ <i>Analizando historial híbrido (Legacy + V51)...</i>", parse_mode=ParseMode.HTML)
        
        with conn.cursor() as cur:
            # --- SQL HÍBRIDO (LA MAGIA) ---
            # Unimos la tabla NUEVA (arbitrage_data) con la VIEJA (price_ticks)
            # Normalizamos nombres: buy_pm y price_binance se convierten en "precio"
            query = """
                WITH combined_data AS (
                    -- Data Nueva (V51)
                    SELECT recorded_at, buy_pm as precio 
                    FROM arbitrage_data 
                    WHERE recorded_at >= NOW() - INTERVAL '30 DAYS' 
                      AND buy_pm > 0
                    
                    UNION ALL
                    
                    -- Data Vieja (Legacy)
                    SELECT recorded_at, price_binance as precio 
                    FROM price_ticks 
                    WHERE recorded_at >= NOW() - INTERVAL '30 DAYS' 
                      AND price_binance > 0
                )
                SELECT 
                    EXTRACT(HOUR FROM recorded_at - INTERVAL '4 hours') as hora,
                    AVG(precio) as precio_promedio,
                    COUNT(*) as volumen_datos
                FROM combined_data
                GROUP BY hora 
                ORDER BY hora ASC;
            """
            cur.execute(query)
            rows = cur.fetchall()

        if not rows:
            await msg.edit_text("⚠️ No se encontraron datos históricos ni nuevos.")
            return

        # --- PROCESAMIENTO IGUAL AL ANTERIOR ---
        # Filtramos horas con poca data (para evitar picos falsos por 1 solo registro)
        data_by_hour = {}
        for r in rows:
            hora, precio, count = int(r[0]), float(r[1]), int(r[2])
            # Solo consideramos horas que tengan al menos 5 registros históricos para ser fiables
            if count >= 5:
                data_by_hour[hora] = precio

        # Validamos horas comerciales (7am a 10pm)
        valid_hours = {k:v for k,v in data_by_hour.items() if 7 <= k <= 22}
        
        if not valid_hours:
            await msg.edit_text("⚠️ Analizando data... intenta más tarde.")
            return

        best_buy_hour = min(valid_hours, key=valid_hours.get)
        best_sell_hour = max(valid_hours, key=valid_hours.get)
        
        min_price = valid_hours[best_buy_hour]
        max_price = valid_hours[best_sell_hour]

        # --- GENERADOR DE GRÁFICO ASCII ---
        def get_bar(price, min_p, max_p):
            if max_p == min_p: return "▬"
            blocks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
            percent = (price - min_p) / (max_p - min_p)
            index = int(percent * (len(blocks) - 1))
            return blocks[index]

        # --- MENSAJE ---
        text = f"🕒 <b>MEJOR HORARIO (Análisis 30 Días)</b>\n"
        text += f"<i>Fusión de data histórica y tiempo real.</i>\n\n"
        
        text += f"📉 <b>MEJOR COMPRA (Barato):</b>\n"
        text += f"⏰ Entre <b>{best_buy_hour:02d}:00 y {best_buy_hour+1:02d}:00</b>\n"
        text += f"💡 <i>Promedio: {min_price:.2f} Bs</i>\n\n"
        
        text += f"📈 <b>MEJOR VENTA (Caro):</b>\n"
        text += f"⏰ Entre <b>{best_sell_hour:02d}:00 y {best_sell_hour+1:02d}:00</b>\n"
        text += f"💰 <i>Promedio: {max_price:.2f} Bs</i>\n\n"

        text += f"📊 <b>Patrón Intradía:</b>\n"
        text += f"<code>(Hora) (Tendencia)</code>\n"
        
        display_hours = [8, 10, 12, 14, 16, 18, 20, 22]
        for h in display_hours:
            if h in data_by_hour:
                price = data_by_hour[h]
                bar = get_bar(price, min_price, max_price)
                text += f"<code>{h:02d}:00 {bar*6}</code>\n"

        text += "\n🧠 <i>Tip: Compra cuando la barra esté baja.</i>"

        await msg.edit_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"Error horario: {e}")
        await msg.edit_text("⚠️ Error calculando historial.")
    finally:
        put_conn(conn)
