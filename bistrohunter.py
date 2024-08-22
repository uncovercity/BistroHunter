import os
from typing import Optional, List, Union
from fastapi import FastAPI, Query, HTTPException
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache

app = FastAPI()

# Configuración básica de logging
logging.basicConfig(level=logging.INFO)

# Acceso a las variables de entorno
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')

# Mapeo manual de días de la semana en español
DAYS_ES = {
    "Monday": "lunes",
    "Tuesday": "martes",
    "Wednesday": "miércoles",
    "Thursday": "jueves",
    "Friday": "viernes",
    "Saturday": "sábado",
    "Sunday": "domingo"
}

def obtener_dia_semana(fecha: datetime) -> str:
    try:
        dia_semana_en = fecha.strftime('%A')  # Obtenemos el día en inglés
        dia_semana_es = DAYS_ES.get(dia_semana_en, dia_semana_en)  # Lo convertimos a español
        return dia_semana_es.lower()
    except Exception as e:
        logging.error(f"Error al obtener el día de la semana: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la fecha")

# Create a TTL cache with a maximum of 1000 items that expire after 30 minutes
airtable_cache = TTLCache(maxsize=1000, ttl=60*30)

def cache_airtable_request(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        cache_key = f"{func.__name__}:{args}:{kwargs}"
        if cache_key in airtable_cache:
            return airtable_cache[cache_key]
        result = func(*args, **kwargs)
        airtable_cache[cache_key] = result
        return result
    return wrapper

@cache_airtable_request
def airtable_request(url, headers, params):
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

@cache_airtable_request
def obtener_horarios(cid: str, dia_semana: str) -> Optional[bool]:
    try:
        table_name = 'Horarios'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }
        params = {
            "filterByFormula": f"AND({{cid}}='{cid}', {{isOpen?}}='{dia_semana}')"
        }

        response_data = airtable_request(url, headers, params)
        
        if response_data:
            records = response_data.get('records', [])
            return bool(records)
        else:
            logging.error("Error al obtener horarios")
            return None
    except Exception as e:
        logging.error(f"Error al obtener horarios: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener horarios")

@cache_airtable_request
def buscar_restaurantes_por_ciudad(city: str) -> Union[str, List[dict]]:
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        params = {
            "filterByFormula": f"OR({{city}}='{city}', {{city_string}}='{city}')"
        }

        response_data = airtable_request(url, headers, params)
        if response_data:
            records = response_data.get('records', [])
            return [record['fields'] for record in records]
        else:
            return "Error: No se pudo conectar a Airtable."
    except Exception as e:
        logging.error(f"Error al buscar restaurantes por ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes por ciudad")

def aplicar_filtros_y_ordenar(restaurantes: List[dict], fecha: datetime, price_range: Optional[str], cocina: Optional[str]) -> List[dict]:
    dia_semana = obtener_dia_semana(fecha)
    restaurantes_abiertos = []

    for record in restaurantes:
        cid = record.get('cid')
        if cid and obtener_horarios(cid, dia_semana):
            restaurantes_abiertos.append(record)
    
    if restaurantes_abiertos:
        # Filtrar y ordenar por 'nota_bh' si existe y es mayor que 0.0
        restaurantes_con_nota_bh = [r for r in restaurantes_abiertos if r.get('nota_bh', 0) > 0]
        
        if restaurantes_con_nota_bh:
            # Ordenar por 'nota_bh' descendente
            restaurantes_con_nota_bh.sort(key=lambda x: x['nota_bh'], reverse=True)
            return restaurantes_con_nota_bh[:3]
        else:
            # Si no hay 'nota_bh', ordenar por 'score' descendente
            restaurantes_abiertos.sort(key=lambda x: x.get('score', 0), reverse=True)
            return restaurantes_abiertos[:3]
    else:
        return []

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente")
):
    try:
        # Primero buscar por ciudad y usar la caché
        restaurantes_por_ciudad = airtable_cache.get(f"buscar_restaurantes_por_ciudad:{city}")
        if restaurantes_por_ciudad is None:
            restaurantes_por_ciudad = buscar_restaurantes_por_ciudad(city)
            airtable_cache[f"buscar_restaurantes_por_ciudad:{city}"] = restaurantes_por_ciudad
        
        if isinstance(restaurantes_por_ciudad, list):
            if date:
                fecha = datetime.strptime(date, "%Y-%m-%d")
            else:
                fecha = datetime.now()

            resultados = aplicar_filtros_y_ordenar(restaurantes_por_ciudad, fecha, price_range, cocina)
            
            return {
                "resultados": [
                    {
                        "titulo": f"{restaurante['title']}. {restaurante['description']}",
                        "nota_bh" if 'nota_bh' in restaurante else "estrellas": restaurante.get('nota_bh', restaurante.get('score', 'N/A')),
                        "rango_de_precios": restaurante['price_range'],
                        "url_maps": restaurante['url']
                    }
                    for restaurante in resultados
                ]
            }
        else:
            return {"mensaje": restaurantes_por_ciudad}
    except Exception as e:
        logging.error(f"Error al obtener los restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener los restaurantes")
