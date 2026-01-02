"""Vector search handler for MCP tools.

Handles vector_search operation (semantic similarity search).
"""

from typing import Any

from src.mcp.errors import InvalidParamsError
from src.storage.vector_store import vector_search
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_vector_search(args: dict[str, Any]) -> dict[str, Any]:
    """Handle vector_search tool call.

    Performs semantic similarity search over fragments/claims using embeddings.

    Args:
        args: Tool arguments with 'query', 'target', optional 'task_id', 'top_k', 'min_similarity'.

    Returns:
        Search result dict with 'ok', 'results', 'total_searched', etc.
    """
    query = args.get("query")
    target = args.get("target", "claims")
    task_id = args.get("task_id")
    top_k = args.get("top_k", 10)
    min_similarity = args.get("min_similarity", 0.5)

    if not query:
        raise InvalidParamsError(
            "query is required",
            param_name="query",
            expected="non-empty string",
        )

    if target not in ("fragments", "claims"):
        raise InvalidParamsError(
            "target must be 'fragments' or 'claims'",
            param_name="target",
            expected="'fragments' or 'claims'",
        )

    if top_k < 1 or top_k > 50:
        raise InvalidParamsError(
            "top_k must be between 1 and 50",
            param_name="top_k",
            expected="integer 1-50",
        )

    if min_similarity < 0.0 or min_similarity > 1.0:
        raise InvalidParamsError(
            "min_similarity must be between 0.0 and 1.0",
            param_name="min_similarity",
            expected="float 0.0-1.0",
        )

    # Map target to target_type
    target_type_map = {"fragments": "fragment", "claims": "claim"}
    target_type = target_type_map.get(target, target)

    with LogContext(task_id=task_id) if task_id else LogContext():
        try:
            results = await vector_search(
                query=query,
                target_type=target_type,
                task_id=task_id,
                top_k=top_k,
                min_similarity=min_similarity,
            )

            # Count total embeddings searched (approximate)
            from src.storage.database import get_database
            from src.utils.config import get_settings

            db = await get_database()
            model_id = get_settings().embedding.model_name

            if task_id and target_type == "claim":
                count_result = await db.fetch_one(
                    """
                    SELECT COUNT(*) as cnt
                    FROM embeddings e
                    JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
                    WHERE e.target_type = 'claim'
                      AND e.model_id = ?
                      AND c.task_id = ?
                    """,
                    (model_id, task_id),
                )
            elif task_id and target_type == "fragment":
                count_result = await db.fetch_one(
                    """
                    WITH task_fragments AS (
                      SELECT DISTINCT e2.source_id AS fragment_id
                      FROM edges e2
                      JOIN claims c2
                        ON e2.target_type = 'claim'
                       AND e2.target_id = c2.id
                      WHERE e2.source_type = 'fragment'
                        AND c2.task_id = ?
                    )
                    SELECT COUNT(*) as cnt
                    FROM embeddings e
                    WHERE e.target_type = 'fragment'
                      AND e.model_id = ?
                      AND e.target_id IN (SELECT fragment_id FROM task_fragments)
                    """,
                    (task_id, model_id),
                )
            else:
                count_result = await db.fetch_one(
                    "SELECT COUNT(*) as cnt FROM embeddings WHERE target_type = ? AND model_id = ?",
                    (target_type, model_id),
                )
            total_searched = count_result["cnt"] if count_result else 0

            return {
                "ok": True,
                "results": results,
                "total_searched": total_searched,
            }

        except Exception as e:
            logger.error("Vector search error", error=str(e), exc_info=True)
            return {
                "ok": False,
                "results": [],
                "total_searched": 0,
                "error": str(e),
            }
