import json
import os
import time
from functools import lru_cache

from app.services.db_service import (
    fetch_inventory_for_vector_index,
    get_inventory_overview,
    get_recent_messages,
    search_inventory_exact,
    search_inventory_fuzzy,
)
from app.services.logging_service import webhook_logger


GENERAL_INVENTORY_TERMS = {
    "available",
    "catalog",
    "collection",
    "have",
    "inventory",
    "items",
    "products",
    "sell",
    "show",
}


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _vector_search_enabled() -> bool:
    return _env_flag("ENABLE_VECTOR_SEARCH", "false")


def _inventory_text(item: dict) -> str:
    parts = [
        item.get("name") or "",
        item.get("brand") or "",
        item.get("category") or "",
        item.get("description") or "",
        " ".join(item.get("tags") or []),
        json.dumps(item.get("features") or {}),
        json.dumps(item.get("attributes") or {}),
    ]
    return " ".join(part for part in parts if part).strip()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_item(item: dict) -> dict:
    tags = item.get("tags") or []
    features = item.get("features") or {}
    attributes = item.get("attributes") or {}
    stock_quantity = int(item.get("stock_quantity") or 0)
    return {
        "id": item.get("id"),
        "sku": item.get("sku"),
        "name": item.get("name"),
        "brand": item.get("brand"),
        "image_url": item.get("image_url"),
        "image_urls": item.get("image_urls") or [],
        "category": item.get("category"),
        "description": item.get("description"),
        "price": item.get("price"),
        "currency": item.get("currency") or "INR",
        "stock_quantity": stock_quantity,
        "in_stock": bool(item.get("in_stock")) or stock_quantity > 0,
        "availability_status": item.get("availability_status") or "unknown",
        "tags": tags,
        "features": features,
        "margin": _safe_float(item.get("margin")),
        "attributes": attributes,
        "retrieval_source": item.get("retrieval_source", "overview"),
        "retrieval_score": _safe_float(item.get("retrieval_score")),
    }


def _format_inventory_items(items: list[dict]) -> str:
    inventory_lines = []
    for item in items:
        normalized_item = _normalize_item(item)
        inventory_lines.append(
            (
                f"- {normalized_item['name']} "
                f"(sku: {normalized_item['sku'] or 'n/a'}, brand: {normalized_item['brand'] or 'n/a'}, "
                f"category: {normalized_item['category'] or 'n/a'}, "
                f"price: {normalized_item['price'] if normalized_item['price'] is not None else 'n/a'} "
                f"{normalized_item['currency']}, stock: {normalized_item['stock_quantity']}, "
                f"status: {normalized_item['availability_status']}, source: {normalized_item['retrieval_source']})"
            ).strip()
        )
        if normalized_item["description"]:
            inventory_lines.append(f"  description: {normalized_item['description']}")
        if normalized_item["tags"]:
            inventory_lines.append(f"  tags: {', '.join(normalized_item['tags'])}")
        if normalized_item["features"]:
            inventory_lines.append(f"  features: {normalized_item['features']}")
        if normalized_item["attributes"]:
            inventory_lines.append(f"  attributes: {normalized_item['attributes']}")
    return "\n".join(inventory_lines)


@lru_cache(maxsize=1)
def _load_embedding_components():
    if not _vector_search_enabled():
        return {
            "faiss": None,
            "np": None,
            "model": None,
            "available": False,
            "error": "vector_search_disabled",
        }
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        model = SentenceTransformer(model_name)
        return {
            "faiss": faiss,
            "np": np,
            "model": model,
            "available": True,
            "error": None,
        }
    except Exception as exc:
        webhook_logger.warning("Vector retrieval unavailable: %s", exc)
        return {
            "faiss": None,
            "np": None,
            "model": None,
            "available": False,
            "error": str(exc),
        }


def _vector_signature(items: list[dict]) -> tuple:
    return tuple(
        (
            item.get("id"),
            item.get("name"),
            item.get("brand"),
            item.get("category"),
            item.get("description"),
            tuple(item.get("tags") or []),
            json.dumps(item.get("features") or {}, sort_keys=True),
            json.dumps(item.get("attributes") or {}, sort_keys=True),
        )
        for item in items
    )


