# 非同期アーキテクチャ分析とMCP統合の改善提案

## Executive Summary

本文書は、Lyraの非同期アーキテクチャの現状分析と、MCPプロトコルの特性を考慮した改善提案を提供します。

**主要な発見:**
- ✅ **サーバ内部の非同期処理は徹底されている** - すべてのMCPハンドラ、検索パイプライン、データベース操作は完全に非同期
- ✅ **ジョブスケジューラと複数のキューシステムが存在** - スロットベースのリソース管理、認証キュー、BFSクローラキューなど
- ✅ **タスク処理状況を監視するMCPツールが存在** - `get_status`がすべての情報を提供
- ⚠️ **MCPプロトコルの制約** - STDIO転送は本質的にシーケンシャル（要求-応答モデル）
- ⚠️ **バッチ操作のサポート不足** - 複数タスク/検索の同時実行にはクライアント側の複数呼び出しが必要

---

## 1. 現状の非同期アーキテクチャ分析

### 1.1 完全非同期のコンポーネント

#### A. MCPサーバ (`src/mcp/server.py` - 1,577行)

**非同期パターン:**
```python
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    result = await _dispatch_tool(name, arguments)
    # ...

async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "create_task": _handle_create_task,      # async
        "get_status": _handle_get_status,         # async
        "search": _handle_search,                 # async
        "stop_task": _handle_stop_task,           # async
        "get_materials": _handle_get_materials,   # async
        "get_auth_queue": _handle_get_auth_queue, # async
        "resolve_auth": _handle_resolve_auth,     # async
        # ...
    }
    return await handler(arguments)
```

**特徴:**
- すべてのツールハンドラが`async def`
- データベース操作は`await get_database()`経由で非同期
- エビデンスグラフ取得は`await get_evidence_graph(task_id)`で非同期
- Chrome自動起動は`asyncio.create_subprocess_exec()`で非同期

#### B. 検索パイプライン (`src/research/pipeline.py` - 1,382行以上)

**完全非同期の検索フロー:**
```python
async def search_action(task_id, query, state, options):
    """統合検索エントリポイント"""
    pipeline = SearchPipeline(task_id, state)
    result = await pipeline.execute(query, search_options)
    return result.to_dict()

class SearchPipeline:
    async def execute(self, query, options):
        # タイムアウト付き実行 (§2.1.5 アイドル検出)
        result = await asyncio.wait_for(
            self._execute_impl(search_id, query, options, result),
            timeout=timeout_seconds
        )
        return result
```

**並列実行パターン:**
```python
# 学術検索とブラウザ検索を並列実行
serp_items, academic_response = await asyncio.gather(
    browser_task, academic_task, return_exceptions=True
)
```

#### C. 検索実行エンジン (`src/research/executor.py` - 841行)

**非同期操作の連鎖:**
```python
async def execute(self, query, priority, budget_pages, ...):
    # クエリ拡張
    expanded_queries = await self._expand_query(query)

    # 検索実行
    serp_items, error = await self._execute_search(expanded_query)

    # フェッチと抽出（並列）
    await self._fetch_and_extract(search_id, item, result)

    # コンテンツ抽出
    extract_result = await extract_content(...)

    # LLM抽出
    result = await llm_extract(...)
```

#### D. エビデンスグラフ (`src/filter/evidence_graph.py` - 1,348行)

**非同期取得と永続化:**
```python
async def get_evidence_graph(task_id: str | None = None) -> EvidenceGraph:
    """エビデンスグラフの取得または作成"""
    global _graph

    if _graph is None or _graph.task_id != task_id:
        _graph = EvidenceGraph(task_id=task_id)
        if task_id:
            await _graph.load_from_db(task_id)  # 非同期ロード

    return _graph

async def add_claim_evidence(...):
    graph = await get_evidence_graph(task_id)
    edge_id = graph.add_edge(...)

    # 即座に永続化
    db = await get_database()
    await db.insert("edges", {...})
```

**特徴:**
- NetworkX DiGraph (インメモリ高速クエリ)
- SQLite永続化バッキング
- 遅延ロード

---

### 1.2 ジョブスケジューラとキューシステム

#### A. スロットベースジョブスケジューラ (`src/scheduler/jobs.py` - 609行)

