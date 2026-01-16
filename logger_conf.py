# logger_conf.py
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s → %(message)s",
    handlers=[
        logging.FileHandler("app.log"),  # guarda logs en un archivo
        logging.StreamHandler()          # también los muestra en consola (Railway)
    ]
)
