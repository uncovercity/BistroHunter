import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Depends
from datetime import datetime
import requests
import logging
from functools import lru_cache
from pydantic import BaseModel, Field

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

class Restaurant(BaseModel):
    titulo: str = Field(..., alias='title')
    descripcion: str = Field(..., alias='bh_message')
    rango_de_precios: str = Field(..., alias='price_range')
    puntuacion_bistrohunter: float = Field(..., alias='score')
    opciones_alimentarias: Optional[List[str]] = Field(None, alias='tripadvisor_dietary_restrictions')

class RestaurantResponse(BaseModel):
    resultados: List[Restaurant]

def get_day_of_week(date: datetime) -> str:
    try:
        day_of_week_en = date.strftime('%A')
        return DAYS_ES.get(day_of_week_en, day_of_week_en).lower()
    except Exception as e:
        logging.error(f"Error getting day of week: {e}")
        raise HTTPException(status_code=500, detail="Error processing date")

@lru_cache(maxsize=1)
def get_airtable_headers():
    return {"Authorization": f"Bearer {AIRTABLE_PAT}"}

def airtable_request(url: str, params: dict) -> dict:
    response = requests.get(url, headers=get_airtable_headers(), params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Airtable API request failed")
    return response.json()

def normalize_price_range(price_range):
    if isinstance(price_range, list):
        return ', '.join(price_range)
    return price_range

def get_restaurants_by_city(
    city: str, 
    day_of_week: Optional[str] = None, 
    price_range: Optional[str] = None,
    cuisine: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None
) -> List[dict]:
    table_name = 'Restaurantes DB'
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"

    formula_parts = [f"OR({{city}}='{city}', {{city_string}}='{city}')"]

    if day_of_week:
        formula_parts.append(f"FIND('{day_of_week}', ARRAYJOIN({{day_opened}}, ', ')) > 0")
    if price_range:
        formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")
    if cuisine:
        formula_parts.append(f"OR(ARRAYJOIN({{grouped_categories}}, ', ') = '{cuisine}', FIND('{cuisine}', ARRAYJOIN({{grouped_categories}}, ', ')) > 0)")
    if diet:
        formula_parts.append(f"FIND('{diet}', ARRAYJOIN({{tripadvisor_dietary_restrictions}}, ', ')) > 0")
    if dish:
        formula_parts.append(f"FIND('{dish}', ARRAYJOIN({{comida_[TESTING]}}, ', ')) > 0")

    filter_formula = "AND(" + ", ".join(formula_parts) + ")"
    logging.info(f"Filter formula: {filter_formula}")

    params = {
        "filterByFormula": filter_formula,
        "sort[0][field]": "score",
        "sort[0][direction]": "desc",
        "maxRecords": 3
    }

    response_data = airtable_request(url, params)
    return response_data.get('records', [])

@app.get("/")
async def root():
    return {"message": "Welcome to the Restaurant Search API"}

@app.get("/api/getRestaurants", response_model=RestaurantResponse)
async def get_restaurants(
    city: str, 
    date: Optional[str] = Query(None, description="Date of planned restaurant visit"),
    price_range: Optional[str] = Query(None, description="Desired price range"),
    cuisine: Optional[str] = Query(None, description="Preferred cuisine type"),
    diet: Optional[str] = Query(None, description="Dietary requirements"),
    dish: Optional[str] = Query(None, description="Specific dish query")
):
    day_of_week = None
    if date:
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            day_of_week = get_day_of_week(date_obj)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    restaurants = get_restaurants_by_city(city, day_of_week, price_range, cuisine, diet, dish)

    if not restaurants:
        raise HTTPException(status_code=404, detail="No restaurants found with the applied filters.")

    return RestaurantResponse(
        resultados=[
            Restaurant(
                title=restaurant['fields'].get('title', 'Untitled'),
                bh_message=restaurant['fields'].get('bh_message', 'No description'),
                price_range=restaurant['fields'].get('price_range', 'Not specified'),
                score=restaurant['fields'].get('score', 'N/A'),
                tripadvisor_dietary_restrictions=restaurant['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            )
            for restaurant in restaurants
        ]
    )
