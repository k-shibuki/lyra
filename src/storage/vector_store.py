"""
Vector store for semantic similarity search.

Provides embedding persistence and vector search functionality.
"""

import struct
from typing import Any

from src.ml_client import get_ml_client
from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding vector to binary blob.

    Args:
        embedding: List of float values.

    Returns:
        Binary blob (4 bytes per float, little-endian).
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)


def deserialize_embedding(blob: bytes) -> list[float]:
    """Deserialize binary blob to embedding vector.

    Args:
        blob: Binary blob.

    Returns:
        List of float values.
    """
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity (0.0-1.0).
    """
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        x = a[i]
        y = b[i]
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    import math

    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0.0:
        return 0.0
    return float(dot / denom)


async def vector_search(
    query: str,
    target_type: str,  # 'fragment' | 'claim'
    task_id: str | None = None,
    top_k: int = 10,
    min_similarity: float = 0.5,
    model_id: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic similarity search over fragments/claims using embeddings.

    Args:
        query: Natural language query.
        target_type: Table to search ('fragment' or 'claim').
        task_id: Optional task ID to scope search.
        top_k: Number of results to return.
        min_similarity: Minimum cosine similarity threshold.

    Returns:
        List of result dicts with 'id', 'similarity', 'text_preview'.
    """
    if model_id is None:
        model_id = get_settings().embedding.model_name

    # 1. Compute query embedding
    ml_client = get_ml_client()
    query_embeddings = await ml_client.embed([query])
    query_vec = query_embeddings[0]

    # 2. Get target embeddings from DB
    db = await get_database()

    sql = """
        SELECT e.target_id, e.embedding_blob, e.dimension,
               CASE
                 WHEN e.target_type = 'fragment' THEN f.text_content
                 WHEN e.target_type = 'claim' THEN c.claim_text
               END as text_content
        FROM embeddings e
        LEFT JOIN fragments f ON e.target_type = 'fragment' AND e.target_id = f.id
        LEFT JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
        WHERE e.target_type = ?
          AND e.model_id = ?
    """
    params: list[Any] = [target_type, model_id]

    # 3. Apply task_id filter if provided
    if task_id and target_type == "claim":
        sql += " AND c.task_id = ?"
        params.append(task_id)
    elif task_id and target_type == "fragment":
        # Fragment doesn't have task_id, need to join via edges
        sql = f"""
        WITH task_fragments AS (
          SELECT DISTINCT e2.source_id AS fragment_id
          FROM edges e2
          JOIN claims c2
            ON e2.target_type = 'claim'
           AND e2.target_id = c2.id
          WHERE e2.source_type = 'fragment'
            AND c2.task_id = ?
        )
        {sql}
        AND e.target_id IN (SELECT fragment_id FROM task_fragments)
        """
        params = [task_id, *params]

    rows = await db.fetch_all(sql, params)

    # 4. Calculate cosine similarity
    results = []
    for row in rows:
        emb_blob = row["embedding_blob"]
        if emb_blob is None:
            continue

        emb = deserialize_embedding(emb_blob)
        if row.get("dimension") and isinstance(row.get("dimension"), int):
            if row["dimension"] != len(emb) or row["dimension"] != len(query_vec):
                continue
        sim = cosine_similarity(query_vec, emb)

        if sim >= min_similarity:
            text_content = row.get("text_content") or ""
            results.append(
                {
                    "id": row["target_id"],
                    "similarity": sim,
                    "text_preview": text_content[:200] if text_content else "",
                }
            )

    # 5. Sort and return top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


async def persist_embedding(
    target_type: str,
    target_id: str,
    embedding: list[float],
    model_id: str | None = None,
) -> None:
    """Persist embedding to database.

    Args:
        target_type: 'fragment' | 'claim'
        target_id: Target entity ID.
        embedding: Embedding vector.
        model_id: Model identifier (default: from settings.embedding.model_name).
    """
    if model_id is None:
        model_id = get_settings().embedding.model_name
    if target_type not in {"fragment", "claim"}:
        raise ValueError("target_type must be 'fragment' or 'claim'")
    if not embedding:
        raise ValueError("embedding must be non-empty")

    db = await get_database()
    embedding_id = f"{target_type}:{target_id}:{model_id}"
    embedding_blob = serialize_embedding(embedding)
    dimension = len(embedding)

    await db.execute(
        """
        INSERT OR REPLACE INTO embeddings
        (id, target_type, target_id, model_id, embedding_blob, dimension)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (embedding_id, target_type, target_id, model_id, embedding_blob, dimension),
    )

    logger.debug(
        "Embedding persisted",
        target_type=target_type,
        target_id=target_id,
        model_id=model_id,
        dimension=dimension,
    )
