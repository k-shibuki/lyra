"""
Search queue worker for Lyra.

Background worker that processes search queue jobs (kind='search_queue').
Implements async search execution per ADR-0010.

Worker lifecycle:
- Started when run_server() starts
- Stopped (cancelled) when run_server() shuts down
- Runs 2 workers for parallel execution
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


async def _get_exploration_state(task_id: str) -> "ExplorationState":
    """Get or create exploration state for a task.

    This is a helper to avoid circular imports with server.py.
    Uses the same cache as the MCP server.
    """
    from src.mcp.server import _get_exploration_state as get_state

    state: ExplorationState = await get_state(task_id)
    return state


async def _search_queue_worker(worker_id: int) -> None:
    """
    Search queue worker coroutine.

    Processes jobs from the search queue (kind='search_queue') in priority order.

    Scheduling policy:
    - priority ASC (high first), then queued_at ASC (FIFO within same priority)
    - No per-task sequential guarantee (a task may have multiple searches in parallel)

    Claim semantics:
    - Uses compare-and-swap (CAS) to atomically claim jobs
    - Prevents two workers from processing the same job

    Cancellation support (ADR-0010 mode=immediate):
    - Registers running jobs with SearchQueueWorkerManager for cancellation tracking
    - Uses conditional UPDATE (WHERE state='running') to prevent overwriting cancelled state

    Args:
        worker_id: Unique identifier for this worker (0 to num_workers-1).
    """
    from src.research.pipeline import search_action

    logger.info("Search queue worker started", worker_id=worker_id)

    while True:
        try:
            db = await get_database()

            # Dequeue: Find next queued job
            # Ordered by priority ASC (lower = higher priority), then queued_at ASC (FIFO)
            row = await db.fetch_one(
                """
                SELECT id, task_id, input_json
                FROM jobs
                WHERE kind = 'search_queue' AND state = 'queued'
                ORDER BY priority ASC, queued_at ASC
                LIMIT 1
                """
            )

            if row is None:
                # Queue is empty - notify batch notification manager (ADR-0007)
                try:
                    from src.utils.notification import notify_search_queue_empty

                    await notify_search_queue_empty()
                except Exception as e:
                    logger.debug("Batch notification failed", error=str(e))

                # Wait before checking again
                await asyncio.sleep(EMPTY_QUEUE_POLL_INTERVAL)
                continue

            search_id = row["id"]
            task_id = row["task_id"]
            input_json = row["input_json"]

            # Parse input data
            try:
                input_data = json.loads(input_json) if input_json else {}
            except json.JSONDecodeError:
                input_data = {}

            query = input_data.get("query", "")
            options = input_data.get("options", {})

            # Attempt to claim the job (CAS)
            # UPDATE only succeeds if state is still 'queued'
            cursor = await db.execute(
                """
                UPDATE jobs
                SET state = 'running', started_at = ?
                WHERE id = ? AND state = 'queued'
                """,
                (datetime.now(UTC).isoformat(), search_id),
            )

            # Check if we won the race
            rowcount = getattr(cursor, "rowcount", 0)
            if rowcount != 1:
                # Another worker claimed it - retry loop
                logger.debug(
                    "Job claimed by another worker",
                    search_id=search_id,
                    worker_id=worker_id,
                )
                continue

            with LogContext(task_id=task_id, search_id=search_id):
                logger.info(
                    "Processing search from queue",
                    search_id=search_id,
                    task_id=task_id,
                    query=query[:100] if query else "",
                    worker_id=worker_id,
                )

                # Get exploration state
                try:
                    state = await _get_exploration_state(task_id)
                except Exception as e:
                    logger.error(
                        "Failed to get exploration state",
                        search_id=search_id,
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
                            search_id,
                        ),
                    )
                    continue

                # Execute search with job tracking for cancellation support
                # Wrap search_action in a separate task so we can cancel it
                # without killing the worker itself (ADR-0010 mode=immediate)
                # ADR-0007: Pass search_job_id for CAPTCHA queue integration
                options_with_job = {
                    **options,
                    "task_id": task_id,
                    "search_job_id": search_id,
                }
                manager = get_worker_manager()
                search_task = asyncio.create_task(
                    search_action(
                        task_id=task_id,
                        query=query,
                        state=state,
                        options=options_with_job,
                    ),
                    name=f"search_action_{search_id}",
                )
                manager.register_job(search_id, task_id, search_task)

                try:
                    result = await search_task

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
                                search_id,
                            ),
                        )
                        if getattr(cursor, "rowcount", 0) > 0:
                            state.notify_status_change()
                            logger.info(
                                "Search awaiting auth (CAPTCHA queued)",
                                search_id=search_id,
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
                                search_id,
                            ),
                        )

                        if getattr(cursor, "rowcount", 0) == 0:
                            # Job was cancelled while we were processing - don't log as completed
                            logger.info(
                                "Search completion skipped (job already cancelled)",
                                search_id=search_id,
                                task_id=task_id,
                            )
                        else:
                            # Notify long polling clients
                            state.notify_status_change()

                            logger.info(
                                "Search completed from queue",
                                search_id=search_id,
                                task_id=task_id,
                                status=result.get("status"),
                                pages_fetched=result.get("pages_fetched"),
                            )

                except asyncio.CancelledError:
                    # stop_task(mode=immediate) cancelled this search_task
                    # The worker itself continues running (does NOT break)
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'cancelled', finished_at = ?
                        WHERE id = ? AND state = 'running'
                        """,
                        (datetime.now(UTC).isoformat(), search_id),
                    )

                    # Notify long polling clients
                    try:
                        state.notify_status_change()
                    except Exception:
                        pass  # Ignore notification errors during cancellation

                    logger.info(
                        "Search cancelled from queue",
                        search_id=search_id,
                        task_id=task_id,
                    )
                    # Do NOT re-raise: worker continues to next job

                except Exception as e:
                    # Search failed - update state to 'failed'
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'failed', finished_at = ?, error_message = ?
                        WHERE id = ? AND state = 'running'
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            str(e)[:1000],  # Truncate long error messages
                            search_id,
                        ),
                    )

                    # Notify long polling clients
                    state.notify_status_change()

                    logger.error(
                        "Search failed from queue",
                        search_id=search_id,
                        task_id=task_id,
                        error=str(e),
                        exc_info=True,
                    )

                finally:
                    # Always unregister job when done (success, failure, or cancel)
                    manager.unregister_job(search_id)

        except asyncio.CancelledError:
            # Worker shutdown
            logger.info("Search queue worker shutting down", worker_id=worker_id)
            break

        except Exception as e:
            # Worker-level error - log and continue
            logger.error(
                "Search queue worker error",
                worker_id=worker_id,
                error=str(e),
                exc_info=True,
            )
            await asyncio.sleep(ERROR_RECOVERY_DELAY)

    logger.info("Search queue worker stopped", worker_id=worker_id)


