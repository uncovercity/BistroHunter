from fastapi import FastAPI, Query
from bistrohunter import buscar_restaurantes

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def
