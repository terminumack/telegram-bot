# shared.py
from collections import deque
import pytz

# Configuración
MAX_HISTORY_POINTS = 20
TIMEZONE = pytz.timezone('America/Caracas')

# Memoria Central (Accesible por todos los archivos)
MARKET_DATA = {
    "price": None,
    "bcv": {},
    "last_updated": "Esperando actualización...",
    "history": deque(maxlen=MAX_HISTORY_POINTS)
}
