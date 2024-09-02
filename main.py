from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana, haversine, enviar_respuesta_a_n8n, extraer_variables_con_gpt
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
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad")
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

        enviar_respuesta_a_n8n(resultados)

        return {"resultados": resultados}
        
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")

@app.post("/procesar-variables")
async def procesar_variables(request: Request):
    try:
        # Recibir los datos enviados desde n8n
        data = await request.json()
        logging.info(f"Datos recibidos: {data}")
        
        # Extraer la conversación del cliente
        client_conversation = data.get('client_conversation')
        
        if not client_conversation:
            raise HTTPException(status_code=400, detail="La consulta en texto es obligatoria.")
        
        # Usar GPT para extraer las variables desde la conversación del cliente
        extracted_data = extraer_variables_desde_gpt(client_conversation)
        
        # Ahora utiliza los datos extraídos para obtener restaurantes o cualquier otro proceso
        city = extracted_data.get('city')
        date = extracted_data.get('date')
        price_range = extracted_data.get('price_range')
        cocina = extracted_data.get('cocina')
        diet = extracted_data.get('diet')
        dish = extracted_data.get('dish')
        zona = extracted_data.get('zona')

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

        # Llamar a la función obtener_restaurantes_por_ciudad con los parámetros recibidos
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
                "distancia": (
                    f"{haversine(float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0)), lat_centro, lon_centro):.2f} km"
                    if zona and 'location/lng' in restaurante['fields'] and 'location/lat' in restaurante['fields'] else "No calculado"
                ),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        enviar_respuesta_a_n8n(resultados)

        return {"mensaje": "Datos procesados y respuesta generada correctamente", "resultados": resultados}
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": f"Ocurrió un error al procesar las variables: {str(e)}"}

