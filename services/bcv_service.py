import logging
import asyncio
import random
import requests
from bs4 import BeautifulSoup
from functools import partial

# --- CONFIGURACIÓN ---
BCV_URL = "https://www.bcv.org.ve/"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.181 Mobile Safari/537.36"
]

# --- MEMORIA (Cache) ---
# Guardamos el último valor válido aquí para usarlo si la página del BCV se cae.
_LAST_KNOWN_RATES = {"usd": None, "eur": None}

def _scrape_sync():
    """
    Función SÍNCRONA (Bloqueante) interna.
    Realiza la petición HTTP y el parsing.
    """
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    # verify=False es necesario porque el certificado del BCV suele estar vencido
    response = requests.get(BCV_URL, headers=headers, timeout=10, verify=False)
    
    if response.status_code != 200:
        raise ValueError(f"Status Code BCV: {response.status_code}")

    soup = BeautifulSoup(response.content, "html.parser")
    
    # Selectores específicos del BCV
    dolar_div = soup.find("div", id="dolar")
    euro_div = soup.find("div", id="euro")
    
    new_rates = {}

    if dolar_div:
        text_usd = dolar_div.find("strong").text.strip().replace(",", ".")
        new_rates["usd"] = float(text_usd)
        
    if euro_div:
        text_eur = euro_div.find("strong").text.strip().replace(",", ".")
        new_rates["eur"] = float(text_eur)

    if not new_rates.get("usd"):
        raise ValueError("No se pudo parsear el precio del HTML")

    return new_rates

async def get_bcv_rates():
    """
    Función PRINCIPAL (Asíncrona).
    Llama al scraper en un hilo separado para no congelar el bot.
    Incluye lógica de reintentos y fallback.
    """
    loop = asyncio.get_running_loop()
    max_retries = 3
    
    for attempt in range(1, max_retries + 1):
        try:
            # 🚀 MAGIA: Ejecutamos la petición bloqueante en un hilo aparte (executor)
            # Esto evita que el bot se congele mientras espera al BCV.
            rates = await loop.run_in_executor(None, _scrape_sync)
            
            # Si tuvimos éxito, actualizamos la memoria y retornamos
            if rates:
                global _LAST_KNOWN_RATES
                _LAST_KNOWN_RATES = rates
                logging.info(f"✅ Tasa BCV Actualizada: {rates['usd']}")
                return rates

        except Exception as e:
            wait_time = attempt * 2  # Espera 2s, luego 4s...
            logging.warning(f"⚠️ Intento {attempt} fallido BCV: {e}. Reintentando en {wait_time}s...")
            await asyncio.sleep(wait_time)

    # Si fallan todos los intentos, devolvemos el último valor conocido
    if _LAST_KNOWN_RATES["usd"]:
        logging.error("❌ BCV Caído. Usando última tasa conocida (Fallback).")
        return _LAST_KNOWN_RATES
    
    # Si no hay ni nuevo ni viejo (ej. acabamos de reiniciar el bot y no hay internet)
    logging.critical("☠️ No se pudo obtener tasa BCV y no hay caché.")
    return None
