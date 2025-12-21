# 認証キュー統合分析: get_auth_queue vs get_status

## Executive Summary

**問題:** `get_auth_queue`と`get_status`の両方が認証キュー情報を返す。統合すべきか？

**結論:** **統合しない（現状維持を推奨）** - ただし、小規模な改善提案あり

**理由:**
- **関心の分離**: `get_status`は「タスクダッシュボード」、`get_auth_queue`は「認証解決ワークフロー専用」
- **UXの観点**: 2段階ワークフロー（監視→解決）が自然
- **パフォーマンス**: get_statusは頻繁にポーリングされるため軽量であるべき
- **ツール数**: 9ツール（v2提案）で十分少ない、これ以上削減の必要性低い

---

## 1. 現状の実装分析

### 1.1 `get_auth_queue` ツール

#### 目的
**ブラウザで手動認証が必要になった場合、認証待ちをキューに積み、ユーザーにまとめて操作してもらうための専用ツール**

#### ツール定義
```python
Tool(
    name="get_auth_queue",
    description="Get pending authentication queue. Supports grouping by domain/type and priority filtering.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID (optional, omit for all tasks)",  # ← 全タスク取得可能
            },
            "group_by": {
                "type": "string",
                "enum": ["none", "domain", "type"],
                "default": "none",
            },
            "priority_filter": {
                "type": "string",
                "enum": ["high", "medium", "low", "all"],
                "default": "all",
            },
        },
    },
)
```

#### 機能

1. **タスク横断的な取得**
   - `task_id`を指定しない場合、**全タスクの認証キュー**を取得
   - 複数タスクで同じドメインの認証が発生した場合に便利

2. **グループ化機能**
   ```python
   # ドメイン別グループ化
   group_by="domain" → {
       "groups": {
           "example.com": [{queue_id: "iq_1", ...}, ...],
           "another.com": [{queue_id: "iq_2", ...}, ...]
       }
   }

   # 認証タイプ別グループ化
   group_by="type" → {
       "groups": {
           "cloudflare": [{...}, ...],
           "captcha": [{...}, ...]
       }
   }
   ```

3. **優先度フィルタリング**
   - `priority_filter="high"` → 高優先度（一次資料）のみ取得
   - ユーザーに重要な認証から操作してもらう

#### レスポンス例（グループ化あり）
```json
{
  "ok": true,
  "group_by": "domain",
  "groups": {
    "arxiv.org": [
      {
        "id": "iq_abc123",
        "task_id": "task_xyz",
        "url": "https://arxiv.org/pdf/...",
        "domain": "arxiv.org",
        "auth_type": "cloudflare",
        "priority": "high",
        "status": "pending",
        "queued_at": "2025-12-21T10:00:00Z"
      }
    ],
    "jstor.org": [
      {
        "id": "iq_def456",
        "task_id": "task_xyz",
        "url": "https://jstor.org/stable/...",
        "domain": "jstor.org",
        "auth_type": "login",
        "priority": "high",
        "status": "pending",
        "queued_at": "2025-12-21T10:05:00Z"
      }
    ]
  },
  "total_count": 2
}
```

### 1.2 `get_status` 内の認証キュー情報

#### 実装箇所
- `src/research/state.py:775-800` - `_get_authentication_queue_summary()`
- `src/research/state.py:622` - `get_status()`が`authentication_queue`を返す

#### 返される情報（サマリーのみ）
```python
async def _get_authentication_queue_summary(self) -> dict[str, Any] | None:
    """Get authentication queue summary for this task."""
    queue = get_intervention_queue()
    summary = await queue.get_authentication_queue_summary(self.task_id)

    # pending_count=0の場合はNoneを返す
    if summary.get("pending_count", 0) == 0:
        return None

    return summary
```

#### レスポンス構造（get_status内）
```json
{
  "ok": true,
  "task_id": "task_xyz",
  "status": "exploring",
  "searches": [...],
  "metrics": {...},
  "budget": {...},
  "auth_queue": {
    "pending_count": 5,
    "high_priority_count": 2,
    "domains": ["arxiv.org", "jstor.org", "nature.com"],
    "oldest_queued_at": "2025-12-21T10:00:00Z",
    "by_auth_type": {
      "cloudflare": 3,
      "login": 2
    }
  },
  "warnings": [
    "[critical] 認証待ち5件（高優先度2件）: 一次資料アクセスがブロック中"
  ]
}
```

