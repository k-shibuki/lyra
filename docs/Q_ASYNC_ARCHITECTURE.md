# 非同期アーキテクチャ改善

> **Status**: DESIGN PROPOSAL（未実装）

> **Scope / Assumptions (Dev Phase)**:
> - **Breaking changes are allowed** (no backward compatibility required at this phase).
> - Source of truth is **ADRs + this plan (Q) + code**. Do **not** rely on `docs/archive/REQUIREMENTS.md`.

## Executive Summary

**問題の本質:** 現在の`search`ツールは同期的にパイプライン全体を実行するため、MCPクライアント（Cursor AI）がブロックされる。これでは複数検索の並列実行が不可能。

**解決策:** ツールを増やすのではなく、**非同期セマンティクスに変更する**
- `search`ツールを内部化（MCPツールから削除）
- `queue_searches`ツールで複数クエリをキューに投入（即座に応答）
- **バックグラウンドワーカー（2 workers）**がキューから**優先度順（同一優先度はFIFO）**に取り出し、並列に処理
- `get_status`に**wait（long polling）**を追加（MCPクライアントに時間感覚がないため）

**結果:** ツール数 12個 → **10個に削減**、クライアントはノンブロッキング、シンプルで効率的

---

## 1. 現状の問題点

### 1.1 同期的なsearchツール

**現在のフロー:**
```
MCPクライアント
  ↓
  call_tool("search", {task_id, query})
  ↓ (ブロック - 数十秒〜数分待機)
MCPサーバ: _handle_search
  ↓ await search_action
  ↓ SearchPipeline.execute
  ↓   SERP検索 → フェッチ → 抽出 → LLM → エビデンス
  ↑ 応答
MCPクライアント (ようやく次の操作が可能)
```

**問題点:**
1. **クライアントがブロックされる** - 検索完了まで他の操作ができない
2. **複数検索の並列実行が不可能** - 1つずつシーケンシャルに呼び出す必要がある
3. **MCPクライアントに時間感覚がない** - 適切なポーリング間隔を設定できない

### 1.2 具体例：3つの検索を実行したい場合

**現在（非効率）:**
```python
# 各searchは数十秒かかる
result1 = await call_tool("search", {task_id, query: "Q1"})  # 30秒
result2 = await call_tool("search", {task_id, query: "Q2"})  # 40秒
result3 = await call_tool("search", {task_id, query: "Q3"})  # 35秒
# 合計: 105秒（シーケンシャル実行）
```

**あるべき姿（効率的）:**
```python
# キューに投入（即座に応答）
await call_tool("queue_searches", {
    task_id: "task_xxx",
    queries: ["Q1", "Q2", "Q3"]
})  # 応答: 即座（< 1秒）

# バックグラウンドで処理（クライアントはブロックされない）
# 内部: 優先度順にキューから取り出し、2 workersで並列実行（完了順は非決定）

# 適切な間隔でポーリング
status = await call_tool("get_status", {
    task_id: "task_xxx",
    wait: 10  # 最大10秒待ってから確認（long polling）
})
# 応答: {searches: [{id: s1, status: completed}, {id: s2, status: running}, ...]}
```

---

## 2. 新しいアーキテクチャ

### 2.1 ツール構成（12個 → 10個に削減）

#### **削除するツール:**
1. ~~`search`~~ → 内部関数化（`search_action`は残す）
2. ~~`notify_user`~~ → 不要（`get_status`のwarningsで十分）
3. ~~`wait_for_user`~~ → 不要（ポーリングで対応）

#### **変更するツール:**
1. **`get_status`** → wait（long polling）を追加

#### **追加するツール:**
1. **`queue_searches`** → 複数クエリをキューに投入

#### **最終構成（10ツール）:**

**注**: Phase 6で`feedback`ツールが追加されたため、元の11ツールは12ツールとなった。

| # | ツール名 | 目的 | 変更 |
|---|---------|------|------|
| 1 | `create_task` | タスク作成 | 変更なし |
| 2 | `queue_searches` | 検索キューに投入 | **新規** |
| 3 | `get_status` | タスク状態確認 | **wait追加** |
| 4 | `stop_task` | タスク終了 | **mode追加（graceful/immediate）** |
| 5 | `get_materials` | レポート素材取得 | 変更なし |
| 6 | `calibration_metrics` | モデル較正評価 | **リネーム（旧calibrate）** |
| 7 | `calibration_rollback` | 較正ロールバック | 変更なし |
| 8 | `get_auth_queue` | 認証キュー取得 | 変更なし |
| 9 | `resolve_auth` | 認証解決 | 変更なし |
| 10 | `feedback` | Human-in-the-loop入力 | **Phase 6で追加** |

### 2.2 アーキテクチャフロー

