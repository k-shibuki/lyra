# ADR-0010: Async Search Queue Architecture

## Date
2025-12-10

## Context

Web検索・クローリングは時間がかかる操作である：

| 操作 | 所要時間 |
|------|----------|
| 検索API呼び出し | 1-3秒 |
| ページ取得 | 2-10秒 |
| JavaScript実行待ち | 3-15秒 |
| LLM抽出 | 1-5秒 |

同期的に処理すると：
- 10ページ × 10秒 = 100秒待機
- MCPクライアントがタイムアウト
- ユーザー体験が悪化

## Decision

**検索リクエストをキューに投入し、非同期で処理する。ポーリングでステータスを確認する。**

### Scheduling Policy (Ordering / Concurrency)

- **Ordering**: The worker processes jobs by **priority ASC**, then **created_at ASC** (FIFO within the same priority).
- **No cross-task fairness**: There is no round-robin or fairness logic across tasks beyond the ordering rule above.
- **No per-task sequential guarantee**: A task may have multiple searches running in parallel.
- **Priority vocabulary**: If priority is exposed, use `high | medium | low` (align with existing Lyra terminology).

### Worker Lifecycle

- The queue worker is started when the MCP server starts (`run_server()` startup).
- The queue worker is stopped (cancelled) when the MCP server shuts down (`run_server()` shutdown).
- Start **2 worker tasks** for parallel execution.

### アーキテクチャ

```
MCPクライアント                          Lyra
     │                                    │
     │  queue_searches([q1, q2, q3])      │
     │ ─────────────────────────────────► │
     │                                    │ ┌─────────────────┐
     │  {task_id: "xxx", queued: 3}       │ │  Search Queue   │
     │ ◄───────────────────────────────── │ │  [q1, q2, q3]   │
     │                                    │ └────────┬────────┘
     │                                    │          │
     │  (MCPクライアントは他の作業)         │          ▼ 非同期処理
     │                                    │   ┌──────────────┐
     │  get_status(task_id, wait=30)      │   │   Worker     │
     │ ─────────────────────────────────► │   │  - Crawl     │
     │                                    │   │  - Extract   │
     │  {progress: "2/3", results: [...]} │   │  - Store     │
     │ ◄───────────────────────────────── │   └──────────────┘
     │                                    │
```

### MCPツール設計

#### queue_searches

```python
@server.tool()
async def queue_searches(
    task_id: str,
    queries: List[str],
    max_results_per_query: int = 10
) -> QueueResult:
    """
    検索クエリをキューに追加（即座に返却）

    Returns:
        task_id: タスク識別子
        queued: キューに追加された数
        estimated_time: 推定完了時間
    """
    for query in queries:
        await search_queue.enqueue(task_id, query, max_results_per_query)

    return QueueResult(
        task_id=task_id,
        queued=len(queries),
        estimated_time=estimate_completion_time(queries)
    )
```

#### get_status（sleep対応）
#### get_status（wait / long polling）

```python
@server.tool()
async def get_status(
    task_id: str,
    wait: int = 0  # 秒数、0なら即座に返却
) -> StatusResult:
    """
    タスクの進捗を取得

    wait > 0 の場合、完了または変化があるまで最大wait秒待機
    """
    if wait > 0:
        # Long polling: 変化があるまで待機
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

### Long Polling の利点

```
従来（短いポーリング）:
  Client: get_status → Server: {progress: "0/3"}
  (1秒後)
  Client: get_status → Server: {progress: "0/3"}
  (1秒後)
  Client: get_status → Server: {progress: "1/3"}
  ...
  → リクエストが多い、レイテンシが悪い

Long Polling:
  Client: get_status(wait=30) → (サーバーで待機)
  (進捗があった時点で)
  Server: {progress: "1/3"}
  → リクエスト削減、即座に通知
```

### ワーカー実装

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
                # 検索実行
                results = await self.search_engine.search(job.query)

                # 各結果をクロール
                for url in results[:job.max_results]:
                    page = await self.crawler.fetch(url)
                    await self.storage.save_page(page)

                    # 進捗を更新（Long pollingに通知）
                    await self.notify_progress(job.task_id)

            except Exception as e:
                await self.record_error(job.task_id, e)
```

### エラーハンドリング

