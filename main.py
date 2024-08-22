from fastapi import FastAPI, Query, HTTPException
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, filtrar_y_ordenar_restaurantes, obtener_dia_semana
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
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente")
):
    try:
        fecha = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
        dia_semana = obtener_dia_semana(fecha)

        # Obtener los restaurantes de la ciudad
        restaurantes = obtener_restaurantes_por_ciudad(city, price_range)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes en la ciudad especificada."}
        
        # Filtrar y ordenar los restaurantes
        top_restaurantes = filtrar_y_ordenar_restaurantes(restaurantes, dia_semana, price_range, cocina)
        
        if not top_restaurantes:
            return {"mensaje": "No se encontraron restaurantes abiertos con los filtros aplicados."}
        
        return {
            "resultados": [
                {
                    "titulo": restaurante['fields'].get('title', 'Sin título'),
                    "descripcion": restaurante['fields'].get('description', 'Sin descripción'),
                    "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                    "puntuacion_bistrohunter": restaurante['fields'].get('nota_bh', restaurante['fields'].get('score', 'N/A'))
                }
                for restaurante in top_restaurantes
            ]
        }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