```
┌─────────────────────────────────────────────────────────────┐
│ MCPクライアント (Cursor AI)                                   │
└─────────────────────────────────────────────────────────────┘
         │
         │ ① queue_searches(task_id, queries: ["Q1", "Q2", "Q3"])
         ↓
┌─────────────────────────────────────────────────────────────┐
│ MCPサーバ: _handle_queue_searches                            │
│   - キューにクエリを追加（DB: jobs テーブル, kind='search_queue'）│
│   - 即座に応答 {ok: true, queued_count: 3}                   │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│ バックグラウンドワーカー (SearchQueueWorker)                  │
│   ① キューから取得: Q1                                       │
│   ② search_action(task_id, "Q1") → SearchPipeline           │
│      - SERP → フェッチ → 抽出 → LLM → エビデンス              │
│   ③ 完了後、次のキュー取得: Q2                               │
│   ④ search_action(task_id, "Q2") → ...                       │
│   ⑤ Q3も同様                                                 │
│   ※ 2 workersで並列実行（同一優先度は投入順に「開始」される）   │
└─────────────────────────────────────────────────────────────┘
         ↑
         │ ステータス監視
         │
┌─────────────────────────────────────────────────────────────┐
│ MCPクライアント                                               │
│   ② get_status(task_id, wait: 10)                            │
│      ↓ (最大10秒待機 / 進捗変化があれば即時応答)               │
│   ③ 応答受信: {                                              │
│        searches: [                                           │
│          {id: s1, query: "Q1", status: "completed"},         │
│          {id: s2, query: "Q2", status: "running"},           │
│          {id: s3, query: "Q3", status: "queued"}             │
│        ],                                                    │
│        queue_depth: 1                                        │
│      }                                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 実装仕様

### 3.1 新しいツール: `queue_searches`

#### ツール定義
```python
Tool(
    name="queue_searches",
    description="Queue multiple search queries for a task. Queries are executed in background by multiple workers. Returns immediately.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID"
            },
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Search queries to execute"
            },
            "options": {
                "type": "object",
                "description": "Optional search options applied to all queries",
                "properties": {
                    "engines": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "max_pages": {"type": "integer"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "default": "medium",
                        "description": "Client-provided priority. Scheduling: priority ASC (high first), then created_at ASC (FIFO within same priority)."
                    }
                }
            }
        },
        "required": ["task_id", "queries"]
    }
)
```

#### ハンドラ実装
```python
async def _handle_queue_searches(args: dict[str, Any]) -> dict[str, Any]:
    """
    キューに検索クエリを追加（即座に応答）

    Args:
        task_id: タスクID
        queries: 検索クエリのリスト
        options: 検索オプション（全クエリに適用）

    Returns:
        {ok: true, queued_count: N, search_ids: [...]}
    """
    from src.mcp.errors import InvalidParamsError, TaskNotFoundError

    task_id = args.get("task_id")
    queries = args.get("queries", [])
    options = args.get("options", {})

    # バリデーション
    if not task_id:
        raise InvalidParamsError("task_id is required")
    if not queries or len(queries) == 0:
        raise InvalidParamsError("queries must not be empty")

    # タスク存在確認
    db = await get_database()
    task = await db.fetch_one("SELECT id FROM tasks WHERE id = ?", (task_id,))
    if task is None:
        raise TaskNotFoundError(task_id)

    # キューに追加（jobs テーブルを使用、kind='search_queue'）
    # 理由: jobs テーブルは既に優先度・状態遷移・スロット・予算管理を持っており、
    #       新テーブル追加はスキーマとauditログの二重管理を招く。
    search_ids = []
    priority = options.get("priority", "medium")
    priority_value = {"high": 10, "medium": 50, "low": 90}.get(priority, 50)

    for query in queries:
        search_id = f"s_{uuid.uuid4().hex[:12]}"
        await db.execute(
            """
            INSERT INTO jobs
                (id, task_id, kind, priority, slot, state, input_json, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                search_id,
                task_id,
                "search_queue",  # JobKind.SEARCH_QUEUE
                priority_value,
                "network_client",  # Slot.NETWORK_CLIENT
                "queued",
                json.dumps({"query": query, "options": options}),
                datetime.now(UTC).isoformat()
            )
        )
        search_ids.append(search_id)

    logger.info(
        "Searches queued",
        task_id=task_id,
        count=len(search_ids),
        queries=queries
    )

    # Note: Worker lifecycle is managed by run_server() (startup/shutdown).

    return {
        "ok": True,
        "queued_count": len(search_ids),
        "search_ids": search_ids,
        "message": f"{len(search_ids)} searches queued. Use get_status to monitor progress."
    }
```

### 3.2 バックグラウンドワーカー: `SearchQueueWorker`

#### 実装
```python
"""
Worker lifecycle policy:
- The worker is started when `run_server()` starts.
- The worker is stopped (cancelled) when `run_server()` shuts down.

Storage policy:
- Uses existing `jobs` table with `kind = 'search_queue'`.
- input_json contains {"query": ..., "options": ...}.
- output_json contains the full result JSON (for auditability).
"""

async def _search_queue_worker():
    """
    検索キューワーカー

    キューから検索を取得し、並列に実行する（workers>1）。

    Scheduling policy:
    - priority ASC (high first), then queued_at ASC (FIFO within same priority)
    - No per-task sequential guarantee (a task may have multiple searches running in parallel)

    Global resource policy:
    - Browser SERP concurrency is fixed to 1 (global) to avoid CDP/profile contention.
    - External rate limits are enforced globally (per-provider for academic APIs, per-domain for fetch).
    """
    from src.research.pipeline import search_action

    db = await get_database()

    while True:
        try:
            # Dequeue from jobs table (kind='search_queue')
            # IMPORTANT for workers>1: Claim atomically to avoid two workers picking the same row.
            #
            # Best practice: compare-and-swap claim (2 statements):
            #   1) SELECT candidate (priority, queued_at)
            #   2) UPDATE ... WHERE id=? AND state='queued'
            #      - If rowcount==1: claim succeeded
            #      - If rowcount==0: another worker won; retry
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
                # キューが空 - 1秒待機
                await asyncio.sleep(1)
                continue

            search_id = row["id"]
            task_id = row["task_id"]
            input_data = json.loads(row["input_json"]) if row["input_json"] else {}
            query = input_data.get("query", "")
            options = input_data.get("options", {})

            # Attempt to claim (CAS)
            cursor = await db.execute(
                "UPDATE jobs SET state = ?, started_at = ? WHERE id = ? AND state = 'queued'",
                ("running", datetime.now(UTC).isoformat(), search_id)
            )
            if getattr(cursor, "rowcount", 0) != 1:
                # Lost the race: another worker claimed it. Retry loop.
                continue

            logger.info(
                "Processing search from queue",
                search_id=search_id,
                task_id=task_id,
                query=query
            )

            # 探索状態を取得
            state = await _get_exploration_state(task_id)

            # 検索を実行（既存のsearch_actionを使用）
            try:
                result = await search_action(
                    task_id=task_id,
                    query=query,
                    state=state,
                    options=options
                )

                # 成功 - ステータスを"completed"に更新、output_json に結果を保存
                await db.execute(
                    """
                    UPDATE jobs
                    SET state = ?, finished_at = ?, output_json = ?
                    WHERE id = ?
                    """,
                    (
                        "completed",
                        datetime.now(UTC).isoformat(),
                        json.dumps(result),
                        search_id
                    )
                )

                # Long polling 通知（進捗変化を待っているクライアントに知らせる）
                state.notify_status_change()

                logger.info(
                    "Search completed from queue",
                    search_id=search_id,
                    task_id=task_id
                )

            except asyncio.CancelledError:
                # stop_task(mode=immediate) によるキャンセル
                # state='cancelled' にすることで「キャンセルされた」ことを明示的に記録
                await db.execute(
                    "UPDATE jobs SET state = ?, finished_at = ? WHERE id = ?",
                    ("cancelled", datetime.now(UTC).isoformat(), search_id)
                )
                logger.info(
                    "Search cancelled from queue",
                    search_id=search_id,
                    task_id=task_id
                )
                raise  # Re-raise to propagate cancellation

            except Exception as e:
                # エラー - ステータスを"failed"に更新
                await db.execute(
                    """
                    UPDATE jobs
                    SET state = ?, finished_at = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        "failed",
                        datetime.now(UTC).isoformat(),
                        str(e),
                        search_id
                    )
                )

                # Long polling 通知
                state.notify_status_change()

                logger.error(
                    "Search failed from queue",
                    search_id=search_id,
                    task_id=task_id,
                    error=str(e),
                    exc_info=True
                )

        except asyncio.CancelledError:
            # Worker shutdown (run_server stop)
            logger.info("Search queue worker shutting down")
            break

        except Exception as e:
            # ワーカー自体のエラー - ログして続行
            logger.error(
                "Search queue worker error",
                error=str(e),
                exc_info=True
            )
            await asyncio.sleep(5)  # エラー時は5秒待機
