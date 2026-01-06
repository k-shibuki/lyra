"""
Job scheduler for Lyra.
Manages job queues, slots, and resource allocation.
Implements budget control per ADR-0010 and ADR-0003.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast

from src.scheduler.budget import (
    BudgetExceededReason,
    BudgetManager,
    get_budget_manager,
)
from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


class JobKind(str, Enum):
    """Job types with priority order.

    Note:
        Per ADR-0004: LLM_FAST/LLM_SLOW are unified into LLM (single 3B model).
        Per ADR-0010: SEARCH_QUEUE added for async search queue architecture.
        Per ADR-0005: VERIFY_NLI added for automatic cross-source NLI verification.
        Per ADR-0015: CITATION_GRAPH added for deferred citation graph processing.
    """

    SERP = "serp"
    FETCH = "fetch"
    EXTRACT = "extract"
    EMBED = "embed"
    LLM = "llm"  # Single LLM job type (per ADR-0004)
    NLI = "nli"
    SEARCH_QUEUE = "search_queue"  # Async search queue (per ADR-0010)
    VERIFY_NLI = "verify_nli"  # Cross-source NLI verification (per ADR-0005)
    CITATION_GRAPH = "citation_graph"  # Deferred citation graph processing (per ADR-0015)


class Slot(str, Enum):
    """Resource slots."""

    GPU = "gpu"
    BROWSER_HEADFUL = "browser_headful"
    NETWORK_CLIENT = "network_client"
    CPU_NLP = "cpu_nlp"


class JobState(str, Enum):
    """Job states."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_AUTH = "awaiting_auth"  # ADR-0007: Paused for CAPTCHA/auth resolution


# Job kind to slot mapping
KIND_TO_SLOT = {
    JobKind.SERP: Slot.NETWORK_CLIENT,
    JobKind.FETCH: Slot.NETWORK_CLIENT,
    JobKind.EXTRACT: Slot.CPU_NLP,
    JobKind.EMBED: Slot.GPU,
    JobKind.LLM: Slot.GPU,  # Single LLM slot (per ADR-0004)
    JobKind.NLI: Slot.CPU_NLP,
    JobKind.SEARCH_QUEUE: Slot.NETWORK_CLIENT,  # Async search queue (per ADR-0010)
    JobKind.VERIFY_NLI: Slot.CPU_NLP,  # Cross-source NLI verification (per ADR-0005)
    JobKind.CITATION_GRAPH: Slot.CPU_NLP,  # Deferred citation graph (per ADR-0015)
}

# Priority order (lower = higher priority)
KIND_PRIORITY = {
    JobKind.SERP: 10,
    JobKind.FETCH: 20,
    JobKind.EXTRACT: 30,
    JobKind.EMBED: 40,
    JobKind.LLM: 60,  # Single LLM priority (per ADR-0004)
    JobKind.NLI: 35,
    JobKind.SEARCH_QUEUE: 25,  # Between FETCH and EXTRACT (per ADR-0010)
    JobKind.VERIFY_NLI: 45,  # After EMBED, before LLM (per ADR-0005)
    JobKind.CITATION_GRAPH: 50,  # After VERIFY_NLI, before LLM (per ADR-0015)
}

# Slot concurrency limits
SLOT_LIMITS = {
    Slot.GPU: 1,
    Slot.BROWSER_HEADFUL: 1,
    Slot.NETWORK_CLIENT: 4,
    Slot.CPU_NLP: 8,
}

# Exclusive slots (cannot run together)
EXCLUSIVE_SLOTS = [
    {Slot.GPU, Slot.BROWSER_HEADFUL},
]