class SearchQueueWorkerManager:
    """Manages lifecycle of search queue workers.

    Provides start/stop methods for integration with run_server().
    Also tracks running jobs for cancellation support (ADR-0010 mode=immediate).
    """

    def __init__(self) -> None:
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        # Running job tracking: search_id -> (task_id, asyncio.Task)
        # Used by cancel_jobs_for_task() for mode=immediate cancellation
        self._running_jobs: dict[str, tuple[str, asyncio.Task[Any]]] = {}

    def register_job(self, search_id: str, task_id: str, job_task: asyncio.Task[Any]) -> None:
        """Register a running search job for cancellation tracking.

        Called by worker when it starts processing a search.

        Args:
            search_id: The search job ID (jobs.id).
            task_id: The research task ID (tasks.id).
            job_task: The asyncio.Task running the search_action.
        """
        self._running_jobs[search_id] = (task_id, job_task)
        logger.debug(
            "Registered running job",
            search_id=search_id,
            task_id=task_id,
            total_running=len(self._running_jobs),
        )

    def unregister_job(self, search_id: str) -> None:
        """Unregister a completed/failed/cancelled search job.

        Called by worker when search processing finishes (any outcome).

        Args:
            search_id: The search job ID to unregister.
        """
        if search_id in self._running_jobs:
            del self._running_jobs[search_id]
            logger.debug(
                "Unregistered job",
                search_id=search_id,
                total_running=len(self._running_jobs),
            )

    async def cancel_jobs_for_task(self, task_id: str) -> int:
        """Cancel all running search jobs for a specific task.

        Used by stop_task(mode=immediate) to cancel in-flight searches.

        Args:
            task_id: The research task ID whose jobs should be cancelled.

        Returns:
            Number of jobs that were cancelled.
        """
        cancelled_count = 0
        jobs_to_cancel: list[tuple[str, asyncio.Task[Any]]] = []

        # Find all jobs for this task
        for search_id, (job_task_id, job_task) in list(self._running_jobs.items()):
            if job_task_id == task_id and not job_task.done():
                jobs_to_cancel.append((search_id, job_task))

        if not jobs_to_cancel:
            return 0

        # Yield to let tasks start running (necessary for proper cancellation)
        await asyncio.sleep(0)

        # Cancel each job
        for search_id, job_task in jobs_to_cancel:
            if not job_task.done():
                job_task.cancel()
                cancelled_count += 1
                logger.info(
                    "Cancelled running search job",
                    search_id=search_id,
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

    async def start(self) -> None:
        """Start all search queue workers."""
        if self._started:
            return

        self._started = True
        self._workers = []
        self._running_jobs = {}

        # Read num_workers from config (ADR-0015)
        settings = get_settings()
        num_workers = settings.concurrency.search_queue.num_workers

        for i in range(num_workers):
            task = asyncio.create_task(
                _search_queue_worker(i),
                name=f"search_queue_worker_{i}",
            )
            self._workers.append(task)

        logger.info(
            "Search queue workers started",
            num_workers=num_workers,
        )

    async def stop(self) -> None:
        """Stop all search queue workers gracefully."""
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
        logger.info("Search queue workers stopped")

    @property
    def is_running(self) -> bool:
        """Check if workers are running."""
        return self._started

    @property
    def running_job_count(self) -> int:
        """Get count of currently running jobs."""
        return len(self._running_jobs)


# Global manager instance
_worker_manager: SearchQueueWorkerManager | None = None


def get_worker_manager() -> SearchQueueWorkerManager:
    """Get or create the global worker manager."""
    global _worker_manager
    if _worker_manager is None:
        _worker_manager = SearchQueueWorkerManager()
    return _worker_manager