```

### 3.3 変更するツール: `get_status` (wait / long polling 追加)

#### 3.3.1 wait（long polling）の実装方式（MCP stdio前提）

MCP（stdio）では、サーバからクライアントへ進捗をpushする常設チャネルを前提にできない。
そのため `get_status(wait=N)` を「サーバ側で最大N秒ブロックし、進捗変化があれば早めに返す」形で実現する。

本プロジェクトでのベストは **`asyncio.Event` + in-memory state** とする。

- 理由:
  - `ExplorationState` は既にタスクごとにメモリ上に存在しており、状態変化を直接検知できる
  - DB polling は無駄な I/O を生み、MCP の応答遅延を増やす
  - ワーカーが完了/失敗/キャンセル時に `state.notify_status_change()` を呼ぶだけでよい

実装の要点:
- `ExplorationState` に `_status_changed: asyncio.Event` を追加
- ワーカーが検索完了/失敗/キャンセル時に `state.notify_status_change()` を呼び、Event を set
- `get_status(wait=N)` は `asyncio.wait_for(state.wait_for_change(), timeout=N)` で待機
- タイムアウト時は現在の状態を返す（`wait=0` と同じ）

```python
# ExplorationState に追加
class ExplorationState:
    def __init__(self, ...):
        ...
        self._status_changed = asyncio.Event()

    def notify_status_change(self) -> None:
        """Notify waiting clients that status has changed."""
        self._status_changed.set()

    async def wait_for_change(self, timeout: float) -> bool:
        """Wait for status change or timeout.

        Returns:
            True if change occurred, False if timeout.
        """
        try:
            await asyncio.wait_for(self._status_changed.wait(), timeout)
            self._status_changed.clear()
            return True
        except asyncio.TimeoutError:
            return False