**アーキテクチャ:**
```python
class JobScheduler:
    def __init__(self):
        # スロットごとにPriorityQueueを作成
        self._queues: dict[Slot, asyncio.PriorityQueue] = {}
        self._running: dict[Slot, set[str]] = {}
        self._workers: dict[Slot, list[asyncio.Task]] = {}

        for slot in Slot:
            self._queues[slot] = asyncio.PriorityQueue()
            self._running[slot] = set()
```

**スロットと並列度:**

| スロット | ジョブタイプ | 並列度 |
|---------|-------------|-------|
| GPU | EMBED, RERANK, LLM | 1 |
| BROWSER_HEADFUL | ブラウザ操作 | 1 |
| NETWORK_CLIENT | SERP, FETCH | 4 |
| CPU_NLP | EXTRACT, NLI | 8 |

**ワーカープール:**
```python
async def start(self):
    # 各スロットに対してワーカータスクを起動
    for slot in Slot:
        limit = SLOT_LIMITS[slot]
        workers = []
        for i in range(limit):
            task = asyncio.create_task(self._worker(slot, i))
            workers.append(task)
        self._workers[slot] = workers

async def _worker(self, slot: Slot, worker_id: int):
    while self._started:
        # タイムアウト付きでジョブを取得
        priority, job_id, ... = await asyncio.wait_for(
            self._queues[slot].get(), timeout=1.0
        )

        # バジェット追跡付きで実行
        result = await self._execute_job(kind, input_data, task_id, cause_id)
```

**バジェット統合 (§3.1, §3.2.2):**
- FETCHジョブ前にページ制限チェック
- LLMジョブ前にLLM比率チェック
- 完了後に消費量を記録

#### B. 認証キュー (`src/utils/notification.py` - 1,639行以上)

**非同期手動介入キュー:**
```python
class InterventionQueue:
    async def enqueue(self, task_id, url, domain, auth_type, ...):
        """キューにURLを追加"""
        await self._db.execute(
            "INSERT INTO intervention_queue ..."
        )

    async def get_pending(self, task_id=None, priority=None):
        """保留中の認証を取得"""
        rows = await self._db.fetch_all(...)
        return [dict(row) for row in rows]

    async def complete(self, queue_id, success, session_data):
        """アイテムを完了としてマーク"""
        # セッションクッキーをキャプチャして再利用
        await self._db.execute(
            "UPDATE intervention_queue SET status='success' ..."
        )
```

**主要機能:**
- ノンブロッキングキュー（ユーザ駆動完了、タイムアウトなし）
- クッキーキャプチャによるセッション再利用
- バッチ操作 (`complete_domain`)
- 3回失敗後のドメインクールダウン

#### C. BFSクローラキュー (`src/crawler/bfs.py`)

```python
queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
```

---

### 1.3 タスク処理状況の監視ツール

#### `get_status` ツール (§3.2.1)

**統合ステータス応答構造:**
```json
{
  "ok": true,
  "task_id": "task_xxx",
  "status": "exploring|paused|completed|failed",
  "query": "元のクエリ",
  "searches": [
    {
      "id": "s_xxx",
      "query": "検索クエリ",
      "status": "running|satisfied|partial|exhausted",
      "pages_fetched": 15,
      "useful_fragments": 23,
      "harvest_rate": 1.53,
      "satisfaction_score": 0.85,
      "has_primary_source": true
    }
  ],
  "metrics": {
    "total_searches": 5,
    "satisfied_count": 3,
    "total_pages": 42,
    "total_fragments": 98,
    "total_claims": 15,
    "elapsed_seconds": 245
  },
  "budget": {
    "pages_used": 42,
    "pages_limit": 120,
    "time_used_seconds": 245,
    "time_limit_seconds": 1200,
    "remaining_percent": 65
  },
  "auth_queue": [
    {
      "id": "iq_xxx",
      "domain": "example.com",
      "auth_type": "cloudflare",
      "status": "pending"
    }
  ],
  "warnings": [],
  "idle_seconds": 12
}
```

**機能:**
- すべての並行検索の状態を追跡
- メトリクス、バジェット、認証キューを統合
- アイドル検出のサポート (§2.1.5)

---

## 2. MCPプロトコルの特性と制約

### 2.1 STDIO転送の本質的な制約

