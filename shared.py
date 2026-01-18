import pytz

# Configuración
TIMEZONE = pytz.timezone('America/Caracas')

# Memoria Central (Accesible por todos los archivos)
MARKET_DATA = {
    "price": None,         # Precio Promedio General (PagoMóvil)
    "bcv": {},             # Tasas BCV (Dólar/Euro)
    "last_updated": "Esperando actualización...",
    "history": [],         # Usamos lista simple para compatibilidad
    
    # 👇 ESTA ES LA SECCIÓN NUEVA VITAL PARA /MERCADO 👇
    "banks": {
        "pm": {"buy": 0, "sell": 0},
        "banesco": {"buy": 0},
        "mercantil": {"buy": 0},
        "provincial": {"buy": 0}
    }
}
