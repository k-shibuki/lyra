# ADR-0014: Browser SERP Resource Control

## Date
2025-12-25

## Status
Accepted (2025-12-25: TabPool + EngineRateLimiter implemented)

## Context

ADR-0010 により `SearchQueueWorker` が2並列で検索を処理する。ブラウザSERP取得には以下の**ローカルリソース競合**が存在する：

| リソース | 制約 | 理由 |
|----------|------|------|
| CDPプロファイル | 同時1セッション | Playwrightの永続コンテキストは共有不可 |
| フィンガープリント | 一貫性必要 | 異なるプロファイルでの同時アクセスはbot検出リスク |
| タブ/メモリ | 有限 | タブ数増加でメモリ圧迫 |

### 現状の制御

```python
# browser_search_provider.py:159
self._rate_limiter = asyncio.Semaphore(1)  # グローバル1並列
```

**問題点:**
1. **過剰な制限**: 異なるエンジン（DuckDuckGo, Mojeek）への同時リクエストも直列化
2. **スケーラビリティ不足**: ページネーション（複数ページ取得）実装時にボトルネック化
3. **リソース非効率**: 1タブで全エンジンを順番に処理

### 関連ADR

- **ADR-0013**: 学術API（Semantic Scholar, OpenAlex）のグローバルレート制限
- **本ADR**: ブラウザSERP（ローカルリソース）の競合制御

両者は「リソース競合制御」という共通テーマだが、リソース特性と解決策が異なるため別ADRとした。

## Decision

**TabPool（タブ管理）を導入し、ブラウザ操作の競合（同一Pageの同時操作）を構造的に排除する。**

> **重要**: 現状の `BrowserSearchProvider` は単一の `page` を共有して `goto()` 等を実行するため、\
> 「エンジン別Semaphore」だけでは **同一Pageへの同時操作** が起き得る。まず **正しさ（競合排除）** を担保する。

### 設計方針

1. **Pageは共有しない**: 検索1回のブラウザ操作は「借りたタブ（Page）」に閉じる
2. **TabPoolで上限を一元管理**: `max_tabs` を1から開始し、段階的に増やす
3. **エンジン別レート制御**: QPS（min_interval）と同時実行数（concurrency）はエンジン単位で制御
4. **設定責務の分離**:
   - **エンジンのQPS/並列**: `config/engines.yaml`（Engine policy）
   - **URLテンプレ/selector**: `config/search_parsers.yaml`（Parser）

### 実装

#### Phase 1: TabPool（max_tabs=1）で正しさを担保（挙動は現状維持）

```python
class BrowserSearchProvider:
    def __init__(self, ...):
        # BrowserContext は共有するが、Page は共有しない
        self._tab_pool = TabPool(max_tabs=1)  # Phase 1: keep behavior stable
        self._engine_locks: dict[str, asyncio.Semaphore] = {}  # per-engine concurrency cap (default 1)
    
    def _get_engine_lock(self, engine: str) -> asyncio.Semaphore:
        if engine not in self._engine_locks:
            self._engine_locks[engine] = asyncio.Semaphore(1)
        return self._engine_locks[engine]
    
    async def search(self, query: str, engine: str, ...) -> SearchResponse:
        # 1) Engine-level concurrency gate
        async with self._get_engine_lock(engine):
            # 2) Acquire a tab (Page) to avoid shared-page contention
            tab = await self._tab_pool.acquire(self._context)
            try:
                return await self._search_impl_on_page(tab, query, engine, ...)
            finally:
                self._tab_pool.release(tab)
```

**効果:**
- **正しさ**: 同一Pageへの同時 `goto()` 等を排除できる
- **挙動維持**: `max_tabs=1` により、並列度は現状と同等（安全な導入）
- **将来拡張**: `max_tabs>1` による並列化を、設定で段階的に有効化できる

#### Phase 2: TabPoolの拡張（max_tabs>1）で並列度を上げる（段階的・実測ベース）

複数ページネーション対応時に検討：

```python
class TabPool:
    """Manage multiple browser tabs for parallel SERP fetching."""
    
    def __init__(self, max_tabs: int = 3):
        self._tabs: list[Page] = []
        self._available = asyncio.Semaphore(max_tabs)
    
    async def acquire(self) -> Page:
        """Acquire a tab from the pool."""
        await self._available.acquire()
        return self._get_or_create_tab()
    
    def release(self, tab: Page) -> None:
        """Release a tab back to the pool."""
        self._available.release()
```

**Note**: Phase 2 で `max_tabs` を増やすと bot検出/メモリ/不安定性のリスクが上がるため、\
まず Phase 1（正しさ担保）を完了し、CAPTCHA率・成功率・レイテンシを監視してから段階的に解放する。

### 設定

エンジン別の制限は `config/engines.yaml` を活用（Engine policy）：

```yaml
duckduckgo:
  # ... engine policy ...
  min_interval: 2.0
  concurrency: 1

mojeek:
  min_interval: 4.0
  concurrency: 1
```

## Consequences

### Positive

1. **正しさの担保**: Page共有による競合を構造的に排除
2. **段階的な並列化**: `max_tabs` を上げるだけで並列度を調整可能
3. **ページネーション対応**: SERP複数ページ取得でも他ジョブを“完全ブロック”しにくい設計になる
4. **設定駆動**: エンジン別QPS/並列は `engines.yaml` で集中管理

### Negative

