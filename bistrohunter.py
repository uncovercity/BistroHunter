# IMPORTS
import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache
from math import radians, cos, sin, asin, sqrt

# Desplegar fast api (no tocar)
app = FastAPI()

# Configuración del logging (nos va a decir dónde están los fallos)
logging.basicConfig(level=logging.INFO)

# Secretos. Esto son urls, claves, tokens y demás que no deben mostrarse públicamente ni subirse a ningún sitio
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

# Calcula la distancia haversiana entre dos puntos (filtro de zona)
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km


def calcular_bounding_box(lat, lon, radio_km=1):
    # Aproximación: 1 grado de latitud ~ 111.32 km
    km_por_grado_lat = 111.32
    delta_lat = radio_km / km_por_grado_lat

    # Para la longitud, depende de la latitud
    cos_lat = cos(radians(lat))
    km_por_grado_lon = 111.32 * cos_lat
    delta_lon = radio_km / km_por_grado_lon

    lat_min = lat - delta_lat
    lat_max = lat + delta_lat
    lon_min = lon - delta_lon
    lon_max = lon + delta_lon

    return {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max
    }

# Función que obtiene las coordenadas de la zona que ha especificado el cliente
def obtener_coordenadas_zona(zona: str, ciudad: str, radio_km: float) -> Optional[dict]:
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": f"zona {zona}, {ciudad}",
            "key": GOOGLE_MAPS_API_KEY,
            "components": "country:ES"
        }
        response = requests.get(url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            geometry = data['results'][0]['geometry']
            location = geometry['location']
            lat_central = location['lat']
            lon_central = location['lng']
            bounding_box = calcular_bounding_box(lat_central, lon_central, radio_km)
            return {
                "location": location,
                "bounding_box": bounding_box
            }
        else:
            logging.error(f"Error en la geocodificación: {data['status']}")
            return None
    except Exception as e:
        logging.error(f"Error al obtener coordenadas de la zona: {e}")
        return None


def obtener_coordenadas(ciudad: str, radio_km: float = 1):
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": f"{ciudad}",
            "key": GOOGLE_MAPS_API_KEY,
            "components": "country:ES"
        }
        response = requests.get(url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            geometry = data['results'][0]['geometry']
            location = geometry['location']
            lat_central = location['lat']
            lon_central = location['lng']
            bounding_box = calcular_bounding_box(lat_central, lon_central, radio_km)
            return {
                "location": location,
                "bounding_box": bounding_box
            }
        else:
            logging.error(f"Error en la geocodificación: {data['status']}")
            return None
    except Exception as e:
        logging.error(f"Error al obtener coordenadas de la zona: {e}")
        return None

# Caché (no tocar)
restaurantes_cache = TTLCache(maxsize=10000, ttl=60 * 30)


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
def airtable_request(url, headers, params, view_id: Optional[str] = None):
    if view_id:
        params["view"] = view_id
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None


@cache_airtable_request
def obtener_restaurantes_por_ciudad(
    city: str,
    dia_semana: Optional[str] = None,
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    zona: Optional[str] = None,
    coordenadas: Optional[list] = None,
    radio_km: float = 1.0,
    sort_by_proximity: bool = True
) -> (list[dict], Optional[str]):
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        # Inicializamos la fórmula de búsqueda
        formula_parts = []

        if price_range:
            ranges = price_range.split(',')
            if len(ranges) == 1:
                formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
            else:
                conditions = [f"FIND('{r.strip()}', ARRAYJOIN({{price_range}}, ', ')) > 0" for r in ranges]
                formula_parts.append(f"OR({', '.join(conditions)})")

        if cocina:
            cocinas = cocina.split(',')
            if len(cocinas) == 1:
                formula_parts.append(f"SEARCH('{cocina.strip()}', {{categories_string}}) > 0")
            else:
                conditions = [f"SEARCH('{c.strip()}', {{categories_string}}) > 0" for c in cocinas]
                formula_parts.append(f"OR({', '.join(conditions)})")

        if diet:
            formula_parts.append(f"SEARCH('{diet}', {{categories_string}}) > 0")

        if dish:
            dishes = dish.split(',')
            if len(dishes) == 1:
                formula_parts.append(f"SEARCH('{dish}', {{google_reviews}}) > 0")
            else:
                conditions = [f"SEARCH('{d.strip()}', {{google_reviews}}) > 0" for d in dishes]
                formula_parts.append(f"OR({', '.join(conditions)})")

        restaurantes_encontrados = []
        filter_formula = None

        if zona:
            zonas_list = [z.strip() for z in zona.split(',')] if ',' in zona else [zona]

            for zona_item in zonas_list:
                location_zona = obtener_coordenadas_zona(zona_item, city, radio_km)
                if not location_zona:
                    logging.error(f"Zona '{zona_item}' no encontrada.")
                    continue

                location = location_zona['location']
                bounding_box = location_zona['bounding_box']
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                formula_parts_zona = formula_parts.copy()
                formula_parts_zona.append(f"{{location/lat}} >= {lat_min}")
                formula_parts_zona.append(f"{{location/lat}} <= {lat_max}")
                formula_parts_zona.append(f"{{location/lng}} >= {lon_min}")
                formula_parts_zona.append(f"{{location/lng}} <= {lon_max}")

                filter_formula_zona = "AND(" + ", ".join(formula_parts_zona) + ")"
                logging.info(f"Fórmula de filtro construida para zona '{zona_item}': {filter_formula_zona}")

                params = {
                    "filterByFormula": filter_formula_zona,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    restaurantes_filtrados = [
                        restaurante for restaurante in response_data['records']
                        if restaurante not in restaurantes_encontrados
                    ]
                    restaurantes_encontrados.extend(restaurantes_filtrados)

            max_total_restaurantes = len(zonas_list) * 10
            restaurantes_encontrados = restaurantes_encontrados[:max_total_restaurantes]

        else:
            if coordenadas:
                logging.info(f"Coordenadas recibidas en get_restaurantes: {coordenadas}")
                coordenadas = [float(coord) for coord in coordenadas.split(",")]
                logging.info(f"Coordenadas procesadas: {coordenadas}")
                location_data = coordenadas
                if not location_data:
                    raise HTTPException(status_code=404, detail="No se pudo calcular la bounding box.")
                
                lat_centro = location_data[0]
                lon_centro = location_data[1]
                bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km=2)
            
                # Crear la fórmula para filtrar en Airtable usando la bounding box
                formula_parts_city = formula_parts.copy()
                formula_parts.append(f"{{location/lat}} >= {bounding_box['lat_min']}")
                formula_parts.append(f"{{location/lat}} <= {bounding_box['lat_max']}")
                formula_parts.append(f"{{location/lng}} >= {bounding_box['lon_min']}")
                formula_parts.append(f"{{location/lng}} <= {bounding_box['lon_max']}")
            
                filter_formula = "AND(" + ", ".join(formula_parts_city) + ")"
                logging.info(f"Fórmula de filtro construida: location = ({coordenadas}), bounding_box = {filter_formula}")
            else:
                logging.info("Usando coordenadas basadas en la ciudad")
                location_city = obtener_coordenadas(city, radio_km)
                if not location_city:
                    raise HTTPException(status_code=404, detail="No se pudieron obtener coordenadas para la ciudad.")

                lat_centro = location_city['location']['lat']
                lon_centro = location_city['location']['lng']

                # Realizamos una búsqueda inicial dentro de la ciudad
                radio_km = 0.5  # Comenzamos con un radio pequeño, 0.5 km
                while len(restaurantes_encontrados) < 10:
                    bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km)
                    formula_parts_city = formula_parts.copy()
                    formula_parts_city.append(f"{{location/lat}} >= {limites['lat_min']}")
                    formula_parts_city.append(f"{{location/lat}} <= {limites['lat_max']}")
                    formula_parts_city.append(f"{{location/lng}} >= {limites['lon_min']}")
                    formula_parts_city.append(f"{{location/lng}} <= {limites['lon_max']}")

                    filter_formula = "AND(" + ", ".join(formula_parts_city) + ")"
                    logging.info(f"Fórmula de filtro construida: location = ({lat_centro}, {lon_centro}), bounding_box = {filter_formula}")

            params = {
                "filterByFormula": filter_formula,
                "sort[0][field]": "NBH2",
                "sort[0][direction]": "desc",
                "maxRecords": 10
            }

            response_data = airtable_request(url, headers, params)
            if response_data and 'records' in response_data:
                restaurantes_filtrados = [
                    restaurante for restaurante in response_data['records']
                    if restaurante not in restaurantes_encontrados  # Evitar duplicados
                ]
                restaurantes_encontrados.extend(restaurantes_filtrados)

            if len(restaurantes_encontrados) >= 10:
                break

            radio_km += 0.5  # Aumentamos el radio

            if radio_km > 2:  # Limitar el rango máximo de búsqueda a 2 km
                break

            # Ordenamos los restaurantes por proximidad si se especifica
            if sort_by_proximity:
                restaurantes_encontrados.sort(key=lambda r: haversine(
                    lon_centro, lat_centro,
                    float(r['fields'].get('location/lng', 0)),
                    float(r['fields'].get('location/lat', 0))
                ))
    
            # Limitamos los resultados a 10 restaurantes
            restaurantes_encontrados = restaurantes_encontrados[:10]
    
        # Devolvemos los restaurantes encontrados y la fórmula de filtro usada
        return restaurantes_encontrados, filter_formula
    
    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes de la ciudad")

