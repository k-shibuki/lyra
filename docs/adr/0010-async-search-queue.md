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

## Design Details

### Storage Policy

- Queue items persist in `jobs` table with `kind = 'search_queue'`
- Completed items store full result JSON for auditability

### Query Deduplication

- `queue_searches` checks for existing `queued`/`running` jobs with same query before inserting
- Prevents redundant work from parallel workers discovering same query

### stop_task Semantics

| Mode | Queued Items | Running Items | ML/NLI Operations |
|------|--------------|---------------|-------------------|
| `graceful` | → cancelled | Wait for completion (30s timeout) | Continue until job completes |
| `immediate` | → cancelled | Cancel via `asyncio.Task.cancel()` | May be interrupted mid-flight |
| `full` | → cancelled | Cancel via `asyncio.Task.cancel()` | Wait for drain (0.5s) |

**DB Impact on stop_task**:
- `tasks.status` → `completed` (or `cancelled` if reason=user_cancelled)
- `jobs.state` → `cancelled` for queued jobs (all modes) and running jobs (immediate/full modes)
- `intervention_queue.status` → `cancelled` for pending auth items
- Claims/fragments already persisted remain in DB for query_sql/vector_search

**Consistency**: Job's `state = 'cancelled'` in `jobs` table is authoritative record. Partial artifacts may exist but are filterable.

### Long Polling

- Uses in-memory `asyncio.Event` per task (not DB polling)
- `get_status(wait=N)` blocks until change or timeout

### Resource Control

| Resource | Control Mechanism | ADR |
|----------|-------------------|-----|
| Browser SERP | TabPool + per-engine policy | [ADR-0014](0014-browser-serp-resource-control.md) |
| Academic APIs | Global rate limiter | [ADR-0013](0013-worker-resource-contention.md) |
| HTTP fetch | Per-domain RateLimiter | - |

## References

- [ADR-0013](0013-worker-resource-contention.md) - Academic API resource control
- [ADR-0014](0014-browser-serp-resource-control.md) - Browser SERP resource control
- `src/scheduler/search_worker.py` - Worker implementation
- `src/mcp/server.py` - MCP tool definitions