1. **複雑性増加**: TabPoolの取得/返却、例外時の確実なreleaseが必要
2. **メモリ増加**: `max_tabs>1` でタブ/DOM保持量が増加
3. **bot検出リスク**: 並列度が高すぎると検出される可能性

### Neutral

1. **学術API変更なし**: ADR-0013で別途対応
2. **HTTPフェッチ変更なし**: 既存 `RateLimiter` で保護済み

## Alternatives Considered

### A. グローバルSemaphore維持（現状）

**却下理由:**
- ページネーション実装時にボトルネック
- 異なるエンジンへの並列リクエストが不可能

### B. 完全並列（ロックなし）

**却下理由:**
- 同一エンジンへの連続リクエストでbot検出リスク
- QPS制限違反の可能性

### C. タブプール先行実装

**再評価（本ADRの結論）:**\
タブプールは「並列化のため」ではなく、「Page共有競合を避けるための抽象化」として Phase 1 から導入する。

## Implementation Status

**Status**: ✅ Phase 3 Implemented (2025-12-27)

### Phase 1: TabPool（max_tabs=1）+ 正しさ担保

- `src/search/tab_pool.py`: `TabPool` + `EngineRateLimiter` 実装済み
- `src/search/browser_search_provider.py`: TabPool 統合済み（max_tabs=1）
- `config/engines.yaml`: min_interval / concurrency 設定追加済み

### Phase 2: max_tabs=2 への拡張（2025-12-25 完了）

- `max_tabs=2` での並列動作テスト実装済み（`tests/test_tab_pool.py`）
- config-driven concurrency 対応（`config/settings.yaml` で設定可能）
- auto-backoff 機能追加（CAPTCHA/403 検出時に自動で並列度を下げる）

### Phase 3: Dynamic Chrome Worker Pool（2025-12-27 完了）

Worker 毎に **独立した Chrome プロセス・プロファイル・CDP ポート** を割り当て、完全分離を実現。

**設計原則:**

1. **num_workers 完全連動**: `settings.yaml` の `num_workers` から Chrome 数を自動決定
2. **後方互換性なし**: 旧来の単一 Chrome 設計は削除
3. **N 拡張可能**: Worker 数が増えても自動対応
4. **ポート自動管理**: `chrome_base_port + worker_id` で計算

**アーキテクチャ:**

```
Worker 0 ──▶ CDP:9222 ──▶ Chrome (Lyra-00) ──▶ user-data-dir/Lyra-00/
Worker 1 ──▶ CDP:9223 ──▶ Chrome (Lyra-01) ──▶ user-data-dir/Lyra-01/
Worker N ──▶ CDP:922N ──▶ Chrome (Lyra-0N) ──▶ user-data-dir/Lyra-0N/
```

**変更ファイル:**

| カテゴリ | ファイル | 変更内容 |
|----------|----------|----------|
| 設定 | `.env`, `.env.example` | `CHROME_PORT` → `CHROME_BASE_PORT`, `CHROME_PROFILE_PREFIX` |
| 設定 | `config/settings.yaml` | `chrome_port` → `chrome_base_port`, `chrome_profile_prefix` |
| 設定 | `src/utils/config.py` | `BrowserConfig` 拡張、ヘルパー関数追加 |
| スクリプト | `scripts/chrome.sh` | プール管理に再設計（start/stop/status） |
| スクリプト | `scripts/lib/chrome/start.sh` | `start_chrome_worker_wsl/linux()` 追加 |
| スクリプト | `scripts/lib/chrome/pool.sh` | 新規：プール管理ロジック |
| スクリプト | `scripts/mcp.sh` | 起動時に Chrome Pool 自動起動 |
| Python | `src/search/browser_search_provider.py` | `get_chrome_port(worker_id)` で動的接続 |
| Python | `src/crawler/fetcher.py` | 同上 |

**設定ヘルパー関数:**

```python
# src/utils/config.py
def get_chrome_port(worker_id: int) -> int:
    """Worker ID から CDP ポートを計算"""
    return get_settings().browser.chrome_base_port + worker_id

def get_chrome_profile(worker_id: int) -> str:
    """Worker ID からプロファイル名を計算"""
    prefix = get_settings().browser.chrome_profile_prefix
    return f"{prefix}{worker_id:02d}"

def get_all_chrome_ports() -> list[int]:
    """全 Worker の CDP ポートリストを取得"""
    base = get_settings().browser.chrome_base_port
    n = get_settings().concurrency.search_queue.num_workers
    return [base + i for i in range(n)]
```

**Makefile コマンド:**

```bash
make chrome         # プール全体のステータス表示
make chrome-start   # num_workers 分の Chrome を起動
make chrome-stop    # 全 Chrome を停止
make chrome-restart # 再起動
```

**メリット:**

1. **完全分離**: プロセス・プロファイル・Cookie が独立
2. **フィンガープリント分離**: 各 Chrome が独自のブラウザ指紋
3. **障害分離**: 1 つの Chrome がブロックされても他は動作
4. **動的スケール**: `num_workers` 変更で自動追従

## Related

- [ADR-0010: Async Search Queue Architecture](0010-async-search-queue.md) - ワーカー並列実行の基盤
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - 学術APIレート制限
- [archive/R_SERP_ENHANCEMENT.md](../archive/R_SERP_ENHANCEMENT.md) - ページネーション機能詳細（アーカイブ）

