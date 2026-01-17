import requests
import logging
import asyncio
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
]

async def get_binance_price(trade_type="BUY", bank="PagoMovil", reference_price=None):
    """
    Obtiene precio de Binance permitiendo filtros (BUY/SELL y Banco).
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    
    # 1. Determinar precio de referencia para el filtro de monto
    # Si no nos dan referencia, usamos 65.0 por defecto
    current_ref = reference_price if reference_price else 65.0
    
    # Monto seguro: entre 2000 y 20000 Bs (Ajustado a tu lógica)
    safe_amount = max(2000, min(int(current_ref * 20), 20000))
    
    # 2. Configurar Payload
    payload = {
        "page": 1, 
        "rows": 5, # Traemos 5 para tener margen
        "payTypes": [bank] if bank else [], # Si es None, busca todos
        "publisherType": "merchant",
        "transAmount": str(safe_amount), 
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": trade_type # "BUY" o "SELL"
    }

    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
        data = response.json()

        # Fallback: Si no hay merchants, buscamos a todos
        if not data.get("data"):
            del payload["publisherType"]
            response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
            data = response.json()

        prices = [float(item["adv"]["price"]) for item in data.get("data", [])]

        if not prices:
            return None

        # Promedio Top 3
        top_prices = prices[:3]
        avg_price = sum(top_prices) / len(top_prices)
        
        return round(avg_price, 2)

    except Exception as e:
        logging.error(f"❌ Error Binance ({trade_type}): {e}")
        return None
