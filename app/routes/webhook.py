import os

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.services.groq_service import generate_ai_reply
from app.services.logging_service import WEBHOOK_LOG_FILE, webhook_logger
from app.services.whatsapp_service import send_whatsapp_text

router = APIRouter()
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "Ayush_AI_Chat")
WEBHOOK_LOG_TOKEN = os.getenv("WEBHOOK_LOG_TOKEN")


@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        webhook_logger.info("Webhook verified successfully.")
        return PlainTextResponse(content=challenge)

    webhook_logger.warning(
        "Webhook verification failed. mode=%s token_match=%s has_challenge=%s",
        mode,
        token == VERIFY_TOKEN,
        bool(challenge),
    )
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook")
async def receive_message(request: Request):
    try:
        data = await request.json()
    except Exception:
        webhook_logger.exception("Webhook POST failed: invalid JSON body.")
        return {"status": "failed"}

    webhook_logger.info("Webhook POST received.")

    try:
        value = data["entry"][0]["changes"][0]["value"]
        message_data = value["messages"][0]
    except (KeyError, IndexError) as exc:
        webhook_logger.info("Webhook ignored: no message payload. error=%s", exc)
        return {"status": "ignored"}

    if message_data.get("type") != "text":
        webhook_logger.info(
            "Webhook ignored: unsupported message type=%s",
            message_data.get("type"),
        )
        return {"status": "ignored"}

    message = message_data.get("text", {}).get("body", "").strip()
    mobile = message_data.get("from")

    if not message or not mobile:
        webhook_logger.info(
            "Webhook ignored: missing message or mobile. has_message=%s has_mobile=%s",
            bool(message),
            bool(mobile),
        )
        return {"status": "ignored"}

    print(f"User ({mobile}): {message}")
    webhook_logger.info("Incoming message from=%s text=%s", mobile, message)

    try:
        reply = generate_ai_reply(message)
        sent = send_whatsapp_text(mobile, reply)
    except Exception:
        webhook_logger.exception("Webhook POST failed while generating or sending reply.")
        return {"status": "failed"}

    print(f"Bot: {reply}")
    webhook_logger.info("Reply generated for=%s sent=%s", mobile, sent)

    return {"status": "sent" if sent else "failed"}


@router.get("/admin/webhook-log")
async def view_webhook_log(request: Request):
    token = request.query_params.get("token")
    if not WEBHOOK_LOG_TOKEN or token != WEBHOOK_LOG_TOKEN:
        webhook_logger.warning("Webhook log access denied.")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        content = WEBHOOK_LOG_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""

    return PlainTextResponse(content=content)
