from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana, haversine
import logging
from datetime import datetime
import os
import requests

app = FastAPI()

CHATWOOT_API_URL = "https://app.chatwoot.com/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
CHATWOOT_API_KEY = os.getenv('CHATWOOT_API_KEY')
ACCOUNT_ID = os.getenv('ACCOUNT_ID')

estado_conversaciones = {}

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de BistroHunter"}

def enviar_mensaje_chatwoot(conversation_id, mensaje):
    headers = {
        "Content-Type": "application/json",
        "api_access_token": CHATWOOT_API_KEY
    }

    data = {
        "content": mensaje,
        "message_type": "outgoing",
        "private": False
    }

    url = CHATWOOT_API_URL.format(account_id=ACCOUNT_ID, conversation_id=conversation_id)

    response = requests.post(url, headers=headers, json=data)

    if response.status_code not in [200, 201]:
        raise Exception(f"Error al enviar mensaje: {response.text}")

    return response.json()

def manejar_conversacion(conversation_id, mensaje_recibido):
    estado = estado_conversaciones.get(conversation_id, {
        "ciudad": None,
        "fecha": None,
        "rango_precios": None,
        "tipo_cocina": None,
        "dieta": None,
        "plato_especifico": None,
        "zona": None,
        "paso": 0
    })

    mensaje_recibido = mensaje_recibido.strip()

    if estado["paso"] == 0:
        # Paso 0: Saludo inicial
        enviar_mensaje_chatwoot(conversation_id, "¡Hola! Soy BistroHunter, tu recomendador de restaurantes de confianza. ¿En qué ciudad te gustaría buscar un restaurante?")
        estado["paso"] += 1

    elif estado["paso"] == 1:
        # Paso 1: El cliente ha respondido la ciudad
        estado["ciudad"] = mensaje_recibido
        enviar_mensaje_chatwoot(conversation_id, 
            "¡Perfecto! ¿Te gustaría proporcionar más detalles opcionales?\n"
            "Puedes darme cualquiera de los siguientes datos:\n"
            "- Fecha de la reserva (formato: AAAA-MM-DD)\n"
            "- Tipo de cocina\n"
            "- Preferencia dietética (vegetariano, vegano, sin gluten, etc.)\n"
            "- Algún plato específico que te gustaría comer\n"
            "- Zona de la ciudad\n"
            "Si no tienes alguna preferencia, puedes dejar el campo en blanco.")
        estado["paso"] += 1

    elif estado["paso"] == 2:
        # Paso 2: El cliente puede proporcionar información opcional en un solo mensaje
        # Se espera que el cliente proporcione una respuesta que incluya todos o algunos de los parámetros
        datos_extra = mensaje_recibido.split(",")  # Separar los datos por comas (puedes cambiar esto según el formato esperado)

        # Asignar los valores opcionales
        estado["fecha"] = datos_extra[0].strip() if len(datos_extra) > 0 and datos_extra[0] else None
        estado["tipo_cocina"] = datos_extra[1].strip() if len(datos_extra) > 1 and datos_extra[1] else None
        estado["dieta"] = datos_extra[2].strip() if len(datos_extra) > 2 and datos_extra[2] else None
        estado["plato_especifico"] = datos_extra[3].strip() if len(datos_extra) > 3 and datos_extra[3] else None
        estado["zona"] = datos_extra[4].strip() if len(datos_extra) > 4 and datos_extra[4] else None

        # Ahora, se procede a la búsqueda de restaurantes
        enviar_mensaje_chatwoot(conversation_id, "¡Gracias! Estoy buscando restaurantes basados en tu información...")

        # Llamar a la función obtener_restaurantes_por_ciudad con los datos recopilados
        try:
            ciudad = estado["ciudad"]
            fecha = estado.get("fecha", None)
            tipo_cocina = estado.get("tipo_cocina", None)
            dieta = estado.get("dieta", None)
            plato_especifico = estado.get("plato_especifico", None)
            zona = estado.get("zona", None)

            # Convertir la fecha en día de la semana si se proporcionó
            dia_semana = None
            if fecha:
                try:
                    fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
                    dia_semana = obtener_dia_semana(fecha_dt)
                except ValueError:
                    enviar_mensaje_chatwoot(conversation_id, "El formato de la fecha no es válido. La buscaremos sin este filtro.")

            restaurantes = obtener_restaurantes_por_ciudad(ciudad, dia_semana, None, tipo_cocina, dieta, plato_especifico, zona)

            if restaurantes:
                enviar_mensaje_chatwoot(conversation_id, "Aquí tienes algunas recomendaciones de restaurantes:")
                for restaurante in restaurantes:
                    enviar_mensaje_chatwoot(conversation_id, f"Restaurante: {restaurante['titulo']}, Descripción: {restaurante['descripcion']}, Precio: {restaurante['rango_de_precios']}, URL: {restaurante['url']}")
            else:
                enviar_mensaje_chatwoot(conversation_id, "Lo siento, no encontramos restaurantes que coincidan con tus criterios.")

        except Exception as e:
            logging.error(f"Error en la búsqueda de restaurantes: {e}")
            enviar_mensaje_chatwoot(conversation_id, "Ocurrió un error al buscar los restaurantes.")

        # Limpiar el estado de la conversación después de completar
        estado_conversaciones.pop(conversation_id, None)

    estado_conversaciones[conversation_id] = estado

@app.post("/webhook/chatwoot")
async def webhook_chatwoot(request: Request):
    data = await request.json()
    logging.info(f"Datos recibidos: {data}")

    # Verificar si hay mensajes en la clave "messages"
    if "messages" in data and len(data["messages"]) > 0:
        message_data = data["messages"][0]  # Obtener el primer mensaje
        conversation_id = message_data.get("conversation_id")
        mensaje_recibido = message_data.get("content")

        if conversation_id and mensaje_recibido:
            manejar_conversacion(conversation_id, mensaje_recibido)
        else:
            logging.error("Faltan datos en el mensaje recibido")
    else:
        logging.error("No se encontraron mensajes en los datos recibidos")

    return {"status": "success"}


