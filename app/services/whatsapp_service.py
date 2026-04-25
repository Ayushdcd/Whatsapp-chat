import os

import requests

from app.services.logging_service import webhook_logger

WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v24.0")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")


def _whatsapp_messages_url() -> str | None:
    if not WHATSAPP_PHONE_NUMBER_ID:
        return None
    return (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )


def _whatsapp_headers() -> dict:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def send_whatsapp_text(to_number: str, message: str) -> bool:
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        print("WhatsApp Error: phone number ID or access token is not set.")
        webhook_logger.error("WhatsApp send failed: missing phone ID or access token.")
        return False

    url = _whatsapp_messages_url()
    headers = _whatsapp_headers()
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
        webhook_logger.error("WhatsApp network error: %s", exc)
        return False
    except requests.exceptions.Timeout:
        print("WhatsApp Timeout Error: request timed out.")
        webhook_logger.error("WhatsApp timeout error.")
        return False
    except requests.RequestException as exc:
        print("WhatsApp Error:", exc)
        webhook_logger.error("WhatsApp request error: %s", exc)
        return False

    if response.status_code not in (200, 201):
        print("WhatsApp API Error:", response.status_code, response.text)
        webhook_logger.error(
            "WhatsApp API error: status=%s response=%s",
            response.status_code,
            response.text,
        )
        return False

    webhook_logger.info("WhatsApp message sent to=%s", to_number)
    return True


def send_whatsapp_image(to_number: str, image_url: str, caption: str = "") -> bool:
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        print("WhatsApp Error: phone number ID or access token is not set.")
        webhook_logger.error("WhatsApp image send failed: missing phone ID or access token.")
        return False

    url = _whatsapp_messages_url()
    headers = _whatsapp_headers()
    image_payload = {
        "link": image_url,
    }
    if caption:
        image_payload["caption"] = caption[:1024]

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": image_payload,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        print("WhatsApp Network Error:", exc)
        webhook_logger.error("WhatsApp image network error: %s", exc)
        return False
    except requests.exceptions.Timeout:
        print("WhatsApp Timeout Error: request timed out.")
        webhook_logger.error("WhatsApp image timeout error.")
        return False
    except requests.RequestException as exc:
        print("WhatsApp Error:", exc)
        webhook_logger.error("WhatsApp image request error: %s", exc)
        return False

    if response.status_code not in (200, 201):
        print("WhatsApp API Error:", response.status_code, response.text)
        webhook_logger.error(
            "WhatsApp image API error: status=%s response=%s",
            response.status_code,
            response.text,
        )
        return False

    webhook_logger.info("WhatsApp image sent to=%s image_url=%s", to_number, image_url)
    return True
