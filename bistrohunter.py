#IMPORTS
import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache
from math import radians, cos, sin, asin, sqrt

#Desplegar fast api (no tocar)
app = FastAPI()

#Configuración del logging (nos va a decir dónde están los fallos)
logging.basicConfig(level=logging.INFO)

#Secretos. Esto son urls, claves, tokens y demás que no deben mostrarse públicamente ni subirse a ningún sitio
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

#Calcula la distancia haversiana entre dos puntos (filtro de zona)
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
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

def busqueda_coordenadas_airtable(coordenadas: list, radio_km: float = 1.0) -> Optional[dict]:
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "latlng": f"{coordenadas[0]}, {coordenadas[1]}",
            "key": GOOGLE_MAPS_API_KEY,
            "components": "country:ES"
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data['status'] == 'OK':
            location = {"lat": coordenadas[0], "lng": coordenadas[1]}
            bounding_box = calcular_bounding_box(coordenadas[0], coordenadas[1], radio_km)
            return {
                "location": location,
                "bounding_box": bounding_box
            }
        else:
            logging.error(f"Error en la geocodificación: {data['status']} - {data.get('error_message', '')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la solicitud de geocodificación: {e}")
        return None
    except KeyError as e:
        logging.error(f"Clave faltante en la respuesta de geocodificación: {e}")
        return None
    except Exception as e:
        logging.error(f"Error inesperado: {e}")
        return None

#Función que obtiene las coordenadas de la zona que ha especificado el cliente
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

def obtener_coordenadas(ciudad: str, radio_km: float=1):
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
        
#Caché (no tocar)
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

#Función que realiza la petición a la API de Airtable
def airtable_request(url, headers, params, view_id: Optional[str] = None):
    if view_id:
        params["view"] = view_id
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

@cache_airtable_request