@app.post("/procesar-variables")

#Esta es la función que convierte los datos que ha extraído el agente de IA en las variables que usa la función obtener_restaurantes y luego llama a esta misma función y extrae y ofrece los resultados
async def procesar_variables(request: Request):
    try:
        data = await request.json()
        logging.info(f"Datos recibidos: {data}")
        
        city = data.get('city')
        date = data.get('date')
        price_range = data.get('price_range')
        cocina = data.get('cocina')
        diet = data.get('diet')
        dish = data.get('dish')
        zona = data.get('zona')
        coordenadas = data.get('coordenadas')

        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        # Llama a la función obtener_restaurantes_por_ciudad y construye la filter_formula
        restaurantes, filter_formula = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona,
            coordenadas=coordenadas
        )

        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method

        # Capturar la información del request
        http_request_info = f'{request_method} {full_url} HTTP/1.1 200 OK'
        
        # Si no se encontraron restaurantes, devolver el mensaje y el request_info
        if not restaurantes:
            return {
                "request_info": http_request_info,
                "variables": {
                    "city": city,
                    "zone": zona,
                    "cuisine_type": cocina,
                    "price_range": price_range,
                    "date": date,
                    "alimentary_restrictions": diet,
                    "specific_dishes": dish
                },
                "mensaje": "No se encontraron restaurantes con los filtros aplicados."
            }
        
        # Procesar los restaurantes
        resultados = [
            {
                "bh_message": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "url": restaurante['fields'].get('url', 'No especificado')
            }
            for restaurante in restaurantes
        ]
        
        # Devolver los resultados junto con el log de la petición HTTP
        return {
            "request_info": http_request_info,
            "variables": {
                "city": city,
                "zone": zona,
                "cuisine_type": cocina,
                "price_range": price_range,
                "date": date,
                "alimentary_restrictions": diet,
                "specific_dishes": dish
            },
            "resultados": resultados
        }
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": "Ocurrió un error al procesar las variables"}
