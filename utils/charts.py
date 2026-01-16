# utils/charts.py
import matplotlib
matplotlib.use('Agg') # Importante para que no intente abrir ventanas en el servidor
import matplotlib.pyplot as plt
import io
import logging
from datetime import datetime
import psycopg2
from database.db_pool import get_conn, put_conn

# --- INSTRUCCIÓN: ---
# Ve a tu bot.py, BUSCA las funciones:
# 1. def generate_public_price_chart()
# 2. def generate_stats_chart()
# ... y CÓRTALAS de allá y PÉGALAS AQUÍ DEBAJO 👇

# (Pega aquí generate_public_price_chart)
def generate_public_price_chart():
    # (Código V44 - Se mantiene igual)
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT date, (price_sum / NULLIF(count, 0)) as avg_binance, bcv_price FROM daily_stats ORDER BY date DESC LIMIT 7")
        data = cur.fetchall()
        today_date = datetime.now(TIMEZONE).date()
        current_binance = MARKET_DATA["price"]
        current_bcv = MARKET_DATA["bcv"]["usd"] if MARKET_DATA["bcv"] else 0
        has_today = any(d[0] == today_date for d in data)
        if not has_today and current_binance: data.insert(0, (today_date, current_binance, current_bcv))
        data.sort(key=lambda x: x[0]) 
        dates = [d[0].strftime('%d/%m') for d in data]
        prices_bin = [d[1] for d in data]
        prices_bcv = [d[2] if d[2] > 0 else None for d in data]
        if not prices_bin: return None
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(6, 8)) 
        bg_color = '#1e1e1e'
        fig.patch.set_facecolor(bg_color); ax.set_facecolor(bg_color)
        ax.plot(dates, prices_bin, color='#F3BA2F', marker='o', linewidth=4, label="Binance")
        ax.plot(dates, prices_bcv, color='#2979FF', marker='s', linewidth=2, linestyle='--', label="BCV")
        ax.set_title('TASA BINANCE VZLA', color='#F3BA2F', fontsize=18, fontweight='bold', pad=25)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=2, frameon=False)
        for i, price in enumerate(prices_bin):
            ax.annotate(f"{price:.2f}", (dates[i], prices_bin[i]), textcoords="offset points", xytext=(0,15), ha='center', color='white', fontsize=11, fontweight='bold')
        for i, price in enumerate(prices_bcv):
            if price: ax.annotate(f"{price:.2f}", (dates[i], prices_bcv[i]), textcoords="offset points", xytext=(0,-20), ha='center', color='#2979FF', fontsize=10, fontweight='bold')
        fig.text(0.5, 0.5, '@tasabinance_bot', fontsize=28, color='white', ha='center', va='center', alpha=0.08, rotation=45, fontweight='bold')
        plt.tight_layout()
        plt.savefig(buf, format='png', facecolor=bg_color, dpi=100)
        buf.seek(0); plt.close(); cur.close(); conn.close()
        return buf
    except Exception: return None

# (Pega aquí generate_stats_chart)
def generate_stats_chart():
    if not DATABASE_URL: return None
    buf = io.BytesIO()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT TO_CHAR(joined_at, 'MM-DD'), COUNT(*) 
            FROM users WHERE joined_at >= NOW() - INTERVAL '7 DAYS'
            GROUP BY 1 ORDER BY 1
        """)
        growth_data = cur.fetchall()
        cur.execute("""
            SELECT command, COUNT(*) FROM activity_logs 
            GROUP BY command ORDER BY 2 DESC LIMIT 5
        """)
        cmd_data = cur.fetchall()
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
        bg_color = '#212121'
        fig.patch.set_facecolor(bg_color)
        ax1.set_facecolor(bg_color)
        ax2.set_facecolor(bg_color)
        if growth_data:
            dates = [row[0] for row in growth_data]
            counts = [row[1] for row in growth_data]
            bars = ax1.bar(dates, counts, color='#F3BA2F') 
            ax1.set_title('Nuevos Usuarios (7 Días)', color='white', fontsize=12)
            ax1.bar_label(bars, color='white')
        else: ax1.text(0.5, 0.5, "Sin datos", ha='center', color='gray')
        if cmd_data:
            labels = [row[0] for row in cmd_data]
            sizes = [row[1] for row in cmd_data]
            ax2.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, textprops={'color':"white"})
            ax2.set_title('Comandos Favoritos', color='white', fontsize=12)
        else: ax2.text(0.5, 0.5, "Esperando data", ha='center', color='gray')
        plt.tight_layout()
        plt.savefig(buf, format='png', facecolor=bg_color)
        buf.seek(0)
        plt.close()
        cur.close()
        conn.close()
        return buf
    except Exception: return None
