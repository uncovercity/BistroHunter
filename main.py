from fastapi import FastAPI, Query, HTTPException
from datetime import datetime
import logging
from typing import Optional, List, Union
from bistrohunter import buscar_restaurantes_por_ciudad, aplicar_filtros_y_ordenar, airtable_cache

app = FastAPI()

# Configuración básica de logging
logging.basicConfig(level=logging.INFO)

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
        # Intentar obtener los restaurantes de la caché
        restaurantes_por_ciudad = airtable_cache.get(f"buscar_restaurantes_por_ciudad:{city}")
        if restaurantes_por_ciudad is None:
            # Si no están en caché, hacer la búsqueda en Airtable
            restaurantes_por_ciudad = buscar_restaurantes_por_ciudad(city)
            # Guardar el resultado en la caché
            airtable_cache[f"buscar_restaurantes_por_ciudad:{city}"] = restaurantes_por_ciudad

        if isinstance(restaurantes_por_ciudad, list):
            # Procesar la fecha
            if date:
                fecha = datetime.strptime(date, "%Y-%m-%d")
            else:
                fecha = datetime.now()

            # Aplicar filtros y ordenar
            resultados = aplicar_filtros_y_ordenar(restaurantes_por_ciudad, fecha, price_range, cocina)
            
            # Formatear los resultados para la respuesta
            return {
                "resultados": [
                    {
                        "nombre": restaurante.get('title', 'N/A'),
                        "cocina": restaurante.get('grouped_categories', 'N/A'),
                        "estrellas": restaurante.get('nota_bh', restaurante.get('score', 'N/A')),
                        "rango_de_precios": restaurante.get('price_range', 'N/A'),
                        "url_maps": restaurante.get('url', 'N/A')
                    }
                    for restaurante in resultados
                ]
            }
        else:
            return {"mensaje": restaurantes_por_ciudad}
    except Exception as e:
        logging.error(f"Error al obtener los restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener los restaurantes")
