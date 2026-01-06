"""Helper functions for MCP server operations.

Provides common utility functions used across MCP tool handlers.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from src.storage.database import get_database
from src.utils.logging import ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)

# ============================================================
# Exploration State Management
# ============================================================

# Cache of exploration states per task
_exploration_states: dict[str, Any] = {}
# Lock to prevent race condition in _get_exploration_state (H-F fix)
_exploration_state_locks: dict[str, asyncio.Lock] = {}
_exploration_state_global_lock = asyncio.Lock()


async def get_exploration_state(task_id: str) -> Any:
    """Get or create exploration state for a task.

    Uses per-task locking to prevent race condition where multiple
    coroutines create separate ExplorationState instances for the
    same task_id (H-F fix).
    """
    from src.research.state import ExplorationState

    # Get or create per-task lock (with global lock protection)
    async with _exploration_state_global_lock:
        if task_id not in _exploration_state_locks:
            _exploration_state_locks[task_id] = asyncio.Lock()
        lock = _exploration_state_locks[task_id]

    # Use per-task lock to prevent race condition
    async with lock:
        if task_id not in _exploration_states:
            state = ExplorationState(task_id)
            await state.load_state()
            _exploration_states[task_id] = state

        return _exploration_states[task_id]


def clear_exploration_state(task_id: str) -> None:
    """Clear exploration state from cache."""
    if task_id in _exploration_states:
        del _exploration_states[task_id]


# ============================================================
# Database Query Helpers
# ============================================================


async def get_metrics_from_db(db: Any, task_id: str) -> dict[str, Any]:
    """Get metrics directly from database for a task.

    H-D fix: Fallback when ExplorationState is not available.
    Fetches counts from DB tables instead of returning zeros.

    Note: DB schema has task_id on queries and claims, but pages/fragments
    are linked via serp_items → pages → fragments chain.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Metrics dict with counts from DB.
    """
    try:
        # Count queries/searches
        cursor = await db.execute(
            "SELECT COUNT(*) FROM queries WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        total_searches = row[0] if row else 0

        # Count pages for a task.
        #
        # There are 2 task-linking paths:
        # 1) SERP path: queries(task_id) -> serp_items(query_id, url) -> pages(url)
        # 2) Academic API path: resource_index(task_id, page_id, status='completed') -> pages(id)
        cursor = await db.execute(
            """
            SELECT COUNT(DISTINCT page_id) FROM (
                SELECT p.id AS page_id
            FROM pages p
            JOIN serp_items si ON p.url = si.url
            JOIN queries q ON si.query_id = q.id
            WHERE q.task_id = ?
                UNION
                SELECT ri.page_id AS page_id
                FROM resource_index ri
                WHERE ri.task_id = ?
                  AND ri.status = 'completed'
                  AND ri.page_id IS NOT NULL
            )
            """,
            (task_id, task_id),
        )
        row = await cursor.fetchone()
        total_pages = row[0] if row else 0

        # Count fragments for a task via task-linked pages (SERP + Academic API).
        cursor = await db.execute(
            """
            SELECT COUNT(DISTINCT f.id)
            FROM fragments f
            WHERE f.page_id IN (
                SELECT page_id FROM (
                    SELECT p.id AS page_id
                    FROM pages p
            JOIN serp_items si ON p.url = si.url
            JOIN queries q ON si.query_id = q.id
            WHERE q.task_id = ?
                    UNION
                    SELECT ri.page_id AS page_id
                    FROM resource_index ri
                    WHERE ri.task_id = ?
                      AND ri.status = 'completed'
                      AND ri.page_id IS NOT NULL
                )
            )
            """,
            (task_id, task_id),
        )
        row = await cursor.fetchone()
        total_fragments = row[0] if row else 0

        # Count claims (has direct task_id)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM claims WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        total_claims = row[0] if row else 0

        # Get task creation time for elapsed_seconds
        cursor = await db.execute(
            "SELECT created_at FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        elapsed_seconds = 0
        if row and row[0]:
            try:
                created_at = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                elapsed_seconds = int((datetime.now(UTC) - created_at).total_seconds())
            except (ValueError, TypeError):
                pass

        return {
            "total_searches": total_searches,
            "satisfied_count": 0,  # Can't determine from DB alone
            "total_pages": total_pages,
            "total_fragments": total_fragments,
            "total_claims": total_claims,
            "elapsed_seconds": elapsed_seconds,
        }
    except Exception as e:
        logger.warning("Failed to get metrics from DB", task_id=task_id, error=str(e))
        return {
            "total_searches": 0,
            "satisfied_count": 0,
            "total_pages": 0,
            "total_fragments": 0,
            "total_claims": 0,
            "elapsed_seconds": 0,
        }


async def get_search_queue_status(db: Any, task_id: str) -> dict[str, Any]:
    """Get search queue status for a task.

    Returns queue depth, running count, and item details.
    Per ADR-0010: Search queue status in get_status response.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Queue status dict with depth, running, and items.
    """
    try:
        cursor = await db.execute(
            """
            SELECT id, input_json, state, priority, queued_at, started_at, finished_at
            FROM jobs
            WHERE task_id = ? AND kind = 'search_queue'
            ORDER BY priority ASC, queued_at ASC
            """,
            (task_id,),
        )
        rows = await cursor.fetchall()

        items = []
        queued_count = 0
        running_count = 0

        for row in rows:
            if isinstance(row, dict):
                item_id = row["id"]
                input_json = row["input_json"]
                state = row["state"]
                priority = row["priority"]
                queued_at = row["queued_at"]
                started_at = row["started_at"]
                finished_at = row["finished_at"]
            else:
                item_id = row[0]
                input_json = row[1]
                state = row[2]
                priority = row[3]
                queued_at = row[4]
                started_at = row[5]
                finished_at = row[6]

            # Parse input to get query
            query = ""
            if input_json:
                try:
                    input_data = json.loads(input_json)
                    query = input_data.get("query", "")
                except json.JSONDecodeError:
                    pass

            # Count by state
            if state == "queued":
                queued_count += 1
            elif state == "running":
                running_count += 1

            items.append(
                {
                    "id": item_id,
                    "query": query,
                    "status": state,
                    "priority": priority,
                    "created_at": queued_at,
                    "started_at": started_at,
                    "completed_at": finished_at,
                }
            )

        return {
            "depth": queued_count,
            "running": running_count,
            "items": items,
        }
    except Exception as e:
        logger.warning("Failed to get search queue status", error=str(e))
        return {
            "depth": 0,
            "running": 0,
            "items": [],
        }


async def get_task_jobs_summary(db: Any, task_id: str) -> dict[str, Any]:
    """Get summary of all job kinds for a task.

    Returns aggregated counts by kind and state for visibility into
    VERIFY_NLI, CITATION_GRAPH, and other job types.

    Per ADR-0015: Expose all job kinds in get_status for transparency.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Jobs summary dict with by_kind breakdown.
    """
    try:
        cursor = await db.execute(
            """
            SELECT kind, state, COUNT(*) as count
            FROM jobs
            WHERE task_id = ?
            GROUP BY kind, state
            ORDER BY kind, state
            """,
            (task_id,),
        )
        rows = await cursor.fetchall()

        # Initialize summary structure
        by_kind: dict[str, dict[str, int]] = {}

        for row in rows:
            if isinstance(row, dict):
                kind = row["kind"]
                state = row["state"]
                count = row["count"]
            else:
                kind = row[0]
                state = row[1]
                count = row[2]

            if kind not in by_kind:
                by_kind[kind] = {
                    "queued": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "awaiting_auth": 0,
                }

            if state in by_kind[kind]:
                by_kind[kind][state] = count

        # Calculate totals
        total_queued = sum(k.get("queued", 0) for k in by_kind.values())
        total_running = sum(k.get("running", 0) for k in by_kind.values())
        total_completed = sum(k.get("completed", 0) for k in by_kind.values())
        total_failed = sum(k.get("failed", 0) for k in by_kind.values())

        return {
            "total_queued": total_queued,
            "total_running": total_running,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "by_kind": by_kind,
        }
    except Exception as e:
        logger.warning("Failed to get task jobs summary", error=str(e))
        return {
            "total_queued": 0,
            "total_running": 0,
            "total_completed": 0,
            "total_failed": 0,
            "by_kind": {},
        }


async def get_pending_auth_info(db: Any, task_id: str) -> dict[str, Any]:
    """Get pending authentication info for a task.

    Per ADR-0007: Returns info about CAPTCHAs awaiting human intervention.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Pending auth info dict.
    """
    try:
        # Count awaiting_auth jobs
        cursor = await db.execute(
            """
            SELECT COUNT(*) as count FROM jobs
            WHERE task_id = ? AND kind = 'search_queue' AND state = 'awaiting_auth'
            """,
            (task_id,),
        )
        row = await cursor.fetchone()
        awaiting_count = row["count"] if row else 0

        # Get pending intervention queue items for this task
        cursor = await db.execute(
            """
            SELECT domain, auth_type, queued_at FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            ORDER BY queued_at ASC
            """,
            (task_id,),
        )
        pending_rows = await cursor.fetchall()

        # Group by domain
        by_domain: dict[str, list[str]] = {}
        for row in pending_rows:
            domain = row["domain"] if isinstance(row, dict) else row[0]
            auth_type = row["auth_type"] if isinstance(row, dict) else row[1]
            by_domain.setdefault(domain, []).append(auth_type)

        return {
            "awaiting_auth_jobs": awaiting_count,
            "pending_captchas": len(pending_rows),
            "domains": [
                {"domain": d, "auth_types": list(set(t)), "count": len(t)}
                for d, t in by_domain.items()
            ],
        }
    except Exception as e:
        logger.warning("Failed to get pending auth info", error=str(e))
        return {
            "awaiting_auth_jobs": 0,
            "pending_captchas": 0,
            "domains": [],
        }


async def get_domain_overrides() -> list[dict[str, Any]]:
    """Get active domain override rules from DB.

    Returns list of override rules for get_status response .
    Per ADR-0012: expose domain_overrides for auditability.
    """
    try:
        db = await get_database()
        cursor = await db.execute(
            """
            SELECT id, domain_pattern, decision, reason, updated_at
            FROM domain_override_rules
            WHERE is_active = 1
            ORDER BY updated_at DESC
            """
        )
        rows = await cursor.fetchall()

        overrides = []
        for row in rows:
            if isinstance(row, dict):
                overrides.append(
                    {
                        "rule_id": row["id"],
                        "domain_pattern": row["domain_pattern"],
                        "decision": row["decision"],
                        "reason": row["reason"] or "",
                        "updated_at": row["updated_at"] or "",
                    }
                )
            else:
                overrides.append(
                    {
                        "rule_id": row[0],
                        "domain_pattern": row[1],
                        "decision": row[2],
                        "reason": row[3] or "",
                        "updated_at": row[4] or "",
                    }
                )
        return overrides
    except Exception as e:
        logger.warning("Failed to get domain overrides", error=str(e))
        return []


async def check_chrome_cdp_ready() -> bool:
    """
    Check if Chrome CDP is available.

    Performs a lightweight HTTP check to the CDP endpoint without
    initializing full Playwright.

    Returns:
        True if CDP is available, False otherwise.
    """
    import aiohttp

    from src.utils.config import get_settings

    settings = get_settings()
    chrome_host = settings.browser.chrome_host
    # Use base port (worker 0) for health check
    chrome_port = settings.browser.chrome_base_port
    cdp_url = f"http://{chrome_host}:{chrome_port}/json/version"

    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(cdp_url) as response:
                return response.status == 200
    except Exception as e:
        logger.debug("Chrome health check failed", cdp_url=cdp_url, error=str(e))
        return False
