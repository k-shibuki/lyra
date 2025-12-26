# ADR-0010: Async Search Queue Architecture

## Date
2025-12-10

## Context

Web search and crawling are time-consuming operations:

| Operation | Time Required |
|-----------|--------------|
| Search API call | 1-3 seconds |
| Page fetch | 2-10 seconds |
| JavaScript execution wait | 3-15 seconds |
| LLM extraction | 1-5 seconds |

Synchronous processing results in:
- 10 pages × 10 seconds = 100 seconds wait
- MCP client timeout
- Poor user experience

## Decision

**Submit search requests to a queue for asynchronous processing. Check status via polling.**

### Scheduling Policy (Ordering / Concurrency)

- **Ordering**: The worker processes jobs by **priority ASC**, then **created_at ASC** (FIFO within the same priority).
- **No cross-task fairness**: There is no round-robin or fairness logic across tasks beyond the ordering rule above.
- **No per-task sequential guarantee**: A task may have multiple searches running in parallel.
- **Priority vocabulary**: If priority is exposed, use `high | medium | low` (align with existing Lyra terminology).

### Worker Lifecycle

- The queue worker is started when the MCP server starts (`run_server()` startup).
- The queue worker is stopped (cancelled) when the MCP server shuts down (`run_server()` shutdown).
- Start **2 worker tasks** for parallel execution.

### Architecture

```
MCP Client                               Lyra
     │                                    │
     │  queue_searches([q1, q2, q3])      │
     │ ─────────────────────────────────► │
     │                                    │ ┌─────────────────┐
     │  {task_id: "xxx", queued: 3}       │ │  Search Queue   │
     │ ◄───────────────────────────────── │ │  [q1, q2, q3]   │
     │                                    │ └────────┬────────┘
     │                                    │          │
     │  (MCP client does other work)      │          ▼ Async processing
     │                                    │   ┌──────────────┐
     │  get_status(task_id, wait=30)      │   │   Worker     │
     │ ─────────────────────────────────► │   │  - Crawl     │
     │                                    │   │  - Extract   │
     │  {progress: "2/3", results: [...]} │   │  - Store     │
     │ ◄───────────────────────────────── │   └──────────────┘
     │                                    │
```

### MCP Tool Design

#### queue_searches

```python
@server.tool()
async def queue_searches(
    task_id: str,
    queries: List[str],
    max_results_per_query: int = 10
) -> QueueResult:
    """
    Add search queries to queue (returns immediately)

    Returns:
        task_id: Task identifier
        queued: Number added to queue
        estimated_time: Estimated completion time
    """
    for query in queries:
        await search_queue.enqueue(task_id, query, max_results_per_query)

    return QueueResult(
        task_id=task_id,
        queued=len(queries),
        estimated_time=estimate_completion_time(queries)
    )
```

#### get_status (wait / long polling)

```python
@server.tool()
async def get_status(
    task_id: str,
    wait: int = 0  # Seconds, 0 returns immediately
) -> StatusResult:
    """
    Get task progress

    If wait > 0, waits up to wait seconds until completion or change
    """
    if wait > 0:
        # Long polling: wait until change
        result = await wait_for_progress(task_id, timeout=wait)
    else:
        result = await get_current_status(task_id)

    return StatusResult(
        task_id=task_id,
        status=result.status,  # "running", "completed", "failed"
        progress=f"{result.completed}/{result.total}",
        results=result.available_results,
        errors=result.errors
    )
```

### Long Polling Benefits

```
Traditional (short polling):
  Client: get_status → Server: {progress: "0/3"}
  (1 second later)
  Client: get_status → Server: {progress: "0/3"}
  (1 second later)
  Client: get_status → Server: {progress: "1/3"}
  ...
  → Many requests, poor latency

Long Polling:
  Client: get_status(wait=30) → (server waits)
  (when progress occurs)
  Server: {progress: "1/3"}
  → Reduced requests, immediate notification
```

### Worker Implementation

