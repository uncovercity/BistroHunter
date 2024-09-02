import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
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
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

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
        "lon_max": lon - lon_delta
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

        # Construir los filtros constantes
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
        location = None

        if zona:
            location = obtener_coordenadas(zona, city)
            if not location:
                raise HTTPException(status_code=404, detail="Zona no encontrada.")
            lat_centro = location['lat']
            lon_centro = location['lng']

    
        while len(restaurantes_encontrados) < 3:

            formula_parts_zona = formula_parts

            if zona and location:
                limites = obtener_limites_geograficos(lat_centro, lon_centro, distancia_km)
                formula_parts_zona.append(f"AND({{location/lat}} >= {limites['lat_min']}, {{location/lat}} <= {limites['lat_max']})")
                formula_parts_zona.append(f"AND({{location/lng}} >= {limites['lon_min']}, {{location/lng}} <= {limites['lon_max']})")

            filter_formula = "AND(" + ", ".join(formula_parts_zona) + ")"
            logging.info(f"Fórmula de filtro construida: {filter_formula} para distancia {distancia_km} km")

            params = {
                "filterByFormula": filter_formula,
                "sort[0][field]": "score",
                "sort[0][direction]": "desc",
                "maxRecords": 3
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
            restaurantes_encontrados.sort(key=lambda r: haversine(lon_centro, lat_centro, float(r['fields'].get('location/lng', 0)), float(r['fields'].get('location/lat', 0))))

        return restaurantes_encontrados[:3]

    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes de la ciudad")
    
def enviar_respuesta_a_n8n(resultados):
    try:
        response = requests.post(N8N_WEBHOOK_URL, json={"resultados": resultados})
        response.raise_for_status()
        logging.info("Resultados enviados a n8n con éxito.")
    except requests.exceptions.HTTPError as err:
        logging.error(f"Error al enviar resultados a n8n: {err}")
        raise

@app.post("/api/extraer-variables-gpt")
def extraer_variables_desde_gpt(client_conversation: str) -> dict:
    """
    Envía la conversación del cliente a tu GPT personalizado para extraer variables.
    """
    try:
        response = requests.post(
            "https://bistrohunter.onrender.com/api/extraer-variables",  # URL de tu GPT personalizado
            json={"client_conversation": client_conversation}
        )
        response.raise_for_status()
        
        extracted_data = response.json()
        logging.info(f"Datos extraídos por GPT: {extracted_data}")
        
        return extracted_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al conectar con el servidor GPT: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la consulta con GPT")




@app.post("/api/procesar-variables")
async def procesar_variables(request: Request):
    try:
        # Recibir los datos enviados desde n8n
        data = await request.json()
        logging.info(f"Datos recibidos: {data}")
        
        # Extraer la conversación del cliente
        client_conversation = data.get('client_conversation')
        logging.info(f"Client conversation: {client_conversation}")
        
        if not client_conversation:
            raise HTTPException(status_code=400, detail="La consulta en texto es obligatoria.")
        
        # Usar GPT para extraer las variables desde la conversación del cliente
        extracted_data = extraer_variables_con_gpt(client_conversation)
        logging.info(f"Datos extraídos: {extracted_data}")
        
        # Ahora utiliza los datos extraídos para obtener restaurantes o cualquier otro proceso
        city = extracted_data.get('city')
        date = extracted_data.get('date')
        price_range = extracted_data.get('price_range')
        cocina = extracted_data.get('cocina')
        diet = extracted_data.get('diet')
        dish = extracted_data.get('dish')
        zona = extracted_data.get('zona')

        logging.info(f"City: {city}, Date: {date}, Price Range: {price_range}, Cocina: {cocina}, Diet: {diet}, Dish: {dish}, Zona: {zona}")

        # Validación básica: al menos una ciudad debe estar presente
        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        # Procesar la fecha si se proporciona
        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        logging.info(f"Día de la semana: {dia_semana}")

        # Llamar a la función obtener_restaurantes_por_ciudad con los parámetros recibidos
        restaurantes = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona
        )

        logging.info(f"Restaurantes encontrados: {restaurantes}")
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}
        
        resultados = [
            {
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A'),
                "distancia": (
                    f"{haversine(float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0)), lat_centro, lon_centro):.2f} km"
                    if zona and 'location/lng' in restaurante['fields'] and 'location/lat' in restaurante['fields'] else "No calculado"
                ),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        enviar_respuesta_a_n8n(resultados)

        return {"mensaje": "Datos procesados y respuesta generada correctamente", "resultados": resultados}
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": f"Ocurrió un error al procesar las variables: {str(e)}"}

