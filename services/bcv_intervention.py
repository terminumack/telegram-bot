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
    Usa un sistema de reintentos para combatir la lentitud del servidor.
    """
    url = "https://www.bcv.org.ve/politica-cambiaria/intervencion-cambiaria"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    # 🔥 NUEVO: Bucle de 3 intentos
    for intento in range(3):
        try:
            # Subimos la paciencia a 25 segundos
            response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=25, verify=False)
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
                
                # ¡ÉXITO!
                return {
                    "fecha": fecha_limpia,
                    "tasa_eur": tasa_eur_float
                }
                
            return None

        except requests.exceptions.Timeout:
            logging.warning(f"⚠️ BCV lento (Intento {intento + 1}/3). Reintentando...")
            await asyncio.sleep(2) # Pausa de 2 segundos antes del próximo intento
        except Exception as e:
            logging.warning(f"⚠️ Error leyendo intervención BCV: {e}")
            return None # Si es un error distinto a lentitud, abortamos de una vez
            
    logging.error("❌ BCV no respondió la intervención después de 3 intentos.")
    return None
