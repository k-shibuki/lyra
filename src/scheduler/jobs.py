"""
Job scheduler for Lyra.
Manages job queues, slots, and resource allocation.
Implements budget control per ADR-0010 and ADR-0003.

DB-Driven Architecture:
- DB is the sole source of truth for job state.
- Workers poll DB for queued jobs and claim them atomically.
- In-memory queue is NOT used; submit() only inserts into DB.
- Restart resets all queued/running jobs to failed (no auto-resume).
"""

import asyncio
import json
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
        Per ADR-0010: TARGET_QUEUE for async target queue architecture (query + URL).
        Per ADR-0005: VERIFY_NLI added for automatic cross-source NLI verification.
        Per ADR-0015: CITATION_GRAPH added for deferred citation graph processing.
    """

    SERP = "serp"
    FETCH = "fetch"
    EXTRACT = "extract"
    EMBED = "embed"
    LLM = "llm"  # Single LLM job type (per ADR-0004)
    NLI = "nli"
    TARGET_QUEUE = "target_queue"  # Async target queue - query + URL (per ADR-0010)
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
    JobKind.TARGET_QUEUE: Slot.NETWORK_CLIENT,  # Async target queue (per ADR-0010)
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
    JobKind.TARGET_QUEUE: 25,  # Between FETCH and EXTRACT (per ADR-0010)
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

# Polling interval for DB-driven workers
DB_POLL_INTERVAL_SECONDS = 0.5


class JobScheduler:
    """Job scheduler with slot-based resource management and budget control.

    DB-Driven Architecture:
    - submit() inserts job into DB only (no in-memory queue).
    - Workers poll DB for 'queued' jobs and claim atomically.
    - On startup, stale queued/running jobs are reset to 'failed'.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._workers: dict[Slot, list[asyncio.Task[None]]] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._budget_manager: BudgetManager | None = None

        # Running job tracking for cancellation (job_id -> asyncio.Task)
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

        # Job timing for LLM ratio tracking
        self._job_start_times: dict[str, float] = {}

    async def start(self) -> None:
        """Start the scheduler workers.

        On startup:
        1. Reset stale queued/running jobs to 'failed' (server_restart_reset).
        2. Start worker coroutines that poll DB for jobs.
        """
        if self._started:
            return

        self._started = True

        # Reset stale jobs on startup (fail_all policy)
        await self._reset_inflight_jobs_on_startup()

        # Initialize budget manager
        self._budget_manager = await get_budget_manager()

        # Start worker tasks for each slot
        for slot in Slot:
            limit = SLOT_LIMITS[slot]
            workers: list[asyncio.Task[None]] = []
            for i in range(limit):
                task = asyncio.create_task(self._worker(slot, i))
                workers.append(task)
            self._workers[slot] = workers

        logger.info("Job scheduler started")

    async def _reset_inflight_jobs_on_startup(self) -> None:
        """Reset all queued/running jobs to 'failed' on startup.

        This ensures:
        - No jobs auto-resume after restart (fail_all policy).
        - get_status.milestones won't be blocked by orphaned queued jobs.
        """
        db = await get_database()
        now = datetime.now(UTC).isoformat()

        # Update all queued/running jobs to failed
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = ?, finished_at = ?, error_message = ?
            WHERE state IN (?, ?)
            """,
            (
                JobState.FAILED.value,
                now,
                "server_restart_reset",
                JobState.QUEUED.value,
                JobState.RUNNING.value,
            ),
        )
        reset_count = getattr(cursor, "rowcount", 0)

        if reset_count > 0:
            logger.warning(
                "Reset stale jobs on startup",
                reset_count=reset_count,
                policy="fail_all",
            )

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

        DB-Driven: Only inserts job into DB. Workers poll DB for jobs.

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

        # Generate job ID with kind-based prefix for readability
        uuid_suffix = uuid.uuid4().hex[:12]
        kind_prefix = {
            JobKind.TARGET_QUEUE: "tq_",
            JobKind.VERIFY_NLI: "vnli_",
            JobKind.CITATION_GRAPH: "cg_",
        }.get(kind, "job_")
        job_id = f"{kind_prefix}{uuid_suffix}"

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

        # Check exclusivity (via DB running count)
        can_queue = await self._check_exclusivity_db(slot)
        if not can_queue:
            return {
                "accepted": False,
                "job_id": job_id,
                "reason": "exclusive_slot_busy",
            }

        # Store job in database (DB is the only queue)
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
                "input_json": json.dumps(input_data),  # Use proper JSON serialization
                "queued_at": datetime.now(UTC).isoformat(),
                "cause_id": cause_id,
            },
        )

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
            "eta": await self._estimate_eta_db(slot),
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

    async def _check_exclusivity_db(self, slot: Slot) -> bool:
        """Check if slot can accept jobs based on exclusivity rules (DB-based).

        Args:
            slot: Target slot.

        Returns:
            True if slot can accept jobs.
        """
        db = await get_database()

        for exclusive_group in EXCLUSIVE_SLOTS:
            if slot in exclusive_group:
                # Check if any other slot in the group has running jobs
                for other_slot in exclusive_group:
                    if other_slot != slot:
                        row = await db.fetch_one(
                            """
                            SELECT COUNT(*) as cnt FROM jobs
                            WHERE slot = ? AND state = ?
                            """,
                            (other_slot.value, JobState.RUNNING.value),
                        )
                        count = row["cnt"] if row else 0
                        if count > 0:
                            return False
        return True

    async def _estimate_eta_db(self, slot: Slot) -> str:
        """Estimate time until job starts (DB-based).

        Args:
            slot: Target slot.

        Returns:
            ETA string.
        """
        db = await get_database()

        # Count queued jobs for this slot
        queued_row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE slot = ? AND state = ?",
            (slot.value, JobState.QUEUED.value),
        )
        queued_count = queued_row["cnt"] if queued_row else 0

        # Count running jobs for this slot
        running_row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE slot = ? AND state = ?",
            (slot.value, JobState.RUNNING.value),
        )
        running_count = running_row["cnt"] if running_row else 0

        limit = SLOT_LIMITS[slot]

        # Simple estimate: assume each job takes 30 seconds
        waiting = max(0, queued_count - (limit - running_count))
        eta_seconds = waiting * 30

        if eta_seconds < 60:
            return f"{eta_seconds}s"
        else:
            return f"{eta_seconds // 60}m"

    async def _claim_next_job(
        self, slot: Slot
    ) -> tuple[str, JobKind, dict[str, Any], str | None, str | None] | None:
        """Claim the next queued job for a slot atomically.

        Uses UPDATE with WHERE state='queued' and rowcount check for atomicity.
        ORDER BY priority ASC, queued_at ASC for FIFO within priority.

        Args:
            slot: Target slot.

        Returns:
            Tuple of (job_id, kind, input_data, task_id, cause_id) or None if no job.
        """
        db = await get_database()
        now = datetime.now(UTC).isoformat()

        # Check exclusivity before claiming
        if not await self._check_exclusivity_db(slot):
            return None

        # Check slot concurrency limit
        running_row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE slot = ? AND state = ?",
            (slot.value, JobState.RUNNING.value),
        )
        running_count = running_row["cnt"] if running_row else 0
        if running_count >= SLOT_LIMITS[slot]:
            return None

        # Find next queued job for this slot
        job = await db.fetch_one(
            """
            SELECT id, kind, input_json, task_id, cause_id
            FROM jobs
            WHERE slot = ? AND state = ?
            ORDER BY priority ASC, queued_at ASC
            LIMIT 1
            """,
            (slot.value, JobState.QUEUED.value),
        )

        if not job:
            return None

        job_id = job["id"]
        kind_str = job["kind"]
        input_json = job["input_json"]
        task_id = job["task_id"]
        cause_id = job["cause_id"]

        # Atomic claim: UPDATE with WHERE state='queued'
        cursor = await db.execute(
            """
            UPDATE jobs
            SET state = ?, started_at = ?
            WHERE id = ? AND state = ?
            """,
            (JobState.RUNNING.value, now, job_id, JobState.QUEUED.value),
        )

        # Check if claim succeeded (another worker may have claimed it)
        if getattr(cursor, "rowcount", 0) == 0:
            return None

        # Parse input_json
        try:
            input_data = json.loads(input_json) if input_json else {}
        except (json.JSONDecodeError, TypeError):
            # Fallback for legacy str(dict) format
            try:
                input_data = eval(input_json) if input_json else {}  # noqa: S307
            except Exception:
                input_data = {}

        kind = JobKind(kind_str)
        return (job_id, kind, input_data, task_id, cause_id)

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

        DB-Driven: Polls DB for queued jobs instead of in-memory queue.

        Args:
            slot: Slot to work on.
            worker_id: Worker ID within slot.
        """
        logger.debug("Worker started", slot=slot.value, worker_id=worker_id)

        while self._started:
            try:
                # Poll DB for next job
                claimed = await self._claim_next_job(slot)

                if claimed is None:
                    # No job available, wait before polling again
                    await asyncio.sleep(DB_POLL_INTERVAL_SECONDS)
                    continue

                job_id, kind, input_data, task_id, cause_id = claimed

                # Record start time for budget tracking
                job_start_time = time.time()
                self._job_start_times[job_id] = job_start_time

                logger.info("Job started", job_id=job_id, kind=kind.value, slot=slot.value)

                # Create task for execution (for cancellation tracking)
                # Bind loop variables to avoid B023
                _kind = kind
                _input_data = input_data
                _task_id = task_id
                _cause_id = cause_id

                async def execute_job(
                    job_kind: JobKind = _kind,
                    job_input: dict[str, Any] = _input_data,
                    job_task_id: str | None = _task_id,
                    job_cause_id: str | None = _cause_id,
                ) -> dict[str, Any]:
                    with CausalTrace(job_cause_id) as trace:
                        return await self._execute_job(job_kind, job_input, job_task_id, trace.id)

                exec_task = asyncio.create_task(execute_job())
                self._running_tasks[job_id] = exec_task

                # Execute job
                db = await get_database()
                try:
                    result = await exec_task

                    # Re-check job state before marking completed (stop_task may have cancelled)
                    current_state = await db.fetch_one(
                        "SELECT state FROM jobs WHERE id = ?",
                        (job_id,),
                    )
                    if current_state and current_state["state"] == JobState.CANCELLED.value:
                        logger.info("Job was cancelled during execution", job_id=job_id)
                    else:
                        # Record budget consumption
                        await self._record_budget_consumption(task_id, kind, job_start_time)

                        # Mark as completed
                        await db.update(
                            "jobs",
                            {
                                "state": JobState.COMPLETED.value,
                                "finished_at": datetime.now(UTC).isoformat(),
                                "output_json": json.dumps(result) if result else None,
                            },
                            "id = ?",
                            (job_id,),
                        )
                        logger.info("Job completed", job_id=job_id, kind=kind.value)

                except asyncio.CancelledError:
                    # Job was cancelled (by cancel_running_jobs)
                    await db.update(
                        "jobs",
                        {
                            "state": JobState.CANCELLED.value,
                            "finished_at": datetime.now(UTC).isoformat(),
                            "error_message": "cancelled_by_stop_task",
                        },
                        "id = ?",
                        (job_id,),
                    )
                    logger.info("Job cancelled", job_id=job_id, kind=kind.value)

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
                    self._running_tasks.pop(job_id, None)

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

        elif kind == JobKind.TARGET_QUEUE:
            # Unified target queue execution (ADR-0010)
            # Handles query, url, and doi targets
            return await self._execute_target_queue_job(input_data, task_id, cause_id)

        else:
            raise ValueError(f"Unknown job kind: {kind}")

    async def _execute_target_queue_job(
        self,
        input_data: dict[str, Any],
        task_id: str | None,
        cause_id: str,
    ) -> dict[str, Any]:
        """Execute a target_queue job.

        Handles query, url, and doi target kinds per ADR-0010.

        Args:
            input_data: Job input containing target and options.
            task_id: Task ID.
            cause_id: Causal trace ID.

        Returns:
            Execution result dict.
        """
        from src.mcp.helpers import get_exploration_state
        from src.research.pipeline import ingest_doi_action, ingest_url_action, search_action

        if not task_id:
            raise ValueError("task_id is required for TARGET_QUEUE jobs")

        target = input_data.get("target", {})
        target_kind = target.get("kind", "query")
        options = input_data.get("options", {})

        # Get exploration state
        state = await get_exploration_state(task_id)

        # Execute based on target kind
        if target_kind == "query":
            query = target.get("query", "")
            query_options = target.get("options", {})
            merged_options = {**options, **query_options}
            merged_options["task_id"] = task_id

            result = await search_action(
                task_id=task_id,
                query=query,
                state=state,
                options=merged_options,
            )

        elif target_kind == "url":
            url = target.get("url", "")
            depth = target.get("depth", 0)
            reason = target.get("reason", "manual")
            context = target.get("context", {})
            policy = target.get("policy", {})
            options_with_task = {**options, "task_id": task_id}

            result = await ingest_url_action(
                task_id=task_id,
                url=url,
                state=state,
                depth=depth,
                reason=reason,
                context=context,
                policy=policy,
                options=options_with_task,
            )

        elif target_kind == "doi":
            doi = target.get("doi", "")
            reason = target.get("reason", "manual")
            context = target.get("context", {})
            options_with_task = {**options, "task_id": task_id}

            result = await ingest_doi_action(
                task_id=task_id,
                doi=doi,
                state=state,
                reason=reason,
                context=context,
                options=options_with_task,
            )

        else:
            raise ValueError(f"Unknown target kind: {target_kind}")

        # Notify long polling clients
        state.notify_status_change()

        # Enqueue VERIFY_NLI job after successful completion (ADR-0005)
        # Always enqueue - verify_claims_nli handles empty cases gracefully
        if result.get("ok", True) and not result.get("captcha_queued"):
            await self._enqueue_verify_nli_if_needed(task_id, result)

        # Check if target queue is empty for batch notification (ADR-0007)
        await self._check_target_queue_empty(task_id)

        return result

    async def _enqueue_verify_nli_if_needed(self, task_id: str, result: dict[str, Any]) -> None:
        """Enqueue VERIFY_NLI job after target completion.

        ADR-0005: Cross-source NLI verification is triggered per target_queue job.
        """
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

    async def _check_target_queue_empty(self, task_id: str) -> None:
        """Check if target queue is empty and notify if so (ADR-0007).

        Called after each target_queue job completes.
        """
        try:
            db = await get_database()
            row = await db.fetch_one(
                """
                SELECT COUNT(*) as cnt FROM jobs
                WHERE task_id = ? AND kind = 'target_queue'
                  AND state IN ('queued', 'running')
                """,
                (task_id,),
            )
            count = row["cnt"] if row else 0

            if count == 0:
                from src.utils.batch_notification import notify_target_queue_empty

                await notify_target_queue_empty()
        except Exception as e:
            logger.debug("Batch notification check failed", error=str(e))

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending/queued job.

        Args:
            job_id: Job ID to cancel.

        Returns:
            True if cancelled successfully.
        """
        db = await get_database()

        result = await db.update(
            "jobs",
            {
                "state": JobState.CANCELLED.value,
                "finished_at": datetime.now(UTC).isoformat(),
            },
            "id = ? AND state IN ('pending', 'queued')",
            (job_id,),
        )

        if result > 0:
            logger.info("Job cancelled", job_id=job_id)
            return True
        return False

    async def cancel_running_jobs_for_task(self, task_id: str) -> int:
        """Cancel all running jobs for a task.

        Used by stop_task(mode=immediate/full) to cancel in-flight jobs.

        Args:
            task_id: Task ID.

        Returns:
            Number of jobs cancelled.
        """
        cancelled_count = 0
        db = await get_database()

        for job_id, task in list(self._running_tasks.items()):
            # Check if this job belongs to the task
            job = await db.fetch_one(
                "SELECT task_id FROM jobs WHERE id = ?",
                (job_id,),
            )
            if job and job["task_id"] == task_id:
                task.cancel()
                cancelled_count += 1
                logger.info("Cancelled running job", job_id=job_id, task_id=task_id)

        return cancelled_count

    async def wait_for_task_jobs_to_complete(self, task_id: str, timeout: float = 30.0) -> int:
        """Wait for all running jobs for a task to complete.

        Used by stop_task(mode=graceful) to wait for running jobs to finish naturally.
        Does NOT cancel the jobs, just waits for them.

        Args:
            task_id: The research task ID whose jobs to wait for.
            timeout: Maximum time to wait in seconds.

        Returns:
            Number of jobs that were waited on.
        """
        db = await get_database()
        jobs_to_wait: list[tuple[str, asyncio.Task[Any]]] = []

        # Find all running jobs for this task
        for job_id, job_task in list(self._running_tasks.items()):
            if job_task.done():
                continue
            # Check if this job belongs to the task
            job = await db.fetch_one(
                "SELECT task_id FROM jobs WHERE id = ?",
                (job_id,),
            )
            if job and job["task_id"] == task_id:
                jobs_to_wait.append((job_id, job_task))

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
