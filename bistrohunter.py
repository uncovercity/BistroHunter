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

# Create a TTL cache with a maximum of 100 items that expire after 5 minutes
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
def buscar_restaurantes(city: str, date: Optional[str] = None, price_range: Optional[str] = None, cocina: Optional[str] = None) -> Union[str, List[dict]]:
    try:
        limit = 3  # Variable limit para limitar el número de restaurantes

        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
        else:
            fecha = datetime.now()
        dia_semana = obtener_dia_semana(fecha)
    
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        formula_parts = [f"OR({{city}}='{city}', {{city_string}}='{city}')"]

        # Agregar la búsqueda por cocina si se proporciona
        if cocina:
            formula_parts.append(f"FIND('{cocina}', {{grouped_categories}}) > 0")
    
        # Agregar el rango de precios si se proporciona
        if price_range:
            formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")

        filter_formula = "AND(" + ", ".join(formula_parts) + ")"

        params = {
            "filterByFormula": filter_formula
        }

        response_data = airtable_request(url, headers, params)
        if response_data:
            records = response_data.get('records', [])
            if not records:
                return "No se encontraron restaurantes en la ciudad especificada."
            
            restaurantes_abiertos = []

            for record in records[:limit]:
                cid = record['fields'].get('cid')
                if cid and obtener_horarios(cid, dia_semana):
                    restaurantes_abiertos.append(record['fields'])
            
            if restaurantes_abiertos:
                return restaurantes_abiertos  
            else:
                return "No se encontraron restaurantes abiertos hoy."
        else:
            return "Error: No se pudo conectar a Airtable."
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
    logging.info(f"Consulta enviada a Airtable: {url} con filtro: {filter_formula}")


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
    resultados = buscar_restaurantes(city, date, price_range, cocina)
    
    if isinstance(resultados, list):
        return {
            "resultados": [
                {
                    "titulo": restaurante['title'],
                    "estrellas": restaurante.get('score', 'N/A'),
                    "rango_de_precios": restaurante['price_range'],
                    "url_maps": restaurante['url']
                }
                for restaurante in resultados
            ]
        }
    else:
        return {"mensaje": resultados}
