# Q_ASYNC_ARCHITECTURE.md レビューメモ

> **作成日**: 2025-12-24
> **目的**: `docs/Q_ASYNC_ARCHITECTURE.md` の技術レビュー結果（コードベース検証済み）

---

## 1. Executive Summary

Q_ASYNC_ARCHITECTURE.md は**技術的に筋が良い設計**である。MCP protocol の制約（stdio、push通知不可）を正しく理解し、その制約内での最適解を導出している。

**Phase 1 は実装済み**であり、設計が机上の空論ではなく実証済みである点が高く評価できる。

当初の技術レビューで指摘した一部の懸念について、コードベース調査の結果、**不適切な指摘だった点を訂正**する。

---

## 2. 当初の指摘と検証結果

### 2.1 ワーカー数2固定

**当初の指摘**: 動的スケーリングの設計が不足。将来的にはconfigurable化が望ましい。

**検証結果**:

```python
# src/scheduler/search_worker.py:26
NUM_WORKERS = 2
```

- ADR-0010 line 37: "Start **2 worker tasks** for parallel execution."
- **意図的な設計決定**であり、問題ではない
- 定数として定義されており、将来configurable化も容易

**結論**: 妥当な指摘だが、**優先度は低い**。現時点では意図的な設計。

---

### 2.2 Browser SERP concurrency=1 ← 指摘を撤回

**当初の指摘**: グローバル制約がボトルネック化するリスク。CDPプロファイル分離で改善可能か検討の余地。

**検証結果**:

```python
# src/search/browser_search_provider.py:159
self._rate_limiter = asyncio.Semaphore(1)
```

ADR-0010 line 272:
> "Browser (SERP) concurrency: fixed to **1** to avoid CDP/profile contention."

**これは技術的制約に基づく合理的な設計**:

1. **CDPプロファイル共有**: Lyraは実ブラウザプロファイルをCDP接続で使用（ADR-0006）
2. **プロファイルは1つ**: 同時に複数のブラウザ操作を行うと状態競合が発生
3. **分離は困難**: プロファイル分離はCookie/セッション一貫性を壊し、CAPTCHA増加を招く

**結論**: **指摘は不適切だった**。これは「問題点」ではなく「技術的制約に基づく正しい設計」。

---

### 2.3 エラーリトライ戦略が未定義

**当初の指摘**: `state='failed'`後の自動リトライ回数、指数バックオフ、デッドレターキューの設計がない。

**検証結果**:

```python
# src/scheduler/search_worker.py:211-235
except Exception as e:
    # Search failed - update state to 'failed'
    await db.execute(
        """
        UPDATE jobs
        SET state = 'failed', finished_at = ?, error_message = ?
        WHERE id = ?
        """,
        ...
    )
```

- 失敗時は`state='failed'`で終了し、**自動リトライなし**
- ADR-0010のエラーハンドリングセクション（line 169-189）にもリトライ戦略の記載なし

**設計意図の推測**:
- MCPクライアント（Cursor AI）側でリトライを判断する設計かもしれない
- 「部分的な成功」を許容し、失敗は`errors`として報告する方針

**結論**: **妥当な指摘**。ただし、以下の選択肢がある：

| 選択肢 | 説明 | 適用場面 |
|--------|------|----------|
| A. 自動リトライ | ワーカーが指数バックオフでリトライ | 一時的エラー（ネットワーク、レート制限） |
| B. MCPクライアント責任 | クライアントが`get_status`で失敗検知しリトライ判断 | 恒久的エラー（CAPTCHA、認証必要） |
| C. 現状維持 | リトライなし、失敗はログ | シンプルさ優先 |

→ **ADR追加候補**: エラーリトライポリシー（自動リトライ vs クライアント責任）の設計判断

---

### 2.4 同一タスク内の検索順序

**当初の指摘**: 完了順が非決定的である旨は記載あるが、順序保証が必要なケースへの対応策がない。

**検証結果**:

ADR-0010 line 30:
> "No per-task sequential guarantee: A task may have multiple searches running in parallel."

```python
# src/scheduler/search_worker.py:54-55
# Scheduling policy:
# - priority ASC (high first), then queued_at ASC (FIFO within same priority)
# - No per-task sequential guarantee (a task may have multiple searches in parallel)
```

**これは意図的な設計決定**:
- 同一タスクの検索を並列実行することで、全体の完了時間を短縮
- 順序が必要な場合は、クライアント側で`queue_searches`を分割して逐次呼び出し可能

**結論**: **指摘ではなく設計の特性として認識すべき**。ドキュメントには明記されている。

---

## 3. 設計の優れた点（コード検証済み）

### 3.1 Long polling の実装

```python
# src/research/state.py:284
self._status_changed: asyncio.Event = asyncio.Event()

# src/research/state.py:315-323
def notify_status_change(self) -> None:
    """Notify waiting clients that status has changed."""
    self._status_changed.set()
```

- **asyncio.Event による in-memory 通知**
- DB polling より効率的
- Q_ASYNC_ARCHITECTURE の設計通りに実装済み

### 3.2 CAS（Compare-And-Swap）によるジョブ取得

```python
# src/scheduler/search_worker.py:102-122
# Attempt to claim the job (CAS)
# UPDATE only succeeds if state is still 'queued'
cursor = await db.execute(
    """
    UPDATE jobs
    SET state = 'running', started_at = ?
    WHERE id = ? AND state = 'queued'
    """,
    ...
)

# Check if we won the race
rowcount = getattr(cursor, "rowcount", 0)
if rowcount != 1:
    # Another worker claimed it - retry loop
    continue
```

