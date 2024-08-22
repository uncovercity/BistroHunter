from fastapi import FastAPI, Query
from bistrohunter import buscar_restaurantes
from typing import Optional

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
    resultados = buscar_restaurantes(city, date, price_range, cocina)
    
    if isinstance(resultados, list):
        return {
            "resultados": [
                {
                    "titulo": f"{restaurante.get('title', 'N/A')}. {restaurante.get('description', 'N/A')}",
                    "estrellas": restaurante.get('score', 'N/A'),
                    "rango_de_precios": restaurante.get('price_range', 'N/A'),
                    "url_maps": restaurante.get('url', 'N/A')
                }
                for restaurante in resultados
            ]
        }
    else:
        return {"mensaje": resultados}
