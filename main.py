from fastapi import FastAPI, Query
from bistrohunter import buscar_restaurantes

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str, 
    date: str = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: str = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: str = Query(None, description="El tipo de cocina que prefiere el cliente")
):
    # Asegúrate de que se pasa 'cocina' a 'buscar_restaurantes'
    resultados = buscar_restaurantes(city, date, price_range, cocina)
    
    if isinstance(resultados, list):
        return {
            "resultados": [
                {
                    "nombre": f"{restaurante.get('title', 'N/A')}. {restaurante.get('description', 'N/A')}",
                    "cocina": restaurante['grouped_categories'],
                    "estrellas": restaurante.get('score', 'N/A'),
                    "rango_de_precios": restaurante['price_range'],
                    "url_maps": restaurante['url']
                }
                for restaurante in resultados
            ]
        }
    else:
        return {"mensaje": resultados}
