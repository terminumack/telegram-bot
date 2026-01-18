import requests
import logging
import asyncio
import random
from shared import MARKET_DATA  # <--- IMPORTAMOS LA MEMORIA

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
]

def fetch_binance_specific(trade_type, bank_input, amount):
    """
    Función Síncrona. Recibe 'amount' que puede variar en cada llamada.
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    
    payload = {
        "page": 1, 
        "rows": 5, 
        "payTypes": [bank_input] if bank_input else [],
        "publisherType": "merchant",
        "transAmount": str(amount), # <--- AQUÍ SE USA EL MONTO CALCULADO
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": trade_type
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()
        
        # Fallback: Si no hay merchants, buscamos a todos
        if not data.get("data"):
            del payload["publisherType"]
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            data = response.json()

        prices = [float(item["adv"]["price"]) for item in data.get("data", [])]
        
        if not prices: return 0.0
        
        top_prices = prices[:3]
        return sum(top_prices) / len(top_prices)

    except Exception:
        return 0.0

async def get_market_snapshot():
    """
    EL SUPER-SCANNER DINÁMICO:
    Calcula el filtro basado en $20 USD al precio actual.
    """
    # 1. CALCULO DINÁMICO DEL FILTRO
    # Obtenemos el precio actual de la memoria. Si no existe (arranque), usamos 65.0
    current_price = MARKET_DATA["price"] if MARKET_DATA["price"] else 65.0
    
    # Regla de los $20 USD (Monto estándar de transacción)
    # Ejemplo: 65 Bs * 20 = 1300 Bs
    dynamic_amount = int(current_price * 20)
    
    # 2. LANZAMOS PETICIONES CON EL MONTO AJUSTADO
    tasks = [
        # PagoMóvil
        asyncio.to_thread(fetch_binance_specific, "BUY", "PagoMovil", dynamic_amount),
        asyncio.to_thread(fetch_binance_specific, "SELL", "PagoMovil", dynamic_amount),
        # Banesco
        asyncio.to_thread(fetch_binance_specific, "BUY", "Banesco", dynamic_amount),
        asyncio.to_thread(fetch_binance_specific, "SELL", "Banesco", dynamic_amount),
        # Mercantil
        asyncio.to_thread(fetch_binance_specific, "BUY", "Mercantil", dynamic_amount),
        asyncio.to_thread(fetch_binance_specific, "SELL", "Mercantil", dynamic_amount),
        # Provincial
        asyncio.to_thread(fetch_binance_specific, "BUY", "Provincial", dynamic_amount),
        asyncio.to_thread(fetch_binance_specific, "SELL", "Provincial", dynamic_amount)
    ]
    
    results = await asyncio.gather(*tasks)
    
    return {
        "pm_buy": results[0],  "pm_sell": results[1],
        "ban_buy": results[2], "ban_sell": results[3],
        "mer_buy": results[4], "mer_sell": results[5],
        "pro_buy": results[6], "pro_sell": results[7]
    }

# Wrapper legacy (mantenemos por seguridad)
async def get_binance_price(trade_type="BUY", bank="PagoMovil", reference_price=None):
    amount = int((reference_price or 65.0) * 20)
    price = await asyncio.to_thread(fetch_binance_specific, trade_type, bank, amount)
    return round(price, 2) if price > 0 else None
