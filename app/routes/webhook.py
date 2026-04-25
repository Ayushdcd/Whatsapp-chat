import os
import time
import csv
import json
from io import StringIO
from pathlib import Path

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.services.db_service import create_message, upsert_inventory_item, upsert_user
from app.services.groq_service import generate_ai_reply
from app.services.logging_service import WEBHOOK_LOG_FILE, webhook_logger
from app.services.rag_service import build_sales_context
from app.services.whatsapp_service import send_whatsapp_image, send_whatsapp_text

router = APIRouter()
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "Ayush_AI_Chat")
WEBHOOK_LOG_TOKEN = os.getenv("WEBHOOK_LOG_TOKEN")
INVENTORY_ADMIN_TOKEN = os.getenv("INVENTORY_ADMIN_TOKEN", WEBHOOK_LOG_TOKEN)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _extract_message_data(data: dict):
    try:
        return data["entry"][0]["changes"][0]["value"]["messages"][0], "whatsapp"
    except (KeyError, IndexError, TypeError):
        pass

    try:
        return data["messages"][0], "test"
    except (KeyError, IndexError, TypeError):
        return None, None


def _resolve_public_base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def _build_inventory_image_url(request: Request, item: dict | None) -> str | None:
    if not item:
        return None

    raw_image_url = item.get("image_url")
    if not raw_image_url and item.get("image_urls"):
        raw_image_url = item["image_urls"][0]
    if not raw_image_url:
        return None

    normalized = str(raw_image_url).replace("\\", "/").strip()
    if normalized.startswith(("http://", "https://")):
        return normalized

    if normalized.startswith("app/images/"):
        relative_path = normalized.removeprefix("app/images/")
    elif normalized.startswith("/images/"):
        relative_path = normalized.removeprefix("/images/")
    else:
        relative_path = Path(normalized).name

    if not relative_path:
        return None

    return f"{_resolve_public_base_url(request)}/images/{relative_path}"


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
    started_at = time.perf_counter()
    try:
        data = await request.json()
    except Exception:
        webhook_logger.exception("Webhook POST failed: invalid JSON body.")
        return {"status": "failed"}

    webhook_logger.info("Webhook POST received.")

    message_data, payload_format = _extract_message_data(data)
    if not message_data:
        webhook_logger.info(
            "Webhook ignored: no message payload. top_level_keys=%s",
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )
        return {"status": "ignored"}

    message_type = message_data.get("type", "text" if "text" in message_data else None)
    if message_type != "text":
        webhook_logger.info(
            "Webhook ignored: unsupported message type=%s",
            message_type,
        )
        return {"status": "ignored"}

    message = message_data.get("text", {}).get("body", "").strip()
    mobile = message_data.get("from")
    whatsapp_message_id = message_data.get("id")

    if not message or not mobile:
        webhook_logger.info(
            "Webhook ignored: missing message or mobile. has_message=%s has_mobile=%s",
            bool(message),
            bool(mobile),
        )
        return {"status": "ignored"}

    print(f"User ({mobile}): {message}")
    webhook_logger.info(
        "Incoming message format=%s from=%s text=%s",
        payload_format,
        mobile,
        message,
    )

    user_id = upsert_user(
        external_id=mobile,
        source="whatsapp",
        phone=mobile,
        metadata={"last_payload_format": payload_format},
    )
    create_message(
        user_id=user_id,
        role="user",
        content=message,
        message_type=message_type,
        raw_payload={
            "payload_format": payload_format,
            "whatsapp_message_id": whatsapp_message_id,
            "webhook_payload": data,
        },
    )

    try:
        rag_result = build_sales_context(user_id=user_id, user_message=message)
        reply = generate_ai_reply(message, context=rag_result["prompt_context"])
        primary_item = rag_result["retrieved_items"][0] if rag_result["retrieved_items"] else None
        image_url = _build_inventory_image_url(request, primary_item)
        if image_url:
            sent = send_whatsapp_image(mobile, image_url=image_url, caption=reply)
            if not sent:
                webhook_logger.warning(
                    "WhatsApp image send failed, falling back to text. to=%s image_url=%s",
                    mobile,
                    image_url,
                )
                sent = send_whatsapp_text(mobile, reply)
        else:
            sent = send_whatsapp_text(mobile, reply)
    except Exception:
        create_message(
            user_id=user_id,
            role="assistant",
            content="Reply generation failed.",
            raw_payload={
                "payload_format": payload_format,
                "send_status": "failed",
                "error_message": "reply_generation_or_send_exception",
            },
        )
        webhook_logger.exception("Webhook POST failed while generating or sending reply.")
        return {"status": "failed"}

    print(f"Bot: {reply}")
    pipeline_latency_ms = int((time.perf_counter() - started_at) * 1000)
    webhook_logger.info(
        "RAG pipeline %s",
        json.dumps(
            {
                "query": message,
                "retrieved_items": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "score": item.get("business_score"),
                        "image_url": item.get("image_url"),
                        "sources": item.get("retrieval_sources")
                        or [item.get("retrieval_source")],
                    }
                    for item in rag_result["retrieved_items"]
                ],
                "response": reply,
                "latency_ms": pipeline_latency_ms,
            },
            ensure_ascii=True,
        ),
    )
    webhook_logger.info("Reply generated for=%s sent=%s", mobile, sent)
    create_message(
        user_id=user_id,
        role="assistant",
        content=reply,
        raw_payload={
            "rag_context_used": bool(rag_result["retrieved_items"]),
            "rag_debug": rag_result["debug"],
            "image_url": _build_inventory_image_url(
                request,
                rag_result["retrieved_items"][0] if rag_result["retrieved_items"] else None,
            ),
            "payload_format": payload_format,
            "send_status": "sent" if sent else "failed",
            "error_message": None if sent else "whatsapp_send_failed",
        },
    )
    if not sent:
        return {"status": "failed", "reason": "whatsapp_send_failed"}

    return {"status": "sent"}


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