```python
class SearchWorker:
    async def process_queue(self):
        while True:
            # IMPORTANT: dequeue must be atomic when multiple workers run.
            # Use "claim" semantics (queued -> running) in a single DB operation
            # (e.g., UPDATE ... RETURNING) or a transaction (BEGIN IMMEDIATE)
            # to avoid two workers picking the same queued item.
            job = await self.queue.dequeue()
            if job is None:
                await asyncio.sleep(0.1)
                continue

            try:
                # Execute search
                results = await self.search_engine.search(job.query)

                # Crawl each result
                for url in results[:job.max_results]:
                    page = await self.crawler.fetch(url)
                    await self.storage.save_page(page)

                    # Update progress (notify long polling)
                    await self.notify_progress(job.task_id)

            except Exception as e:
                await self.record_error(job.task_id, e)
```

### Error Handling

```python
@dataclass
class StatusResult:
    task_id: str
    status: str
    progress: str
    results: List[PageSummary]
    errors: List[ErrorInfo]  # Report partial errors too

# Processing continues despite errors
{
    "status": "running",
    "progress": "8/10",
    "results": [...],  # 8 successful items
    "errors": [
        {"url": "https://...", "reason": "timeout"},
        {"url": "https://...", "reason": "403 Forbidden"}
    ]
}
```

## Consequences

### Positive
- **Non-blocking**: MCP client doesn't need to wait
- **Parallel Processing**: Multiple queries processed simultaneously
- **Timeout Avoidance**: Long processing doesn't cause MCP timeout
- **Partial Results**: Can get intermediate results before completion

### Negative
- **Complexity**: Queue management, worker management required
- **State Management**: Task state persistence required
- **Hard to Debug**: Async processing traces are complex

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Synchronous Processing | Simple | Timeout issues | Rejected |
| WebSocket | Real-time | Complex implementation, MCP incompatible | Rejected |
| Short Polling | Simple | Too many requests | Rejected |
| Server-Sent Events | Lightweight | MCP incompatible | Rejected |

## Implementation Status

**Status**: Phase 1-6 ✅ Complete

### Phase Summary

| Phase | Content | Status |
|-------|---------|--------|
| Phase 1 | `queue_searches` tool, `get_status` with `wait` parameter | ✅ Complete (2025-12-24) |
| Phase 2 | `search`, `notify_user`, `wait_for_user` tools removed | ✅ Complete (2025-12-24) |
| Phase 3 | Initial validation, `stop_task` `mode` parameter (graceful/immediate) | ✅ Complete (2025-12-24) |
| Phase 4 | Search Resource Control (Academic API + Browser SERP) | ✅ Complete (2025-12-25) ([ADR-0013](0013-worker-resource-contention.md), [ADR-0014](0014-browser-serp-resource-control.md)) |
| Phase 5 | SERP Enhancement (Pagination) | ✅ Complete (2025-12-26) |
| Phase 6 | calibration_metrics action removed, adapters table added | ✅ Complete (2025-12-25) |

### Phase 1-3 Implementation Summary

| Change | Status |
|--------|--------|
| `search`, `notify_user`, `wait_for_user` removed | ✅ Complete |
| `queue_searches` added | ✅ Complete |
| `get_status` with `wait` parameter | ✅ Complete |
| `stop_task` with `mode` parameter | ✅ Complete |
| Performance/stability tests | ✅ Complete |
| E2E validation script | ✅ Complete |
| Result | 13 tools → 10 tools (23% reduction) |

### Storage Policy (Auditability)

- Queue items are persisted in the existing `jobs` table with `kind = 'search_queue'`.
  - **Rationale**: The `jobs` table already has priority, state transitions, slot management, and budget tracking. Adding a new table would duplicate schema and audit log management.
  - `input_json` stores the query and search options.
  - `output_json` stores the full result JSON produced by the pipeline execution.
- For **auditability**, completed items store the **full result JSON** (`jobs.output_json`).

### Query Deduplication

`queue_searches` prevents duplicate queries within the same task:

