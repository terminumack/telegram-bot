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
import urllib3
import logging
import asyncio

# --- MEMORIA (Cache) ---
# Guardamos el último valor válido aquí para usarlo si la página del BCV se cae.
_LAST_KNOWN_RATES = {"usd": None, "eur": None}
# Desactivar advertencias de seguridad (El BCV tiene certificados malos)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _scrape_sync():
async def get_bcv_rates():
    """
    Función SÍNCRONA (Bloqueante) interna.
    Realiza la petición HTTP y el parsing.
    Obtiene las tasas del BCV (Dólar y Euro) haciendo Web Scraping.
    Si falla, retorna None rápidamente para no colgar al bot.
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
    url = "https://www.bcv.org.ve"

    new_rates = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
    }

    if dolar_div:
        text_usd = dolar_div.find("strong").text.strip().replace(",", ".")
        new_rates["usd"] = float(text_usd)
    try:
        # Ejecutamos la petición en un hilo aparte para no bloquear al bot
        # Timeout reducido a 5 segundos (Si en 5s no responde, abortamos)
        response = await asyncio.to_thread(
            requests.get, 
            url, 
            headers=headers, 
            timeout=5, 
            verify=False 
        )

    if euro_div:
        text_eur = euro_div.find("strong").text.strip().replace(",", ".")
        new_rates["eur"] = float(text_eur)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        rates = {}

    if not new_rates.get("usd"):
        raise ValueError("No se pudo parsear el precio del HTML")
        # Buscamos el Dólar (ID: dolar)
        usd_tag = soup.find("div", {"id": "dolar"})
        if usd_tag:
            rates["dolar"] = _parse_value(usd_tag)

    return new_rates
        # Buscamos el Euro (ID: euro)
        euro_tag = soup.find("div", {"id": "euro"})
        if euro_tag:
            rates["euro"] = _parse_value(euro_tag)

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
        # Si no encontramos nada, devolvemos None
        if not rates:
            logging.warning("⚠️ BCV respondió pero no se encontraron las tasas en el HTML.")
            return None

        except Exception as e:
            wait_time = attempt * 2  # Espera 2s, luego 4s...
            logging.warning(f"⚠️ Intento {attempt} fallido BCV: {e}. Reintentando en {wait_time}s...")
            await asyncio.sleep(wait_time)
        return rates

    # Si fallan todos los intentos, devolvemos el último valor conocido
    if _LAST_KNOWN_RATES["usd"]:
        logging.error("❌ BCV Caído. Usando última tasa conocida (Fallback).")
        return _LAST_KNOWN_RATES
    
    # Si no hay ni nuevo ni viejo (ej. acabamos de reiniciar el bot y no hay internet)
    logging.critical("☠️ No se pudo obtener tasa BCV y no hay caché.")
    return None
    except requests.exceptions.Timeout:
        logging.warning("⚠️ Timeout conectando con BCV (La página está lenta).")
        return None
    except Exception as e:
        logging.error(f"❌ Error obteniendo BCV: {e}")
        return None

def _parse_value(tag):
    """Función auxiliar para limpiar el texto del HTML."""
    try:
        # Buscamos la etiqueta <strong> dentro del div
        value_tag = tag.find("strong")
        if not value_tag:
            return 0.0
            
        text = value_tag.text.strip()
        # Reemplazamos coma por punto (Formato Venezuela 45,50 -> 45.50)
        clean_text = text.replace(',', '.')
        return float(clean_text)
    except Exception:
        return 0.0

async def get_bcv_intervention():
    """
    Lee la página de Política Cambiaria del BCV y extrae la Tasa de Intervención.
    Retorna un diccionario con 'fecha' y 'tasa_eur' (Bs/EUR), o None si falla.
    """
    url = "https://www.bcv.org.ve/politica-cambiaria/intervencion-cambiaria"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    try:
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=5, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table")
        if not table: return None
            
        tbody = table.find("tbody")
        if not tbody: return None
            
        first_row = tbody.find("tr")
        if not first_row: return None
            
        cols = first_row.find_all("td")
        
        if len(cols) >= 3:
            fecha_raw = cols[0].text.strip()
            fecha_limpia = " ".join(fecha_raw.split())
            
            tasa_raw = cols[-1].text.strip()
            
            try:
                tasa_eur_float = float(tasa_raw.replace('.', '').replace(',', '.'))
            except ValueError:
                return None 
            
            return {
                "fecha": fecha_limpia,
                "tasa_eur": tasa_eur_float
            }
            
        return None

    except Exception as e:
        logging.warning(f"⚠️ Error leve leyendo intervención BCV: {e}")
        return None
