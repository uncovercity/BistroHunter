from fastapi import FastAPI, Query, HTTPException
from typing import Optional
from bistrohunter import get_restaurants_by_city, get_day_of_week, RestaurantResponse, Restaurant
from datetime import datetime
import logging

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants", response_model=RestaurantResponse)
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente")
):
    try:
        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = get_day_of_week(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD.")
        
        # Obtener los restaurantes filtrados y ordenados desde Airtable
        restaurantes = get_restaurants_by_city(city, dia_semana, price_range, cocina, diet, dish)
        
        if not restaurantes:
            raise HTTPException(status_code=404, detail="No se encontraron restaurantes con los filtros aplicados.")
        
        return RestaurantResponse(
            resultados=[
                Restaurant(
                    title=restaurante['fields'].get('title', 'Sin título'),
                    bh_message=restaurante['fields'].get('bh_message', 'Sin descripción'),
                    price_range=restaurante['fields'].get('price_range', 'No especificado'),
                    score=restaurante['fields'].get('score', 'N/A'),
                    tripadvisor_dietary_restrictions=restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
                )
                for restaurante in restaurantes
            ]
        )
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
