import matplotlib
# ⚠️ IMPORTANTE: Backend sin interfaz gráfica para servidores
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import logging
from database.stats import get_conn, put_conn # <--- Import correcto para la V51

def generate_public_price_chart():
    """Genera el gráfico de precios históricos usando 'arbitrage_data'."""
    conn = get_conn()
    if not conn: return None
    buf = None
    
    try:
        logging.info("📊 Iniciando generación de gráfico...")
        
        dates = []
        prices = []
        
        with conn.cursor() as cur:
            # CONSULTA CORREGIDA:
            # Usamos 'arbitrage_data' que es la tabla que SÍ se está llenando.
            # Sacamos el promedio por día de los últimos 7 días.
            cur.execute("""
                SELECT 
                    DATE(created_at) as dia, 
                    AVG(buy_pm) as precio_promedio
                FROM arbitrage_data 
                WHERE created_at >= NOW() - INTERVAL '7 DAYS' 
                GROUP BY dia 
                ORDER BY dia ASC
            """)
            rows = cur.fetchall()

            for r in rows:
                dates.append(r[0]) # Objeto Date
                prices.append(float(r[1])) # Float

        if len(prices) < 2:
            logging.warning("⚠️ Datos insuficientes para graficar (Mínimo 2 días).")
            return None

        # --- CREAR FIGURA MEJORADA ---
        plt.figure(figsize=(10, 5), dpi=100)
        
        # Línea Dorada Binance
        plt.plot(dates, prices, marker='o', linestyle='-', color='#F0B90B', linewidth=2, label='Tasa Binance')
        
        # Relleno debajo (Efecto profesional)
        plt.fill_between(dates, prices, min(prices)*0.99, color='#F0B90B', alpha=0.1)
        
        # Títulos y Estilos
        plt.title('Tendencia de la Tasa (Últimos 7 Días)', fontsize=14, fontweight='bold', color='#333333')
        plt.ylabel('Bolívares (Bs)', fontsize=12)
        plt.grid(True, which='both', linestyle='--', alpha=0.5)
        
        # Formato de Fechas Inteligente (Eje X)
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator())
        plt.xticks(rotation=0) # Fechas horizontales se leen mejor
        
        # Etiqueta del Precio Final (El detalle que gusta a los usuarios)
        last_date = dates[-1]
        last_price = prices[-1]
        plt.annotate(f'{last_price:.2f} Bs', 
                     xy=(last_date, last_price), 
                     xytext=(0, 15), textcoords='offset points',
                     ha='center', fontsize=10, fontweight='bold', 
                     bbox=dict(boxstyle="round,pad=0.3", fc="#F0B90B", ec="none", alpha=0.9))

        plt.tight_layout()

        # --- GUARDAR EN MEMORIA ---
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0) # Rebobinar
        
        logging.info("✅ Gráfico generado correctamente.")

    except Exception as e:
        logging.error(f"❌ Error generando gráfico: {e}")
        return None
    finally:
        plt.close() # Limpiar memoria de matplotlib
        put_conn(conn)
        
    return buf

def generate_stats_chart():
    """Placeholder para gráfico de admins"""
    return None
