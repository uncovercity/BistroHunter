from fastapi import FastAPI
from bistrohunter import buscar_restaurantes

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/restaurantes/{city}")
async def get_restaurantes(city: str):
    resultados = buscar_restaurantes(city)
    
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
