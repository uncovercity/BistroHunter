from fastapi import FastAPI, HTTPException, Request
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana, haversine, enviar_respuesta_a_n8n, extraer_variables_desde_gpt
import logging
from datetime import datetime

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    client_conversation: Optional[str] = None,  # La conversación del cliente
    city: Optional[str] = None, 
    date: Optional[str] = None, 
    price_range: Optional[str] = None, 
    cocina: Optional[str] = None, 
    diet: Optional[str] = None, 
    dish: Optional[str] = None, 
    zona: Optional[str] = None
):
    try:
        # Si se proporciona una conversación del cliente, extraer las variables usando GPT
        if client_conversation:
            extracted_data = extraer_variables_desde_gpt(client_conversation)
            city = extracted_data.get('city', city)
            date = extracted_data.get('date', date)
            price_range = extracted_data.get('price_range', price_range)
            cocina = extracted_data.get('cocina', cocina)
            diet = extracted_data.get('diet', diet)
            dish = extracted_data.get('dish', dish)
            zona = extracted_data.get('zona', zona)

        # Validación básica: al menos una ciudad debe estar presente
        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        # Procesar la fecha si se proporciona
        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        # Llamar a la función obtener_restaurantes_por_ciudad con los parámetros recibidos o extraídos
        restaurantes = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona
        )

        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}

        resultados = [
            {
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('score', 'N/A'),
                "distancia": restaurante.get('distancia', 'No calculado'),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        enviar_respuesta_a_n8n(resultados)

        return {"resultados": resultados}
        
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")

