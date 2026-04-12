import os
import requests

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def generate_ai_reply(user_message: str, context: str = ""):
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        print("Groq Error: GROQ_API_KEY is not set.")
        return "Sorry, AI is not configured yet."

    url = "https://api.groq.com/openai/v1/chat/completions"

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful sales assistant. Be short and conversational."
            },
            {
                "role": "user",
                "content": context + "\nUser: " + user_message
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        print("Groq Network Error:", exc)
        return "Sorry, the AI service is temporarily unreachable."
    except requests.exceptions.Timeout:
        print("Groq Timeout Error: request timed out.")
        return "Sorry, the AI service took too long to respond."
    except requests.RequestException as exc:
        print("Groq Error:", exc)
        return "Sorry, something went wrong."

    if response.status_code != 200:
        print("Groq Error:", response.text)
        return "Sorry, something went wrong."

    data = response.json()
    return data['choices'][0]['message']['content']
