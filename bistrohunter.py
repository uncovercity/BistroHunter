import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache
from math import radians, cos, sin, asin, sqrt
import openai


app = FastAPI()

logging.basicConfig(level=logging.INFO)

BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
openai.api_key = os.getenv("OPENAI_API_KEY")

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
            formula_parts_zona = formula_parts[:]
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
            restaurantes_encontrados.sort(
                key=lambda r: haversine(lon_centro, lat_centro, float(r['fields'].get('location/lng', 0)), float(r['fields'].get('location/lat', 0))))

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

@app.post("/procesar-variables")
async def procesar_variables(request: Request):
    try:
        # Recibir el texto completo de la consulta desde n8n
        data = await request.json()
        client_conversation = data.get('client_conversation')
        logging.info(f"Consulta recibida: {client_conversation}")

        if not client_conversation:
            raise HTTPException(status_code=400, detail="La consulta en texto es obligatoria.")

        # Lógica de GPT para extraer variables desde el texto de client_conversation
        extracted_data = extraer_variables_con_gpt(client_conversation)

        # Extraer las variables obtenidas por GPT
        city = extracted_data.get('city')
        date = extracted_data.get('date')
        price_range = extracted_data.get('price_range')
        cocina = extracted_data.get('cocina')
        diet = extracted_data.get('diet')
        dish = extracted_data.get('dish')
        zona = extracted_data.get('zona')

        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        # Obtener los restaurantes basados en las variables extraídas
        restaurantes = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona
        )

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

        # Enviar los resultados a n8n
        enviar_respuesta_a_n8n(resultados)

        return {"mensaje": "Datos procesados y respuesta generada correctamente", "resultados": resultados}
    
    except Exception as e:
        logging.error(f"Error al procesar la consulta: {e}")
        return {"error": "Ocurrió un error al procesar la consulta"}

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

def extraer_variables_con_gpt(client_conversation: str) -> dict:
    """
    Esta función utiliza GPT para extraer variables relevantes de una conversación
    del cliente. Las variables que se extraen incluyen ciudad, fecha, rango de precios,
    tipo de cocina, restricciones alimentarias, plato específico y zona.

    Args:
    client_conversation (str): La conversación completa del cliente.

    Returns:
    dict: Un diccionario con las variables extraídas.
    """

    # Construir el prompt con el formato proporcionado y la conversación del cliente
    prompt = f"""
    {client_conversation}

        Hello! I am BistroHunter, your personal assistant for finding the best restaurants. I'm here to help you have the best possible dining experience.
    
    ### STEP 1: Collecting Information
    - **CITY is mandatory**: If the client does not provide a city, you must ask for it and keep asking until it is provided.
    - If the client provides **DATE, CUISINE TYPE, PRICE RANGE, ALIMENTARY RESTRICTIONS, SPECIFIC DISHES**, collect this information as well to offer the best possible restaurant options.
    - **DATE is optional**: If the client provides a date, check the day of the week and determine if it is a holiday in the specified city. 
      - **If it is a holiday**, always warn the client: "Please note that the restaurant's hours might differ due to the holiday, or it might even be closed."
      - **If the client does not provide a date**, always include the following warning: "Since you haven't specified a date, please remember to check the opening hours of the recommended restaurants."
    
    ### STEP 2: Adapting to the Client's Style
    - **Language and Tone**: Always respond in the language or dialect the client uses. If the client writes in French, respond in French; if they write in Catalan, respond in Catalan. 
      - If you do not recognize the dialect but understand the language, respond in the standard dialect of that language. If you cannot recognize the language, respond in Spanish.
    - **Formality**: Mirror the client's tone and formality. If the client is formal, maintain a formal tone; if they are informal, respond in a friendly, casual manner.
    
    ### STEP 3: Processing the Request
    - Convert the client's criteria into the appropriate format for Airtable.
      - **Cuisine Type**: Convert the cuisine type provided by the client into one of these specific categories: Española, Otros, India, Fusión, Italiano, Mexicano, Chino, Japonés, Asiático, Healthy, Americana, Latina, Vegetariano, Árabe, Vegano, Hindú.
      - **Price Range**: Ensure the price range is converted into the intervals used in Airtable (e.g., “10-20 €“, “20-30 €”, etc.).
    - Retrieve the top 3 restaurant options, ordered by score (stars) in descending order.
    
    ### STEP 4: Responding to the Client
    - Begin with a friendly greeting, using the client's name if provided.
    - Include any warnings about date and opening hours based on whether the client provided a date.
    - Present the top 3 restaurant options, ensuring they are ordered by their score in descending order.
    - Conclude the message by reminding the client that you can assist with making reservations.
    
    ### CRITICAL Reminder:
    - **ALWAYS** include a warning about checking the opening hours if the client has not provided a date. This warning must be given **before** presenting the restaurant options.
    
    ### REMEMBER:
    - **ALWAYS** include a warning about checking the opening hours if the client has not provided a date. This warning must be given **before** presenting the restaurant options.
    
    ### EXAMPLES:
    
    1. **If the client provides a date**:
       - "Here are the best restaurant options for your visit on [date]: ..."
    
    2. **If the client does NOT provide a date**:
       - "Since you haven't specified a date, please remember to check the opening hours of the recommended restaurants before your visit. Here are the top options: ..."
        """

    try:
        # Llamada a la API de OpenAI para procesar el prompt
        response = openai.Completion.create(
        model="gpt-4o",  # Especifica el modelo GPT-4 aquí
        prompt=prompt,
        max_tokens=150,
        n=1,
        stop=None,
        temperature=0.7,
    )


        # Extraer la respuesta de GPT y convertirla a un diccionario
        gpt_response = response.choices[0].text.strip()
        extracted_data = eval(gpt_response)

        return extracted_data

    except Exception as e:
        logging.error(f"Error al procesar la consulta con GPT: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la consulta con GPT")

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str,
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"),
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
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

        return {"resultados": resultados}

    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
