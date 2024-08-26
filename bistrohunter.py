import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache

app = FastAPI()

logging.basicConfig(level=logging.INFO)

BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')


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
        dia_semana_en = fecha.strftime('%A')  
        dia_semana_es = DAYS_ES.get(dia_semana_en, dia_semana_en)  
        return dia_semana_es.lower()
    except Exception as e:
        logging.error(f"Error al obtener el día de la semana: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la fecha")


restaurantes_cache = TTLCache(maxsize=10000, ttl=60*30)

def cache_airtable_request(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        cache_key = f"{func.__name__}:{args}:{kwargs}"
        if cache_key in restaurantes_cache:
            return restaurantes_cache[cache_key]
        result = func(*args, **kwargs)
        restaurantes_cache[cache_key] = result
        return result
    return wrapper

@cache_airtable_request
def airtable_request(url, headers, params):
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

@cache_airtable_request
def obtener_restaurantes_por_ciudad(
    city: str, 
    dia_semana: Optional[str], 
    price_range: Optional[str] = None,
    cocina: Optional[str] = None
) -> List[dict]:
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }
        
 
        formula_parts = [
    f"AND(OR({{city}}='{city}', {{city_string}}='{city}'), {{es_cadena?}}=FALSE())"
]
        
        if dia_semana:
            formula_parts.append(f"FIND('{dia_semana}', ARRAYJOIN({{day_opened}}, ', ')) > 0")

        if price_range:
            formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
        
        if cocina:
             
            exact_match = f"ARRAYJOIN({{grouped_categories}}, ', ') = '{cocina}'"
            
            flexible_match = f"FIND('{cocina}', ARRAYJOIN({{grouped_categories}}, ', ')) > 0"
            
            formula_parts.append(f"OR({exact_match}, {flexible_match})")
        
      
        filter_formula = "AND(" + ", ".join(formula_parts) + ")"
        
     
        logging.info(f"Fórmula de filtro construida: {filter_formula}")
        
        params = {
            "filterByFormula": filter_formula,
            "sort[0][field]": "score",
            "sort[0][direction]": "desc",
            "maxRecords": 3
        }

        response_data = airtable_request(url, headers, params)
        if response_data:
            return response_data.get('records', [])
        else:
            logging.error("Error al obtener restaurantes de la ciudad")
            return []
    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes de la ciudad")

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
        
        if date:

            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

       
        restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}
        
        return {
            "resultados": [
                {
                    "titulo": restaurante['fields'].get('title', 'Sin título'),
                    "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                    "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                    "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A')
                }
                for restaurante in restaurantes
            ]
        }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
