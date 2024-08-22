import openai
import requests

# Define la función que hará la llamada a tu API en Render
def call_get_restaurantes(city, date, price_range=None, cocina=None):
    # URL de tu API desplegada en Render
    url = f"https://your-api-onrender.com/api/getRestaurants?city={city}&date={date}"
    if price_range:
        url += f"&price_range={price_range}"
    if cocina:
        url += f"&cocina={cocina}"
    
    response = requests.get(url)
    return response.json()

# Simulación de una solicitud de usuario y procesamiento por OpenAI
user_input = "Estoy buscando un restaurante en Madrid el viernes con un rango de precios de 30-40 y cocina Italiana."

# Configura la llamada a OpenAI
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "Eres un asistente útil."},
        {"role": "user", "content": user_input},
    ],
    functions=[
        {
            "name": "get_restaurantes",
            "description": "Obtén los mejores restaurantes según las preferencias del usuario utilizando una API desplegada en Render que se conecta a Airtable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "La ciudad donde el usuario quiere encontrar restaurantes."},
                    "date": {"type": "string", "description": "La fecha para la reserva del restaurante."},
                    "price_range": {"type": "string", "description": "El rango de precios deseado."},
                    "cocina": {"type": "string", "description": "El tipo de cocina preferido."}
                },
                "required": ["city", "date"]
            }
        }
    ],
    function_call={"name": "get_restaurantes"}
)

# Extrae los argumentos de la función
function_args = response["choices"][0]["message"]["function_call"]["arguments"]
city = function_args.get("city")
date = function_args.get("date")
price_range = function_args.get("price_range")
cocina = function_args.get("cocina")

# Llama a la API de Render
restaurant_data = call_get_restaurantes(city, date, price_range, cocina)
print(restaurant_data)
