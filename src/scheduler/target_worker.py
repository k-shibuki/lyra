"""
Target queue worker for Lyra.

Background worker that processes target queue jobs (kind='target_queue').
Implements async search/URL execution per ADR-0010.

Handles both target kinds:
- kind='query': Search query execution
- kind='url': Direct URL ingestion (citation chasing)

Worker lifecycle:
- Started when run_server() starts
- Stopped (cancelled) when run_server() shuts down
- Runs configurable number of workers for parallel execution
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import LogContext, get_logger

if TYPE_CHECKING:
    from src.research.state import ExplorationState

logger = get_logger(__name__)

# Polling interval when queue is empty
EMPTY_QUEUE_POLL_INTERVAL = 1.0

# Error recovery delay
ERROR_RECOVERY_DELAY = 5.0


async def _enqueue_verify_nli_if_needed(task_id: str, result: dict) -> None:
    """
    Enqueue VERIFY_NLI job after target completion.

    Always enqueues for completed targets - the verify_claims_nli function
    queries the DB for claims and handles empty cases gracefully.
    This ensures Academic API-extracted claims (which may not appear in
    the result dict) are also verified.

    ADR-0005: Cross-source NLI verification is triggered per target_queue job.

    Args:
        task_id: Task ID.
        result: Result dict from search_action/ingest_url_action (used for logging only).
    """
    # Log what the target produced (for debugging)
    pages_fetched = result.get("pages_fetched", 0)
    status = result.get("status", "unknown")

    logger.debug(
        "Enqueuing VERIFY_NLI job after target completion",
        task_id=task_id,
        target_status=status,
        pages_fetched=pages_fetched,
    )

    try:
        from src.filter.cross_verification import enqueue_verify_nli_job

        await enqueue_verify_nli_job(task_id=task_id)
    except Exception as e:
        # Don't fail the target if VERIFY_NLI enqueue fails
        logger.warning(
            "Failed to enqueue VERIFY_NLI job",
            task_id=task_id,
            error=str(e),
        )


async def _get_exploration_state(task_id: str) -> ExplorationState:
    """Get or create exploration state for a task.

    This is a helper to avoid circular imports with server.py.
    Uses the same cache as the MCP server.
    """
    from src.mcp.helpers import get_exploration_state as get_state

    state: ExplorationState = await get_state(task_id)
    return state


async def _target_queue_worker(worker_id: int) -> None:
    """
    Target queue worker coroutine.

    Processes jobs from the target queue (kind='target_queue') in priority order.

    Scheduling policy:
    - priority ASC (high first), then queued_at ASC (FIFO within same priority)
    - No per-task sequential guarantee (a task may have multiple targets in parallel)

    Claim semantics:
    - Uses compare-and-swap (CAS) to atomically claim jobs
    - Prevents two workers from processing the same job

    Cancellation support (ADR-0010 mode=immediate):
    - Registers running jobs with TargetQueueWorkerManager for cancellation tracking
    - Uses conditional UPDATE (WHERE state='running') to prevent overwriting cancelled state

    Args:
        worker_id: Unique identifier for this worker (0 to num_workers-1).
    """
    from src.research.pipeline import search_action

    logger.info("Target queue worker started", worker_id=worker_id)

    while True:
        try:
            db = await get_database()

            # Dequeue: Find next queued job
            # Ordered by priority ASC (lower = higher priority), then queued_at ASC (FIFO)
            row = await db.fetch_one(
                """
                SELECT id, task_id, input_json
                FROM jobs
                WHERE kind = 'target_queue' AND state = 'queued'
                ORDER BY priority ASC, queued_at ASC
                LIMIT 1
                """
            )

            if row is None:
                # Queue is empty - notify batch notification manager (ADR-0007)
                try:
                    from src.utils.batch_notification import notify_target_queue_empty

                    await notify_target_queue_empty()
                except Exception as e:
                    logger.debug("Batch notification failed", error=str(e))

                # Wait before checking again
                await asyncio.sleep(EMPTY_QUEUE_POLL_INTERVAL)
                continue

            target_id = row["id"]
            task_id = row["task_id"]
            input_json = row["input_json"]

            # Parse input data
            try:
                input_data = json.loads(input_json) if input_json else {}
            except json.JSONDecodeError:
                input_data = {}

            target = input_data.get("target", {})
            target_kind = target.get("kind", "query")
            options = input_data.get("options", {})

            # Attempt to claim the job (CAS)
            # UPDATE only succeeds if state is still 'queued'
            cursor = await db.execute(
                """
                UPDATE jobs
                SET state = 'running', started_at = ?
                WHERE id = ? AND state = 'queued'
                """,
                (datetime.now(UTC).isoformat(), target_id),
            )

            # Check if we won the race
            rowcount = getattr(cursor, "rowcount", 0)
            if rowcount != 1:
                # Another worker claimed it - retry loop
                logger.debug(
                    "Job claimed by another worker",
                    target_id=target_id,
                    worker_id=worker_id,
                )
                continue

            with LogContext(task_id=task_id, target_id=target_id):
                # Log differently based on target kind
                if target_kind == "query":
                    query = target.get("query", "")
                    logger.info(
                        "Processing query target from queue",
                        target_id=target_id,
                        task_id=task_id,
                        query=query[:100] if query else "",
                        worker_id=worker_id,
                    )
                else:
                    url = target.get("url", "")
                    logger.info(
                        "Processing URL target from queue",
                        target_id=target_id,
                        task_id=task_id,
                        url=url[:100] if url else "",
                        reason=target.get("reason", "manual"),
                        depth=target.get("depth", 0),
                        worker_id=worker_id,
                    )

                # Get exploration state
                try:
                    state = await _get_exploration_state(task_id)
                except Exception as e:
                    logger.error(
                        "Failed to get exploration state",
                        target_id=target_id,
                        task_id=task_id,
                        error=str(e),
                    )
                    # Mark as failed
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'failed', finished_at = ?, error_message = ?
                        WHERE id = ?
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            f"Failed to get exploration state: {e}",
                            target_id,
                        ),
                    )
                    continue

                # Execute target based on kind
                manager = get_worker_manager()

                if target_kind == "query":
                    # Query target: Execute search_action
                    query = target.get("query", "")
                    query_options = target.get("options", {})
                    merged_options = {**options, **query_options}

                    # ADR-0007: Pass target_job_id for CAPTCHA queue integration
                    # ADR-0014 Phase 3: Pass worker_id for context isolation
                    options_with_job = {
                        **merged_options,
                        "task_id": task_id,
                        "target_job_id": target_id,
                        "worker_id": worker_id,
                    }
                    target_task = asyncio.create_task(
                        search_action(
                            task_id=task_id,
                            query=query,
                            state=state,
                            options=options_with_job,
                        ),
                        name=f"search_action_{target_id}",
                    )
                elif target_kind == "url":
                    # URL target: Execute ingest_url_action
                    from src.research.pipeline import ingest_url_action

                    url = target.get("url", "")
                    depth = target.get("depth", 0)
                    reason = target.get("reason", "manual")
                    context = target.get("context", {})
                    policy = target.get("policy", {})

                    options_with_job = {
                        **options,
                        "task_id": task_id,
                        "target_job_id": target_id,
                        "worker_id": worker_id,
                    }
                    target_task = asyncio.create_task(
                        ingest_url_action(
                            task_id=task_id,
                            url=url,
                            state=state,
                            depth=depth,
                            reason=reason,
                            context=context,
                            policy=policy,
                            options=options_with_job,
                        ),
                        name=f"ingest_url_action_{target_id}",
                    )
                else:
                    # DOI target: Execute ingest_doi_action
                    from src.research.pipeline import ingest_doi_action

                    doi = target.get("doi", "")
                    reason = target.get("reason", "manual")
                    context = target.get("context", {})

                    options_with_job = {
                        **options,
                        "task_id": task_id,
                        "target_job_id": target_id,
                        "worker_id": worker_id,
                    }
                    target_task = asyncio.create_task(
                        ingest_doi_action(
                            task_id=task_id,
                            doi=doi,
                            state=state,
                            reason=reason,
                            context=context,
                            options=options_with_job,
                        ),
                        name=f"ingest_doi_action_{target_id}",
                    )

                manager.register_job(target_id, task_id, target_task)

                try:
                    result = await target_task

                    # ADR-0007: Check if CAPTCHA was queued - set awaiting_auth state
                    if result.get("captcha_queued"):
                        cursor = await db.execute(
                            """
                            UPDATE jobs
                            SET state = 'awaiting_auth', finished_at = ?, output_json = ?
                            WHERE id = ? AND state = 'running'
                            """,
                            (
                                datetime.now(UTC).isoformat(),
                                json.dumps(result, ensure_ascii=False),
                                target_id,
                            ),
                        )
                        if getattr(cursor, "rowcount", 0) > 0:
                            state.notify_status_change()
                            logger.info(
                                "Target awaiting auth (CAPTCHA queued)",
                                target_id=target_id,
                                task_id=task_id,
                                queue_id=result.get("queue_id"),
                            )
                    else:
                        # Success - update state to 'completed' with race condition protection
                        # Only update if state is still 'running' (prevents overwriting 'cancelled')
                        cursor = await db.execute(
                            """
                            UPDATE jobs
                            SET state = 'completed', finished_at = ?, output_json = ?
                            WHERE id = ? AND state = 'running'
                            """,
                            (
                                datetime.now(UTC).isoformat(),
                                json.dumps(result, ensure_ascii=False),
                                target_id,
                            ),
                        )

                        if getattr(cursor, "rowcount", 0) == 0:
                            # Job was cancelled while we were processing - don't log as completed
                            logger.info(
                                "Target completion skipped (job already cancelled)",
                                target_id=target_id,
                                task_id=task_id,
                            )
                        else:
                            # Notify long polling clients
                            state.notify_status_change()

                            logger.info(
                                "Target completed from queue",
                                target_id=target_id,
                                task_id=task_id,
                                target_kind=target_kind,
                                status=result.get("status"),
                                pages_fetched=result.get("pages_fetched"),
                            )

                            # ADR-0005: Enqueue VERIFY_NLI job for cross-source verification
                            # This runs NLI on new claims against fragments from other sources
                            await _enqueue_verify_nli_if_needed(task_id, result)

                except asyncio.CancelledError:
                    # stop_task(mode=immediate) cancelled this target_task
                    # The worker itself continues running (does NOT break)
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'cancelled', finished_at = ?
                        WHERE id = ? AND state = 'running'
                        """,
                        (datetime.now(UTC).isoformat(), target_id),
                    )

                    # Notify long polling clients
                    try:
                        state.notify_status_change()
                    except Exception:
                        pass  # Ignore notification errors during cancellation

                    logger.info(
                        "Target cancelled from queue",
                        target_id=target_id,
                        task_id=task_id,
                    )
                    # Do NOT re-raise: worker continues to next job

                except Exception as e:
                    # Target failed - update state to 'failed'
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'failed', finished_at = ?, error_message = ?
                        WHERE id = ? AND state = 'running'
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            str(e)[:1000],  # Truncate long error messages
                            target_id,
                        ),
                    )

                    # Notify long polling clients
                    state.notify_status_change()

                    logger.error(
                        "Target failed from queue",
                        target_id=target_id,
                        task_id=task_id,
                        target_kind=target_kind,
                        error=str(e),
                        exc_info=True,
                    )

                finally:
                    # Always unregister job when done (success, failure, or cancel)
                    manager.unregister_job(target_id)

        except asyncio.CancelledError:
            # Worker shutdown
            logger.info("Target queue worker shutting down", worker_id=worker_id)
            break

        except Exception as e:
            # Worker-level error - log and continue
            logger.error(
                "Target queue worker error",
                worker_id=worker_id,
                error=str(e),
                exc_info=True,
            )
            await asyncio.sleep(ERROR_RECOVERY_DELAY)

    logger.info("Target queue worker stopped", worker_id=worker_id)


