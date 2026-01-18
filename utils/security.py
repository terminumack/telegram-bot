from functools import wraps
import time
from telegram import Update

# Diccionario en memoria para guardar la última vez que el usuario habló
# Estructura: { user_id: timestamp_unix }
user_cooldowns = {}

def rate_limited(rate_limit_seconds=2.0):
    """
    Decorador de Seguridad.
    Si un usuario envía comandos más rápido que el límite, el bot lo ignora.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, *args, **kwargs):
            # Si no es un mensaje de usuario (ej: callback), dejamos pasar
            if not update.effective_user:
                return await func(update, *args, **kwargs)

            user_id = update.effective_user.id
            current_time = time.time()
            
            # Verificamos cuándo fue la última vez
            last_time = user_cooldowns.get(user_id, 0)
            
            # SI VA MUY RÁPIDO -> IGNORAR (RETURN)
            if current_time - last_time < rate_limit_seconds:
                return # No ejecutamos nada, el bot "se hace el sordo"

            # SI ESTÁ BIEN -> ACTUALIZAR Y EJECUTAR
            user_cooldowns[user_id] = current_time
            
            # Limpieza de memoria (Garbage Collection manual)
            # Si el diccionario crece mucho (ej: 10,000 usuarios en 1 hora), lo limpiamos
            if len(user_cooldowns) > 10000:
                user_cooldowns.clear() 
                
            return await func(update, *args, **kwargs)
        return wrapper
    return decorator
