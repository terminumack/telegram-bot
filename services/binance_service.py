import requests
import logging
import asyncio
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
]

def fetch_binance_specific(trade_type, bank_input, amount=2000):
    """
    Función Síncrona (Bloqueante) para consultar un banco específico.
    Incluye lógica de reintento (Fallback) si no hay comerciantes verificados.
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    
    # Payload inicial (Buscamos solo Comerciantes 'merchant')
    payload = {
        "page": 1, 
        "rows": 5, 
        "payTypes": [bank_input] if bank_input else [],
        "publisherType": "merchant",
        "transAmount": str(amount),
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": trade_type
    }

    try:
        # Intento 1: Comerciantes Verificados
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()
        
        # Intento 2: Fallback (Si no hay merchant, buscamos a todos)
        if not data.get("data"):
            del payload["publisherType"] # Quitamos el filtro
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            data = response.json()

        prices = [float(item["adv"]["price"]) for item in data.get("data", [])]
        
        if not prices: return 0.0
        
        # Promedio de los primeros 3 para evitar precios falsos
        top_prices = prices[:3]
        avg_price = sum(top_prices) / len(top_prices)
        
        return avg_price

    except Exception as e:
        # logging.error(f"Error Binance {bank_input}: {e}") 
        return 0.0

async def get_market_snapshot():
    """
    EL MULTI-SCANNER:
    Lanza 5 peticiones en paralelo. Tarda lo mismo que hacer una sola (aprox 2 seg).
    """
    # Definimos las tareas (pero no las ejecutamos aún)
    # Usamos un monto base de 2000 Bs para filtrar órdenes muy pequeñas
    tasks = [
        asyncio.to_thread(fetch_binance_specific, "BUY", "PagoMovil", 2000),
        asyncio.to_thread(fetch_binance_specific, "SELL", "PagoMovil", 2000),
        asyncio.to_thread(fetch_binance_specific, "BUY", "Banesco", 2000),
        asyncio.to_thread(fetch_binance_specific, "BUY", "Mercantil", 2000),
        asyncio.to_thread(fetch_binance_specific, "BUY", "Provincial", 2000)
    ]
    
    # ¡FUEGO! Ejecutamos todas a la vez
    results = await asyncio.gather(*tasks)
    
    # Retornamos el diccionario listo para bot.py
    return {
        "pm_buy": results[0],
        "pm_sell": results[1],
        "ban_buy": results[2],
        "mer_buy": results[3],
        "pro_buy": results[4]
    }

# Mantenemos esta función por compatibilidad si algún archivo viejo la llama
async def get_binance_price(trade_type="BUY", bank="PagoMovil", reference_price=None):
    """Wrapper de compatibilidad para código legado."""
    price = await asyncio.to_thread(fetch_binance_specific, trade_type, bank)
    return round(price, 2) if price > 0 else None
