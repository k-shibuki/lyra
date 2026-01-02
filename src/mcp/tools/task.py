"""Task management handlers for MCP tools.

Handles create_task, get_status, and stop_task operations.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.mcp.helpers import (
    clear_exploration_state,
    get_domain_overrides,
    get_exploration_state,
    get_metrics_from_db,
    get_pending_auth_info,
    get_search_queue_status,
)
from src.mcp.response_meta import attach_meta, create_minimal_meta
from src.research.pipeline import stop_task_action
from src.scheduler.search_worker import get_worker_manager
from src.storage.database import get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_create_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle create_task tool call.

    Creates a new research task and returns task_id.
    Per ADR-0003: Returns task_id, query, created_at, budget.
    """
    query = args["query"]
    config = args.get("config", {})

    # Generate task ID
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    # Extract budget config
    budget_config = config.get("budget", {})
    budget_pages = budget_config.get("budget_pages", 120)
    max_seconds = budget_config.get("max_seconds", 1200)

    with LogContext(task_id=task_id):
        logger.info("Creating task", query=query[:100])

        # Store task in database
        db = await get_database()

        created_at = datetime.now(UTC).isoformat()

        await db.execute(
            """
            INSERT INTO tasks (id, query, status, config_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, query, "created", json.dumps(config), created_at),
        )

        response = {
            "ok": True,
            "task_id": task_id,
            "query": query,
            "created_at": created_at,
            "budget": {
                "budget_pages": budget_pages,
                "max_seconds": max_seconds,
            },
        }
        return attach_meta(response, create_minimal_meta())


async def handle_get_status(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_status tool call.

    Implements ADR-0003: Unified task and exploration status.
    Implements ADR-0010: Long polling with wait parameter.

    Returns task info, search states, queue status, metrics, budget, auth queue.

    Note: Returns data only, no recommendations. Cursor AI decides next actions.
    """
    task_id = args.get("task_id")
    wait = args.get("wait", 0)

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    # Validate wait parameter (per schema: 0-180s)
    if wait < 0 or wait > 180:
        raise InvalidParamsError(
            "wait must be between 0 and 180",
            param_name="wait",
            expected="integer 0-180",
        )

    with LogContext(task_id=task_id):
        # Get exploration state first for long polling
        state = None
        try:
            state = await get_exploration_state(task_id)
            # Record activity for ADR-0002 idle timeout tracking
            state.record_activity()
        except Exception as e:
            logger.debug(
                "No exploration state available",
                task_id=task_id,
                error=str(e),
            )

        # Long polling: wait for status change (ADR-0010)
        if wait > 0 and state is not None:
            logger.debug(f"Long polling wait={wait}s", task_id=task_id)
            await state.wait_for_change(timeout=float(wait))

        # Get task info from DB
        db = await get_database()
        task = await db.fetch_one(
            "SELECT id, query, status, created_at FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Map DB status to spec status
        db_status = task["status"] if isinstance(task, dict) else task[2]
        task_query = task["query"] if isinstance(task, dict) else task[1]

        # Get exploration state status
        exploration_status = None
        if state is not None:
            try:
                exploration_status = await state.get_status()
            except Exception as e:
                logger.debug(
                    "Failed to get exploration status",
                    task_id=task_id,
                    error=str(e),
                )

        # Build unified response per ADR-0003
        if exploration_status:
            # Convert searches to ADR-0003 format (text -> query field name mapping)
            searches = []
            for sq in exploration_status.get("searches", []):
                searches.append(
                    {
                        "id": sq.get("id"),
                        "query": sq.get("text"),
                        "status": sq.get("status"),
                        "pages_fetched": sq.get("pages_fetched", 0),
                        "useful_fragments": sq.get("useful_fragments", 0),
                        "harvest_rate": sq.get("harvest_rate", 0.0),
                        "satisfaction_score": sq.get("satisfaction_score", 0.0),
                        "has_primary_source": sq.get("has_primary_source", False),
                    }
                )

            # Map task_status to status field
            status_map = {
                "exploring": "exploring",
                "created": "exploring",
                "awaiting_decision": "paused",
                "paused": "paused",  # Direct mapping for paused status
                "finalizing": "exploring",
                "completed": "completed",
                "failed": "failed",
            }
            status = status_map.get(exploration_status.get("task_status", db_status), "exploring")

            metrics = exploration_status.get("metrics", {})
            budget = exploration_status.get("budget", {})

            # Calculate remaining percent
            budget_pages_used = budget.get("budget_pages_used", 0)
            budget_pages_limit = budget.get("budget_pages_limit", 120)
            remaining_percent = int((1 - budget_pages_used / max(1, budget_pages_limit)) * 100)

            # Get blocked domains info for transparency
            from src.filter.source_verification import get_source_verifier

            verifier = get_source_verifier()
            blocked_domains = verifier.get_blocked_domains_info()

            # Get domain overrides from DB
            domain_overrides = await get_domain_overrides()

            # Get search queue status (ADR-0010)
            queue_info = await get_search_queue_status(db, task_id)

            # Get pending auth info (ADR-0007)
            pending_auth = await get_pending_auth_info(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "query": task_query,
                "searches": searches,
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": int(pending_auth.get("pending_captchas", 0)),
                "metrics": {
                    "total_searches": len(searches),
                    "satisfied_count": metrics.get("satisfied_count", 0),
                    "total_pages": metrics.get("total_pages", 0),
                    "total_fragments": metrics.get("total_fragments", 0),
                    "total_claims": metrics.get("total_claims", 0),
                    "elapsed_seconds": metrics.get("elapsed_seconds", 0),
                },
                "budget": {
                    "budget_pages_used": budget_pages_used,
                    "budget_pages_limit": budget_pages_limit,
                    "time_used_seconds": budget.get("time_used_seconds", 0),
                    "time_limit_seconds": budget.get("time_limit_seconds", 1200),
                    "remaining_percent": remaining_percent,
                },
                "auth_queue": exploration_status.get("authentication_queue"),
                "warnings": exploration_status.get("warnings", []),
                "idle_seconds": exploration_status.get("idle_seconds", 0),  # ADR-0002
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
            }

            # Add evidence_summary when status is completed
            if status == "completed":
                evidence_summary = await _get_evidence_summary(db, task_id)
                response["evidence_summary"] = evidence_summary

            return attach_meta(response, create_minimal_meta())
        else:
            # No exploration state - return minimal info
            # Get blocked domains info for transparency
            from src.filter.source_verification import get_source_verifier

            verifier = get_source_verifier()
            blocked_domains = verifier.get_blocked_domains_info()

            # Get domain overrides from DB
            domain_overrides = await get_domain_overrides()

            # Get search queue status (ADR-0010)
            queue_info = await get_search_queue_status(db, task_id)

            # Get pending auth info (ADR-0007)
            pending_auth = await get_pending_auth_info(db, task_id)

            # H-D fix: Fetch metrics directly from DB when exploration state unavailable
            db_metrics = await get_metrics_from_db(db, task_id)

            response = {
                "ok": True,
                "task_id": task_id,
                "status": db_status or "created",
                "query": task_query,
                "searches": [],
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": int(pending_auth.get("pending_captchas", 0)),
                "metrics": db_metrics,
                "budget": {
                    "budget_pages_used": db_metrics.get("total_pages", 0),
                    "budget_pages_limit": 120,
                    "time_used_seconds": db_metrics.get("elapsed_seconds", 0),
                    "time_limit_seconds": 1200,
                    "remaining_percent": max(
                        0, int((1 - db_metrics.get("total_pages", 0) / 120) * 100)
                    ),
                },
                "auth_queue": None,
                "warnings": [],
                "idle_seconds": 0,  # ADR-0002 (no exploration state)
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
            }

            # Add evidence_summary when status is completed
            if db_status == "completed":
                evidence_summary = await _get_evidence_summary(db, task_id)
                response["evidence_summary"] = evidence_summary

            return attach_meta(response, create_minimal_meta())


async def handle_stop_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle stop_task tool call.

    Implements ADR-0003: Finalizes task and returns summary.
    Implements ADR-0010: Stop modes (graceful/immediate).

    Mode semantics:
    - graceful: Cancel queued jobs, wait for running jobs to complete.
    - immediate: Cancel all queued and running jobs immediately.
    """
    task_id = args.get("task_id")
    reason = args.get("reason", "completed")
    mode = args.get("mode", "graceful")

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if mode not in ("graceful", "immediate"):
        raise InvalidParamsError(
            "mode must be 'graceful' or 'immediate'",
            param_name="mode",
            expected="'graceful' or 'immediate'",
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

        # Get exploration state
        state = await get_exploration_state(task_id)

        # Record activity for ADR-0002 idle timeout tracking
        state.record_activity()

        # Handle search queue jobs based on mode (ADR-0010)
        await cancel_search_queue_jobs(task_id, mode, db)

        # Cancel pending auth queue items for this task
        await cancel_auth_queue_for_task(task_id, db)

        # Execute stop through unified API
        result = await stop_task_action(
            task_id=task_id,
            state=state,
            reason=reason,
            mode=mode,
        )

        # Clear cached state
        clear_exploration_state(task_id)

        # Update task status in DB
        await db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (result.get("final_status", "completed"), task_id),
        )

        # Include mode in response for transparency
        result["mode"] = mode

        return result


async def cancel_search_queue_jobs(
    task_id: str,
    mode: str,
    db: Any,
) -> dict[str, int]:
    """
    Cancel search queue jobs for a task based on stop mode.

    Args:
        task_id: The task ID.
        mode: Stop mode ('graceful' or 'immediate').
        db: Database connection.

    Returns:
        Dict with counts of cancelled jobs by previous state.

    Mode semantics (ADR-0010):
    - graceful: Only cancel 'queued' jobs. Running jobs complete normally.
    - immediate: Cancel both 'queued' and 'running' jobs, including in-flight
                 search_action executions via asyncio.Task.cancel().
    """
    now = datetime.now(UTC).isoformat()
    counts = {"queued_cancelled": 0, "running_cancelled": 0, "tasks_cancelled": 0}

    # Always cancel queued jobs (DB state only)
    cursor = await db.execute(
        """
        UPDATE jobs
        SET state = 'cancelled', finished_at = ?
        WHERE task_id = ? AND kind = 'search_queue' AND state = 'queued'
        """,
        (now, task_id),
    )
    counts["queued_cancelled"] = getattr(cursor, "rowcount", 0)

    if mode == "immediate":
        # Cancel running jobs: both DB state and actual asyncio.Task
        # Step 1: Cancel running worker tasks (this triggers CancelledError)
        manager = get_worker_manager()
        tasks_cancelled = await manager.cancel_jobs_for_task(task_id)
        counts["tasks_cancelled"] = tasks_cancelled

        # Step 2: Update DB state for any running jobs that weren't tracked
        # (defensive: handles edge cases where job wasn't registered)
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = 'cancelled', finished_at = ?
            WHERE task_id = ? AND kind = 'search_queue' AND state = 'running'
            """,
            (now, task_id),
        )
        counts["running_cancelled"] = getattr(cursor, "rowcount", 0)

    logger.info(
        "Search queue jobs cancelled",
        task_id=task_id,
        mode=mode,
        queued_cancelled=counts["queued_cancelled"],
        running_cancelled=counts["running_cancelled"],
        tasks_cancelled=counts.get("tasks_cancelled", 0),
    )

    return counts


async def cancel_auth_queue_for_task(task_id: str, db: Any) -> int:
    """Cancel pending auth queue items for a stopped task.

    Per ADR-0007: When a task is stopped, all pending authentication
    queue items for that task should be marked as cancelled.

    Args:
        task_id: The task ID.
        db: Database connection.

    Returns:
        Number of auth queue items cancelled.
    """
    cursor = await db.execute(
        """
        UPDATE intervention_queue
        SET status = 'cancelled', completed_at = datetime('now')
        WHERE task_id = ? AND status IN ('pending', 'in_progress')
        """,
        (task_id,),
    )
    cancelled_count = getattr(cursor, "rowcount", 0)

    if cancelled_count > 0:
        logger.info(
            "Auth queue items cancelled for stopped task",
            task_id=task_id,
            cancelled_count=cancelled_count,
        )

    return cancelled_count


async def _get_evidence_summary(db: Any, task_id: str) -> dict[str, Any]:
    """Get evidence summary statistics for completed task.

    Args:
        db: Database connection.
        task_id: Task ID.

    Returns:
        Evidence summary dict with counts and top domains.
    """
    # Count claims
    claims_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM claims WHERE task_id = ?",
        (task_id,),
    )
    total_claims = claims_row["cnt"] if claims_row else 0

    # Count fragments (via edges linked to task's claims)
    fragments_row = await db.fetch_one(
        """
        SELECT COUNT(DISTINCT f.id) as cnt
        FROM fragments f
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        """,
        (task_id,),
    )
    total_fragments = fragments_row["cnt"] if fragments_row else 0

    # Count pages (via fragments)
    pages_row = await db.fetch_one(
        """
        SELECT COUNT(DISTINCT p.id) as cnt
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        """,
        (task_id,),
    )
    total_pages = pages_row["cnt"] if pages_row else 0

    # Count edges by relation
    edges_row = await db.fetch_one(
        """
        SELECT
            COUNT(CASE WHEN e.relation = 'supports' THEN 1 END) as supporting,
            COUNT(CASE WHEN e.relation = 'refutes' THEN 1 END) as refuting,
            COUNT(CASE WHEN e.relation = 'neutral' THEN 1 END) as neutral
        FROM edges e
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        """,
        (task_id,),
    )
    supporting_edges = edges_row["supporting"] if edges_row else 0
    refuting_edges = edges_row["refuting"] if edges_row else 0
    neutral_edges = edges_row["neutral"] if edges_row else 0

    # Get top domains
    domains_rows = await db.fetch_all(
        """
        SELECT p.domain, COUNT(DISTINCT p.id) as page_count
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        GROUP BY p.domain
        ORDER BY page_count DESC
        LIMIT 10
        """,
        (task_id,),
    )
    top_domains = [row["domain"] for row in domains_rows]

    return {
        "total_claims": total_claims,
        "total_fragments": total_fragments,
        "total_pages": total_pages,
        "supporting_edges": supporting_edges,
        "refuting_edges": refuting_edges,
        "neutral_edges": neutral_edges,
        "top_domains": top_domains,
    }