- Before inserting a new job, check if an identical query already exists for the task with `state IN ('queued', 'running')`.
- If found, skip the duplicate (log and continue).
- **Rationale**: Parallel workers may discover the same query via different code paths. Preventing duplicates avoids redundant work and database bloat.

```python
# Pseudocode (server.py: _handle_queue_searches)
existing = await db.fetch_one(
    "SELECT id FROM jobs WHERE task_id = ? AND kind = 'search_queue' "
    "AND state IN ('queued', 'running') AND json_extract(input_json, '$.query') = ?",
    (task_id, query),
)
if existing:
    logger.info("Skipping duplicate query", task_id=task_id, query=query[:50])
    continue
```

### stop_task Semantics (Two Modes)

`stop_task` supports two stop modes:

- **mode=graceful**:
  - Do not start new queued items for the task (queued → cancelled).
  - Wait for running items to complete so their full result JSON can be persisted.
- **mode=immediate**:
  - queued → cancelled.
  - running → cancelled via `asyncio.Task.cancel()`. Result JSON is not persisted.
  - **Batch cancellation**: All running jobs for the task are cancelled at once (`SearchQueueWorkerManager.cancel_jobs_for_task()`).
  - **Worker continuity**: Workers survive individual job cancellations and continue processing other tasks. The worker catches `CancelledError` from the `search_action` task and continues its loop.

**Logical consistency guarantee**: With async I/O and incremental persistence, "immediate" may still leave partial DB artifacts (pages/fragments) written before cancellation. However, **the job's `state = 'cancelled'` in the `jobs` table provides the authoritative record** that the search was cancelled. Downstream consumers can filter out data associated with cancelled jobs.

Cleanup note: For hard cleanup, follow ADR-0005 (Evidence Graph Structure) and use **hard(orphans_only)** after soft cleanup if storage reclamation is required.

### Long Polling Implementation

- Long polling is implemented using **`asyncio.Event`** in `ExplorationState`, not DB polling.
- **Rationale**: `ExplorationState` is already in-memory per task. DB polling adds unnecessary I/O and latency.
- When a search completes, fails, or queue depth changes, the worker calls `state.notify_status_change()` which sets the event.
- `get_status(wait=N)` uses `asyncio.wait_for(state.wait_for_change(), timeout=N)`.
- If timeout expires with no change, the current status is returned (same as `wait=0`).

### Migration Strategy

- Phase 1 completes with `queue_searches` working. **Old tools (`search`, `notify_user`, `wait_for_user`) remain available** during Phase 1.
- Phase 2 removes old tools after confirming `queue_searches` + `get_status(wait)` pattern works in Cursor Rules/Commands.

### Global Rate Limits / Resource Control

When running multiple queue workers, external rate limits must still be respected globally:

| Resource | Control | Status | ADR |
|----------|---------|--------|-----|
| **Browser (SERP)** | TabPool (max_tabs=1) + per-engine policy | ✅ Implemented | [ADR-0014](0014-browser-serp-resource-control.md) |
| **Academic APIs** | Global rate limiter per provider | ✅ Implemented | [ADR-0013](0013-worker-resource-contention.md) |
| **HTTP fetch** | `RateLimiter` per domain | ✅ Implemented | - |

**Note**: 
- Academic API rate limiting (**Phase 4.A**): See [ADR-0013](0013-worker-resource-contention.md).
- Browser SERP resource control (**Phase 4.B**): See [ADR-0014](0014-browser-serp-resource-control.md).

## References
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - Phase 4.A Academic API resource contention control
- [ADR-0014: Browser SERP Resource Control](0014-browser-serp-resource-control.md) - Phase 4.B Browser SERP resource control
- `src/mcp/server.py` - MCP tool definitions
- `src/research/executor.py` - Search execution
- `src/research/pipeline.py` - Pipeline orchestration
- `src/scheduler/jobs.py` - Job scheduler
- `src/scheduler/search_worker.py` - SearchQueueWorker implementation
