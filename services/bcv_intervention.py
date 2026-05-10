import requests
from bs4 import BeautifulSoup
import urllib3
import logging
import asyncio

# Desactivar advertencias de seguridad
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

async def get_bcv_intervention():
    """
    Lee la página de Política Cambiaria del BCV y extrae la Tasa de Intervención.
    Retorna un diccionario con 'fecha' y 'tasa_eur' (Bs/EUR), o None si falla.
    """
    url = "https://www.bcv.org.ve/politica-cambiaria/intervencion-cambiaria"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    try:
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=15, verify=False)
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
        logging.warning(f"⚠️ Error leyendo intervención BCV: {e}")
        return None
