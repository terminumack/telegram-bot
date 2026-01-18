import pytz

# Configuración
TIMEZONE = pytz.timezone('America/Caracas')

# Memoria Central (Accesible por todos los archivos)
# shared.py (Solo actualiza la parte de MARKET_DATA)

MARKET_DATA = {
    "price": None,
    "bcv": {},
    "last_updated": "Iniciando...",
    "history": [],
    "banks": {
        "pm":        {"buy": 0, "sell": 0},
        "banesco":   {"buy": 0, "sell": 0}, # <--- Agregamos sell
        "mercantil": {"buy": 0, "sell": 0}, # <--- Agregamos sell
        "provincial":{"buy": 0, "sell": 0}  # <--- Agregamos sell
    }
}
# shared.py (Solo actualiza la parte de MARKET_DATA)

