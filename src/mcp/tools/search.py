"""Search queue handler for MCP tools.

Handles queue_searches operation.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.storage.database import get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_queue_searches(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle queue_searches tool call.

    Queues multiple search queries for background execution.
    Returns immediately with queued count and search IDs.

    Per ADR-0010: Async search queue architecture.

    Args:
        task_id: Task ID
        queries: List of search queries
        options: Optional search options (applied to all queries)

    Returns:
        {ok: true, queued_count: N, search_ids: [...]}
    """
    task_id = args.get("task_id")
    queries = args.get("queries", [])
    options = args.get("options", {})

    # Validation
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if not queries or len(queries) == 0:
        raise InvalidParamsError(
            "queries must not be empty",
            param_name="queries",
            expected="non-empty array of strings",
        )

    with LogContext(task_id=task_id):
        # Verify task exists
        db = await get_database()
        task = await db.fetch_one(
            "SELECT id FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Determine priority value from string
        priority_str = options.get("priority", "medium")
        priority_map = {"high": 10, "medium": 50, "low": 90}
        priority_value = priority_map.get(priority_str, 50)

        # Queue each search (with duplicate detection)
        search_ids = []
        skipped_count = 0
        now = datetime.now(UTC).isoformat()

        for query in queries:
            # Check for duplicate query in same task (queued or running)
            existing = await db.fetch_one(
                """
                SELECT id FROM jobs
                WHERE task_id = ? AND kind = 'search_queue'
                  AND state IN ('queued', 'running')
                  AND json_extract(input_json, '$.query') = ?
                """,
                (task_id, query),
            )
            if existing:
                # Skip duplicate query
                logger.debug(
                    "Skipping duplicate query",
                    task_id=task_id,
                    query=query[:50],
                    existing_id=existing.get("id"),
                )
                skipped_count += 1
                continue

            search_id = f"s_{uuid.uuid4().hex[:12]}"

            # Prepare input JSON
            input_data = {
                "query": query,
                "options": {k: v for k, v in options.items() if k != "priority"},
            }

            # Insert into jobs table (kind='search_queue')
            await db.execute(
                """
                INSERT INTO jobs
                    (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    search_id,
                    task_id,
                    "search_queue",
                    priority_value,
                    "network_client",
                    "queued",
                    json.dumps(input_data, ensure_ascii=False),
                    now,
                ),
            )
            search_ids.append(search_id)

        logger.info(
            "Searches queued",
            task_id=task_id,
            queued=len(search_ids),
            skipped=skipped_count,
            priority=priority_str,
        )

        message = f"{len(search_ids)} searches queued"
        if skipped_count > 0:
            message += f" ({skipped_count} duplicates skipped)"
        message += ". Use get_status(wait=N) to monitor progress."
        return {
            "ok": True,
            "queued_count": len(search_ids),
            "skipped_count": skipped_count,
            "search_ids": search_ids,
            "message": message,
        }


