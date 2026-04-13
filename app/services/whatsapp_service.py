import os

import requests

WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v24.0")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")


def send_whatsapp_text(to_number: str, message: str) -> bool:
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        print("WhatsApp Error: phone number ID or access token is not set.")
        return False

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        print("WhatsApp Network Error:", exc)
        return False
    except requests.exceptions.Timeout:
        print("WhatsApp Timeout Error: request timed out.")
        return False
    except requests.RequestException as exc:
        print("WhatsApp Error:", exc)
        return False

    if response.status_code not in (200, 201):
        print("WhatsApp API Error:", response.status_code, response.text)
        return False

    return True
