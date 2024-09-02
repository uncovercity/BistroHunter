from fastapi import FastAPI, HTTPException, Request
from typing import Optional
import requests
import logging
from datetime import datetime
from math import radians, cos, sin, asin, sqrt

app = FastAPI()

# Configuraciones y constantes
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

# Función para obtener el día de la semana en español
def obtener_dia_semana(fecha: datetime) -> str:
    dia_semana_en = fecha.strftime('%A')
    dia_semana_es = DAYS_ES.get(dia_semana_en, dia_semana_en)
    return dia_semana_es.lower()

# Función Haversine para calcular la distancia
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km

# Función para obtener coordenadas
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

# Función para hacer la solicitud a Airtable
def airtable_request(url, headers, params):
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

# Función para obtener restaurantes por ciudad
def obtener_restaurantes_por_ciudad(city: str, dia_semana: Optional[str] = None, 
                                    price_range: Optional[str] = None, cocina: Optional[str] = None,
                                    diet: Optional[str] = None, dish: Optional[str] = None,
                                    zona: Optional[str] = None) -> list:
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {"Authorization": f"Bearer {AIRTABLE_PAT}"}

        formula_parts = [f"OR({{city}}='{city}', {{city_string}}='{city}')"]

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

        filter_formula = "AND(" + ", ".join(formula_parts) + ")"
        params = {"filterByFormula": filter_formula, "sort[0][field]": "score", "sort[0][direction]": "desc", "maxRecords": 3}

        response_data = airtable_request(url, headers, params)
        return response_data.get('records', []) if response_data else []

    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes de la ciudad")

# Función para extraer variables usando GPT
def extraer_variables_desde_gpt(client_conversation: str) -> dict:
    try:
        response = requests.post(
            "https://bistrohunter.onrender.com/api/extraer-variables",
            json={"client_conversation": client_conversation}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al conectar con el servidor GPT: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la consulta con GPT")

@app.get("/api/getRestaurants")
async def get_restaurantes(client_conversation: str):
    try:
        # Extraer variables desde la conversación usando GPT
        extracted_data = extraer_variables_desde_gpt(client_conversation)

        # Obtener variables extraídas
        city = extracted_data.get('city')
        date = extracted_data.get('date')
        price_range = extracted_data.get('price_range')
        cocina = extracted_data.get('cocina')
        diet = extracted_data.get('diet')
        dish = extracted_data.get('dish')
        zona = extracted_data.get('zona')

        # Validación básica
        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        # Procesar la fecha si se proporciona
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        # Buscar restaurantes basados en las variables extraídas
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

        # Formatear la respuesta
        resultados = [
            {
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A'),
                "distancia": (
                    f"{haversine(float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0)), float(zona['lng']), float(zona['lat'])):.2f} km"
                    if zona and 'location/lng' in restaurante['fields'] and 'location/lat' in restaurante['fields'] else "No calculado"
                ),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        return {"resultados": resultados}

    except Exception as e:
        logging.error(f"Error al procesar la solicitud: {e}")
        return {"error": f"Ocurrió un error al procesar la solicitud: {str(e)}"}