#### 警告生成ロジック（§16.7.3）
```python
def _generate_auth_queue_alerts(self, auth_queue) -> list[str]:
    """Generate alerts for authentication queue status."""
    if auth_queue is None:
        return []

    pending_count = auth_queue.get("pending_count", 0)
    high_priority_count = auth_queue.get("high_priority_count", 0)

    # Critical: ≥5件 OR 高優先≥2件
    if pending_count >= 5 or high_priority_count >= 2:
        return ["[critical] 認証待ち5件（高優先度2件）: 一次資料アクセスがブロック中"]

    # Warning: ≥3件
    elif pending_count >= 3:
        return ["[warning] 認証待ち3件 (arxiv.org, jstor.org, ...)"]

    return []
```

### 1.3 `resolve_auth` ツール（認証解決）

#### 目的
ユーザーがブラウザで認証を完了した後、その完了をサーバーに報告する

#### 機能

1. **単一アイテム解決**
   ```python
   await resolve_auth({
       "target": "item",
       "queue_id": "iq_abc123",
       "action": "complete",
       "success": True
   })
   # → セッションクッキーをキャプチャして保存
   ```

2. **ドメイン一括解決**
   ```python
   await resolve_auth({
       "target": "domain",
       "domain": "arxiv.org",
       "action": "complete",
       "success": True
   })
   # → arxiv.orgの全認証待ちを一括解決
   # → セッションクッキーをキャプチャ
   ```

3. **スキップ**
   ```python
   await resolve_auth({
       "target": "domain",
       "domain": "jstor.org",
       "action": "skip"
   })
   # → jstor.orgの認証待ちを全てスキップ（アクセス不可とマーク）
   ```

---

## 2. 機能の重複分析

### 2.1 重複している部分

| 情報 | get_status | get_auth_queue |
|------|-----------|---------------|
| 認証待ち件数 | ✅ サマリー | ✅ 詳細リスト |
| 高優先度件数 | ✅ | ✅ (filter可能) |
| ドメインリスト | ✅ (配列) | ✅ (グループ化可能) |
| 認証タイプ | ✅ (集計) | ✅ (グループ化可能) |

### 2.2 get_auth_queue特有の機能

| 機能 | get_status | get_auth_queue |
|------|-----------|---------------|
| **全タスク横断取得** | ❌ (task_id必須) | ✅ (task_id省略可能) |
| **グループ化** | ❌ | ✅ (domain/type) |
| **優先度フィルタ** | ❌ | ✅ (high/medium/low) |
| **個別アイテム詳細** | ❌ | ✅ (queue_id, URL含む) |

### 2.3 get_status特有の機能

| 機能 | get_status | get_auth_queue |
|------|-----------|---------------|
| **検索状態** | ✅ | ❌ |
| **メトリクス** | ✅ | ❌ |
| **バジェット** | ✅ | ❌ |
| **警告生成** | ✅ (auth含む) | ❌ |
| **sleep機能** | ✅ (v2提案) | ❌ |

---

## 3. MCPクライアントUX分析

### 3.1 典型的なワークフロー

#### シナリオ: Cursor AIが探索中に認証が必要になった

```python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ステップ1: 定期的なステータス監視（ポーリング）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
while exploring:
    status = await get_status(task_id, sleep_seconds=10)

    # 認証警告を検出
    if status.warnings contains "[critical] 認証待ち":
        # → 認証が必要と判断
        break

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ステップ2: 認証の詳細を取得（ドメインでグループ化）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
auth_details = await get_auth_queue(
    task_id=task_id,
    group_by="domain",
    priority_filter="high"  # 高優先度のみ
)

# → ユーザーに提示
print("以下のドメインで認証が必要です:")
for domain, items in auth_details.groups.items():
    print(f"  - {domain} ({len(items)}件)")
    print(f"    例: {items[0].url}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ステップ3: ユーザーがブラウザで認証を完了
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# (ユーザーがChromeで arxiv.org にログイン)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ステップ4: 認証完了を報告（ドメイン一括）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
result = await resolve_auth(
    target="domain",
    domain="arxiv.org",
    action="complete",
    success=True
)
# → セッションクッキーがキャプチャされる
# → arxiv.orgの全認証待ちが解決

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ステップ5: 探索再開
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# (Lyraが保存されたクッキーを使ってarxiv.orgにアクセス)
```

### 3.2 ワークフローの特徴

#### A. 2段階設計の利点

| フェーズ | ツール | 目的 | 頻度 |
|---------|-------|------|------|
| **監視** | `get_status` | 全体状況把握 | 高頻度（10秒ごと） |
| **解決** | `get_auth_queue` + `resolve_auth` | 認証ワークフロー | 低頻度（認証発生時のみ） |

**UXの観点:**
- ✅ **関心の分離**: 監視と解決が明確に分離
- ✅ **パフォーマンス**: get_statusは軽量（グループ化処理なし）
- ✅ **柔軟性**: 認証解決時のみ詳細を取得（不要な情報を常に返さない）

