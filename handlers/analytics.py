import asyncio
import statistics
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from database.stats import get_conn, put_conn, log_activity
from database.users import track_user

async def horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Tracking
    await asyncio.to_thread(track_user, update.effective_user)
    await asyncio.to_thread(log_activity, user_id, "/horario")
    
    conn = get_conn()
    if not conn: return

    try:
        msg = await update.message.reply_text("⏳ <i>Calculando ventajas porcentuales...</i>", parse_mode=ParseMode.HTML)
        
        with conn.cursor() as cur:
            # La consulta SQL sigue igual (trae promedios absolutos)
            # La magia porcentual la haremos en Python
            query = """
                WITH combined_data AS (
                    SELECT recorded_at, buy_pm as precio 
                    FROM arbitrage_data 
                    WHERE recorded_at >= NOW() - INTERVAL '30 DAYS' 
                      AND buy_pm > 0
                    UNION ALL
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
            await msg.edit_text("⚠️ Aún no hay suficiente data para calcular porcentajes.")
            return

        # --- PROCESAMIENTO MATEMÁTICO ---
        data_by_hour = {}
        for r in rows:
            hora, precio, count = int(r[0]), float(r[1]), int(r[2])
            if count >= 5: # Filtro de fiabilidad
                data_by_hour[hora] = precio

        valid_hours = {k:v for k,v in data_by_hour.items() if 7 <= k <= 23 or k == 0} # Incluimos hasta media noche
        
        if not valid_hours:
            await msg.edit_text("⚠️ Data insuficiente. Intenta más tarde.")
            return

        # 1. Calcular la Media Global del día (El "Cero" relativo)
        all_prices = list(valid_hours.values())
        daily_mean = sum(all_prices) / len(all_prices)

        # 2. Encontrar Picos y Valles
        best_buy_hour = min(valid_hours, key=valid_hours.get) # Hora más barata
        best_sell_hour = max(valid_hours, key=valid_hours.get) # Hora más cara
        
        min_price = valid_hours[best_buy_hour]
        max_price = valid_hours[best_sell_hour]

        # 3. CONVERTIR A PORCENTAJES (La clave)
        # Cuánto te ahorras comprando a la hora baja vs la media del día
        ahorro_pct = ((min_price - daily_mean) / daily_mean) * 100
        
        # Cuánto ganas extra vendiendo a la hora alta vs la media del día
        ganancia_pct = ((max_price - daily_mean) / daily_mean) * 100
        
        # El GAP Total (Diferencia entre comprar barato y vender caro)
        total_gap = ((max_price - min_price) / min_price) * 100

        # --- GENERADOR GRÁFICO ---
        def get_bar(price, min_p, max_p):
            if max_p == min_p: return "▬"
            blocks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
            percent = (price - min_p) / (max_p - min_p)
            index = int(percent * (len(blocks) - 1))
            index = max(0, min(index, len(blocks) - 1))
            return blocks[index]

        # --- MENSAJE ---
        text = f"🕒 <b>ESTRATEGIA HORARIA (Intradía)</b>\n"
        text += f"<i>Ventaja porcentual vs Promedio Diario.</i>\n\n"
        
        text += f"📉 <b>MEJOR COMPRA (Barato):</b>\n"
        text += f"⏰ Hora: <b>{best_buy_hour:02d}:00 - {best_buy_hour+1:02d}:00</b>\n"
        text += f"✅ <b>{ahorro_pct:.2f}%</b> más barato que la media.\n\n"
        
        text += f"📈 <b>MEJOR VENTA (Caro):</b>\n"
        text += f"⏰ Hora: <b>{best_sell_hour:02d}:00 - {best_sell_hour+1:02d}:00</b>\n"
        text += f"🚀 <b>+{ganancia_pct:.2f}%</b> de ganancia sobre la media.\n\n"

        text += f"📊 <b>Potencial de Arbitraje:</b>\n"
        text += f"Si compras a las {best_buy_hour}:00 y vendes a las {best_sell_hour}:00,\n"
        text += f"💰 <b>Margen Teórico: {total_gap:.2f}%</b>\n\n"

        text += f"<b>Patrón Visual:</b>\n"
        
        display_hours = [8, 10, 12, 14, 16, 18, 20, 22]
        for h in display_hours:
            if h in data_by_hour:
                price = data_by_hour[h]
                bar = get_bar(price, min_price, max_price)
                # Calculamos % relativo de esa hora específica
                diff = ((price - daily_mean) / daily_mean) * 100
                sign = "+" if diff > 0 else ""
                text += f"<code>{h:02d}:00 {bar*4} {sign}{diff:.1f}%</code>\n"

        text += "\n🧠 <i>Tip: % negativo es bueno para comprar.</i>"

        await msg.edit_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"Error horario: {e}")
        await msg.edit_text("⚠️ Error calculando porcentajes.")
    finally:
        put_conn(conn)
