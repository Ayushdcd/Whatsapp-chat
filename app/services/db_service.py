import json
import os
import re
from contextlib import contextmanager
from typing import Optional

from app.services.logging_service import webhook_logger

try:
    from psycopg import connect
except ImportError:  # pragma: no cover
    connect = None


def _build_database_url() -> Optional[str]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    postgres_db = os.getenv("POSTGRES_DB")
    postgres_user = os.getenv("POSTGRES_USER")
    postgres_password = os.getenv("POSTGRES_PASSWORD")
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")

    if not all([postgres_db, postgres_user, postgres_password]):
        return None

    return (
        f"postgresql://{postgres_user}:{postgres_password}"
        f"@{postgres_host}:{postgres_port}/{postgres_db}"
    )


def is_database_enabled() -> bool:
    return bool(_build_database_url())


@contextmanager
def _get_connection():
    database_url = _build_database_url()

    if connect is None:
        raise RuntimeError(
            "Postgres support is not installed. Run `pip install -r requirements.txt`."
        )

    if not database_url:
        raise RuntimeError(
            "Database is not configured. Set DATABASE_URL or POSTGRES_* variables."
        )

    with connect(database_url) as connection:
        yield connection


def init_db():
    if not is_database_enabled():
        webhook_logger.info("Database init skipped: Postgres config not set.")
        return

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                except Exception:
                    webhook_logger.exception("pg_trgm extension enable failed.")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        external_id VARCHAR(100) NOT NULL,
                        source VARCHAR(20) NOT NULL CHECK (source IN ('whatsapp', 'web')),
                        name VARCHAR(100),
                        phone VARCHAR(20),
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        preferences JSONB,
                        metadata JSONB,
                        UNIQUE (external_id, source)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                        content TEXT NOT NULL,
                        message_type VARCHAR(20) DEFAULT 'text',
                        raw_payload JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS inventory_items (
                        id SERIAL PRIMARY KEY,
                        sku VARCHAR(100) UNIQUE,
                        name VARCHAR(255) NOT NULL,
                        brand VARCHAR(100),
                        image_url TEXT,
                        image_urls JSONB,
                        category VARCHAR(100),
                        description TEXT,
                        price NUMERIC(10, 2),
                        currency VARCHAR(10) DEFAULT 'INR',
                        stock_quantity INT DEFAULT 0,
                        in_stock BOOLEAN DEFAULT TRUE,
                        availability_status VARCHAR(30) DEFAULT 'in_stock',
                        tags TEXT[],
                        features JSONB,
                        margin NUMERIC(10, 2) DEFAULT 0,
                        attributes JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS preferences JSONB
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS brand VARCHAR(100)
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS image_url TEXT
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS image_urls JSONB
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS in_stock BOOLEAN DEFAULT TRUE
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS tags TEXT[]
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS features JSONB
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE inventory_items
                    ADD COLUMN IF NOT EXISTS margin NUMERIC(10, 2) DEFAULT 0
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_users_external_source
                    ON users (external_id, source)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_messages_user_created
                    ON messages (user_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_inventory_name_category
                    ON inventory_items (name, category)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_inventory_name_trgm
                    ON inventory_items
                    USING gin (name gin_trgm_ops)
                    """
                )
            connection.commit()
        webhook_logger.info("Database initialized successfully.")
    except Exception:
        webhook_logger.exception("Database init failed.")


def upsert_user(
    *,
    external_id: str,
    source: str,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    preferences: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Optional[int]:
    if not is_database_enabled():
        return None

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        external_id,
                        source,
                        name,
                        phone,
                        preferences,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (external_id, source)
                    DO UPDATE SET
                        name = COALESCE(EXCLUDED.name, users.name),
                        phone = COALESCE(EXCLUDED.phone, users.phone),
                        preferences = COALESCE(EXCLUDED.preferences, users.preferences),
                        metadata = COALESCE(EXCLUDED.metadata, users.metadata),
                        last_seen = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        external_id,
                        source,
                        name,
                        phone,
                        json.dumps(preferences) if preferences is not None else None,
                        json.dumps(metadata) if metadata is not None else None,
                    ),
                )
                user_id = cursor.fetchone()[0]
            connection.commit()
            return user_id
    except Exception:
        webhook_logger.exception("Failed to upsert user. external_id=%s", external_id)
        return None


def create_message(
    *,
    user_id: Optional[int],
    role: str,
    content: str,
    message_type: str = "text",
    raw_payload: Optional[dict] = None,
) -> Optional[int]:
    if not user_id or not is_database_enabled():
        return None

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO messages (
                        user_id,
                        role,
                        content,
                        message_type,
                        raw_payload
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        user_id,
                        role,
                        content,
                        message_type,
                        json.dumps(raw_payload) if raw_payload is not None else None,
                    ),
                )
                message_id = cursor.fetchone()[0]
            connection.commit()
            return message_id
    except Exception:
        webhook_logger.exception("Failed to create message. user_id=%s role=%s", user_id, role)
        return None


def _row_to_inventory_item(row, *, extra: Optional[dict] = None) -> dict:
    item = {
        "id": row[0],
        "sku": row[1],
        "name": row[2],
        "brand": row[3],
        "image_url": row[4],
        "image_urls": row[5] or [],
        "category": row[6],
        "description": row[7],
        "price": float(row[8]) if row[8] is not None else None,
        "currency": row[9],
        "stock_quantity": row[10],
        "in_stock": bool(row[11]) if row[11] is not None else False,
        "availability_status": row[12],
        "tags": row[13] or [],
        "features": row[14],
        "margin": float(row[15]) if row[15] is not None else 0.0,
        "attributes": row[16],
    }
    if extra:
        item.update(extra)
    return item


def _inventory_select_columns() -> str:
    return """
        id,
        sku,
        name,
        brand,
        image_url,
        image_urls,
        category,
        description,
        price,
        currency,
        stock_quantity,
        in_stock,
        availability_status,
        tags,
        features,
        margin,
        attributes
    """


def _tokenize_inventory_query(query: str) -> list[str]:
    stop_words = {
        "a",
        "an",
        "are",
        "available",
        "any",
        "do",
        "for",
        "have",
        "i",
        "in",
        "is",
        "me",
        "of",
        "on",
        "show",
        "tell",
        "the",
        "what",
        "you",
    }
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query.lower())
        if len(token) > 1 and token not in stop_words
    ]


def get_recent_messages(*, user_id: Optional[int], limit: int = 6) -> list[dict]:
    if not user_id or not is_database_enabled():
        return []

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT role, content, created_at
                    FROM messages
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                rows = cursor.fetchall()
        return [
            {"role": row[0], "content": row[1], "created_at": row[2].isoformat()}
            for row in reversed(rows)
        ]
    except Exception:
        webhook_logger.exception("Failed to fetch recent messages. user_id=%s", user_id)
        return []


def search_inventory_exact(query: str, limit: int = 5) -> list[dict]:
    if not query or not is_database_enabled():
        return []

    tokens = _tokenize_inventory_query(query)
    search_terms = tokens or [query.strip().lower()]
    like_terms = [f"%{term}%" for term in search_terms]

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                where_clauses = []
                order_score_parts = []
                params: list[object] = []

                for like_term in like_terms:
                    where_clauses.append(
                        """
                        (
                            name ILIKE %s
                            OR brand ILIKE %s
                            OR category ILIKE %s
                            OR description ILIKE %s
                            OR CAST(COALESCE(tags, ARRAY[]::TEXT[]) AS TEXT) ILIKE %s
                            OR CAST(COALESCE(features, '{}'::jsonb) AS TEXT) ILIKE %s
                            OR CAST(COALESCE(attributes, '{}'::jsonb) AS TEXT) ILIKE %s
                        )
                        """
                    )
                    params.extend(
                        [
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                        ]
                    )
                    order_score_parts.append(
                        """
                        CASE
                            WHEN name ILIKE %s THEN 4
                            WHEN brand ILIKE %s THEN 3.5
                            WHEN category ILIKE %s THEN 3
                            WHEN description ILIKE %s THEN 2
                            WHEN CAST(COALESCE(tags, ARRAY[]::TEXT[]) AS TEXT) ILIKE %s THEN 1.5
                            WHEN CAST(COALESCE(features, '{}'::jsonb) AS TEXT) ILIKE %s THEN 1.25
                            WHEN CAST(COALESCE(attributes, '{}'::jsonb) AS TEXT) ILIKE %s THEN 1
                            ELSE 0
                        END
                        """
                    )
                    params.extend(
                        [
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                            like_term,
                        ]
                    )

                query_sql = f"""
                    SELECT
                        {_inventory_select_columns()},
                        ({' + '.join(order_score_parts)}) AS retrieval_score
                    FROM inventory_items
                    WHERE {" OR ".join(where_clauses)}
                    ORDER BY retrieval_score DESC, updated_at DESC
                    LIMIT %s
                """
                params.append(limit)
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()
        return [
            _row_to_inventory_item(
                row[:-1],
                extra={
                    "retrieval_source": "sql",
                    "retrieval_score": float(row[-1]) if row[-1] is not None else 0.0,
                },
            )
            for row in rows
        ]
    except Exception:
        webhook_logger.exception("Failed to run exact inventory search.")
        return []


def search_inventory_fuzzy(query: str, limit: int = 5) -> list[dict]:
    if not query or not is_database_enabled():
        return []

    normalized_query = query.strip().lower()
    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {_inventory_select_columns()},
                        GREATEST(
                            similarity(LOWER(name), %s),
                            similarity(LOWER(COALESCE(brand, '')), %s),
                            similarity(LOWER(COALESCE(category, '')), %s)
                        ) AS retrieval_score
                    FROM inventory_items
                    WHERE
                        LOWER(name) %% %s
                        OR LOWER(COALESCE(brand, '')) %% %s
                        OR LOWER(COALESCE(category, '')) %% %s
                    ORDER BY retrieval_score DESC, updated_at DESC
                    LIMIT %s
                    """,
                    (
                        normalized_query,
                        normalized_query,
                        normalized_query,
                        normalized_query,
                        normalized_query,
                        normalized_query,
                        limit,
                    ),
                )
                rows = cursor.fetchall()
        return [
            _row_to_inventory_item(
                row[:-1],
                extra={
                    "retrieval_source": "fuzzy",
                    "retrieval_score": float(row[-1]) if row[-1] is not None else 0.0,
                },
            )
            for row in rows
        ]
    except Exception:
        webhook_logger.exception("Failed to run fuzzy inventory search.")
        return []


def search_inventory(query: str, limit: int = 5) -> list[dict]:
    return search_inventory_exact(query, limit=limit)


def get_inventory_overview(limit: int = 5) -> list[dict]:
    if not is_database_enabled():
        return []

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {_inventory_select_columns()}
                    FROM inventory_items
                    ORDER BY
                        CASE
                            WHEN availability_status = 'in_stock' THEN 1
                            WHEN availability_status = 'low_stock' THEN 2
                            ELSE 3
                        END,
                        updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [_row_to_inventory_item(row) for row in rows]
    except Exception:
        webhook_logger.exception("Failed to fetch inventory overview.")
        return []


def fetch_inventory_for_vector_index() -> list[dict]:
    if not is_database_enabled():
        return []

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_inventory_select_columns()}
                    FROM inventory_items
                    ORDER BY updated_at DESC, id DESC
                    """
                )
                rows = cursor.fetchall()
        return [_row_to_inventory_item(row) for row in rows]
    except Exception:
        webhook_logger.exception("Failed to fetch inventory for vector index.")
        return []


def upsert_inventory_item(item: dict) -> Optional[int]:
    if not is_database_enabled():
        return None

    try:
        with _get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO inventory_items (
                        sku,
                        name,
                        brand,
                        image_url,
                        image_urls,
                        category,
                        description,
                        price,
                        currency,
                        stock_quantity,
                        in_stock,
                        availability_status,
                        tags,
                        features,
                        margin,
                        attributes,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s, %s::jsonb, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (sku)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        brand = EXCLUDED.brand,
                        image_url = EXCLUDED.image_url,
                        image_urls = EXCLUDED.image_urls,
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        currency = EXCLUDED.currency,
                        stock_quantity = EXCLUDED.stock_quantity,
                        in_stock = EXCLUDED.in_stock,
                        availability_status = EXCLUDED.availability_status,
                        tags = EXCLUDED.tags,
                        features = EXCLUDED.features,
                        margin = EXCLUDED.margin,
                        attributes = EXCLUDED.attributes,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        item.get("sku"),
                        item.get("name"),
                        item.get("brand"),
                        item.get("image_url"),
                        json.dumps(item.get("image_urls") or []),
                        item.get("category"),
                        item.get("description"),
                        item.get("price"),
                        item.get("currency") or "INR",
                        item.get("stock_quantity", 0),
                        item.get("in_stock", True),
                        item.get("availability_status") or "in_stock",
                        item.get("tags") or [],
                        json.dumps(item.get("features") or {}),
                        item.get("margin", 0),
                        json.dumps(item.get("attributes") or {}),
                    ),
                )
                item_id = cursor.fetchone()[0]
            connection.commit()
            return item_id
    except Exception:
        webhook_logger.exception("Failed to upsert inventory item. sku=%s", item.get("sku"))
        return None