- 2ワーカー並列実行時のレースコンディションを防止
- アトミックな状態遷移

### 3.3 graceful/immediate stop の実装

```python
# src/scheduler/search_worker.py:192-209
except asyncio.CancelledError:
    # Worker shutdown or stop_task(mode=immediate)
    # Mark as cancelled and re-raise
    await db.execute(
        """
        UPDATE jobs
        SET state = 'cancelled', finished_at = ?
        WHERE id = ?
        """,
        ...
    )
    raise  # Re-raise to propagate cancellation
```

- `state='cancelled'` による論理的一貫性の保証
- ADR-0010 の設計通り

### 3.4 既存インフラの再利用

```python
# src/scheduler/search_worker.py - jobs テーブルを使用
# kind='search_queue' として検索リクエストを保存
```

- 新テーブルを作成せず、既存の `jobs` テーブルを拡張
- 優先度・状態遷移・スロット管理を再利用
- スキーマの二重管理を回避

---

## 4. ADR-0010 との一貫性

Q_ASYNC_ARCHITECTURE.md と ADR-0010 は**高い一貫性**を持っている。

| 項目 | ADR-0010 | Q_ASYNC_ARCHITECTURE | 実装 |
|------|----------|---------------------|------|
| ワーカー数 | 2 | 2 | ✅ `NUM_WORKERS = 2` |
| スケジューリング | priority ASC, then FIFO | 同じ | ✅ 実装済み |
| Long polling | asyncio.Event | asyncio.Event | ✅ 実装済み |
| Storage | jobs テーブル | jobs テーブル | ✅ 実装済み |
| stop_task | graceful/immediate | graceful/immediate | ✅ 実装済み |

**不整合なし**。設計書とADRと実装が一致している。

---

## 5. 追加検討事項

### 5.1 エラーリトライポリシー（ADR追加候補）

**決定すべき内容**:

1. **自動リトライの対象**: どのエラーを自動リトライすべきか？
   - ネットワークタイムアウト → 自動リトライ
   - CAPTCHA → 認証キュー（現行設計）
   - 404/403 → リトライ不要

2. **リトライ回数と間隔**:
   - 最大3回、指数バックオフ（2s, 4s, 8s）が一般的

3. **デッドレターキュー**: 最終的に失敗したジョブをどう扱うか

**現状の選択肢**:

| 選択肢 | メリット | デメリット |
|--------|----------|------------|
| 自動リトライ追加 | 一時的エラーからの自動回復 | 複雑性増加、恒久エラーでの無駄なリトライ |
| MCPクライアント責任 | シンプル、柔軟 | クライアント実装依存 |
| 現状維持 | 最もシンプル | 回復可能なエラーも失敗扱い |

→ **推奨**: 現時点では**現状維持**（Phase 1完了済み）。運用データを見てから判断。

---

### 5.2 ワーカー数の設定化（将来課題）

```python
# 現状
NUM_WORKERS = 2

# 将来（設定可能化）
from src.utils.config import get_settings
NUM_WORKERS = get_settings().scheduler.search_queue_workers  # default: 2
```

**優先度**: 低。現状で問題が発生していない。

---

## 6. 新規ADR追加の提案

### 6.1 必須（設計判断が必要）

| ADR番号候補 | タイトル | 決定すべき内容 |
|-------------|----------|---------------|
| なし | - | Q関連で新規ADRは不要 |

### 6.2 推奨（運用データを見てから検討）

| 項目 | 対応方法 |
|------|----------|
| エラーリトライポリシー | 運用データを見てからADR追加を検討 |

### 6.3 不要

| 項目 | 理由 |
|------|------|
| Browser SERP concurrency | 技術的制約に基づく正しい設計 |
| ワーカー数設定化 | 現状で問題なし |
| 検索順序保証 | 設計として明記済み |

---

## 7. 結論

Q_ASYNC_ARCHITECTURE.md は**技術的に優れた設計**であり、以下の点で高く評価できる：

1. **MCP protocolの制約を正しく理解**: stdio、push通知不可という制約内での最適解
2. **実装済み（Phase 1完了）**: 設計が実証されている
3. **ADR-0010との一貫性**: 設計書・ADR・実装が一致
4. **既存インフラの再利用**: 新テーブル作成を避け、jobsテーブルを拡張

**当初の指摘の訂正**:

| 指摘 | 検証結果 |
|------|----------|
| ワーカー数2固定 | 妥当だが優先度低い |
| Browser SERP concurrency=1 | **不適切な指摘** - 技術的制約に基づく正しい設計 |
| エラーリトライ戦略 | 妥当 - ただし現状維持も選択肢 |
| 検索順序 | 設計の特性として認識 |

**現時点でのアクション**: 特になし。設計・実装ともに成熟しており、Phase 2（ツール削除）へ進むことが適切。

---

## 8. コードベース調査で確認したファイル

| ファイル | 確認内容 |
|----------|----------|
| `src/scheduler/search_worker.py` | ワーカー実装、CAS、キャンセル処理 |
| `src/scheduler/jobs.py` | JobKind、Slot、スケジューラ |
| `src/search/browser_search_provider.py` | SERP concurrency制御 |
| `src/research/state.py` | asyncio.Event によるlong polling |
| `docs/adr/0010-async-search-queue.md` | 設計判断の確認 |
