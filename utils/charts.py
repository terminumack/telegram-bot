import matplotlib
# ⚠️ Backend no interactivo (OBLIGATORIO para Railway/Servidores)
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import io
import logging
from datetime import datetime
from database.stats import get_conn, put_conn
from shared import MARKET_DATA, TIMEZONE

def generate_public_price_chart():
    """
    Genera el gráfico visual usando 'daily_stats' (Histórico) + RAM (Tiempo Real).
    Estilo: Dark Mode, Amarillo (Binance) vs Azul (BCV).
    """
    conn = get_conn()
    if not conn: return None
    
    buf = io.BytesIO()
    
    try:
        with conn.cursor() as cur:
            # 1. Consultamos la tabla VIEJA (daily_stats)
            # Traemos los últimos 7 días
            cur.execute("""
                SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price 
                FROM daily_stats 
                ORDER BY date DESC LIMIT 7
            """)
            data = cur.fetchall()

        # 2. INYECCIÓN DE DATOS EN TIEMPO REAL
        # Para que el punto de "HOY" salga en el gráfico aunque no se haya guardado en DB aún.
        today_date = datetime.now(TIMEZONE).date()
        current_binance = MARKET_DATA.get("price")
        
        # Manejo seguro del BCV
        bcv_data = MARKET_DATA.get("bcv", {})
        current_bcv = bcv_data.get("dolar") if bcv_data else 0
        
        # Si hoy no está en la DB, lo agregamos manualmente a la lista
        # data es una lista de tuplas, la convertimos a lista de listas para editarla
        data = [list(x) for x in data]
        
        has_today = any(d[0] == today_date for d in data)
        if not has_today and current_binance and current_binance > 0:
            # Insertamos: [fecha, precio_binance, precio_bcv]
            data.insert(0, [today_date, current_binance, current_bcv or 0])

        # Ordenamos por fecha (Ascendente) para graficar de Izquierda a Derecha
        data.sort(key=lambda x: x[0])

        # Validación mínima: Necesitamos al menos 2 puntos para una línea
        if len(data) < 2:
            return None

        # --- PREPARACIÓN MATPLOTLIB ---
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        # BCV: Convertimos 0 a None para que la línea se corte en lugar de caer al suelo
        prices_bcv = [d[2] if d[2] and d[2] > 10 else None for d in data]

        # --- ESTILO VISUAL (DARK MODE) ---
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(6, 8)) # Formato vertical para móviles
        
        # Colores de Fondo
        bg_color = '#1e1e1e'
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        # 1. LÍNEA BINANCE (Amarilla y Gruesa)
        ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=4, label="Binance")
        
        # 2. LÍNEA BCV (Azul y Punteada)
        # Solo graficamos si hay datos válidos de BCV
        if any(p is not None for p in prices_bcv):
            ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, linestyle='--', label="BCV")

        # Títulos y Leyenda
        ax.set_title('TASA BINANCE VZLA', color='#F3BA2F', fontsize=18, fontweight='bold', pad=25)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=2, frameon=False, fontsize=10)

        # Limpieza de Bordes (Para un look más moderno)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#555555')
        ax.spines['left'].set_color('#555555')
        
        # Grid sutil
        ax.grid(True, axis='y', alpha=0.1, color='white', linestyle=':')

        # Ajuste de Márgenes (Para que las etiquetas no se corten arriba/abajo)
        ax.margins(y=0.15) 

        # --- ETIQUETAS DE VALORES (ANNOTATIONS) ---
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

        # Marca de agua (Watermark)
        fig.text(0.5, 0.5, '@tasabinance_bot', fontsize=30, color='white', 
                 ha='center', va='center', alpha=0.08, rotation=45, fontweight='bold')

        plt.tight_layout()
        
        # Guardar en Memoria RAM
        plt.savefig(buf, format='png', facecolor=bg_color, dpi=100)
        buf.seek(0)
        
    except Exception as e:
        logging.error(f"❌ Error generando gráfico: {e}")
        return None
    finally:
        plt.close() # ¡CRÍTICO! Liberar memoria RAM
        put_conn(conn) # Devolver conexión DB

    return buf

def generate_stats_chart():
    """
    Placeholder para futuros gráficos de admin (ej: usuarios nuevos).
    """
    return None
