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
    get_target_queue_status,
    get_task_jobs_summary,
)
from src.mcp.response_meta import attach_meta, create_minimal_meta
from src.research.pipeline import stop_task_action
from src.storage.database import get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


def _compute_milestones(
    *,
    queue_info: dict[str, Any],
    pending_auth: dict[str, Any] | None,
    jobs_summary: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Compute task_id-level stability flags for AI decision-making.

    Returns only the flags AI needs to decide "what can I do next?":
    - citation_candidates_stable: Can proceed to v_reference_candidates for Citation Chasing
    - nli_results_stable: NLI verification results are complete
    - blockers: Why not stable (empty when all stable)

    For detailed job counts, AI can inspect jobs.by_kind directly.
    """

    def _kind_drained(kind: str) -> bool:
        k = (jobs_summary.get("by_kind") or {}).get(kind) or {}
        return int(k.get("queued", 0)) == 0 and int(k.get("running", 0)) == 0

    queue_depth = int(queue_info.get("depth", 0))
    queue_running = int(queue_info.get("running", 0))
    target_queue_drained = queue_depth == 0 and queue_running == 0

    pending_auth_count = int((pending_auth or {}).get("pending_captchas", 0))
    auth_cleared = pending_auth_count == 0

    citation_graph_drained = _kind_drained("citation_graph")
    nli_verification_drained = _kind_drained("verify_nli")

    # citation_candidates_stable: v_reference_candidates won't grow anymore
    citation_candidates_stable = target_queue_drained and citation_graph_drained and auth_cleared

    # nli_results_stable: NLI verification is complete
    nli_results_stable = nli_verification_drained

    # Blockers: why not stable (for debugging, empty when all stable)
    blockers: list[str] = []
    if not target_queue_drained:
        blockers.append("target_queue")
    if not citation_graph_drained:
        blockers.append("citation_graph")
    if not auth_cleared:
        blockers.append("pending_auth")
    if not nli_verification_drained:
        blockers.append("verify_nli")

    milestones = {
        "citation_candidates_stable": citation_candidates_stable,
        "nli_results_stable": nli_results_stable,
        "blockers": blockers,
    }
    return milestones, pending_auth_count


def _get_pending_auth_message(pending_auth_count: int) -> str | None:
    """Get unified message for pending auth challenges.

    Returns None if no challenges pending, otherwise returns
    a structured message for AI consumption.

    Args:
        pending_auth_count: Number of pending auth items.

    Returns:
        Message string or None.
    """
    if pending_auth_count == 0:
        return None

    return (
        f"{pending_auth_count} blocking challenge(s) detected. "
        "User action required: resolve manually then tell AI 'resolved', "
        "or tell AI 'skip' to bypass. Use get_auth_queue for details."
    )


async def handle_create_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle create_task tool call.

    Creates a new research task and returns task_id.
    Per ADR-0017: hypothesis is the central claim to verify.
    """
    hypothesis = args["hypothesis"]
    config = args.get("config", {})

    # Generate task ID
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    # Extract budget config
    budget_config = config.get("budget", {})
    budget_pages = budget_config.get("budget_pages", 500)
    max_seconds = budget_config.get("max_seconds", 3600)

    with LogContext(task_id=task_id):
        logger.info("Creating task", hypothesis=hypothesis[:100])

        # Store task in database
        db = await get_database()

        created_at = datetime.now(UTC).isoformat()

        await db.execute(
            """
            INSERT INTO tasks (id, hypothesis, status, config_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, hypothesis, "created", json.dumps(config), created_at),
        )

        response = {
            "ok": True,
            "task_id": task_id,
            "hypothesis": hypothesis,
            "created_at": created_at,
            "budget": {
                "budget_pages": budget_pages,
                "max_seconds": max_seconds,
            },
            "message": f"Task created. Use queue_targets(task_id='{task_id}', targets=[{{kind:'query', query:'...'}}]) to start exploration.",
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

    # Validate wait parameter (per schema: 1-300s, 0 allowed for immediate)
    if wait < 0 or wait > 300:
        raise InvalidParamsError(
            "wait must be between 0 and 300",
            param_name="wait",
            expected="integer 0-300",
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
            "SELECT id, hypothesis, status, created_at FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Map DB status to spec status
        db_status = task["status"] if isinstance(task, dict) else task[2]
        task_hypothesis = task["hypothesis"] if isinstance(task, dict) else task[1]

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
            # Note: "completed" is deprecated, map to "paused" for backward compatibility
            status_map = {
                "exploring": "exploring",
                "created": "exploring",
                "awaiting_decision": "paused",
                "paused": "paused",
                "finalizing": "exploring",  # (deprecated)
                "completed": "paused",  # (deprecated) -> paused for backward compat
                "cancelled": "paused",  # Cancelled tasks are also resumable
                "failed": "failed",
            }
            status = status_map.get(exploration_status.get("task_status", db_status), "exploring")

            metrics = exploration_status.get("metrics", {})
            budget = exploration_status.get("budget", {})

            # Get budget values for response
            budget_pages_used = budget.get("budget_pages_used", 0)
            budget_pages_limit = budget.get("budget_pages_limit", 500)

            # Get blocked domains info for transparency
            from src.filter.source_verification import get_source_verifier

            verifier = get_source_verifier()
            blocked_domains = verifier.get_blocked_domains_info()

            # Get domain overrides from DB
            domain_overrides = await get_domain_overrides()

            # Get target queue status (ADR-0010)
            queue_info = await get_target_queue_status(db, task_id)

            # Get pending auth info (ADR-0007)
            pending_auth = await get_pending_auth_info(db, task_id)

            # Get all jobs summary (ADR-0015: VERIFY_NLI, CITATION_GRAPH visibility)
            jobs_summary = await get_task_jobs_summary(db, task_id)

            # db_only: Always compute total_* metrics from DB, even when ExplorationState exists.
            db_metrics = await get_metrics_from_db(db, task_id)

            milestones, pending_auth_count = _compute_milestones(
                queue_info=queue_info,
                pending_auth=pending_auth,
                jobs_summary=jobs_summary,
            )

            response = {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "hypothesis": task_hypothesis,
                "searches": searches,
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": pending_auth_count,
                # Unified message for pending auth (when count > 0)
                "pending_auth_message": _get_pending_auth_message(pending_auth_count),
                "metrics": {
                    "total_searches": db_metrics.get("total_searches", len(searches)),
                    "satisfied_count": metrics.get("satisfied_count", 0),
                    "total_pages": db_metrics.get("total_pages", 0),
                    "total_fragments": db_metrics.get("total_fragments", 0),
                    "total_claims": db_metrics.get("total_claims", 0),
                    "elapsed_seconds": metrics.get("elapsed_seconds", 0),
                },
                "budget": {
                    "budget_pages_used": db_metrics.get("total_pages", budget_pages_used),
                    "budget_pages_limit": budget_pages_limit,
                    "time_used_seconds": budget.get("time_used_seconds", 0),
                    "time_limit_seconds": budget.get("time_limit_seconds", 3600),
                    "remaining_percent": max(
                        0,
                        int(
                            (
                                1
                                - (db_metrics.get("total_pages", budget_pages_used))
                                / max(1, budget_pages_limit)
                            )
                            * 100
                        ),
                    ),
                },
                "auth_queue": exploration_status.get("authentication_queue"),
                "warnings": exploration_status.get("warnings", []),
                "idle_seconds": exploration_status.get("idle_seconds", 0),  # ADR-0002
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
                "jobs": jobs_summary,  # ADR-0015: All job kinds status
                "milestones": milestones,  # AI UX: stable next actions for this task_id
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

            # Get target queue status (ADR-0010)
            queue_info = await get_target_queue_status(db, task_id)

            # Get pending auth info (ADR-0007)
            pending_auth = await get_pending_auth_info(db, task_id)

            # Get all jobs summary (ADR-0015: VERIFY_NLI, CITATION_GRAPH visibility)
            jobs_summary = await get_task_jobs_summary(db, task_id)

            # H-D fix: Fetch metrics directly from DB when exploration state unavailable
            db_metrics = await get_metrics_from_db(db, task_id)

            milestones, pending_auth_count = _compute_milestones(
                queue_info=queue_info,
                pending_auth=pending_auth,
                jobs_summary=jobs_summary,
            )

            response = {
                "ok": True,
                "task_id": task_id,
                "status": db_status or "created",
                "hypothesis": task_hypothesis,
                "searches": [],
                "queue": queue_info,  # ADR-0010: Search queue status
                "pending_auth": pending_auth,  # ADR-0007: CAPTCHA queue status
                # Convenience field for agents/clients: quick check without parsing nested structures
                "pending_auth_count": pending_auth_count,
                # Unified message for pending auth (when count > 0)
                "pending_auth_message": _get_pending_auth_message(pending_auth_count),
                "metrics": db_metrics,
                "budget": {
                    "budget_pages_used": db_metrics.get("total_pages", 0),
                    "budget_pages_limit": 500,
                    "time_used_seconds": db_metrics.get("elapsed_seconds", 0),
                    "time_limit_seconds": 3600,
                    "remaining_percent": max(
                        0, int((1 - db_metrics.get("total_pages", 0) / 500) * 100)
                    ),
                },
                "auth_queue": None,
                "warnings": [],
                "idle_seconds": 0,  # ADR-0002 (no exploration state)
                "blocked_domains": blocked_domains,  # Added for transparency
                "domain_overrides": domain_overrides,  #
                "jobs": jobs_summary,  # ADR-0015: All job kinds status
                "milestones": milestones,  # AI UX: stable next actions for this task_id
            }

            # Add evidence_summary when status is completed
            if db_status == "completed":
                evidence_summary = await _get_evidence_summary(db, task_id)
                response["evidence_summary"] = evidence_summary

            return attach_meta(response, create_minimal_meta())


async def handle_stop_task(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle stop_task tool call.

    Implements ADR-0003: Finalizes task session (pauses task).
    Implements ADR-0010: Stop modes (graceful/immediate) and scope.

    Scope semantics:
    - all_jobs (default): Cancel all job kinds for this task. This is the
      recommended default to ensure "stop means stop".
    - target_queue_only: Only cancel target_queue jobs. VERIFY_NLI,
      CITATION_GRAPH, and other jobs are allowed to complete.

    Mode semantics:
    - graceful: Cancel queued jobs, wait for running jobs to complete.
    - immediate: Cancel all queued and running jobs immediately.
    - full: Cancel all jobs AND wait for operations to drain.

    Reason semantics:
    - session_completed: Session ends, task paused and resumable.
    - budget_exhausted: Budget depleted, task paused and resumable.
    - user_cancelled: User explicitly cancelled, task paused.

    Note: Tasks are always resumable. Use queue_targets on a paused task
    to add more targets and continue exploration.
    """
    task_id = args.get("task_id")
    reason = args.get("reason", "session_completed")
    mode = args.get("mode", "graceful")
    scope = args.get("scope", "all_jobs")  # Default changed to all_jobs

    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if mode not in ("graceful", "immediate", "full"):
        raise InvalidParamsError(
            "mode must be 'graceful', 'immediate', or 'full'",
            param_name="mode",
            expected="'graceful', 'immediate', or 'full'",
        )

    if scope not in ("target_queue_only", "all_jobs"):
        raise InvalidParamsError(
            "scope must be 'target_queue_only' or 'all_jobs'",
            param_name="scope",
            expected="'target_queue_only' or 'all_jobs'",
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

        # Handle jobs based on mode and scope (ADR-0010, ADR-0015)
        cancelled_counts = await cancel_jobs_by_scope(task_id, mode, scope, db)

        # Cancel pending auth queue items for this task
        await cancel_auth_queue_for_task(task_id, db)

        # ADR-0007: Release held CAPTCHA tabs for this task
        from src.search.tab_pool import get_all_tab_pools

        held_tabs_released = 0
        for pool in get_all_tab_pools().values():
            held_tabs_released += await pool.release_held_tabs_for_task(task_id)
        if held_tabs_released > 0:
            logger.info(
                "Released held CAPTCHA tabs for task",
                task_id=task_id,
                released_count=held_tabs_released,
            )

        # Execute stop through unified API
        result = await stop_task_action(
            task_id=task_id,
            state=state,
            reason=reason,
            mode=mode,
        )

        # Clear cached state
        clear_exploration_state(task_id)

        # Update task status in DB (paused = session ended but resumable)
        await db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (result.get("final_status", "paused"), task_id),
        )

        # Include mode, scope, and cancellation details in response for transparency
        result["mode"] = mode
        result["scope"] = scope
        result["cancelled_counts"] = cancelled_counts

        # List unaffected job kinds for clarity
        if scope == "target_queue_only":
            result["unaffected_kinds"] = ["verify_nli", "citation_graph", "embed", "nli"]
        else:
            result["unaffected_kinds"] = []

        return result


async def cancel_jobs_by_scope(
    task_id: str,
    mode: str,
    scope: str,
    db: Any,
) -> dict[str, Any]:
    """
    Cancel jobs for a task based on mode and scope.

    Args:
        task_id: The task ID.
        mode: Stop mode ('graceful', 'immediate', or 'full').
        scope: Job scope ('target_queue_only' or 'all_jobs').
        db: Database connection.

    Returns:
        Dict with counts of cancelled/waited jobs by kind and state.

    Scope semantics:
    - all_jobs (default): Cancel all job kinds for this task.
    - target_queue_only: Only cancel 'target_queue' jobs.

    Mode semantics (ADR-0010):
    - graceful: Cancel 'queued' jobs and WAIT for running jobs to complete naturally.
    - immediate: Cancel both 'queued' and 'running' jobs immediately via asyncio.Task.cancel().
    - full: Cancel all jobs (like immediate) AND wait for ML/NLI operations to drain.
    """
    now = datetime.now(UTC).isoformat()

    # Determine which job kinds to cancel based on scope
    if scope == "target_queue_only":
        job_kinds = ["target_queue"]
    else:  # all_jobs
        job_kinds = [
            "target_queue",
            "verify_nli",
            "citation_graph",
            "embed",
            "nli",
            "serp",
            "fetch",
            "extract",
            "llm",
        ]

    counts: dict[str, Any] = {
        "queued_cancelled": 0,
        "running_cancelled": 0,
        "tasks_cancelled": 0,
        "scheduler_jobs_cancelled": 0,
        "jobs_waited": 0,
        "by_kind": {},
    }

    for kind in job_kinds:
        kind_counts = {"queued": 0, "running": 0}

        # Cancel queued jobs (DB state only)
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = 'cancelled', finished_at = ?
            WHERE task_id = ? AND kind = ? AND state = 'queued'
            """,
            (now, task_id, kind),
        )
        kind_counts["queued"] = getattr(cursor, "rowcount", 0)
        counts["queued_cancelled"] += kind_counts["queued"]

        if mode in ("immediate", "full"):
            # Cancel running jobs (DB state)
            cursor = await db.execute(
                """
                UPDATE jobs
                SET state = 'cancelled', finished_at = ?
                WHERE task_id = ? AND kind = ? AND state = 'running'
                """,
                (now, task_id, kind),
            )
            kind_counts["running"] = getattr(cursor, "rowcount", 0)
            counts["running_cancelled"] += kind_counts["running"]

        if kind_counts["queued"] > 0 or kind_counts["running"] > 0:
            counts["by_kind"][kind] = kind_counts

    # Handle running task cancellation via JobScheduler (unified)
    # All job kinds (including target_queue) are now handled by JobScheduler
    from src.scheduler.jobs import get_scheduler

    scheduler = await get_scheduler()

    if mode == "graceful":
        # Wait for running jobs to complete naturally (don't cancel them)
        # For graceful mode, we just wait - the DB update above already cancelled queued jobs
        jobs_waited = await scheduler.wait_for_task_jobs_to_complete(task_id, timeout=30.0)
        counts["jobs_waited"] = jobs_waited
    elif mode in ("immediate", "full"):
        # Cancel all running jobs for this task via JobScheduler
        scheduler_cancelled = await scheduler.cancel_running_jobs_for_task(task_id)
        counts["tasks_cancelled"] = scheduler_cancelled

    return counts


async def cancel_target_queue_jobs(
    task_id: str,
    mode: str,
    db: Any,
) -> dict[str, int]:
    """
    Cancel target queue jobs for a task based on stop mode.

    DEPRECATED: Use cancel_jobs_by_scope with scope='target_queue_only' instead.

    Args:
        task_id: The task ID.
        mode: Stop mode ('graceful', 'immediate', or 'full').
        db: Database connection.

    Returns:
        Dict with counts of cancelled/waited jobs by previous state.

    Mode semantics (ADR-0010):
    - graceful: Cancel 'queued' jobs and WAIT for running jobs to complete naturally.
    - immediate: Cancel both 'queued' and 'running' jobs immediately via asyncio.Task.cancel().
    - full: Cancel all jobs (like immediate) AND wait for ML/NLI operations to drain.
    """
    result = await cancel_jobs_by_scope(task_id, mode, "target_queue_only", db)
    return {
        "queued_cancelled": result.get("queued_cancelled", 0),
        "running_cancelled": result.get("running_cancelled", 0),
        "tasks_cancelled": result.get("tasks_cancelled", 0),
        "jobs_waited": result.get("jobs_waited", 0),
    }


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