```

#### 新しいツール定義
```python
Tool(
    name="get_status",
    description="Get unified task and exploration status. Optionally wait (long polling) before returning. Returns task info, search states (including queued searches), metrics, budget, and auth queue. No recommendations - data only.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID to get status for"
            },
            "wait": {
                "type": "integer",
                "description": "Max seconds to wait for progress before returning (long polling). Default: 0 (return immediately).",
                "default": 0,
                "minimum": 0,
                "maximum": 60
            }
        },
        "required": ["task_id"]
    }
)
```

#### 新しいハンドラ実装
```python
async def _handle_get_status(args: dict[str, Any]) -> dict[str, Any]:
    """
    タスクステータスを取得（オプションでwait / long polling）

    Args:
        task_id: タスクID
        wait: 進捗変化があるまで最大wait秒待機（デフォルト: 0 = 即時返却）

    Returns:
        タスク状態、検索状態（キュー含む）、メトリクス、バジェット、認証キュー
    """
    from src.mcp.errors import InvalidParamsError, TaskNotFoundError

    task_id = args.get("task_id")
    wait = args.get("wait", 0)

    if not task_id:
        raise InvalidParamsError("task_id is required")

    # 探索状態を取得（Long polling のため先に取得）
    state = await _get_exploration_state(task_id)

    # Long polling (MCP client has no time sense; server provides it)
    # Semantics: wait for progress change OR until timeout=wait.
    if wait > 0:
        logger.debug(f"Long polling wait={wait}s", task_id=task_id)
        # asyncio.Event を使って変化を待つ（DB polling しない）
        await state.wait_for_change(timeout=float(wait))

    # タスク存在確認
    db = await get_database()
    task = await db.fetch_one(
        "SELECT id, query, status FROM tasks WHERE id = ?",
        (task_id,)
    )

    if task is None:
        raise TaskNotFoundError(task_id)

    # 既存のステータス取得ロジック
    status_data = await state.get_status()

    # ★ 新規: 検索キュー（jobs テーブル、kind='search_queue'）の状態を追加
    queue_items = await db.fetch_all(
        """
        SELECT id, input_json, state, priority, queued_at, started_at, finished_at
        FROM jobs
        WHERE task_id = ? AND kind = 'search_queue'
        ORDER BY priority ASC, queued_at ASC
        """,
        (task_id,)
    )

    queued_searches = []
    for row in queue_items:
        input_data = json.loads(row["input_json"]) if row["input_json"] else {}
        queued_searches.append({
            "id": row["id"],
            "query": input_data.get("query", ""),
            "status": row["state"],  # "queued", "running", "completed", "failed", "cancelled"
            "priority": row["priority"],
            "created_at": row["queued_at"],
            "started_at": row["started_at"],
            "completed_at": row["finished_at"]
        })

    # 既存の検索状態（state.get_status()から）とキューを統合
    all_searches = status_data.get("searches", [])

    # キュー深度を計算
    queue_depth = sum(1 for s in queued_searches if s["status"] == "queued")
    running_count = sum(1 for s in queued_searches if s["status"] == "running")

    return {
        "ok": True,
        "task_id": task_id,
        "status": task["status"],
        "query": task["query"],
        "searches": all_searches,  # 実行中/完了した検索
        "queue": {
            "depth": queue_depth,       # キューに残っている数
            "running": running_count,   # 実行中の数
            "items": queued_searches    # キューの全アイテム
        },
        "metrics": status_data.get("metrics", {}),
        "budget": status_data.get("budget", {}),
        "auth_queue": status_data.get("auth_queue", []),
        "warnings": status_data.get("warnings", []),
        "idle_seconds": status_data.get("idle_seconds", 0)
    }
```

### 3.4 データベース: 既存 `jobs` テーブルの拡張

新規テーブルは作成しない。既存の `jobs` テーブル（`src/storage/schema.sql`）を使用する。

```sql
-- 既存の jobs テーブルを使用（変更不要）
-- kind = 'search_queue' として検索リクエストを保存
--
-- jobs テーブルは既に以下を持つ:
--   id, task_id, kind, priority, slot, state, input_json, output_json,
--   error_message, queued_at, started_at, finished_at, ...
--
-- 検索リクエスト用のマッピング:
--   kind = 'search_queue'
--   slot = 'network_client'
--   input_json = {"query": "...", "options": {...}}
--   output_json = 検索結果JSON（completed時）
--   state = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
```

**理由（ADR-0010 参照）**:
- `jobs` テーブルは既に優先度・状態遷移・スロット・予算管理を持っている
- 新テーブル追加はスキーマと監査ログの二重管理を招く
- `JobKind` に `SEARCH_QUEUE = "search_queue"` を追加するだけでよい

**キャンセル時の論理的一貫性**:
- `stop_task(mode=immediate)` でキャンセルされた場合、`jobs.state = 'cancelled'` が設定される
- これにより「このジョブはキャンセルされた」ことが明示的に記録される
- 部分的に書き込まれた pages/fragments は残り得るが、`state='cancelled'` を参照することで論理的に除外可能

---

### 3.5 変更するツール: `stop_task`（停止モードを追加）

`stop_task` は「完了を待つ」か「即時に打ち切る」かを選べる。

- **mode=graceful**:
  - これ以上キューから新規ジョブを開始しない（`jobs.state = 'queued'` → `'cancelled'`）
  - すでにrunningの検索は完了を待つ（`jobs.output_json` に結果JSONを保存する）
  - 監査性（フル結果JSON）を優先したい場合のデフォルト
- **mode=immediate**:
  - queued → cancelled（`jobs.state = 'cancelled'`）
  - running → `asyncio.Task.cancel()` でキャンセルし、`jobs.state = 'cancelled'` に更新（result JSONは保存しない）
  - **soft cleanup を実施**し、タスク固有データ（claims/queries/serp_items 等）と、当該taskのclaimsに接続するedgesを削除して不可視化する
  - ただしキャンセル時点までにDBへ書かれた pages/fragments 等の"痕跡"は残り得る（強い原子性はv1では保証しない）
  - `pages.url UNIQUE` のため pages/fragments はタスク横断で再利用され得る（詳細は ADR-0005 の Data Ownership & Scope を参照）

**論理的一貫性の保証**:
- `jobs.state = 'cancelled'` が設定されることで、「このジョブはキャンセルされた」ことが明示的に記録される
- 下流の処理（レポート生成、get_materials 等）は `state = 'cancelled'` のジョブに紐づくデータを論理的に除外できる
- 技術的に「途中痕跡ゼロ」を保証するのは難しいため、v1は **論理的一貫性（jobs.state で整合）** と **クリーンに復帰できる運用** を優先する

#### Hard cleanup（orphans_only）

soft cleanup の後、ストレージ回収が必要な場合に限り **hard(orphans_only)** を実行し、孤児データのみを削除する。
仕様の正は `docs/adr/0005-evidence-graph-structure.md`（Cleanup Policy）とする。

## 4. 使用例

### 4.1 典型的なワークフロー

```python
# ① タスク作成
response = await call_tool("create_task", {
    "query": "量子コンピュータの最新動向を調査"
})
task_id = response["task_id"]  # "task_abc123"

