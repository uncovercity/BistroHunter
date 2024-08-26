from fastapi import FastAPI, Query, HTTPException
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana
import logging
from datetime import datetime

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente")
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)
        
        # Obtener los restaurantes filtrados y ordenados desde Airtable
        restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}
        
        return {
            "resultados": [
                {
                    "titulo": restaurante['fields'].get('title', 'Sin título'),
                    "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                    "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                    "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A'),
                    **({"opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions')} if diet else {})
                }
                for restaurante in restaurantes
            ]
        }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