#### B. 統合した場合の問題点

**Option: get_statusにget_auth_queueの機能を統合**

```python
# 統合後（仮）
status = await get_status(
    task_id=task_id,
    sleep_seconds=10,
    auth_group_by="domain",      # ← 新しいパラメータ
    auth_priority_filter="high"  # ← 新しいパラメータ
)
```

**問題:**
1. **パラメータの複雑化** - get_statusの責務が不明確に
2. **パフォーマンス低下** - 毎回グループ化処理が走る（不要な場合も）
3. **全タスク取得不可** - get_statusはtask_id必須、認証の全タスク横断取得ができない
4. **UXの悪化** - "ステータス確認"と"認証解決"が混在

---

## 4. 統合オプションの比較

### Option A: 統合しない（現状維持）

**設計:**
- `get_status` - タスク全体のダッシュボード（認証サマリー含む）
- `get_auth_queue` - 認証解決専用（詳細取得、グループ化、フィルタリング）
- `resolve_auth` - 認証完了報告

**Pros:**
- ✅ **関心の分離**: 明確な責務
- ✅ **パフォーマンス**: get_statusは軽量のまま
- ✅ **柔軟性**: 全タスク横断の認証取得が可能
- ✅ **UX**: 2段階ワークフローが自然（監視→解決）

**Cons:**
- ⚠️ ツール数が多い（9ツール）- ただし、これは許容範囲

**ツール数:** 9ツール

### Option B: get_statusに統合

**設計:**
- `get_status` - すべての情報を返す（認証詳細、グループ化も）
- `resolve_auth` - 認証完了報告

**Pros:**
- ✅ ツール数削減（8ツール）

**Cons:**
- ❌ **パラメータ複雑化**: get_statusのパラメータが増える
- ❌ **パフォーマンス**: 毎回グループ化処理（オプションでも実装が複雑に）
- ❌ **全タスク取得不可**: task_id必須
- ❌ **責務の混在**: ダッシュボードと認証解決が混在

**ツール数:** 8ツール

### Option C: get_statusから認証情報を削除（分離強化）

**設計:**
- `get_status` - 検索状態、メトリクス、バジェットのみ（認証情報なし）
- `get_auth_queue` - 認証キューのすべて（サマリーも詳細も）
- `resolve_auth` - 認証完了報告

**Pros:**
- ✅ **完全な分離**: 各ツールの責務が明確
- ✅ **パフォーマンス**: get_statusが最軽量

**Cons:**
- ⚠️ **UX悪化**: Cursor AIは常に2つのツールを呼ぶ必要がある
  ```python
  # 毎回2回呼び出し
  status = await get_status(task_id)
  auth = await get_auth_queue(task_id)
  ```
- ⚠️ **認証警告の欠如**: get_statusのwarningsに認証アラートが含まれない

**ツール数:** 9ツール

---

## 5. 推奨案と改善提案

### 5.1 推奨: **Option A（現状維持）**

**理由:**
1. **関心の分離とUXのバランスが最適**
   - get_statusで「認証が必要」という警告を検出
   - get_auth_queueで詳細を取得して解決
   - 自然な2段階ワークフロー

2. **パフォーマンス**
   - get_statusは頻繁にポーリングされる（10秒ごと）
   - 重いグループ化処理を含めるべきではない

3. **柔軟性**
   - 全タスク横断の認証取得が可能（複数タスク実行時に便利）

4. **ツール数は許容範囲**
   - 9ツール（v2提案）は十分少ない
   - これ以上削減する必要性は低い

### 5.2 小規模改善提案

#### A. get_auth_queueにsleep機能を追加（オプション）

**動機:** 認証解決後、すぐにキューを確認するのではなく、少し待ってから確認したい場合

```python
Tool(
    name="get_auth_queue",
    inputSchema={
        "properties": {
            "task_id": {"type": "string"},
            "group_by": {"type": "string", "enum": ["none", "domain", "type"]},
            "priority_filter": {"type": "string"},
            "sleep_seconds": {  # ← 追加
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "maximum": 60,
                "description": "Seconds to sleep before checking queue"
            }
        }
    }
)
```

**効果:** 認証解決ワークフローでのポーリング最適化

#### B. get_statusのauth_queueにquick_actionsヒントを追加

**動機:** Cursor AIに次のアクションを示唆

```python
# get_statusのレスポンス例
{
  "auth_queue": {
    "pending_count": 5,
    "high_priority_count": 2,
    "domains": ["arxiv.org", "jstor.org"],
    "quick_actions": [  # ← 追加
      {
        "action": "resolve_domain",
        "domain": "arxiv.org",
        "reason": "2件の高優先度認証待ち"
      }
    ]
  }
}
```

