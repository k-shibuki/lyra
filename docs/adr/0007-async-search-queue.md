# ADR-0007: Async Search Queue Architecture

## Status
Accepted

## Date
2025-12-21

## Context

従来の`search`ツールは同期的に動作していた：

```
MCPクライアント
  ↓ call_tool("search", {query})
  ↓ (ブロック - 数十秒〜数分待機)
MCPサーバ: 検索実行
  ↑ 応答
MCPクライアント (ようやく次の操作が可能)
```

この設計には以下の問題がある：

| 問題 | 詳細 |
|------|------|
| クライアントブロック | 検索完了まで他の操作不可 |
| 並列実行不可 | 複数クエリを1つずつシーケンシャルに実行 |
| 時間感覚の欠如 | MCPクライアントは適切なポーリング間隔を判断できない |

例：3つの検索を実行する場合

```python
# 各searchは数十秒かかる
result1 = await call_tool("search", {query: "Q1"})  # 30秒
result2 = await call_tool("search", {query: "Q2"})  # 40秒
result3 = await call_tool("search", {query: "Q3"})  # 35秒
# 合計: 105秒（シーケンシャル実行、クライアントはずっとブロック）
```

## Decision

**非同期セマンティクスを採用し、ツール数を削減する。**

### アーキテクチャ変更

| 変更 | 内容 |
|------|------|
| 削除 | `search`（同期）, `notify_user`, `wait_for_user` |
| 追加 | `queue_searches`（非同期キュー投入） |
| 変更 | `get_status`に`sleep_seconds`パラメータ追加 |

**ツール数: 11個 → 9個（18%削減）**

### 新しいフロー

```
MCPクライアント
  ↓ queue_searches(queries: ["Q1", "Q2", "Q3"])
  ↓ (即座に応答)
MCPサーバ: キューに追加

バックグラウンドワーカー:
  Q1実行 → Q2実行 → Q3実行（シーケンシャル）

MCPクライアント
  ↓ get_status(task_id, sleep_seconds: 10)
  ↓ (10秒待機後に状態返却)
  ↓ 完了まで繰り返し
```

### queue_searches

```python
# 複数クエリを即座にキュー投入
await call_tool("queue_searches", {
    task_id: "task_xxx",
    queries: ["Q1", "Q2", "Q3"],
    options: { priority: "high" }
})
# 応答: 即座（< 1秒）
# {ok: true, queued_count: 3, search_ids: ["s_1", "s_2", "s_3"]}
```

### get_status with sleep_seconds

MCPクライアントは時間感覚がないため、サーバー側でスリープを制御：

```python
# サーバー側で10秒待機してから状態確認
status = await call_tool("get_status", {
    task_id: "task_xxx",
    sleep_seconds: 10
})
# 無駄なポーリングループを回避
```

### 最終ツール構成（9ツール）

| # | ツール | 目的 |
|---|--------|------|
| 1 | `create_task` | タスク作成 |
| 2 | `queue_searches` | 検索キュー投入 |
| 3 | `get_status` | 状態確認（sleep機能付き） |
| 4 | `stop_task` | タスク終了 |
| 5 | `get_materials` | 素材取得 |
| 6 | `calibrate` | モデル校正 |
| 7 | `calibrate_rollback` | 校正ロールバック |
| 8 | `get_auth_queue` | 認証キュー取得 |
| 9 | `resolve_auth` | 認証完了報告 |

### 認証ツールを統合しない理由

`get_auth_queue`と`resolve_auth`を`get_status`に統合することを検討したが、以下の理由で分離を維持：

| 観点 | 理由 |
|------|------|
| 関心の分離 | 監視（get_status）と認証解決は別ワークフロー |
| パフォーマンス | get_statusは10秒ごとの高頻度ポーリング。グループ化処理を含めるべきでない |
| 柔軟性 | get_auth_queue(task_id=null)で全タスク横断取得が可能 |

## Consequences

### Positive
- **ノンブロッキング**: クライアントは即座に次の操作が可能
- **効率的ポーリング**: sleep_secondsで無駄なループを削減
- **ツール削減**: 11→9（シンプル化）
- **拡張性**: 将来の並列ワーカー化に対応可能

### Negative
- **状態管理**: キューとワーカーの管理が必要
- **DBスキーマ追加**: search_queueテーブルが必要
- **デバッグ難**: 非同期処理のトレースが複雑

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 同期search維持 | シンプル | クライアントブロック、並列不可 | 却下 |
| SSEストリーミング | リアルタイム通知 | 実装複雑、MCP制約 | 将来検討 |
| 並列実行 | 高速化 | 探索状態の整合性問題 | 将来検討 |

## References
- `docs/archive/Q_ASYNC_ARCHITECTURE.md`（アーカイブ）
- `src/mcp/server.py` - MCPハンドラ
- `src/storage/schema.sql` - search_queueテーブル
