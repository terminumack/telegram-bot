import matplotlib
matplotlib.use('Agg') # Backend para servidores sin pantalla
import matplotlib.pyplot as plt
import io
import logging
from datetime import datetime
from database.stats import get_conn, put_conn
from shared import MARKET_DATA, TIMEZONE

def generate_public_price_chart():
    """
    Genera el gráfico usando la tabla histórica 'daily_stats' (Estilo Original).
    Incluye línea de Binance y línea de BCV.
    """
    conn = get_conn()
    if not conn: return None
    
    buf = io.BytesIO()
    
    try:
        with conn.cursor() as cur:
            # 1. Consultamos la tabla VIEJA (daily_stats)
            cur.execute("""
                SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price 
                FROM daily_stats 
                ORDER BY date DESC LIMIT 7
            """)
            data = cur.fetchall()

        # 2. Datos en tiempo real (Para que el punto de hoy salga aunque no se haya guardado en DB)
        today_date = datetime.now(TIMEZONE).date()
        current_binance = MARKET_DATA.get("price")
        
        # Manejo seguro del BCV en tiempo real
        bcv_data = MARKET_DATA.get("bcv", {})
        current_bcv = bcv_data.get("dolar") if bcv_data else 0
        
        # Si hoy no está en la DB, lo agregamos manualmente a la lista
        has_today = any(d[0] == today_date for d in data)
        if not has_today and current_binance:
            # Insertamos tupla: (fecha, precio_binance, precio_bcv)
            data.insert(0, (today_date, current_binance, current_bcv or 0))

        # Ordenamos por fecha (Ascendente) para que el gráfico vaya de izq a der
        data.sort(key=lambda x: x[0])

        if len(data) < 2:
            return None

        # Preparar listas para Matplotlib
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        # Solo graficar BCV si tiene valor > 0, si no None (para que no caiga a cero)
        prices_bcv = [d[2] if d[2] and d[2] > 0 else None for d in data]

        # --- ESTILO VISUAL (TU ORIGINAL DARK) ---
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(6, 8))
        
        # Colores originales
        bg_color = '#1e1e1e'
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        # Línea Binance (Amarilla gruesa)
        ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=4, label="Binance")
        
        # Línea BCV (Azul punteada)
        # Filtramos None para evitar errores al graficar
        if any(prices_bcv):
            ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, linestyle='--', label="BCV")

        # Títulos y Leyenda
        ax.set_title('TASA BINANCE VZLA', color='#F3BA2F', fontsize=18, fontweight='bold', pad=25)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=2, frameon=False)

        # Etiquetas de valores (Anotaciones)
        # Binance (Arriba)
        for i, price in enumerate(prices_bin):
            if price:
                ax.annotate(f"{price:.2f}", (dates[i], prices_bin[i]), 
                           textcoords="offset points", xytext=(0,15), ha='center', 
                           color='white', fontsize=11, fontweight='bold')
        
        # BCV (Abajo)
        for i, price in enumerate(prices_bcv):
            if price:
                ax.annotate(f"{price:.2f}", (dates[i], prices_bcv[i]), 
                           textcoords="offset points", xytext=(0,-20), ha='center', 
                           color='#2979FF', fontsize=10, fontweight='bold')

        # Marca de agua
        fig.text(0.5, 0.5, '@tasabinance_bot', fontsize=28, color='white', 
                 ha='center', va='center', alpha=0.08, rotation=45, fontweight='bold')

        plt.tight_layout()
        
        # Guardar
        plt.savefig(buf, format='png', facecolor=bg_color, dpi=100)
        buf.seek(0)
        
    except Exception as e:
        logging.error(f"❌ Error generando gráfico: {e}")
        return None
    finally:
        plt.close() # Liberar memoria RAM
        put_conn(conn) # Devolver conexión al pool

    return buf

def generate_stats_chart():
    """
    Gráfico para Admin (/stats). 
    Si quieres implementar el de torta/barras, ponlo aquí.
    Por ahora retorna None para evitar errores.
    """
    return None