```python
@dataclass
class StatusResult:
    task_id: str
    status: str
    progress: str
    results: List[PageSummary]
    errors: List[ErrorInfo]  # 部分的なエラーも報告

# エラーがあっても処理継続
{
    "status": "running",
    "progress": "8/10",
    "results": [...],  # 成功した8件
    "errors": [
        {"url": "https://...", "reason": "timeout"},
        {"url": "https://...", "reason": "403 Forbidden"}
    ]
}
```

## Consequences

### Positive
- **非ブロッキング**: MCPクライアントが待機不要
- **並列処理**: 複数クエリを同時処理可能
- **タイムアウト回避**: 長時間処理でもMCPタイムアウトしない
- **部分結果**: 完了前でも途中結果を取得可能

### Negative
- **複雑性**: キュー管理、ワーカー管理が必要
- **状態管理**: タスク状態の永続化が必要
- **デバッグ困難**: 非同期処理のトレースが複雑

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 同期処理 | シンプル | タイムアウト問題 | 却下 |
| WebSocket | リアルタイム | 実装複雑、MCP非対応 | 却下 |
| 短いポーリング | シンプル | リクエスト過多 | 却下 |
| Server-Sent Events | 軽量 | MCP非対応 | 却下 |

## Implementation Status

**Status**: Phase 1-3 ✅ 完了 / Phase 4 🔜 計画中

詳細は `docs/Q_ASYNC_ARCHITECTURE.md` を参照。

### フェーズ一覧

| Phase | 内容 | 状態 |
|-------|------|------|
| Phase 1 | `queue_searches` ツール追加、`get_status` に `wait` パラメータ追加 | ✅ 完了 (2025-12-24) |
| Phase 2 | `search`, `notify_user`, `wait_for_user` ツール削除 | ✅ 完了 (2025-12-24) |
| Phase 3 | 一次検証、`stop_task` の `mode` パラメータ（graceful/immediate）追加 | ✅ 完了 (2025-12-24) |
| Phase 4 | リソース競合制御（学術APIグローバルレート制限） | 🔜 計画中 ([ADR-0013](0013-worker-resource-contention.md)) |

### Phase 1-3 実装サマリー

| 変更 | 状態 |
|------|------|
| `search`, `notify_user`, `wait_for_user` 削除 | ✅ 完了 |
| `queue_searches` 追加 | ✅ 完了 |
| `get_status` に `wait` パラメータ追加 | ✅ 完了 |
| `stop_task` に `mode` パラメータ追加 | ✅ 完了 |
| パフォーマンス/安定性テスト | ✅ 完了 |
| E2E検証スクリプト | ✅ 完了 |
| 結果 | 13ツール → 10ツール（23%削減） |

### Storage Policy (Auditability)

- Queue items are persisted in the existing `jobs` table with `kind = 'search_queue'`.
  - **Rationale**: The `jobs` table already has priority, state transitions, slot management, and budget tracking. Adding a new table would duplicate schema and audit log management.
  - `input_json` stores the query and search options.
  - `output_json` stores the full result JSON produced by the pipeline execution.
- For **auditability**, completed items store the **full result JSON** (`jobs.output_json`).

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

| Resource | Control | Status |
|----------|---------|--------|
| **Browser (SERP)** | `BrowserSearchProvider` singleton + `Semaphore(1)` | ✅ Implemented |
| **Academic APIs** | Global rate limiter per provider | 🔜 Phase 4 ([ADR-0013](0013-worker-resource-contention.md)) |
| **HTTP fetch** | `RateLimiter` per domain | ✅ Implemented |

**Note**: Academic API rate limiting is tracked as **Phase 4** in [Q_ASYNC_ARCHITECTURE.md](../Q_ASYNC_ARCHITECTURE.md). See [ADR-0013](0013-worker-resource-contention.md) for design details.

## References
- `docs/Q_ASYNC_ARCHITECTURE.md` - 非同期アーキテクチャ詳細設計
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - Phase 4 リソース競合制御
- `src/mcp/server.py` - MCPツール定義
- `src/research/executor.py` - 検索実行
- `src/research/pipeline.py` - パイプラインオーケストレーション
- `src/scheduler/jobs.py` - ジョブスケジューラ
- `src/scheduler/search_worker.py` - SearchQueueWorker実装
