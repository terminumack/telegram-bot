import logging
import asyncio
import random
import requests

# --- CONFIGURACIÓN ---
BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.181 Mobile Safari/537.36"
]

# Bancos por defecto (igual que en tu bot original)
DEFAULT_BANKS = ["PagoMovil", "Banesco", "Mercantil", "Provincial"]

# Cache en memoria por si falla la API
_LAST_BINANCE_PRICE = None

def _fetch_binance_sync(trade_type="BUY", bank_filter=None, last_known_price=60.0):
    """
    Lógica EXACTA de tu algoritmo original, ejecutada de forma síncrona.
    """
    ua = random.choice(USER_AGENTS)
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    
    # --- 1. Cálculo del Safe Amount (Tu lógica original) ---
    # Asumimos FILTER_MIN_USD como 20 (aprox) si no está definido, para mantener la lógica
    # safe_amount = max(2000, min(int(last_known * FILTER_MIN_USD), 20000))
    # Aquí replico tu lógica usando el precio de referencia que pasamos como argumento
    safe_amount = max(2000, min(int(last_known_price * 20), 20000))

    pay_types = [bank_filter] if bank_filter else DEFAULT_BANKS

    # Payload inicial (Con filtro Merchant)
    payload = {
        "page": 1, 
        "rows": 3, # Tu configuración original
        "payTypes": pay_types,
        "publisherType": "merchant", # FILTRO IMPORTANTE: Solo Verificados
        "transAmount": str(safe_amount),
        "asset": "USDT",
        "fiat": "VES",
        "tradeType": trade_type
    }

    try:
        # --- INTENTO 1: Buscar Comerciantes Verificados ---
        response = requests.post(BINANCE_P2P_URL, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        # --- INTENTO 2 (Fallback): Si no hay verificados, buscar en TODOS ---
        # Tal cual tu código: if not data.get("data")
        if not data.get("data"):
            logging.info(f"⚠️ Sin merchants verificados, buscando en general...")
            payload.pop("publisherType", None) # Quitamos el filtro
            response = requests.post(BINANCE_P2P_URL, json=payload, headers=headers, timeout=10)
            data = response.json()

        ads = data.get("data", [])
        
        if not ads:
            return None

        # --- CÁLCULO DE PRECIO (Tu algoritmo) ---
        prices = [float(item["adv"]["price"]) for item in ads if "adv" in item]
        
        if not prices:
            return None

        # Promedio simple
        avg_price = sum(prices) / len(prices)
        return avg_price

    except Exception as e:
        logging.error(f"❌ Error interno Binance: {e}")
        return None

async def get_binance_price(trade_type="BUY", bank_filter=None, reference_price=60.0):
    """
    Wrapper Asíncrono.
    Llama a tu lógica original sin bloquear el bot.
    """
    loop = asyncio.get_running_loop()
    
    try:
        # run_in_executor envía la función síncrona a un hilo aparte
        price = await loop.run_in_executor(
            None, 
            lambda: _fetch_binance_sync(trade_type, bank_filter, reference_price)
        )

        if price:
            global _LAST_BINANCE_PRICE
            _LAST_BINANCE_PRICE = price
            return price
            
    except Exception as e:
        logging.error(f"Error en wrapper async: {e}")

    # Si falla, devolvemos el último conocido (Cache)
    if _LAST_BINANCE_PRICE:
        return _LAST_BINANCE_PRICE
    
    return None
