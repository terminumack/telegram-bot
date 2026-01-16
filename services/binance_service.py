import requests
import logging
import asyncio
import random

# Lista de User-Agents para evitar bloqueos
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
]

async def get_binance_price():
    """
    Obtiene el precio USDT replicando EXACTAMENTE tu lógica original.
    1. Intenta Merchants (Verificados). Si falla, busca a todos.
    2. Filtra por bancos específicos y monto.
    3. Promedia el Top 3.
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    
    # Configuración original tuya
    # Como no tenemos acceso a MARKET_DATA aquí, usamos un default de 60 para el cálculo
    last_known = 65.0 
    # Tu lógica de monto seguro: max(2000, min(...))
    safe_amount = max(2000, min(int(last_known * 20), 20000))
    
    pay_types = ["PagoMovil", "Banesco", "Mercantil", "Provincial"]
    
    payload = {
        "page": 1, 
        "rows": 3,  # Tu código original pedía 3
        "payTypes": pay_types, 
        "publisherType": "merchant", # Primero intentamos solo verificados
        "transAmount": str(safe_amount), 
        "asset": "USDT", 
        "fiat": "VES", 
        "tradeType": "BUY"
    }

    try:
        # Ejecutamos la petición en un hilo aparte
        response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
        data = response.json()

        # Lógica de Fallback (Tu código original)
        # Si no hay comerciantes verificados, borramos el filtro y buscamos a todos
        if not data.get("data"):
            del payload["publisherType"]
            response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
            data = response.json()

        # Extraer precios
        prices = [float(item["adv"]["price"]) for item in data.get("data", [])]

        if not prices:
            return None

        # Tu cálculo original: Promedio simple de lo que encontró
        avg_price = sum(prices) / len(prices)
        
        return round(avg_price, 2)

    except Exception as e:
        logging.error(f"❌ Error obteniendo precio Binance (Lógica Original): {e}")
        return None