class JobScheduler:
    """Job scheduler with slot-based resource management and budget control."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._queues: dict[Slot, asyncio.PriorityQueue] = {}
        self._running: dict[Slot, set[str]] = {}
        self._workers: dict[Slot, list[asyncio.Task]] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._budget_manager: BudgetManager | None = None

        # Job timing for LLM ratio tracking
        self._job_start_times: dict[str, float] = {}

        # Initialize queues and running sets
        for slot in Slot:
            self._queues[slot] = asyncio.PriorityQueue()
            self._running[slot] = set()

    async def start(self) -> None:
        """Start the scheduler workers."""
        if self._started:
            return

        self._started = True

        # Initialize budget manager
        self._budget_manager = await get_budget_manager()

        # Start worker tasks for each slot
        for slot in Slot:
            limit = SLOT_LIMITS[slot]
            workers = []
            for i in range(limit):
                task = asyncio.create_task(self._worker(slot, i))
                workers.append(task)
            self._workers[slot] = workers

        logger.info("Job scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        if not self._started:
            return

        self._started = False

        # Cancel all workers
        for _slot, workers in self._workers.items():
            for task in workers:
                task.cancel()

        # Wait for cancellation
        for _slot, workers in self._workers.items():
            for task in workers:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._workers.clear()
        logger.info("Job scheduler stopped")

    async def submit(
        self,
        kind: JobKind | str,
        input_data: dict[str, Any],
        *,
        priority: int | None = None,
        task_id: str | None = None,
        cause_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a job for execution.

        Args:
            kind: Job kind.
            input_data: Job input data.
            priority: Override priority (lower = higher).
            task_id: Associated task ID.
            cause_id: Causal trace ID.

        Returns:
            Job submission result.
        """
        if isinstance(kind, str):
            kind = JobKind(kind)

        slot = KIND_TO_SLOT[kind]

        if priority is None:
            priority = KIND_PRIORITY[kind]

        job_id = str(uuid.uuid4())

        # Budget check for tasks with budget
        if task_id and self._budget_manager:
            budget_ok, budget_reason = await self._check_budget(task_id, kind)
            if not budget_ok:
                logger.warning(
                    "Job rejected due to budget",
                    job_id=job_id,
                    task_id=task_id,
                    kind=kind.value,
                    reason=budget_reason,
                )
                return {
                    "accepted": False,
                    "job_id": job_id,
                    "reason": f"budget_{budget_reason}",
                }

        # Check exclusivity
        can_queue = await self._check_exclusivity(slot)
        if not can_queue:
            return {
                "accepted": False,
                "job_id": job_id,
                "reason": "exclusive_slot_busy",
            }

        # Store job in database
        db = await get_database()
        await db.insert(
            "jobs",
            {
                "id": job_id,
                "task_id": task_id,
                "kind": kind.value,
                "priority": priority,
                "slot": slot.value,
                "state": JobState.QUEUED.value,
                "input_json": str(input_data),
                "queued_at": datetime.now(UTC).isoformat(),
                "cause_id": cause_id,
            },
        )

        # Add to queue
        await self._queues[slot].put((priority, job_id, input_data, kind, task_id, cause_id))

        logger.info(
            "Job submitted",
            job_id=job_id,
            kind=kind.value,
            slot=slot.value,
            priority=priority,
        )

        return {
            "accepted": True,
            "job_id": job_id,
            "slot": slot.value,
            "priority": priority,
            "eta": await self._estimate_eta(slot),
        }

    async def _check_budget(
        self,
        task_id: str,
        kind: JobKind,
    ) -> tuple[bool, str | None]:
        """
        Check if job is within task budget.

        Args:
            task_id: Task identifier.
            kind: Job kind.

        Returns:
            Tuple of (can_proceed, reason_if_not).
        """
        if not self._budget_manager:
            return True, None

        # Check general budget (time and page limits)
        can_continue, reason = await self._budget_manager.check_and_update(task_id)
        if not can_continue:
            return False, reason.value if reason else "budget_exceeded"

        # For FETCH jobs, check page limit
        if kind == JobKind.FETCH:
            can_fetch = await self._budget_manager.can_fetch_page(task_id)
            if not can_fetch:
                return False, BudgetExceededReason.PAGE_LIMIT.value

        # For LLM jobs, check ratio limit
        if kind == JobKind.LLM:
            # Estimate LLM time (single 3B model ~5s per ADR-0004)
            estimated_time = 5.0
            can_run = await self._budget_manager.can_run_llm(task_id, estimated_time)
            if not can_run:
                return False, BudgetExceededReason.LLM_RATIO.value

        return True, None

    async def _check_exclusivity(self, slot: Slot) -> bool:
        """Check if slot can accept jobs based on exclusivity rules.

        Args:
            slot: Target slot.

        Returns:
            True if slot can accept jobs.
        """
        async with self._lock:
            for exclusive_group in EXCLUSIVE_SLOTS:
                if slot in exclusive_group:
                    # Check if any other slot in the group is busy
                    for other_slot in exclusive_group:
                        if other_slot != slot and len(self._running[other_slot]) > 0:
                            return False
        return True

    async def _estimate_eta(self, slot: Slot) -> str:
        """Estimate time until job starts.

        Args:
            slot: Target slot.

        Returns:
            ETA string.
        """
        queue_size = self._queues[slot].qsize()
        running_count = len(self._running[slot])
        limit = SLOT_LIMITS[slot]

        # Simple estimate: assume each job takes 30 seconds
        waiting = max(0, queue_size - (limit - running_count))
        eta_seconds = waiting * 30

        if eta_seconds < 60:
            return f"{eta_seconds}s"
        else:
            return f"{eta_seconds // 60}m"

    async def _record_budget_consumption(
        self,
        task_id: str | None,
        kind: JobKind,
        job_start_time: float,
    ) -> None:
        """
        Record budget consumption after job completion.

        Args:
            task_id: Task identifier.
            kind: Job kind.
            job_start_time: When the job started (time.time()).
        """
        if not task_id or not self._budget_manager:
            return

        job_duration = time.time() - job_start_time

        # Record page fetch
        if kind == JobKind.FETCH:
            await self._budget_manager.check_and_update(
                task_id,
                record_page=True,
            )
            logger.debug(
                "Page fetch recorded",
                task_id=task_id,
                duration=job_duration,
            )

        # Record LLM time
        if kind == JobKind.LLM:
            await self._budget_manager.check_and_update(
                task_id,
                llm_time_seconds=job_duration,
            )
            logger.debug(
                "LLM time recorded",
                task_id=task_id,
                kind=kind.value,
                duration=job_duration,
            )

    async def _worker(self, slot: Slot, worker_id: int) -> None:
        """Worker coroutine for a slot.

        Args:
            slot: Slot to work on.
            worker_id: Worker ID within slot.
        """
        logger.debug("Worker started", slot=slot.value, worker_id=worker_id)

        while self._started:
            try:
                # Get job from queue
                priority, job_id, input_data, kind, task_id, cause_id = await asyncio.wait_for(
                    self._queues[slot].get(),
                    timeout=1.0,
                )

                # Check exclusivity before running
                if not await self._check_exclusivity(slot):
                    # Re-queue the job
                    await self._queues[slot].put(
                        (priority, job_id, input_data, kind, task_id, cause_id)
                    )
                    await asyncio.sleep(1.0)
                    continue

                # Mark as running
                async with self._lock:
                    self._running[slot].add(job_id)

                # Record start time for budget tracking
                job_start_time = time.time()
                self._job_start_times[job_id] = job_start_time

                # Update job state
                db = await get_database()
                await db.update(
                    "jobs",
                    {"state": JobState.RUNNING.value, "started_at": datetime.now(UTC).isoformat()},
                    "id = ?",
                    (job_id,),
                )

                logger.info("Job started", job_id=job_id, kind=kind.value, slot=slot.value)

                # Execute job
                try:
                    with CausalTrace(cause_id) as trace:
                        result = await self._execute_job(kind, input_data, task_id, trace.id)

                    # Record budget consumption
                    await self._record_budget_consumption(task_id, kind, job_start_time)

                    # Mark as completed
                    await db.update(
                        "jobs",
                        {
                            "state": JobState.COMPLETED.value,
                            "finished_at": datetime.now(UTC).isoformat(),
                            "output_json": str(result),
                        },
                        "id = ?",
                        (job_id,),
                    )

                    logger.info("Job completed", job_id=job_id, kind=kind.value)

                except Exception as e:
                    # Mark as failed
                    await db.update(
                        "jobs",
                        {
                            "state": JobState.FAILED.value,
                            "finished_at": datetime.now(UTC).isoformat(),
                            "error_message": str(e),
                        },
                        "id = ?",
                        (job_id,),
                    )

                    logger.error("Job failed", job_id=job_id, kind=kind.value, error=str(e))

                finally:
                    # Cleanup
                    self._job_start_times.pop(job_id, None)
                    # Remove from running
                    async with self._lock:
                        self._running[slot].discard(job_id)

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker error", slot=slot.value, worker_id=worker_id, error=str(e))
                await asyncio.sleep(1.0)

        logger.debug("Worker stopped", slot=slot.value, worker_id=worker_id)

    async def _execute_job(
        self,
        kind: JobKind,
        input_data: dict[str, Any],
        task_id: str | None,
        cause_id: str,
    ) -> dict[str, Any]:
        """Execute a job.

        Args:
            kind: Job kind.
            input_data: Job input.
            task_id: Task ID.
            cause_id: Causal trace ID.

        Returns:
            Job result.
        """
        if kind == JobKind.SERP:
            from src.search import search_serp

            return {"results": await search_serp(**input_data, task_id=task_id)}

        elif kind == JobKind.FETCH:
            from src.crawler.fetcher import fetch_url

            return await fetch_url(**input_data, task_id=task_id)

        elif kind == JobKind.EXTRACT:
            from src.extractor.content import extract_content

            return await extract_content(**input_data)

        elif kind == JobKind.EMBED:
            from src.filter.ranking import get_embedding_ranker

            ranker = get_embedding_ranker()
            embeddings = await ranker.encode(input_data.get("texts", []))
            return {"embeddings": embeddings}

        elif kind == JobKind.LLM:
            from src.filter.llm import llm_extract

            return await llm_extract(**input_data)

        elif kind == JobKind.NLI:
            from src.filter.nli import nli_judge

            return {"results": await nli_judge(**input_data)}

        elif kind == JobKind.VERIFY_NLI:
            from src.filter.cross_verification import verify_claims_nli

            return await verify_claims_nli(**input_data)

        elif kind == JobKind.CITATION_GRAPH:
            from src.research.citation_graph import process_citation_graph

            return await process_citation_graph(**input_data)

        else:
            raise ValueError(f"Unknown job kind: {kind}")

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job.

        Args:
            job_id: Job ID to cancel.

        Returns:
            True if cancelled successfully.
        """
        db = await get_database()

        result = await db.update(
            "jobs",
            {"state": JobState.CANCELLED.value},
            "id = ? AND state IN ('pending', 'queued')",
            (job_id,),
        )

        if result > 0:
            logger.info("Job cancelled", job_id=job_id)
            return True
        return False

    async def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Get job status.

        Args:
            job_id: Job ID.

        Returns:
            Job status dict or None.
        """
        db = await get_database()
        return await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))


# Global scheduler instance
_scheduler: JobScheduler | None = None


async def get_scheduler() -> JobScheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = JobScheduler()
        await _scheduler.start()
    return _scheduler


async def schedule_job(job: dict[str, Any]) -> dict[str, Any]:
    """Schedule a job (MCP tool handler).

    Args:
        job: Job specification.

    Returns:
        Scheduling result.
    """
    scheduler = await get_scheduler()

    kind = job.get("kind")
    priority = job.get("priority")
    input_data = job.get("input", {})
    task_id = job.get("task_id")

    if kind is None:
        raise ValueError("Job 'kind' is required")

    return await scheduler.submit(
        kind=cast(JobKind | str, kind),
        input_data=input_data,
        priority=priority,
        task_id=task_id,
    )