# ② 複数の検索をキューに投入（即座に応答）
await call_tool("queue_searches", {
    "task_id": task_id,
    "queries": [
        "量子コンピュータ 2025 最新論文",
        "量子エラー訂正 実用化",
        "量子アルゴリズム 機械学習応用"
    ],
    "options": {
        "priority": "high",
        "max_pages": 10
    }
})
# 応答: {ok: true, queued_count: 3, search_ids: ["s_1", "s_2", "s_3"]}

# ③ ステータスをポーリング（最大10秒待機してから確認 / long polling）
while True:
    status = await call_tool("get_status", {
        "task_id": task_id,
        "wait": 10  # ← MCPクライアントに時間感覚を提供（long polling）
    })

    # キューの状態を確認
    queue_depth = status["queue"]["depth"]
    running = status["queue"]["running"]

    print(f"Queue: {queue_depth}, Running: {running}")

    # 全て完了したか確認
    if queue_depth == 0 and running == 0:
        break

# ④ レポート素材を取得
materials = await call_tool("get_materials", {
    "task_id": task_id
})

# ⑤ タスク終了（停止モードを選べる）
# - graceful: 実行中は完了を待つ（監査性優先）
# - immediate: 即時打ち切り（結果JSONは保存しない）
await call_tool("stop_task", {
    "task_id": task_id,
    "reason": "completed",
    "mode": "graceful"
})
```

### 4.2 優先度付き検索

```python
# 高優先度の検索を先に実行
await call_tool("queue_searches", {
    "task_id": task_id,
    "queries": ["緊急: 重要な調査"],
    "options": {"priority": "high"}
})

