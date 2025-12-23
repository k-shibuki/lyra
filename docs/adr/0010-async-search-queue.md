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

## References
- `docs/Q_ASYNC_ARCHITECTURE.md`（アーカイブ）
- `src/queue/search_queue.py` - キュー実装
- `src/workers/search_worker.py` - ワーカー実装
- `src/mcp/tools/search.py` - MCPツール定義
