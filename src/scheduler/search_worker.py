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
from typing import TYPE_CHECKING

from src.storage.database import get_database
from src.utils.logging import LogContext, get_logger

if TYPE_CHECKING:
    from src.research.state import ExplorationState

logger = get_logger(__name__)

# Number of parallel workers (ADR-0010)
NUM_WORKERS = 2

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

    return await get_state(task_id)


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

    Args:
        worker_id: Unique identifier for this worker (0 to NUM_WORKERS-1).
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
                # Queue is empty - wait before checking again
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

                # Execute search
                try:
                    result = await search_action(
                        task_id=task_id,
                        query=query,
                        state=state,
                        options=options,
                    )

                    # Success - update state to 'completed'
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'completed', finished_at = ?, output_json = ?
                        WHERE id = ?
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            json.dumps(result, ensure_ascii=False),
                            search_id,
                        ),
                    )

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
                    # Worker shutdown or stop_task(mode=immediate)
                    # Mark as cancelled and re-raise
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'cancelled', finished_at = ?
                        WHERE id = ?
                        """,
                        (datetime.now(UTC).isoformat(), search_id),
                    )

                    logger.info(
                        "Search cancelled from queue",
                        search_id=search_id,
                        task_id=task_id,
                    )
                    raise  # Re-raise to propagate cancellation

                except Exception as e:
                    # Search failed - update state to 'failed'
                    await db.execute(
                        """
                        UPDATE jobs
                        SET state = 'failed', finished_at = ?, error_message = ?
                        WHERE id = ?
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
    """

    def __init__(self) -> None:
        self._workers: list[asyncio.Task[None]] = []
        self._started = False

    async def start(self) -> None:
        """Start all search queue workers."""
        if self._started:
            return

        self._started = True
        self._workers = []

        for i in range(NUM_WORKERS):
            task = asyncio.create_task(
                _search_queue_worker(i),
                name=f"search_queue_worker_{i}",
            )
            self._workers.append(task)

        logger.info(
            "Search queue workers started",
            num_workers=NUM_WORKERS,
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
        logger.info("Search queue workers stopped")

    @property
    def is_running(self) -> bool:
        """Check if workers are running."""
        return self._started


# Global manager instance
_worker_manager: SearchQueueWorkerManager | None = None


def get_worker_manager() -> SearchQueueWorkerManager:
    """Get or create the global worker manager."""
    global _worker_manager
    if _worker_manager is None:
        _worker_manager = SearchQueueWorkerManager()
    return _worker_manager