# 通常優先度の検索（後から実行される）
await call_tool("queue_searches", {
    "task_id": task_id,
    "queries": ["補足調査1", "補足調査2"],
    "options": {"priority": "medium"}
})
```

### 4.3 ステータスレスポンス例

```json
{
  "ok": true,
  "task_id": "task_abc123",
  "status": "exploring",
  "query": "量子コンピュータの最新動向を調査",
  "searches": [
    {
      "id": "s_1",
      "query": "量子コンピュータ 2025 最新論文",
      "status": "completed",
      "pages_fetched": 8,
      "useful_fragments": 15,
      "satisfaction_score": 0.92
    }
  ],
  "queue": {
    "depth": 1,
    "running": 1,
    "items": [
      {
        "id": "s_2",
        "query": "量子エラー訂正 実用化",
        "status": "running",
        "priority": "high",
        "created_at": "2025-12-21T10:00:00Z",
        "started_at": "2025-12-21T10:05:00Z"
      },
      {
        "id": "s_3",
        "query": "量子アルゴリズム 機械学習応用",
        "status": "queued",
        "priority": "medium",
        "created_at": "2025-12-21T10:00:01Z"
      }
    ]
  },
  "metrics": {
    "total_searches": 1,
    "satisfied_count": 1,
    "total_pages": 8,
    "total_fragments": 15
  },
  "budget": {
    "pages_used": 8,
    "pages_limit": 120,
    "remaining_percent": 93
  }
}
```

---

## 5. アーキテクチャの利点

### 5.1 MCPクライアント視点

| 項目 | 現在（同期search） | 新しい設計（queue_searches） |
|------|-------------------|------------------------------|
| **ブロッキング** | あり（数十秒〜数分） | なし（即座に応答） |
| **複数検索** | シーケンシャル呼び出し必要 | 1回の呼び出しで複数投入 |
| **ポーリング** | タイミングが難しい | wait（long polling）で制御可能 |
| **ツール数** | 12個 | **10個** |
| **複雑さ** | 中程度 | **シンプル** |

### 5.2 サーバ内部視点

| 項目 | 利点 |
|------|------|
| **非同期処理** | 既存のsearch_actionを再利用、変更最小限 |
| **リソース管理** | ジョブスケジューラとの統合が容易 |
| **エラーハンドリング** | キュー単位でリトライ・スキップが可能 |
| **監視** | jobsテーブル（kind='search_queue'）で全体像を把握 |
| **スケーラビリティ** | ワーカー数を増やせば並列度向上可能（将来） |

### 5.3 MCPクライアントの時間感覚問題の解決

**問題:** Cursor AIなどのMCPクライアントは適切なポーリング間隔を判断できない

**解決策:** `get_status`の`wait`パラメータ（long polling）
```python
# クライアント側（Cursor AI）
# サーバ側で10秒待機してから状態確認
# → クライアントは無駄なループを回さない
status = await call_tool("get_status", {
    "task_id": task_id,
    "wait": 10
})
```

**効果:**
- クライアント側のコードがシンプル
- サーバ側で適切な待機時間を制御
- ネットワーク/CPU負荷の削減

---

## 6. 実装ロードマップ

> **DBフェーズ**: 開発フェーズ（DB作り直しOK、migration不要）

### Phase 1: コア機能実装 ✅ DONE

**前提作業:**
- [ ] Cursor Rules/Commands の `search` ツール呼び出し箇所を特定（移行計画立案）
- [x] `rm data/lyra.db` でDB削除（テストは `test_database` フィクスチャで隔離されるため影響なし）

**1.1 JobKind 拡張（スキーマ変更不要）**
- [x] `src/scheduler/jobs.py` の `JobKind` に `SEARCH_QUEUE = "search_queue"` を追加
- [x] `KIND_TO_SLOT` / `KIND_PRIORITY` に対応エントリを追加
- [x] **テスト**: JobKind.SEARCH_QUEUE を使ったジョブ投入の単体テスト

**1.2 バックグラウンドワーカー**
- [x] `_search_queue_worker()` 実装（`src/scheduler/search_worker.py`）
- [x] `run_server()` で起動/停止を管理（2 workers）
- [x] `asyncio.CancelledError` でのキャンセル処理（`jobs.state = 'cancelled'` に更新）
- [x] **テスト**: ワーカーの単体テスト（モック使用）

**1.3 新しいツール: queue_searches**
- [x] ツール定義（`src/mcp/server.py`）
- [x] `_handle_queue_searches`ハンドラ実装
- [x] レスポンススキーマ（`src/mcp/schemas/queue_searches.json`）
- [x] **テスト**: ツールハンドラの単体テスト

**1.4 既存ツールの変更: get_status**
- [x] `wait`パラメータ追加（`src/mcp/server.py`）
- [x] `queue`フィールド追加、スキーマ更新（`src/mcp/schemas/get_status.json`）
- [x] `ExplorationState` に `asyncio.Event` 追加（`src/research/state.py`）
- [x] **テスト**: get_status拡張の単体テスト

**1.5 統合テスト**
- [x] キュー投入 → ワーカー処理 → ステータス確認のE2Eフロー
- [x] エラーケース（タスク不在、バジェット超過など）
- [x] **ゲート**: Phase 1完了条件 = 全テストパス + queue_searchesが動作

### Phase 2: ツール削除とクライアント移行

> **依存**: Phase 1完了後に開始（queue_searchesが動作することが前提）

**2.1 MCPクライアント側更新**
- [ ] Cursor Rules (`.cursor/rules/`): `search` → `queue_searches` + `get_status(wait=N)` パターンへ移行
- [ ] Cursor Commands (`.cursor/commands/`): 使用例を更新
- [ ] テスト用プロンプトで動作確認

**2.2 ツール削除**
- [ ] `search`ツール: MCPツール定義から削除、`search_action`は維持（ワーカーが使用）
- [ ] `notify_user`, `wait_for_user`: MCPツール定義から削除、ハンドラ削除
- [ ] 依存コードの確認・修正

**2.3 ドキュメント更新**
- [ ] `README.md` のMCPツール一覧を更新（12ツール → 10ツール）
- [ ] Cursor Rules/Commands (`.cursor/rules/`, `.cursor/commands/`) 内の使用例を更新
- [ ] **テスト**: 削除後の回帰テスト（既存テストがパスすることを確認）

### Phase 3: 最終検証

**3.1 パフォーマンステスト**
- [ ] 大量キュー（10+検索）
- [ ] ワーカーの安定性

**3.2 Cursor AI統合テスト**
- [ ] 実際のワークフローで動作確認

**3.3 完了チェックリスト**
- [ ] `JobKind.SEARCH_QUEUE` が追加され、`jobs` テーブルで検索キューが管理されている
- [ ] `queue_searches`ツールが動作する
- [ ] `get_status`の`wait`（long polling、asyncio.Event）が動作する
- [ ] `stop_task(mode=immediate)` でキャンセル時に `jobs.state = 'cancelled'` が設定される
- [ ] `search`, `notify_user`, `wait_for_user`がMCPツール一覧から削除されている
- [ ] Cursor Rules/Commandsが更新されている
- [ ] README.mdが最新（10ツール）
- [ ] 全テストがパスする
- [ ] ADR-0010のImplementation Statusを「実装完了」に更新

---

## 7. 将来の拡張性

### 7.1 並列ワーカー（v1で2 workers）

v1では **2 workers** で並列実行する:

```python
# 複数ワーカーを起動（キュー全体で並列）
for i in range(2):
    asyncio.create_task(_search_queue_worker(worker_id=i))
