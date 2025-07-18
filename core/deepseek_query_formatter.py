import requests
from config import OLLAMA_ENDPOINT  # Add if not in config

def format_query(user_input):
    data = {
        "model": "deepseek-r1:32b",
        "messages": [{"role": "user", "content": f"Refine as precise search query: {user_input}"}],
        "stream": False
    }
    response = requests.post(OLLAMA_ENDPOINT, json=data, timeout=120)
    return response.json()['message']['content'].strip()