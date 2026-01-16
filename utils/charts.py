import matplotlib
# ⚠️ IMPORTANTE: Esto debe ir ANTES de importar pyplot
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import io
import logging
from database.db_pool import get_conn, put_conn

def generate_public_price_chart():
    """Genera el gráfico de precios históricos."""
    conn = get_conn()
    buf = None
    try:
        logging.info("📊 Iniciando generación de gráfico...")
        
        with conn.cursor() as cur:
            # Obtenemos los últimos 7 días de datos
            cur.execute("""
                SELECT date, price_sum / count as avg_price 
                FROM daily_stats 
                ORDER BY date ASC 
                LIMIT 30
            """)
            rows = cur.fetchall()

        if not rows:
            logging.warning("⚠️ No hay datos en daily_stats para graficar.")
            return None

        # Separar datos para ejes X e Y
        fechas = [r[0].strftime("%d/%m") for r in rows]
        precios = [float(r[1]) for r in rows]

        # --- CREAR FIGURA ---
        plt.figure(figsize=(10, 5))
        plt.plot(fechas, precios, marker='o', linestyle='-', color='#F3BA2F', linewidth=2)
        
        plt.title('Precio Promedio (Binance P2P)', fontsize=14)
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # --- GUARDAR EN MEMORIA ---
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        
        # 🔑 LA CLAVE MÁGICA: Rebobinar el buffer al inicio
        buf.seek(0) 
        
        logging.info("✅ Gráfico generado correctamente.")

    except Exception as e:
        logging.error(f"❌ Error generando gráfico: {e}")
        return None
    finally:
        # Siempre cerrar el plot y devolver conexión
        plt.close()
        put_conn(conn)
        
    return buf

def generate_stats_chart():
    """Genera gráfico de usuarios (Para Admin)."""
    # (Si no usas este comando aún, puedes dejarlo así simple o copiar la lógica de arriba)
    return None