```

**注意:** 同一タスク内の検索も並列になり得る（完了順は非決定）。必要なら後で「タスク内シーケンシャル」を復活させる。

### 7.2 検索キューの優先度制御

- ユーザ指定の優先度（high/medium/low）
- 動的優先度調整（バジェット残量に応じて）
- デッドライン指定（特定時刻までに完了）

### 7.3 検索結果のストリーミング

SSE転送を使用した場合、検索進捗をリアルタイムで通知:

```python
# 将来の可能性（SSE使用）
async for event in subscribe_search_progress(task_id):
    print(event)  # {type: "page_fetched", page_num: 5, ...}
```

---

## 8. まとめ

### 8.1 主要な変更点

| 変更 | 内容 |
|------|------|
| **削除** | `search`, `notify_user`, `wait_for_user` |
| **追加** | `queue_searches` |
| **変更** | `get_status` (wait追加、キュー状態統合) |
| **内部** | `SearchQueueWorker` (バックグラウンド処理) |

### 8.2 ツール数の変化

```
12ツール → 10ツール

削除: 3個（search, notify_user, wait_for_user）
追加: 1個（queue_searches）
変更: 1個（get_status）
維持: 8個（create_task, stop_task, get_materials, calibration_metrics, calibration_rollback, get_auth_queue, resolve_auth, feedback）
```

### 8.3 効果

1. **シンプル化** - ツール数削減、概念的にも明快
2. **非同期化** - クライアントがブロックされない
3. **効率化** - wait（long polling）で無駄なポーリングを削減
4. **拡張性** - 将来の並列化やストリーミングに対応可能

### 8.4 移行の容易さ

- **既存コードへの影響最小限**
  - `search_action`は維持（内部で使用）
  - ジョブスケジューラとの統合は既存の仕組みを利用
  - ExplorationStateは最小限の変更（`asyncio.Event` 追加のみ、§3.3参照）

- **段階的移行**
  - Phase 1でキュー機能を追加
  - Phase 2で古いツールを削除
  - 互換性を保ちながら移行可能

---

## 9. 認証キュー統合の設計判断

### 9.1 検討課題

10ツール構成において、`get_auth_queue`と`resolve_auth`を維持すべきか、それとも`get_status`に統合すべきかを検討した。

**背景:**
- `get_status`は既に認証キューのサマリー情報を返している
- `get_auth_queue`はより詳細な認証キュー情報を提供
- 部分的な機能重複が存在

### 9.2 詳細分析

#### A. 現在の実装の特徴

**`get_status`の認証情報（サマリー）:**
```json
{
  "auth_queue": {
    "pending_count": 5,
    "high_priority_count": 2,
    "domains": ["arxiv.org", "jstor.org"],
    "by_auth_type": {"cloudflare": 3, "login": 2}
  },
  "warnings": [
    "[critical] 認証待ち5件（高優先度2件）: 一次資料アクセスがブロック中"
  ]
}
```

**`get_auth_queue`の詳細情報:**
```json
{
  "group_by": "domain",
  "groups": {
    "arxiv.org": [
      {
        "queue_id": "iq_abc123",
        "url": "https://arxiv.org/pdf/...",
        "auth_type": "cloudflare",
        "priority": "high"
      }
    ]
  }
}
```

**`get_auth_queue`特有の機能:**
1. **全タスク横断取得** - `task_id`省略で全タスクの認証キューを取得
2. **グループ化** - ドメイン別/タイプ別にグループ化
3. **優先度フィルタリング** - 高優先度のみ取得など
4. **個別アイテム詳細** - queue_id、URL、認証タイプなど

#### B. MCPクライアントUXワークフロー

```python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# フェーズ1: 監視（高頻度ポーリング - 10秒ごと）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
while exploring:
    status = await get_status(task_id, wait=10)

    # 警告から認証の必要性を検出
    if "[critical] 認証待ち" in status.warnings:
        break  # → 認証解決フェーズへ

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# フェーズ2: 認証解決（認証発生時のみ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 詳細を取得してユーザーに提示
auth_details = await get_auth_queue(
    task_id=task_id,
    group_by="domain",
    priority_filter="high"
)