class TargetQueueWorkerManager:
    """Manages lifecycle of target queue workers.

    Provides start/stop methods for integration with run_server().
    Also tracks running jobs for cancellation support (ADR-0010 mode=immediate).
    """

    def __init__(self) -> None:
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        # Running job tracking: target_id -> (task_id, asyncio.Task)
        # Used by cancel_jobs_for_task() for mode=immediate cancellation
        self._running_jobs: dict[str, tuple[str, asyncio.Task[Any]]] = {}

    def register_job(self, target_id: str, task_id: str, job_task: asyncio.Task[Any]) -> None:
        """Register a running target job for cancellation tracking.

        Called by worker when it starts processing a target.

        Args:
            target_id: The target job ID (jobs.id).
            task_id: The research task ID (tasks.id).
            job_task: The asyncio.Task running the search_action/ingest_url_action.
        """
        self._running_jobs[target_id] = (task_id, job_task)
        logger.debug(
            "Registered running job",
            target_id=target_id,
            task_id=task_id,
            total_running=len(self._running_jobs),
        )

    def unregister_job(self, target_id: str) -> None:
        """Unregister a completed/failed/cancelled target job.

        Called by worker when target processing finishes (any outcome).

        Args:
            target_id: The target job ID to unregister.
        """
        if target_id in self._running_jobs:
            del self._running_jobs[target_id]
            logger.debug(
                "Unregistered job",
                target_id=target_id,
                total_running=len(self._running_jobs),
            )

    async def cancel_jobs_for_task(self, task_id: str) -> int:
        """Cancel all running target jobs for a specific task.

        Used by stop_task(mode=immediate) to cancel in-flight targets.

        Args:
            task_id: The research task ID whose jobs should be cancelled.

        Returns:
            Number of jobs that were cancelled.
        """
        cancelled_count = 0
        jobs_to_cancel: list[tuple[str, asyncio.Task[Any]]] = []

        # Find all jobs for this task
        for target_id, (job_task_id, job_task) in list(self._running_jobs.items()):
            if job_task_id == task_id and not job_task.done():
                jobs_to_cancel.append((target_id, job_task))

        if not jobs_to_cancel:
            return 0

        # Yield to let tasks start running (necessary for proper cancellation)
        await asyncio.sleep(0)

        # Cancel each job
        for target_id, job_task in jobs_to_cancel:
            if not job_task.done():
                job_task.cancel()
                cancelled_count += 1
                logger.info(
                    "Cancelled running target job",
                    target_id=target_id,
                    task_id=task_id,
                )

        # Wait for cancellations to propagate (with timeout)
        if cancelled_count > 0:
            tasks_to_wait = [job_task for _, job_task in jobs_to_cancel if not job_task.done()]
            if tasks_to_wait:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks_to_wait, return_exceptions=True),
                        timeout=5.0,
                    )
                except TimeoutError:
                    logger.warning(
                        "Timeout waiting for job cancellations",
                        task_id=task_id,
                        pending_count=len(tasks_to_wait),
                    )

        return cancelled_count

    async def wait_for_task_jobs_to_complete(self, task_id: str, timeout: float = 30.0) -> int:
        """Wait for all running target jobs for a task to complete.

        Used by stop_task(mode=graceful) to wait for running jobs to finish naturally.
        Does NOT cancel the jobs, just waits for them.

        Args:
            task_id: The research task ID whose jobs to wait for.
            timeout: Maximum time to wait in seconds.

        Returns:
            Number of jobs that were waited on.
        """
        jobs_to_wait: list[tuple[str, asyncio.Task[Any]]] = []

        # Find all jobs for this task
        for target_id, (job_task_id, job_task) in list(self._running_jobs.items()):
            if job_task_id == task_id and not job_task.done():
                jobs_to_wait.append((target_id, job_task))

        if not jobs_to_wait:
            return 0

        logger.info(
            "Waiting for running jobs to complete",
            task_id=task_id,
            job_count=len(jobs_to_wait),
            timeout=timeout,
        )

        # Wait for jobs to complete (with timeout)
        tasks_to_wait = [job_task for _, job_task in jobs_to_wait]
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_to_wait, return_exceptions=True),
                timeout=timeout,
            )
            logger.info(
                "All running jobs completed",
                task_id=task_id,
                job_count=len(jobs_to_wait),
            )
        except TimeoutError:
            logger.warning(
                "Timeout waiting for jobs to complete (will proceed with finalization)",
                task_id=task_id,
                pending_count=len([t for t in tasks_to_wait if not t.done()]),
            )

        return len(jobs_to_wait)

    async def start(self) -> None:
        """Start all target queue workers."""
        if self._started:
            return

        self._started = True
        self._workers = []
        self._running_jobs = {}

        # Read num_workers from config (ADR-0010)
        settings = get_settings()
        num_workers = settings.concurrency.target_queue.num_workers

        for i in range(num_workers):
            task = asyncio.create_task(
                _target_queue_worker(i),
                name=f"target_queue_worker_{i}",
            )
            self._workers.append(task)

        logger.info(
            "Target queue workers started",
            num_workers=num_workers,
        )

    async def stop(self) -> None:
        """Stop all target queue workers gracefully."""
        if not self._started:
            return

        self._started = False

        # Cancel all workers
        for task in self._workers:
            task.cancel()

        # Wait for cancellation to complete
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._workers = []
        self._running_jobs = {}
        logger.info("Target queue workers stopped")

    @property
    def is_running(self) -> bool:
        """Check if workers are running."""
        return self._started

    @property
    def running_job_count(self) -> int:
        """Get count of currently running jobs."""
        return len(self._running_jobs)


# Global manager instance
_worker_manager: TargetQueueWorkerManager | None = None


def get_worker_manager() -> TargetQueueWorkerManager:
    """Get or create the global worker manager."""
    global _worker_manager
    if _worker_manager is None:
        _worker_manager = TargetQueueWorkerManager()
    return _worker_manager
