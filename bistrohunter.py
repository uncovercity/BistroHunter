import os
from typing import Optional, List
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

# Crear un caché TTL con un máximo de 1000 elementos que expiran después de 30 minutos
restaurantes_cache = TTLCache(maxsize=1000, ttl=60*30)

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
    price_range: Optional[str] = None
) -> List[dict]:
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }
        
        # Construir la fórmula para Airtable
        formula_parts = [f"OR({{city}}='{city}', {{city_string}}='{city}')"]
        
        if price_range:
            # Usar ARRAYJOIN para unir los valores del campo price_range y filtrar
            formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
        
        filter_formula = "AND(" + ", ".join(formula_parts) + ")"
        
        params = {
            "filterByFormula": filter_formula
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

def filtrar_y_ordenar_restaurantes(
    restaurantes: List[dict], 
    dia_semana: str, 
    price_range: Optional[str] = None, 
    cocina: Optional[str] = None
) -> List[dict]:
    # Filtrar por día de la semana
    restaurantes_abiertos = [
        r for r in restaurantes
        if dia_semana in r.get('fields', {}).get('day_opened', [])
    ]

    # Ordenar por nota_bh o score
    restaurantes_ordenados = sorted(
        restaurantes_abiertos,
        key=lambda r: r.get('fields', {}).get('nota_bh', 0) or r.get('fields', {}).get('score', 0),
        reverse=True
    )

    # Seleccionar los 3 con la puntuación más alta
    top_restaurantes = restaurantes_ordenados[:3]

    # Aplicar filtros adicionales si se proporcionan
    if price_range:
        top_restaurantes = [
            r for r in top_restaurantes
            if price_range in r.get('fields', {}).get('price_range', [])
        ]
    if cocina:
        top_restaurantes = [
            r for r in top_restaurantes
            if cocina in r.get('fields', {}).get('grouped_categories', '')
        ]

    return top_restaurantes

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
        fecha = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
        dia_semana = obtener_dia_semana(fecha)

        # Obtener los restaurantes de la ciudad
        restaurantes = obtener_restaurantes_por_ciudad(city, price_range)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes en la ciudad especificada."}
        
        # Filtrar y ordenar los restaurantes
        top_restaurantes = filtrar_y_ordenar_restaurantes(restaurantes, dia_semana, price_range, cocina)
        
        if not top_restaurantes:
            return {"mensaje": "No se encontraron restaurantes abiertos con los filtros aplicados."}
        
        return {
            "resultados": [
                {
                    "titulo": restaurante['fields'].get('title', 'Sin título'),
                    "descripcion": restaurante['fields'].get('description', 'Sin descripción'),
                    "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                    "puntuacion_bistrohunter": restaurante['fields'].get('nota_bh', restaurante['fields'].get('score', 'N/A'))
                }
                for restaurante in top_restaurantes
            ]
        }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
