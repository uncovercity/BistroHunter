from fastapi import FastAPI, Query, HTTPException
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana
import logging
from datetime import datetime
import os
import requests

app = FastAPI()

# El token de acceso a la API de Chatwoot se obtiene desde una variable de entorno
api_access_token = os.getenv('api_access_token')

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

# Función para enviar mensaje al cliente vía Chatwoot
@app.post("/api/chatwoot_message")
async def chatwoot_message(conversation_id: str):
    """
    Envia un mensaje al cliente vía Chatwoot para preguntarle sobre los filtros de búsqueda de restaurantes.
    
    Args:
        conversation_id (str): El ID de la conversación de Chatwoot.
    """
    url = f"https://app.chatwoot.com/api/v1/accounts/99502/conversations/{conversation_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "api_access_token": api_access_token
    }
    
    # El mensaje que se enviará al cliente para recolectar las variables necesarias
    message = """
    ¡Hola! Soy BistroHunter. Encontraré el mejor restaurante para ti. Necesito que me digas en qué ciudad quieres disfrutar de tu experiencia. 
    Cuantos más datos me des (plato que te apetece, zona de la ciudad, rango de precios, fecha, restricciones alimenticias o alergias, tipo de cocina...), 
    mejor podré ayudarte.
    """
    
    payload = {
        "content": message
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logging.error(f"Error al enviar mensaje a Chatwoot: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Error al enviar mensaje a Chatwoot")
        return {"mensaje": "Mensaje enviado al cliente para solicitar información sobre la búsqueda de restaurantes."}
    except Exception as e:
        logging.error(f"Error en la solicitud a Chatwoot: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar mensaje a Chatwoot")

# Función para recomendar restaurantes basada en las respuestas obtenidas
@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad"),
    conversation_id: Optional[str] = Query(None, description="El ID de la conversación de Chatwoot")
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)
        
        restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish, zona)
        
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

        # Enviar los resultados al cliente vía Chatwoot
        if conversation_id:
            await chatwoot_message(conversation_id, "Aquí tienes los resultados de tu búsqueda de restaurantes.", api_access_token)

        return {"resultados": resultados}
        
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")

async def chatwoot_message(conversation_id: str, message: str, api_access_token: str):
    """
    Envia un mensaje a través de la API de Chatwoot usando el ID de la conversación.
    """
    url = f"https://app.chatwoot.com/api/v1/accounts/99502/conversations/{conversation_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "api_access_token": api_access_token
    }
    payload = {
        "content": message
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logging.error(f"Error al enviar mensaje a Chatwoot: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Error al enviar mensaje a Chatwoot")
    except Exception as e:
        logging.error(f"Error en la solicitud a Chatwoot: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar mensaje a Chatwoot")
