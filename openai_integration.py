import openai
import requests

# Define la función que hará la llamada a tu API en Render
def call_get_restaurantes(city):
    # URL de tu API desplegada en Render
    response = requests.get(f"https://your-api-onrender.com/restaurantes/{city}")
    return response.json()

# Simulación de una solicitud de usuario y procesamiento por OpenAI
user_input = "Estoy buscando un restaurante en Madrid."

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
                    "city": {"type": "string", "description": "La ciudad donde el usuario quiere encontrar restaurantes."}
                },
                "required": ["city"]
            }
        }
    ],
    function_call={"name": "get_restaurantes"}
)

# Extrae la ciudad del argumento y llama a tu API
function_args = response["choices"][0]["message"]["function_call"]["arguments"]
city = function_args["city"]

# Llama a la API de Render
restaurant_data = call_get_restaurantes(city)
print(restaurant_data)