def _parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "in_stock"}


def _parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_float(value: str | None):
    try:
        stripped = str(value).strip()
        return float(stripped) if stripped else None
    except (TypeError, ValueError):
        return None


@router.post("/admin/upload-inventory")
async def upload_inventory_csv(request: Request):
    token = request.query_params.get("token")
    if not INVENTORY_ADMIN_TOKEN or token != INVENTORY_ADMIN_TOKEN:
        webhook_logger.warning("Inventory upload access denied.")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    raw_bytes = await request.body()
    decoded = raw_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(decoded)))
    uploaded = 0
    upload_name = request.headers.get("x-filename", "inventory.csv")

    for row in rows:
        tags = [tag.strip() for tag in (row.get("tags") or "").split(",") if tag.strip()]
        features = {
            "raw": [feature.strip() for feature in (row.get("features") or "").split(",") if feature.strip()]
        }
        image_urls = [
            image.strip() for image in (row.get("image_urls") or "").split(",") if image.strip()
        ]
        attributes = {
            "source_file": upload_name,
        }
        sku = (row.get("sku") or "").strip() or None
        name = (row.get("name") or "").strip()
        if not name:
            continue

        stock_quantity = _parse_int(row.get("stock_quantity"), default=0)
        price_value = _parse_float(row.get("price"))
        margin_value = _parse_float(row.get("margin"))
        item_id = upsert_inventory_item(
            {
                "sku": sku or f"csv-{uploaded + 1}-{name.lower().replace(' ', '-')}",
                "name": name,
                "brand": (row.get("brand") or "").strip() or None,
                "image_url": (row.get("image_url") or "").strip() or (image_urls[0] if image_urls else None),
                "image_urls": image_urls,
                "category": (row.get("category") or "").strip() or None,
                "description": (row.get("description") or "").strip() or None,
                "price": price_value,
                "currency": (row.get("currency") or "INR").strip() or "INR",
                "stock_quantity": stock_quantity,
                "in_stock": _parse_bool(row.get("in_stock")) or stock_quantity > 0,
                "availability_status": (row.get("availability_status") or "in_stock").strip(),
                "tags": tags,
                "features": features,
                "margin": margin_value or 0,
                "attributes": attributes,
            }
        )
        if item_id:
            uploaded += 1

    webhook_logger.info(
        "Inventory upload completed filename=%s rows=%s uploaded=%s",
        upload_name,
        len(rows),
        uploaded,
    )
    return {
        "status": "ok",
        "filename": upload_name,
        "rows_received": len(rows),
        "rows_upserted": uploaded,
    }
