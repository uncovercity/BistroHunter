#IMPORTS
from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
from bistrohunter import calcular_bounding_box, obtener_restaurantes_por_ciudad, haversine, obtener_coordenadas_zona
import logging
from datetime import datetime

app = FastAPI()

@app.get("/") #Define el mensaje por defecto de nuestra propia API 
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurants")
async def get_restaurantes(
    city: str = Query(...),
    coordenadas: Optional[str] = Query(None),
    price_range: Optional[str] = Query(None),
    cocina: Optional[str] = Query(None),
    diet: Optional[str] = Query(None),
    dish: Optional[str] = Query(None),
    zona: Optional[str] = Query(None),
):
    try:
        logging.info(f"Coordenadas recibidas en get_restaurantes: {coordenadas}")
        
        # Procesar coordenadas si se proporcionan
        if coordenadas:
            try:
                # Convertir de str a lista de floats
                coordenadas = [float(coord) for coord in coordenadas.split(",")]
                logging.info(f"Coordenadas procesadas: {coordenadas}")
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de coordenadas inválido")
        else:
            logging.info("No se proporcionaron coordenadas")

        # Lógica para manejar coordenadas
        if coordenadas:
            
            logging.info(f"Usando coordenadas proporcionadas: {coordenadas}")
            location = coordenadas
            if not location:
                raise HTTPException(status_code=404, detail="Coordenadas no encontradas")
            lat_centro = location[0]
            lon_centro = location[1]
            
            logging.info(f"Calculando bounding box para coordenadas: {lat_centro}, {lon_centro}")
            bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km=2.0)
            formula = f"AND({{location/lat}} >= {bounding_box['lat_min']}, {{location/lat}} <= {bounding_box['lat_max']}, {{location/lng}} >= {bounding_box['lon_min']}, {{location/lng}} <= {bounding_box['lon_max']})"
            logging.info(f"Fórmula de filtro construida: {formula}")
    
            return {"coordenadas": coordenadas, "formula": formula}
        else:
            logging.info("Usando coordenadas basadas en la ciudad")
            location_city = obtener_coordenadas_zona(zona_item, city, radio_km)
            if not location_city:
                raise HTTPException(status_code=404, detail="Ciudad no encontrada")
            lat_centro = location_city['location']['lat']
            lon_centro = location_city['location']['lng']

            logging.info(f"Calculando bounding box para coordenadas: {lat_centro}, {lon_centro}")
            bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km=2.0)
            formula = f"AND({{location/lat}} >= {bounding_box['lat_min']}, {{location/lat}} <= {bounding_box['lat_max']}, {{location/lng}} >= {bounding_box['lon_min']}, {{location/lng}} <= {bounding_box['lon_max']})"
            logging.info(f"Fórmula de filtro construida: {formula}")
    
            return {lat_centro, lon_centro, formula}
    
    except Exception as e:
        logging.error(f"Error al procesar la solicitud: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")
        
@app.post("/procesar-variables")
async def procesar_variables(request: Request):
    try:
        data = await request.json()
        logging.info(f"Datos recibidos: {data}")
        
        city = data.get('city')
        date = data.get('date')
        price_range = data.get('price_range')
        cocina = data.get('cocina')
        diet = data.get('diet')
        dish = data.get('dish')
        zona = data.get('zona')
        coordenadas = data.get('coordenadas')

        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        # Llamar a la función para obtener los restaurantes y la fórmula de filtro
        logging.info(f"Coordenadas recibidas: {coordenadas}")
        restaurantes, filter_formula = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona,
            coordenadas=coordenadas
        )

        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method
        api_call = f'{request_method} {full_url}'

        # Devolver los restaurantes, las variables y la llamada a la API
        if restaurantes:
            return {
                "restaurants": [
                    {
                        "bh_message": r['fields'].get('bh_message', 'Sin descripción'),
                        "url": restaurante['fields'].get('url', 'No especificado')
                    } for r in restaurantes
                ],
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zone": zona
                },
                "api_call": api_call
            }
        else:
            return {
                "mensaje": "No se encontraron restaurantes con los filtros aplicados.",
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zone": zona
                },
                "api_call": api_call
            }
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar variables")