**効果:** Cursor AIの判断を支援（ただし§3.2.1の「推奨なし」方針に反するため要検討）

---

## 6. 最終的なツール構成（v2 + 推奨維持）

### 6.1 ツールリスト（9ツール）

| # | ツール名 | 目的 | 変更 |
|---|---------|------|------|
| 1 | `create_task` | タスク作成 | 変更なし |
| 2 | `queue_searches` | 検索キューに投入 | **新規（v2）** |
| 3 | `get_status` | タスク状態確認 | **sleep追加（v2）** |
| 4 | `stop_task` | タスク終了 | 変更なし |
| 5 | `get_materials` | レポート素材取得 | 変更なし |
| 6 | `calibrate` | モデル較正 | 変更なし |
| 7 | `calibrate_rollback` | 較正ロールバック | 変更なし |
| 8 | `get_auth_queue` | 認証キュー取得 | **維持（統合しない）** |
| 9 | `resolve_auth` | 認証解決 | 変更なし |

### 6.2 削除したツール（v2提案から）

| # | 削除ツール | 理由 |
|---|-----------|------|
| 1 | `search` | 内部化（queue_searchesに置き換え） |
| 2 | `notify_user` | 不要（get_statusのwarningsで十分） |
| 3 | `wait_for_user` | 不要（ポーリングで対応） |

### 6.3 認証関連ツールの関係

```
┌─────────────────────────────────────────────────────────────┐
│ 監視フェーズ（高頻度ポーリング）                              │
└─────────────────────────────────────────────────────────────┘
         │
         │ get_status(task_id, sleep_seconds=10)
         ↓
    ┌─────────────────────────────────────┐
    │ 応答:                               │
    │   - searches: [...]                 │
    │   - metrics: {...}                  │
    │   - budget: {...}                   │
    │   - auth_queue: {                   │
    │       pending_count: 5,             │
    │       high_priority_count: 2,       │
    │       domains: ["arxiv.org", ...]   │
    │     }                                │
    │   - warnings: [                     │
    │       "[critical] 認証待ち5件..."   │
    │     ]                                │
    └─────────────────────────────────────┘
         │
         │ warnings に認証アラート検出
         ↓
┌─────────────────────────────────────────────────────────────┐
│ 解決フェーズ（認証発生時のみ）                                │
└─────────────────────────────────────────────────────────────┘
         │
         │ get_auth_queue(task_id, group_by="domain", priority_filter="high")
         ↓
    ┌─────────────────────────────────────┐
    │ 応答:                               │
    │   - group_by: "domain"              │
    │   - groups: {                       │
    │       "arxiv.org": [                │
    │         {queue_id: "iq_1", url: ...}│
    │       ],                             │
    │       "jstor.org": [...]            │
    │     }                                │
    │   - total_count: 5                  │
    └─────────────────────────────────────┘
         │
         │ ユーザーがブラウザで認証完了
         ↓
         │ resolve_auth(target="domain", domain="arxiv.org", action="complete")
         ↓
    ┌─────────────────────────────────────┐
    │ セッションクッキーをキャプチャ      │
    │ arxiv.orgの全認証待ちを解決         │
    └─────────────────────────────────────┘
```

---

## 7. 結論

### 7.1 統合すべきか？ **No（統合しない）**

**理由:**
1. **UXの観点**: 2段階ワークフロー（監視→解決）が自然で効率的
2. **パフォーマンス**: get_statusは軽量であるべき（頻繁なポーリング）
3. **柔軟性**: get_auth_queueの全タスク横断機能は重要
4. **ツール数**: 9ツールは許容範囲（シンプルさと機能のバランス）

### 7.2 推奨アクション

1. **現状維持**: get_auth_queueとget_statusは分離したまま
2. **v2提案の実装**: queue_searches、searchツール削除、get_statusのsleep追加
3. **オプション検討**: get_auth_queueにsleep機能を追加（必要に応じて）

### 7.3 最終ツール構成

**9ツール:**
- タスク管理: `create_task`, `stop_task`
- 検索実行: `queue_searches` (新規)
- 監視: `get_status` (sleep追加)
- 認証: `get_auth_queue`, `resolve_auth`
- その他: `get_materials`, `calibrate`, `calibrate_rollback`

**削減: 11ツール → 9ツール（18%削減）**

---

**文書バージョン:** 1.0
**作成日:** 2025-12-21
**著者:** Claude (Sonnet 4.5)
**レビュー状態:** 分析完了 - 推奨案確定