# Función que toma las variables que le ha dado el asistente de IA para hacer la llamada a la API de Airtable con una serie de condiciones
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
                # Mantener la fórmula original para un solo rango
                formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
            else:
                # Crear una condición OR para múltiples rangos
                conditions = []
                for r in ranges:
                    conditions.append(f"FIND('{r.strip()}', ARRAYJOIN({{price_range}}, ', ')) > 0")
                or_condition = ', '.join(conditions)
                formula_parts.append(f"OR({or_condition})")

        if cocina:
            cocinas = cocina.split(',')
            if len(cocinas) == 1:
                # Mantener la fórmula original para una sola cocina
                formula_parts.append(f"SEARCH('{cocina.strip()}', {{categories_string}}) > 0")
            else:
                # Crear una condición OR para múltiples cocinas
                conditions = []
                for c in cocinas:
                    conditions.append(f"SEARCH('{c.strip()}', {{categories_string}}) > 0")
                or_condition = ', '.join(conditions)
                formula_parts.append(f"OR({or_condition})")

        if diet:
            formula_parts.append(f"SEARCH('{diet}', {{categories_string}}) > 0")
        
        if dish:
            dishes = dish.split(',')
            if len(dishes) ==1:
                formula_parts.append(f"SEARCH('{dish}', {{google_reviews}}) > 0")
            else:
                all_conditions = [f"SEARCH('{d.strip()}', {{google_reviews}}) > 0" for d in dishes]
                all_condition = ' AND '.join(all_conditions)
                any_conditions = [f"SEARCH('{d.strip()}', {{google_reviews}}) > 0" for d in dishes]
                any_condition = ' OR '.join(any_conditions)
                formula_parts.append(f"IF({all_condition}, {all_condition}, {any_condition})")

        # Lista para almacenar todos los restaurantes encontrados
        restaurantes_encontrados = []
        filter_formula = None  # Inicializamos filter_formula

        # Si se especifica zona
        if zona:
            # Verificamos si zona contiene múltiples zonas separadas por comas
            if ',' in zona:
                # Dividimos zona en una lista de zonas
                zonas_list = [z.strip() for z in zona.split(',')]
            else:
                zonas_list = [zona]

            # Iteramos sobre cada zona en la lista
            for zona_item in zonas_list:
                # Obtenemos las coordenadas y bounding_box de la zona
                location_zona = obtener_coordenadas_zona(zona_item, city, radio_km)
                if not location_zona:
                    logging.error(f"Zona '{zona_item}' no encontrada.")
                    continue  # Saltamos a la siguiente zona si no se encuentra

                location = location_zona['location']
                bounding_box = location_zona['bounding_box']

                lat_centro = location['lat']
                lon_centro = location['lng']

                # Extraemos los límites del bounding_box
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                formula_parts_zona = formula_parts.copy()

                # Añadimos los límites a la fórmula de búsqueda
                formula_parts_zona.append(f"{{location/lat}} >= {lat_min}")
                formula_parts_zona.append(f"{{location/lat}} <= {lat_max}")
                formula_parts_zona.append(f"{{location/lng}} >= {lon_min}")
                formula_parts_zona.append(f"{{location/lng}} <= {lon_max}")

                filter_formula_zona = "AND(" + ", ".join(formula_parts_zona) + ")"
                logging.info(f"Fórmula de filtro construida: location = {lat_centro, lon_centro}, bounding_box = {filter_formula_zona} para zona '{zona_item}'")

                params = {
                    "filterByFormula": filter_formula_zona,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10  # Solicitamos hasta 10 restaurantes por zona
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    restaurantes_filtrados = [
                        restaurante for restaurante in response_data['records']
                        if restaurante not in restaurantes_encontrados  # Evitar duplicados
                    ]
                    restaurantes_encontrados.extend(restaurantes_filtrados)

            # Limitamos el total de resultados a 10 restaurantes por zona
            max_total_restaurantes = len(zonas_list) * 10
            restaurantes_encontrados = restaurantes_encontrados[:max_total_restaurantes]

        else:
            # Si no se especifica zona, procedemos como antes
            if coordenadas:
                # Verificamos que coordenadas sea una lista con dos elementos
                if not (isinstance(coordenadas, list) and len(coordenadas) == 2 and all(isinstance(coord, (int, float)) for coord in coordenadas)):
                    raise HTTPException(status_code=400, detail="Las coordenadas deben ser una lista de dos números (latitud y longitud).")
                # Usamos las coordenadas proporcionadas para buscar
                location = busqueda_coordenadas_airtable(coordenadas)
                if not location:
                    raise HTTPException(status_code=404, detail="Coordenadas no encontradas.")
                
                lat_centro = location['location']['lat']
                lon_centro = location['location']['lng']
            else:
                # Si no se proporcionan coordenadas, obtenemos las de la ciudad
                location_city = obtener_coordenadas(city, radio_km)
                if not location_city:
                    raise HTTPException(status_code=404, detail="Ciudad no encontrada.")
                
                lat_centro = location_city['location']['lat']
                lon_centro = location_city['location']['lng']

            # Realizamos una búsqueda inicial dentro de la ciudad
            radio_km = 0.5  # Comenzamos con un radio pequeño, 0.5 km
            while len(restaurantes_encontrados) < 10:
                formula_parts_city = formula_parts.copy()

                limites = calcular_bounding_box(lat_centro, lon_centro, radio_km)
                formula_parts_city.append(f"{{location/lat}} >= {limites['lat_min']}")
                formula_parts_city.append(f"{{location/lat}} <= {limites['lat_max']}")
                formula_parts_city.append(f"{{location/lng}} >= {limites['lon_min']}")
                formula_parts_city.append(f"{{location/lng}} <= {limites['lon_max']}")

                filter_formula = "AND(" + ", ".join(formula_parts_city) + ")"
                logging.info(f"Fórmula de filtro construida: location = {lat_centro, lon_centro}, bounding_box = {filter_formula}")

                params = {
                    "filterByFormula": filter_formula,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    restaurantes_filtrados = [
                        restaurante for restaurante in response_data['records']
                        if restaurante not in restaurantes_encontrados  # Evitar duplicados
                    ]
                    restaurantes_encontrados.extend(restaurantes_filtrados)

                if len(restaurantes_encontrados) >= 10:
                    break  # Si alcanzamos 10 resultados, detenemos la búsqueda

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
            zona=zona
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
