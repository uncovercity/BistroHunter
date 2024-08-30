import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache
from math import radians, cos, sin, asin, sqrt

app = FastAPI()

logging.basicConfig(level=logging.INFO)

BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')


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

def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    km = 6367 * c
    return km

def obtener_coordenadas(zona: str, ciudad: str) -> Optional[dict]:
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": f"{zona}, {ciudad}",
            "key": GOOGLE_MAPS_API_KEY
        }
        response = requests.get(url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return location
        else:
            logging.error(f"Error en la geocodificación: {data['status']}")
            return None
    except Exception as e:
        logging.error(f"Error al obtener coordenadas de la zona: {e}")
        return None

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
def obtener_limites_geograficos(lat: float, lon: float, distancia_km: float = 2.0) -> dict:
    lat_delta = distancia_km / 111.0
    lon_delta = distancia_km / (111.0 * cos(radians(lat)))
    
    return {
        "lat_min": lat - lat_delta,
        "lat_max": lat + lat_delta,
        "lon_min": lon - lon_delta,
        "lon_max": lon + lon_delta
    }

@cache_airtable_request
def obtener_restaurantes_por_ciudad(
    city: str, 
    dia_semana: Optional[str] = None, 
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    zona: Optional[str] = None
) -> List[dict]:
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }
        
        formula_parts = [
            f"OR({{city}}='{city}', {{city_string}}='{city}')"
        ]
        
        if dia_semana:
            formula_parts.append(f"FIND('{dia_semana}', ARRAYJOIN({{day_opened}}, ', ')) > 0")

        if price_range:
            formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
        
        if cocina:
            exact_match = f"ARRAYJOIN({{grouped_categories}}, ', ') = '{cocina}'"
            flexible_match = f"FIND('{cocina}', ARRAYJOIN({{grouped_categories}}, ', ')) > 0"
            formula_parts.append(f"OR({exact_match}, {flexible_match})")

        if diet:
            formula_parts.append(
                f"OR(FIND('{diet}', ARRAYJOIN({{tripadvisor_dietary_restrictions}}, ', ')) > 0, FIND('{diet}', ARRAYJOIN({{dietas_string}}, ', ')) > 0)"
            )

        if dish:
            formula_parts.append(f"FIND('{dish}', ARRAYJOIN({{comida_[TESTING]}}, ', ')) > 0")
        
        restaurantes_encontrados = []
        distancia_km = 2.0
        
        while len(restaurantes_encontrados) < 3:
            
            formula_parts_zona = formula_parts[:]
            
            if zona:
                location = obtener_coordenadas(zona, city)
                if location:
                    limites = obtener_limites_geograficos(location['lat'], location['lng'], distancia_km)
                    formula_parts_zona.append(f"AND({{location/lat}} >= {limites['lat_min']}, {{location/lat}} <= {limites['lat_max']})")
                    formula_parts_zona.append(f"AND({{location/lng}} >= {limites['lon_min']}, {{location/lng}} <= {limites['lon_max']})")
            
            filter_formula = "AND(" + ", ".join(formula_parts_zona) + ")"
            logging.info(f"Fórmula de filtro construida: {filter_formula} para distancia {distancia_km} km")
            
            params = {
                "filterByFormula": filter_formula,
                "sort[0][field]": "score",
                "sort[0][direction]": "desc",
                "maxRecords": 100 
            }

            response_data = airtable_request(url, headers, params)
            if response_data and 'records' in response_data:
                restaurantes_filtrados = [
                    restaurante for restaurante in response_data['records']
                    if restaurante not in restaurantes_encontrados  # Evitar duplicados
                ]
                restaurantes_encontrados.extend(restaurantes_filtrados)

            distancia_km += 2.0

            if distancia_km > 20:
                break
    
        if zona and location:
            lat_centro = location['lat']
            lon_centro = location['lng']
            restaurantes_encontrados.sort(key=lambda r: haversine(lon_centro, lat_centro, float(r['fields'].get('location/lng', 0)), float(r['fields'].get('location/lat', 0))))
        
        return restaurantes_encontrados[:3] 

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
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description = "Plato por el que puede preguntar un cliente específicamente"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad")
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish, zona)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}
        
        return {
            "resultados": [
                {
                    "titulo": restaurante['fields'].get('title', 'Sin título'),
                    "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                    "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                    "url": restaurante['fields'].get('url', 'No especificado'),
                    "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A'),
                    "distancia": f"{haversine(lon_centro, lat_centro, float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0))):.2f} km" if zona else "No calculado"
                }
                for restaurante in restaurantes
            ]
        }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