@lru_cache(maxsize=2)
def _build_vector_index(signature: tuple):
    components = _load_embedding_components()
    if not components["available"]:
        return None

    inventory_items = fetch_inventory_for_vector_index()
    normalized_items = [_normalize_item(item) for item in inventory_items]
    if not normalized_items:
        return None

    model = components["model"]
    embeddings = model.encode(
        [_inventory_text(item) for item in normalized_items],
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")
    index = components["faiss"].IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return {"index": index, "items": normalized_items}


def _search_inventory_vector(query: str, limit: int = 5) -> list[dict]:
    if not _vector_search_enabled():
        return []

    inventory_items = fetch_inventory_for_vector_index()
    signature = _vector_signature(inventory_items)
    if not signature:
        return []

    bundle = _build_vector_index(signature)
    components = _load_embedding_components()
    if not bundle or not components["available"]:
        return []

    model = components["model"]
    query_embedding = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")
    scores, indexes = bundle["index"].search(query_embedding, limit)

    results = []
    for score, index in zip(scores[0], indexes[0]):
        if index < 0:
            continue
        item = dict(bundle["items"][int(index)])
        item["retrieval_source"] = "vector"
        item["retrieval_score"] = float(score)
        results.append(item)
    return results


def _rank_inventory_item(item: dict) -> float:
    retrieval_score = _safe_float(item.get("retrieval_score"))
    in_stock_score = 1.0 if item.get("in_stock") else 0.0
    margin_score = min(max(_safe_float(item.get("margin")) / 100.0, 0.0), 1.0)
    business_score = (retrieval_score * 0.6) + (in_stock_score * 0.2) + (margin_score * 0.2)
    item["business_score"] = round(business_score, 4)
    return business_score


def _merge_results(*result_sets: list[dict], limit: int = 5) -> list[dict]:
    merged: dict[int | str, dict] = {}
    for result_set in result_sets:
        for item in result_set:
            normalized = _normalize_item(item)
            key = normalized.get("id") or normalized.get("sku") or normalized.get("name")
            existing = merged.get(key)
            if not existing:
                normalized["retrieval_sources"] = [normalized["retrieval_source"]]
                merged[key] = normalized
                continue

            if normalized["retrieval_score"] > existing.get("retrieval_score", 0):
                existing["retrieval_score"] = normalized["retrieval_score"]
                existing["retrieval_source"] = normalized["retrieval_source"]
            existing["retrieval_sources"] = sorted(
                set(existing.get("retrieval_sources", [])) | {normalized["retrieval_source"]}
            )
            for field in ("description", "brand", "category", "features", "attributes"):
                if not existing.get(field) and normalized.get(field):
                    existing[field] = normalized[field]

    ranked_items = list(merged.values())
    ranked_items.sort(
        key=lambda item: (
            _rank_inventory_item(item),
            _safe_float(item.get("retrieval_score")),
            item.get("stock_quantity", 0),
        ),
        reverse=True,
    )
    return ranked_items[:limit]


def _structured_inventory_payload(items: list[dict]) -> list[dict]:
    payload = []
    for item in items:
        normalized = _normalize_item(item)
        payload.append(
            {
                "id": normalized["id"],
                "sku": normalized["sku"],
                "name": normalized["name"],
                "brand": normalized["brand"],
                "image_url": normalized["image_url"],
                "image_urls": normalized["image_urls"],
                "category": normalized["category"],
                "price": normalized["price"],
                "currency": normalized["currency"],
                "in_stock": normalized["in_stock"],
                "stock_quantity": normalized["stock_quantity"],
                "availability_status": normalized["availability_status"],
                "tags": normalized["tags"],
                "features": normalized["features"],
                "attributes": normalized["attributes"],
                "retrieval_sources": normalized.get("retrieval_sources")
                or [normalized["retrieval_source"]],
                "retrieval_score": normalized["retrieval_score"],
                "business_score": normalized.get("business_score"),
            }
        )
    return payload


def _build_debug_payload(
    *,
    query: str,
    exact_items: list[dict],
    fuzzy_items: list[dict],
    vector_items: list[dict],
    final_items: list[dict],
    latency_ms: int,
    used_overview: bool,
) -> dict:
    return {
        "query": query,
        "sql_ids": [item.get("id") for item in exact_items],
        "fuzzy_ids": [item.get("id") for item in fuzzy_items],
        "vector_ids": [item.get("id") for item in vector_items],
        "results": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "retrieval_sources": item.get("retrieval_sources")
                or [item.get("retrieval_source")],
                "retrieval_score": item.get("retrieval_score"),
                "business_score": item.get("business_score"),
            }
            for item in final_items
        ],
        "used_overview": used_overview,
        "latency_ms": latency_ms,
    }


def build_sales_context(*, user_id: int | None, user_message: str) -> dict:
    started_at = time.perf_counter()
    exact_items = search_inventory_exact(user_message)
    fuzzy_items = search_inventory_fuzzy(user_message)
    vector_items = _search_inventory_vector(user_message)
    inventory_items = _merge_results(exact_items, fuzzy_items, vector_items)
    recent_messages = get_recent_messages(user_id=user_id, limit=6)
    normalized_message = user_message.lower()
    used_overview = False

    context_parts: list[str] = []

    if inventory_items:
        context_parts.append("Relevant inventory:\n" + _format_inventory_items(inventory_items))
    elif any(term in normalized_message for term in GENERAL_INVENTORY_TERMS):
        overview_items = get_inventory_overview(limit=5)
        if overview_items:
            inventory_items = [_normalize_item(item) for item in overview_items]
            used_overview = True
            context_parts.append(
                "Inventory overview:\n" + _format_inventory_items(overview_items)
            )

    if recent_messages:
        history_lines = [
            f"- {message['role']}: {message['content']}" for message in recent_messages
        ]
        context_parts.append("Recent conversation:\n" + "\n".join(history_lines))

    structured_payload = _structured_inventory_payload(inventory_items)
    context_parts.append(
        "Structured product context JSON:\n"
        + json.dumps(structured_payload, ensure_ascii=True, indent=2)
    )
    context_parts.append(
        "Instruction: Only answer using the provided products. Do not invent any data."
    )

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    debug_payload = _build_debug_payload(
        query=user_message,
        exact_items=exact_items,
        fuzzy_items=fuzzy_items,
        vector_items=vector_items,
        final_items=inventory_items,
        latency_ms=latency_ms,
        used_overview=used_overview,
    )
    webhook_logger.info("RAG retrieval %s", json.dumps(debug_payload, ensure_ascii=True))

    return {
        "prompt_context": "\n\n".join(context_parts),
        "retrieved_items": inventory_items,
        "structured_products": structured_payload,
        "debug": debug_payload,
    }
