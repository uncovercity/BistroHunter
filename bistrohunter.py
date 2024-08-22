import os
from typing import Optional, List, Union
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
def buscar_restaurantes(city: str, date: Optional[str] = None, price_range: Optional[str] = None, cocina: Optional[str] = None) -> Union[str, List[dict]]:
    try:
        limit = 3

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
            
            selected_restaurants = records[:limit]
            
            all_have_nota_bh = all('nota_bh' in record['fields'] and record['fields']['nota_bh'] is not None for record in selected_restaurants)

            if all_have_nota_bh:
                sorted_restaurants = sorted(selected_restaurants, key=lambda r: r['fields']['nota_bh'], reverse=True)
            else:
                sorted_restaurants = sorted(selected_restaurants, key=lambda r: r['fields'].get('score', 0), reverse=True)
            
            return [restaurant['fields'] for restaurant in sorted_restaurants]
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