**プロトコル動作:**
```
クライアント (Cursor AI)
  ↓ JSON-RPC request (stdin)
MCPサーバ (Lyra)
  ↓ 処理 (await _dispatch_tool)
  ↓ 結果生成
  ↑ JSON-RPC response (stdout)
クライアント
```

**STDIO転送の特性:**
- **シーケンシャル通信**: 単一のstdin/stdoutストリーム
- **要求-応答モデル**: 各ツール呼び出しは応答を待つ必要がある
- **改行区切りメッセージ**: JSON-RPCメッセージは改行で区切られる
- **バッチサポート**: プロトコルはバッチをサポートするが、実装が必要

参考文献:
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [Future of MCP Transports (2025)](http://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/)

### 2.2 現在の実装の制約

**問題点:**

1. **バッチ操作の未実装**
   - 複数タスクの作成には複数の`create_task`呼び出しが必要
   - 複数検索の実行には複数の`search`呼び出しが必要
   - 各呼び出しはブロッキング（クライアント視点）

2. **ポーリングベースの監視**
   - `get_status`は能動的な通知を送信しない
   - クライアントは変更を検出するために定期的にポーリングする必要がある
   - MCP 2025はサブスクリプションを検討中だが、まだ未実装

3. **並列タスク実行のワークフロー**
   - クライアント側で複数の同期呼び出しが必要:
     ```
     task1_id = await call_tool("create_task", {query: "Q1"})
     task2_id = await call_tool("create_task", {query: "Q2"})
     task3_id = await call_tool("create_task", {query: "Q3"})

     # 各タスクで検索を実行
     await call_tool("search", {task_id: task1_id, query: "S1"})
     await call_tool("search", {task_id: task2_id, query: "S2"})
     await call_tool("search", {task_id: task3_id, query: "S3"})

     # ステータスをポーリング
     while not all_done:
         status1 = await call_tool("get_status", {task_id: task1_id})
         status2 = await call_tool("get_status", {task_id: task2_id})
         status3 = await call_tool("get_status", {task_id: task3_id})
         await sleep(5)
     ```

---

## 3. アーキテクチャ評価

### 3.1 徹底した非同期処理か？ **はい ✅**

**非同期の浸透度:**
- ✅ すべてのMCPハンドラが非同期
- ✅ タスク作成が非同期（DB操作）
- ✅ 検索パイプラインが完全に非同期（パイプライン、エグゼキュータ、search_serp）
- ✅ フェッチ操作が非同期（Playwright）
- ✅ 抽出操作が非同期（コンテンツ処理）
- ✅ LLM呼び出しが非同期
- ✅ エビデンスグラフ取得が非同期
- ✅ データベース操作が非同期

**並行性管理:**
- ✅ スロットベースのリソース割り当てを持つジョブスケジューラ
- ✅ スロットタイプごとのasyncio.PriorityQueue
- ✅ ワーカープール（スロットあたり1-8ワーカー）
- ✅ スケジューラでのバジェット強制
- ✅ 並列検索: `asyncio.gather(browser_task, academic_task)`
- ✅ タイムアウト管理: アイドル検出のための`asyncio.wait_for()`

### 3.2 MCPサーバの特性は考慮されているか？ **部分的 ⚠️**

**考慮されている点:**
- ✅ STDIO転送の使用（ローカル展開に適している）
- ✅ JSON-RPC準拠のメッセージフォーマット
- ✅ 適切なエラー処理とL7サニタイゼーション (§4.4.1)
- ✅ タスク状態を追跡する`get_status`ツール

**考慮が不十分な点:**
- ⚠️ **バッチ操作の未サポート** - MCPはバッチをサポートするが未実装
- ⚠️ **プッシュ通知なし** - ポーリングベースの監視のみ
- ⚠️ **並列タスク管理の複雑さ** - クライアント側の調整が必要

### 3.3 キューとステータス監視ツールは十分か？ **内部的には十分、外部APIには不十分 ⚠️**

**内部キュー（サーバ側）:**
- ✅ ジョブスケジューラキュー（高スループット非同期ジョブ実行）
- ✅ 認証キュー（ユーザ駆動認証、ノンブロッキング）
- ✅ 探索状態（非同期DB永続化を持つインメモリ状態）

**外部API（クライアント向け）:**
- ✅ `get_status` - タスク、検索、メトリクス、バジェット、認証キューを報告
- ⚠️ **ポーリングが必要** - 自動通知なし
- ⚠️ **バッチステータスクエリなし** - 複数タスクには複数の呼び出しが必要

---

## 4. 改善提案

### 4.1 短期的改善（既存MCP制約内）

#### A. バッチツール呼び出しのサポート

**提案:** MCPのバッチ機能を活用

**実装:**
```python
# 新しいツール: batch_create_tasks
Tool(
    name="batch_create_tasks",
    description="Create multiple research tasks in one call. Returns array of task_ids.",
    inputSchema={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "config": {"type": "object"},
                    },
                    "required": ["query"]
                }
            }
        },
        "required": ["tasks"]
    }
)

# ハンドラ実装
async def _handle_batch_create_tasks(args: dict[str, Any]) -> dict[str, Any]:
    tasks = args.get("tasks", [])
    results = []

    # 並列にタスク作成（DB I/Oの並列化）
    create_coros = [
        _create_single_task(task["query"], task.get("config"))
        for task in tasks
    ]

    task_ids = await asyncio.gather(*create_coros)

    return {
        "ok": True,
        "task_ids": task_ids,
        "count": len(task_ids)
    }
```

#### B. バッチ検索ツール

**提案:** 複数の検索を1回の呼び出しで実行

```python
Tool(
    name="batch_search",
    description="Execute multiple searches across tasks in one call. Returns search_ids.",
    inputSchema={
        "type": "object",
        "properties": {
            "searches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "query": {"type": "string"},
                        "options": {"type": "object"}
                    },
                    "required": ["task_id", "query"]
                }
            }
        },
        "required": ["searches"]
    }
)

async def _handle_batch_search(args: dict[str, Any]) -> dict[str, Any]:
    searches = args.get("searches", [])

    # 並列に検索を実行（真の並列処理）
    search_coros = [
        search_action(
            task_id=s["task_id"],
            query=s["query"],
            state=await _get_exploration_state(s["task_id"]),
            options=s.get("options", {})
        )
        for s in searches
    ]

    results = await asyncio.gather(*search_coros, return_exceptions=True)

    # エラーハンドリングと結果の集約
    return {
        "ok": True,
        "results": [
            {"search_id": r["search_id"], "status": r["status"]}
            if not isinstance(r, Exception)
            else {"error": str(r)}
            for r in results
        ]
    }
```

#### C. バッチステータス取得

**提案:** 複数タスクのステータスを1回の呼び出しで取得

```python
Tool(
    name="batch_get_status",
    description="Get status for multiple tasks in one call.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_ids": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["task_ids"]
    }
)

async def _handle_batch_get_status(args: dict[str, Any]) -> dict[str, Any]:
    task_ids = args.get("task_ids", [])

    # 並列にステータス取得
    status_coros = [
        _get_single_task_status(task_id)
        for task_id in task_ids
    ]

    statuses = await asyncio.gather(*status_coros, return_exceptions=True)

    return {
        "ok": True,
        "statuses": {
            task_id: status
            for task_id, status in zip(task_ids, statuses)
            if not isinstance(status, Exception)
        }
    }
```

#### D. 長時間実行操作のための非同期ジョブAPI

**提案:** 「fire-and-forget」セマンティクスを持つツール

```python
Tool(
    name="search_async",
    description="Start search asynchronously. Returns immediately with operation_id. Poll get_status for completion.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "query": {"type": "string"},
            "options": {"type": "object"}
        },
        "required": ["task_id", "query"]
    }
)

async def _handle_search_async(args: dict[str, Any]) -> dict[str, Any]:
    task_id = args["task_id"]
    query = args["query"]
    options = args.get("options", {})

    # 操作IDを生成
    operation_id = f"op_{uuid.uuid4().hex[:12]}"

    # バックグラウンドタスクとして検索を起動
    asyncio.create_task(
        _execute_search_background(operation_id, task_id, query, options)
    )

    # 即座に応答
    return {
        "ok": True,
        "operation_id": operation_id,
        "status": "started",
        "message": "Search started. Use get_status to check completion."
    }

async def _execute_search_background(operation_id, task_id, query, options):
    """バックグラウンドで検索を実行し、状態を保存"""
    try:
        state = await _get_exploration_state(task_id)
        result = await search_action(task_id, query, state, options)

        # 操作状態を保存（新しいテーブル: async_operations）
        db = await get_database()
        await db.execute(
            "UPDATE async_operations SET status=?, result=? WHERE id=?",
            ("completed", json.dumps(result), operation_id)
        )
    except Exception as e:
        await db.execute(
            "UPDATE async_operations SET status=?, error=? WHERE id=?",
            ("failed", str(e), operation_id)
        )
```

### 4.2 中期的改善（アーキテクチャ拡張）

#### A. WebSocket転送の検討

**課題:** STDIO転送はローカル展開のみ、双方向通信が制限される

**提案:** MCP Streamable HTTP (SSE)への移行を検討

**利点:**
- サーバからクライアントへのプッシュ通知
- 複数の同時サブスクリプション（MCP 2025ロードマップ）
- リモート展開のサポート

**実装の複雑さ:** 中程度
- mcp.server.sse を使用
- クライアント側の変更が必要（Cursor AIの統合）

#### B. サブスクリプションベースのステータス更新

**提案:** ポーリングの代わりにプッシュ通知

```python
Tool(
    name="subscribe_task_updates",
    description="Subscribe to real-time task updates (requires SSE transport).",
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "events": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["search_started", "search_completed", "budget_warning", "auth_required"]
                }
            }
        },
        "required": ["task_id", "events"]
    }
)

# サーバ側実装（SSE転送を想定）
async def _handle_subscribe_task_updates(args: dict[str, Any]) -> AsyncGenerator:
    task_id = args["task_id"]
    events = args.get("events", ["all"])

    # イベントストリームを作成
    async for event in task_event_stream(task_id, events):
        yield {
            "type": "event",
            "event": event["type"],
            "data": event["payload"],
            "timestamp": event["timestamp"]
        }
```

#### C. タスクグループとワークフロー管理

**提案:** 関連タスクをグループ化して並列実行を管理

```python
Tool(
    name="create_task_group",
    description="Create a group of related tasks that can be managed together.",
    inputSchema={
        "type": "object",
        "properties": {
            "group_name": {"type": "string"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "config": {"type": "object"}
                    }
                }
            },
            "workflow": {
                "type": "object",
                "description": "Optional workflow configuration",
                "properties": {
                    "parallel": {"type": "boolean", "default": True},
                    "max_concurrent": {"type": "integer", "default": 3},
                    "dependencies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task_index": {"type": "integer"},
                                "depends_on": {"type": "array", "items": {"type": "integer"}}
                            }
                        }
                    }
                }
            }
        },
        "required": ["group_name", "tasks"]
    }
)

async def _handle_create_task_group(args: dict[str, Any]) -> dict[str, Any]:
    group_name = args["group_name"]
    tasks = args["tasks"]
    workflow = args.get("workflow", {"parallel": True})

    # グループIDを生成
    group_id = f"grp_{uuid.uuid4().hex[:12]}"

    # タスクを作成（並列または依存関係に基づいて）
    if workflow.get("parallel", True):
        # 並列作成
        task_ids = await asyncio.gather(*[
            _create_single_task(t["query"], t.get("config"))
            for t in tasks
        ])
    else:
        # シーケンシャル作成（依存関係を考慮）
        task_ids = await _create_tasks_with_dependencies(tasks, workflow)

    # グループをDBに保存
    db = await get_database()
    await db.execute(
        "INSERT INTO task_groups (id, name, task_ids, workflow) VALUES (?, ?, ?, ?)",
        (group_id, group_name, json.dumps(task_ids), json.dumps(workflow))
    )

    return {
        "ok": True,
        "group_id": group_id,
        "task_ids": task_ids,
        "count": len(task_ids)
    }
```

### 4.3 長期的改善（プロトコル進化）

#### A. MCPプロトコルへのフィードバック

**行動項目:**
- MCPコミュニティに以下の機能を提案:
  - バッチ操作のファーストクラスサポート
  - ネイティブサブスクリプション（進行中）
  - 長時間実行操作のためのoperation_idパターン
  - タスクグループとワークフロー管理

**参加方法:**
- [MCP GitHub Discussions](https://github.com/modelcontextprotocol)
- [MCP Blog](http://blog.modelcontextprotocol.io/)

#### B. カスタム転送レイヤー

**提案:** Lyra特化の転送レイヤー

**利点:**
- 完全な双方向通信
- WebSocketまたはgRPC
- ストリーミング応答
- カスタムプロトコル最適化

**欠点:**
- MCP標準からの逸脱
- クライアント統合の複雑さ
- メンテナンスのオーバーヘッド

---

## 5. 推奨実装ロードマップ

### Phase 1: 即時改善（1-2週間）

1. **バッチツールの実装**
   - `batch_create_tasks`
   - `batch_search`
   - `batch_get_status`

   **理由:** MCPの既存機能を活用、クライアント側の複雑さを削減

2. **非同期ジョブAPIの実装**
   - `search_async` ツール
   - `async_operations` テーブル
   - `get_operation_status` ツール

   **理由:** 長時間実行操作をノンブロッキングにする

### Phase 2: アーキテクチャ拡張（1-2ヶ月）

1. **タスクグループとワークフロー管理**
   - `create_task_group` ツール
   - `task_groups` テーブル
   - 依存関係解決エンジン

   **理由:** 複雑なマルチタスクワークフローをサポート

2. **ポーリング最適化**
   - ロングポーリングサポート（変更があるまで待機）
   - 差分ステータス更新（変更のみ返す）
   - WebSocketベースのステータスストリーム（オプション）

### Phase 3: プロトコル進化（3-6ヶ月）

1. **SSE転送への移行調査**
   - Cursor AI統合の実現可能性
   - パフォーマンスベンチマーク
   - プッシュ通知のプロトタイプ

2. **MCPコミュニティへのフィードバック**
   - バッチ操作のユースケースを共有
   - サブスクリプション機能への貢献
   - エンタープライズスケールのベストプラクティス

---

## 6. 結論

### 主要な発見

1. **✅ Lyraの非同期アーキテクチャは徹底されている**
   - すべての内部操作は完全に非同期
   - ジョブスケジューラは適切なリソース管理を提供
   - キューシステムは堅牢で拡張可能

2. **⚠️ MCPプロトコルの制約が並列ワークフローを制限**
   - STDIO転送は本質的にシーケンシャル
   - バッチ操作は実装が必要
   - ポーリングベースの監視は最適ではない

3. **✅ ステータス監視ツールは存在するが、最適化の余地がある**
   - `get_status`は包括的な情報を提供
   - バッチクエリとプッシュ通知が欠けている

### 推奨される次のステップ

1. **即座に:** Phase 1のバッチツールを実装（最大の効果、最小の労力）
2. **短期:** 非同期ジョブAPIを追加（長時間実行操作のため）
3. **中期:** タスクグループとワークフロー管理を検討（複雑なユースケースのため）
4. **長期:** MCPコミュニティと連携してプロトコルの進化を支援

### 最終評価

Lyraのアーキテクチャは**技術的に堅牢**で**徹底して非同期**ですが、**MCPプロトコルの制約**により、その潜在能力が完全には活用されていません。提案された改善により、既存のMCPエコシステム内で動作しながら、大幅に優れた並列ワークフローのサポートが可能になります。

---

## 7. 参考文献

### MCP仕様とドキュメント

- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [Future of MCP Transports (2025)](http://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/)
- [MCP on Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol)
- [Definitive Guide to MCP (2025)](https://datasciencedojo.com/blog/guide-to-model-context-protocol/)

### Lyra内部ドキュメント

- `docs/REQUIREMENTS.md` - §3.2.1 (MCP Tools), §2.1.5 (Idle Timeout)
- `docs/EVIDENCE_SYSTEM.md` - エビデンスグラフアーキテクチャ
- `src/mcp/server.py` - MCPサーバ実装
- `src/scheduler/jobs.py` - ジョブスケジューラとキュー
- `src/research/pipeline.py` - 検索パイプラインとアクション

---

**文書バージョン:** 1.0
**作成日:** 2025-12-21
**最終更新:** 2025-12-21
**著者:** Claude (Sonnet 4.5) - GitHub Issue分析
**レビュー状態:** 初稿 - レビュー待ち