# ユーザーがブラウザで認証完了後
await resolve_auth(
    target="domain",
    domain="arxiv.org",
    action="complete",
    success=True
)
```

**ワークフローの特徴:**
- **2段階設計**: 監視（頻繁）→ 解決（必要時のみ）
- **関心の分離**: ダッシュボード（get_status）vs 認証ワークフロー（get_auth_queue + resolve_auth）
- **パフォーマンス**: get_statusは軽量（グループ化処理なし）

### 9.3 統合オプションの評価

#### Option A: 統合しない（現状維持）

**設計:**
- `get_status` - タスクダッシュボード（認証サマリー + 警告生成）
- `get_auth_queue` - 認証解決専用（詳細、グループ化、フィルタリング）
- `resolve_auth` - 認証完了報告

**Pros:**
- ✅ **関心の分離**: 監視と解決の責務が明確
- ✅ **パフォーマンス**: get_statusは軽量（10秒ごとのポーリングに最適）
- ✅ **柔軟性**: get_auth_queueで全タスク横断取得が可能
- ✅ **UX**: 2段階ワークフロー（監視→解決）が自然

**Cons:**
- ⚠️ ツール数が9個（ただし許容範囲）

#### Option B: get_statusに統合

**設計:**
- `get_status` - すべての情報（認証詳細、グループ化も含む）
- `resolve_auth` - 認証完了報告

**Pros:**
- ✅ ツール数削減（8個）

**Cons:**
- ❌ **パラメータ複雑化**: auth_group_by, auth_priority_filterなどが追加される
- ❌ **パフォーマンス低下**: 毎回グループ化処理（不要な場合も実行）
- ❌ **全タスク取得不可**: get_statusはtask_id必須
- ❌ **責務の混在**: ダッシュボードと認証解決ワークフローが混ざる

### 9.4 設計判断

**決定: Option A（統合しない・現状維持）**

**判断理由:**

1. **UXの観点**
   - 2段階ワークフロー（監視→解決）がCursor AIの使用パターンに最適
   - get_statusは「状況把握」、get_auth_queueは「問題解決」という明確な役割分担

2. **パフォーマンス**
   - get_statusは10秒ごとに呼ばれる高頻度ポーリング対象
   - グループ化やフィルタリングなどの重い処理を含めるべきではない

3. **柔軟性**
   - get_auth_queue(task_id=null)で全タスクの認証キューを取得可能
   - 複数タスク並行実行時に重要な機能

4. **ツール数の妥当性**
   - 10ツールは十分少ない（12ツールから17%削減）
   - 機能的に必要なツールを無理に削減する必要はない
   - シンプルさと機能性のバランスが重要

**結論:**
`get_auth_queue`と`resolve_auth`は独立したツールとして維持する。これにより、MCPクライアントのUX、パフォーマンス、柔軟性のバランスが最適化される。

### 9.5 最終ツール構成の確定

**10ツール（確定版）:**

| # | ツール名 | 目的 | 設計判断 |
|---|---------|------|---------|
| 1 | `create_task` | タスク作成 | 維持 |
| 2 | `queue_searches` | 検索キューに投入 | **新規（v2）** |
| 3 | `get_status` | タスク状態確認 | **wait追加（v2）** + 認証サマリー維持 |
| 4 | `stop_task` | タスク終了 | **mode追加（graceful/immediate）** |
| 5 | `get_materials` | レポート素材取得 | 維持 |
| 6 | `calibration_metrics` | モデル較正評価 | **リネーム（旧calibrate）** |
| 7 | `calibration_rollback` | 較正ロールバック | 維持 |
| 8 | `get_auth_queue` | 認証キュー詳細取得 | **維持（統合しない）** |
| 9 | `resolve_auth` | 認証完了報告 | 維持 |
| 10 | `feedback` | Human-in-the-loop入力 | **Phase 6で追加** |

**削除されたツール:**
- `search` - 内部化（queue_searchesに置き換え）
- `notify_user` - 不要（get_statusのwarningsで代替）
- `wait_for_user` - 不要（ポーリングで代替）

**ツール削減率:** 12ツール → 10ツール（**17%削減**）

---

## 10. 結論

**現在の`search`ツールは同期的でクライアントをブロックする**という本質的な問題を、**ツールを増やすのではなく非同期セマンティクスに変更する**ことで解決します。

### 主要な設計決定

1. **非同期セマンティクス**
   - `queue_searches` - 即座に応答、バックグラウンド処理
   - SearchQueueWorkerがキューから優先度順に取り出し、2 workersで並列に処理

2. **時間感覚の提供**
   - `get_status` with `wait` - MCPクライアントに時間感覚を提供（long polling）
   - サーバ側で適切な待機時間を制御

3. **ツール統合の方針**
   - ツール数削減（11 → 9）を達成
   - しかし、機能的に必要なツールは維持（get_auth_queue、resolve_auth）
   - シンプルさと機能性のバランスを重視

4. **関心の分離**
   - 監視ツール（get_status）- 軽量、高頻度ポーリング
   - ワークフロー専用ツール（get_auth_queue、queue_searches）- 詳細、必要時のみ
   - 明確な責務分担でUXとパフォーマンスを最適化

### 実現される効果

- ✅ **ノンブロッキング**: クライアントはキュー投入後すぐに次の操作が可能
- ✅ **効率的**: wait（long polling）で無駄なポーリングを削減
- ✅ **シンプル**: 17%のツール削減（12→10）、概念的にも明快
- ✅ **拡張性**: 将来の並列化やストリーミングに対応可能
- ✅ **バランス**: 機能性を損なわず、適切な粒度でツールを設計

この設計により、**効率的で拡張性があり、MCPプロトコルの制約内で最大限のパフォーマンス**を実現できます。

---

**文書バージョン:** 2.2
**作成日:** 2025-12-21
**最終更新:** 2025-12-24（実装ロードマップ更新: DB作り直し方式、MCPクライアント更新を明記）
**著者:** Claude (Sonnet 4.5 / Opus 4.5)
**レビュー状態:** 設計確定 - 実装準備完了

**関連ドキュメント:**
- `docs/adr/0010-async-search-queue.md` - 非同期検索キューADR
- `README.md` - MCPツール一覧（現在12ツール、移行後10ツール）
