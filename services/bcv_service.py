import requests
from bs4 import BeautifulSoup
import urllib3
import logging
import asyncio

# Desactivar advertencias de seguridad (El BCV tiene certificados malos)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

async def get_bcv_rates():
    """
    Obtiene las tasas del BCV (Dólar y Euro) haciendo Web Scraping.
    Si falla, retorna None rápidamente para no colgar al bot.
    """
    url = "https://www.bcv.org.ve"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
    }

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
        
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        rates = {}

        # Buscamos el Dólar (ID: dolar)
        usd_tag = soup.find("div", {"id": "dolar"})
        if usd_tag:
            rates["dolar"] = _parse_value(usd_tag)

        # Buscamos el Euro (ID: euro)
        euro_tag = soup.find("div", {"id": "euro"})
        if euro_tag:
            rates["euro"] = _parse_value(euro_tag)

        # Si no encontramos nada, devolvemos None
        if not rates:
            logging.warning("⚠️ BCV respondió pero no se encontraron las tasas en el HTML.")
            return None

        return rates

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
