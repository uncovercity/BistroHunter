from typing import Optional, List, Union
from fastapi import FastAPI, Query
from datetime import datetime
import requests
import locale

app = FastAPI()

def obtener_dia_semana(fecha: datetime) -> str:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    dia_semana = fecha.strftime('%A').lower()
    return dia_semana

def obtener_horarios(cid: str, dia_semana: str) -> Optional[bool]:
    table_name = 'Horarios'
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_PAT}",
    }
    params = {
        "filterByFormula": f"AND({{cid}}='{cid}', {{isOpen?}}='{dia_semana}')"
    }

    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        records = response.json().get('records', [])
        if records:
            return True  
        else:
            return False  
    else:
        return None

def buscar_restaurantes(city: str, date: Optional[str] = None, price_range: Optional[str] = None) -> Union[str, List[dict]]:
    # Si se proporciona una fecha, convertirla a día de la semana
    if date:
        fecha = datetime.strptime(date, "%Y-%m-%d")
        dia_semana = obtener_dia_semana(fecha)
    else:
        hoy = datetime.now()
        dia_semana = obtener_dia_semana(hoy)
    
    table_name = 'Restaurantes DB'
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_PAT}",
    }

    # Construir la fórmula de filtro
    formula_parts = [f"OR({{city}}='{city}', {{city_string}}='{city}')"]
    
    if price_range:
        formula_parts.append(f"{{price_range}}='{price_range}'")
    
    filter_formula = "AND(" + ", ".join(formula_parts) + ")"

    params = {
        "filterByFormula": filter_formula
    }

    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        records = response.json().get('records', [])
        if not records:
            return "No se encontraron restaurantes en la ciudad especificada."
        
        restaurantes_abiertos = []
        for record in records:
            cid = record['fields'].get('cid')
            if cid and obtener_horarios(cid, dia_semana):
                restaurantes_abiertos.append(record['fields'])
        
        if restaurantes_abiertos:
            return restaurantes_abiertos[:3]  
        else:
            return "No se encontraron restaurantes abiertos hoy."
    else:
        return f"Error: No se pudo conectar a Airtable. Código de estado: {response.status_code}"

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante")
):
    resultados = buscar_restaurantes(city, date, price_range)
    
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
