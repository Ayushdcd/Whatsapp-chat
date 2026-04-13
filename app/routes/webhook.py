import os

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.services.groq_service import generate_ai_reply
from app.services.whatsapp_service import send_whatsapp_text

router = APIRouter()
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "Ayush_AI_Chat")


@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(content=challenge)

    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        value = data["entry"][0]["changes"][0]["value"]
        message_data = value["messages"][0]
    except (KeyError, IndexError):
        return {"status": "ignored"}

    if message_data.get("type") != "text":
        return {"status": "ignored"}

    message = message_data.get("text", {}).get("body", "").strip()
    mobile = message_data.get("from")

    if not message or not mobile:
        return {"status": "ignored"}

    print(f"User ({mobile}): {message}")

    reply = generate_ai_reply(message)
    sent = send_whatsapp_text(mobile, reply)

    print(f"Bot: {reply}")

    return {"status": "sent" if sent else "failed"}
