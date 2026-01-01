# リファクタリングバックログ

本ドキュメントは、コードベース分析により特定されたレガシーパターン、分割すべきモジュール、コード重複を網羅的に記載する。

> **注意**: 行番号はコード変更により随時ずれる。着手時は記載の `grep` コマンドで最新位置を確認すること。

---

## 1. レガシーパターン・命名の揺れ

### 1.1 max_pages → budget_pages 移行

**状態**: ✅ 完了（レガシーバリデーション削除 + スキーマ厳密化）

**概要**: タスク/検索のページ予算を表すパラメータ名が `max_pages` から `budget_pages` に変更された。手動バリデーションコードを削除し、JSON Schema の `additionalProperties: false` でスキーマレベルで不明なキーを拒否するクリーンな実装に変更した。

#### 完了した変更

| ファイル | 変更内容 | 状態 |
|---------|---------|------|
| `src/mcp/server.py` | `create_task.inputSchema.config.budget` に `additionalProperties: false` 追加 | ✅ 完了 |
| `src/mcp/server.py` | `queue_searches.inputSchema.options` に `additionalProperties: false` 追加 | ✅ 完了 |
| `src/mcp/server.py` | `_handle_create_task` 内の手動 `max_pages` バリデーション削除 | ✅ 完了 |
| `src/mcp/server.py` | `_handle_queue_searches` 内の手動 `max_pages` バリデーション削除 | ✅ 完了 |
| `src/research/pipeline.py` | `search_action` 内の手動 `max_pages` バリデーション削除 | ✅ 完了 |
| `tests/test_mcp_create_task.py` | `test_create_task_legacy_max_pages_rejected` テスト削除 | ✅ 完了 |

#### 確認コマンド

```bash
# 手動バリデーションが削除されたことを確認（結果が空であるべき）
grep -n 'if "max_pages" in' src/mcp/server.py src/research/pipeline.py

# スキーマに additionalProperties: false が追加されたことを確認
grep -A 5 'additionalProperties.*False' src/mcp/server.py
```

---

### 1.2 serp_max_pages（SERP用パラメータ）

**状態**: ✅ 正式採用済み（対応不要）

**概要**: SERP（検索結果ページ）のページネーション用パラメータ。`budget_pages`（クロール予算）とは別の概念として正式に定義されている。

#### 確認コマンド

```bash
# 使用箇所の確認
grep -rn 'serp_max_pages' src/

# テストの確認
pytest tests/test_serp_max_pages_propagation.py -v
```

**結論**: これはレガシーではなく、正式なパラメータ。対応不要。

---

### 1.3 Subquery → Search 用語統一

**状態**: ✅ 完了（R-07として完了）

**概要**: 内部用語が `subquery` から `search` に統一された。エイリアスと後方互換性は完全に排除され、クリーンな移行が完了した。

#### 完了した変更

- ✅ すべての `Subquery*` エイリアスを削除（`SubqueryState`, `SubqueryStatus`, `SubqueryExecutor`, `SubqueryResult`, `SubqueryArm`）
- ✅ `min_budget_per_subquery` パラメータを削除（`min_budget_per_search` に統一）
- ✅ `refutation.py` の `subquery_id` → `search_id`、`execute_for_subquery()` → `execute_for_search()` に改名
- ✅ `target_type="subquery"` → `target_type="search"` に更新
- ✅ すべての docstring/コメントを更新
- ✅ テストファイルを全面更新

#### 確認コマンド（参考）

```bash
# エイリアスが存在しないことを確認（結果が空であるべき）
grep -rn 'SubqueryState\|SubqueryStatus\|SubqueryExecutor\|SubqueryResult\|SubqueryArm' src/research/

# 旧用語が存在しないことを確認（結果が空であるべき）
grep -rn 'subquery_id\|min_budget_per_subquery\|execute_for_subquery' src/
```

---

### 1.4 Legacy Mode コード

**状態**: ✅ 完了（2026-01-01）

**概要**: 未使用のlegacyコードを削除し、誤解を招くコメントを改善した。

#### 完了した変更

| ファイル | 変更内容 | 状態 |
|---------|---------|------|
| `src/filter/llm.py` | `OllamaClient` クラス削除 | ✅ 完了 |
| `src/filter/llm.py` | `_get_client()`, `_cleanup_client()` 削除 | ✅ 完了 |
| `src/filter/llm.py` | `cleanup_llm_for_task()`, `set_llm_task_id()` 削除 | ✅ 完了 |
| `src/filter/llm.py` | `llm_extract()` の `use_provider` パラメータ削除 | ✅ 完了 |
| `src/filter/llm.py` | `llm_extract()` の legacyブランチ削除 | ✅ 完了 |
| `src/crawler/browser_fetcher.py` | `_request_manual_intervention()` メソッド削除 | ✅ 完了 |
| `src/crawler/browser_fetcher.py` | legacy interventionパス削除 | ✅ 完了 |
| `src/crawler/browser_fetcher.py` | 不要なimport削除（`get_intervention_manager`, `InterventionStatus`, `InterventionType`） | ✅ 完了 |
| `src/crawler/browser_fetcher.py` | コメント改善（"legacy format" → "Return format"） | ✅ 完了 |
| `src/crawler/fetcher.py` | コメント改善（"legacy path" 削除） | ✅ 完了 |
| `src/search/search_api.py` | `_get_client()` → `generate_with_provider()` に移行 | ✅ 完了 |
| `src/report/chain_of_density.py` | `_get_client()` → `generate_with_provider()` に移行 | ✅ 完了 |
| `src/filter/claim_decomposition.py` | `_get_client()` → `generate_with_provider()` に移行 | ✅ 完了 |
| `src/extractor/quality_analyzer.py` | `OllamaClient` → `LLMProvider` に移行 | ✅ 完了 |
| `tests/test_lifecycle.py` | legacy API関連テスト削除 | ✅ 完了 |
| `tests/test_llm_provider.py` | `use_provider` パラメータ削除 | ✅ 完了 |
| `tests/test_claim_decomposition.py` | パッチ対象を `generate_with_provider` に更新 | ✅ 完了 |
| `tests/test_search.py` | パッチ対象を `generate_with_provider` に更新 | ✅ 完了 |

#### 確認コマンド

```bash
# legacy コードが削除されたことを確認（結果が空であるべき）
grep -rn 'OllamaClient\|_get_client\|cleanup_llm_for_task\|set_llm_task_id\|_request_manual_intervention' src/

# 誤解を招くlegacyコメントが改善されたことを確認
grep -rn 'legacy format\|legacy path\|legacy mode' src/crawler/ src/filter/
```

---

## 2. 分割すべき大規模モジュール

### 2.1 ファイルサイズ一覧（500行以上）

```bash
# 最新のファイルサイズ確認
wc -l src/**/*.py | sort -rn | head -25
```

| ファイル | 行数 | 優先度 |
|---------|------|--------|
| `src/crawler/fetcher.py` | 2826 | **HIGH** |
| `src/mcp/server.py` | 2380 | **HIGH** |
| `src/filter/evidence_graph.py` | 1843 | MEDIUM |
| `src/search/browser_search_provider.py` | 1662 | MEDIUM |
| `src/utils/notification.py` | 1636 | **HIGH** |
| `src/utils/nli_calibration.py` | 1622 | MEDIUM |
| `src/storage/entity_kb.py` | 1615 | MEDIUM |
| `src/research/pipeline.py` | 1607 | MEDIUM |

---

### 2.2 fetcher.py（2826行）分割計画

**状態**: ✅ 完了（2025-01-01）

**概要**: `fetcher.py`（2826行）を6ファイルにクリーン分割。後方互換性は維持せず、全 import パスを新モジュールに更新。

#### 完了した変更

| 新ファイル | 移動対象 | 実際の行数 |
|-----------|---------|-----------|
| `crawler/fetch_result.py` | `FetchResult` | 116 |
| `crawler/tor_controller.py` | `TorController`, `get_tor_controller`, `_can_use_tor` | 228 |
| `crawler/challenge_detector.py` | `_is_challenge_page`, `_detect_challenge_type`, `_estimate_auth_effort` | 156 |
| `crawler/http_fetcher.py` | `HTTPFetcher`, `RateLimiter` | 321 |
| `crawler/browser_fetcher.py` | `BrowserFetcher`, `HumanBehavior` | 1062 |
| `crawler/fetcher.py`（更新） | `fetch_url`, `_fetch_url_impl`, utilities | 1006 |

#### 更新されたファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/crawler/__init__.py` | 新モジュールから直接 import |
| `src/search/browser_search_provider.py` | `HumanBehavior` import 更新 |
| `src/utils/notification.py` | `BrowserFetcher` import 更新 |
| `tests/test_fetcher.py` | 全 import パス更新 |
| `tests/test_tor_daily_limit.py` | `_can_use_tor` import 更新 |
| `tests/test_wayback_fallback.py` | `FetchResult` import 更新 |
| `tests/test_browser_search_provider.py` | パッチ対象更新 |

#### 検証結果

```bash
# 分割後の確認
wc -l src/crawler/fetch_result.py src/crawler/tor_controller.py src/crawler/challenge_detector.py src/crawler/http_fetcher.py src/crawler/browser_fetcher.py src/crawler/fetcher.py
# 116 + 228 + 156 + 321 + 1062 + 1006 = 2889行

# テスト結果
make test-unit
# === 3731 passed, 22 skipped, 21 deselected ===
```

---

### 2.3 mcp/server.py（2380行）分割計画

**状態**: ✅ 完了（2025-01-01）

#### 現状構造確認コマンド

```bash
# ハンドラー・ヘルパー関数の一覧
grep -n '^async def _handle_\|^async def _get_\|^async def _cancel_\|^async def _capture_\|^async def _requeue_\|^async def _reset_\|^async def _check_' src/mcp/server.py
```

#### 現状構造

| 関数 | 行番号 | 移動先 |
|------|--------|--------|
| `_get_exploration_state` | 743 | `mcp/helpers.py` |
| `_get_metrics_from_db` | 779 | `mcp/helpers.py` |
| `_get_search_queue_status` | 877 | `mcp/helpers.py` |
| `_get_pending_auth_info` | 965 | `mcp/helpers.py` |
| `_get_domain_overrides` | 1024 | `mcp/helpers.py` |
| `_handle_create_task` | 1070 | `mcp/tools/task.py` |
| `_handle_get_status` | 1129 | `mcp/tools/task.py` |
| `_handle_queue_searches` | 1344 | `mcp/tools/search.py` |
| `_check_chrome_cdp_ready` | 1483 | `mcp/helpers.py` |
| `_handle_stop_task` | 1518 | `mcp/tools/task.py` |
| `_cancel_search_queue_jobs` | 1596 | `mcp/tools/task.py` |
| `_cancel_auth_queue_for_task` | 1666 | `mcp/tools/task.py` |
| `_handle_get_materials` | 1704 | `mcp/tools/materials.py` |
| `_handle_calibration_metrics` | 1750 | `mcp/tools/calibration.py` |
| `_handle_calibration_rollback` | 1777 | `mcp/tools/calibration.py` |
| `_handle_get_auth_queue` | 1868 | `mcp/tools/auth.py` |
| `_capture_auth_session_cookies` | 1929 | `mcp/tools/auth.py` |
| `_handle_resolve_auth` | 2040 | `mcp/tools/auth.py` |
| `_requeue_awaiting_auth_jobs` | 2228 | `mcp/tools/auth.py` |
| `_reset_circuit_breaker_for_engine` | 2270 | `mcp/tools/auth.py` |
| `_handle_feedback` | 2310 | `mcp/tools/feedback.py` |

#### 分割案

| 新ファイル | 移動対象 | 責務 |
|-----------|---------|------|
| `mcp/helpers.py` | `_get_*` 関数群, `_check_chrome_cdp_ready` | 共通ヘルパー |
| `mcp/tools/task.py` | `_handle_create_task`, `_handle_get_status`, `_handle_stop_task`, `_cancel_*` | タスク管理 |
| `mcp/tools/search.py` | `_handle_queue_searches` | 検索実行 |
| `mcp/tools/materials.py` | `_handle_get_materials` | マテリアル取得 |
| `mcp/tools/calibration.py` | `_handle_calibration_*` | キャリブレーション |
| `mcp/tools/auth.py` | `_handle_*_auth*`, `_capture_*`, `_requeue_*`, `_reset_*` | 認証キュー |
| `mcp/tools/feedback.py` | `_handle_feedback` | フィードバック |
| `mcp/server.py` | ツール定義、ディスパッチ、サーバー起動 | エントリポイント |

#### R-02 着手手順

```bash
# 1. ディレクトリ作成
mkdir -p src/mcp/tools

# 2. 分割順序（依存が少ない順）:
#    a. helpers.py（他から参照される）
#    b. tools/__init__.py
#    c. tools/task.py, tools/search.py, ...
#    d. server.py から import して委譲

# 3. 各ステップ後にテスト実行
make test-unit PYTEST_ARGS="-k mcp"

# 4. MCP サーバー起動確認
make mcp-dev
```

---

### 2.4 utils/notification.py（1636行）分割計画

**状態**: ✅ 完了（2025-01-01、テストモジュールインポート対応済み）

#### 完了した変更

| 新ファイル | 移動対象 | 実際の行数 |
|-----------|---------|-----------|
| `utils/intervention_types.py` | `InterventionStatus`, `InterventionType`, `InterventionResult` | ~80 |
| `utils/intervention_manager.py` | `InterventionManager`, `notify_user`, `notify_domain_blocked`, `check_intervention_status`, `complete_intervention`, `get_intervention_manager` | ~580 |
| `utils/batch_notification.py` | `BatchNotificationManager`, `_get_batch_notification_manager`, `notify_search_queue_empty` | ~147 |
| `utils/intervention_queue.py` | `InterventionQueue`, `get_intervention_queue` | ~864 |
| `utils/notification.py`（更新） | ドキュメントのみ（re-export なし） | ~18 |

#### 更新されたファイル

| ファイル | 変更内容 |
|---------|---------|
| `tests/test_notification.py` | パッチ対象を `intervention_manager`, `intervention_queue`, `batch_notification` に更新 |
| `tests/test_captcha_intervention.py` | パッチ対象を `batch_notification`, `intervention_queue`, `intervention_manager` に更新 |
| `tests/test_intervention_queue.py` | パッチ対象を `intervention_queue` に更新、グローバル変数参照を修正 |
| `tests/test_mcp_auth.py` | パッチ対象を `mcp.tools.auth` に更新 |
| `tests/test_fetcher.py` | パッチ対象を `intervention_queue` に更新 |
| `tests/test_mcp_get_status.py` | パッチ対象を `mcp.tools.task` に更新 |
| `tests/test_source_verification.py` | パッチ対象を `intervention_manager` に更新 |

#### 現状構造確認コマンド（参考）

```bash
grep -n '^class\|^def\|^async def' src/utils/notification.py
```

#### 現状構造

| クラス/関数 | 行番号 | 責務 |
|------------|--------|------|
| `InterventionStatus` | 46 | Enum |
| `InterventionType` | 57 | Enum |
| `InterventionResult` | 70 | データクラス |
| `InterventionManager` | 105 | 介入管理（メイン） |
| `_get_manager()` | 483 | シングルトン取得 |
| `notify_user()` | 491 | ユーザー通知 |
| `notify_domain_blocked()` | 584 | ドメインブロック通知 |
| `check_intervention_status()` | 615 | 状態確認 |
| `complete_intervention()` | 628 | 介入完了 |
| `get_intervention_manager()` | 644 | マネージャー取得 |
| `BatchNotificationManager` | 660 | バッチ通知管理 |
| `_get_batch_notification_manager()` | 772 | シングルトン取得 |
| `notify_search_queue_empty()` | 780 | 検索キュー空通知 |
| `InterventionQueue` | 793 | 介入キュー（DB連携） |
| `get_intervention_queue()` | 1627 | キュー取得 |

#### 分割案

| 新ファイル | 移動対象 | 行数（推定） |
|-----------|---------|-------------|
| `utils/intervention_types.py` | `InterventionStatus`, `InterventionType`, `InterventionResult` | ~80 |
| `utils/intervention_manager.py` | `InterventionManager`, 関連関数 | ~450 |
| `utils/batch_notification.py` | `BatchNotificationManager`, 関連関数 | ~130 |
| `utils/intervention_queue.py` | `InterventionQueue`, `get_intervention_queue` | ~850 |
| `utils/notification.py` | 公開インターフェース、re-export | ~100 |

#### R-03 着手手順

```bash
# 1. 依存関係の確認
grep -rn 'from src.utils.notification import' src/ tests/

# 2. 分割順序:
#    a. intervention_types.py（Enum, dataclass）
#    b. intervention_manager.py
#    c. batch_notification.py
#    d. intervention_queue.py
#    e. notification.py（re-export 禁止、後方互換は排除）

# 3. テスト実行
make test-unit PYTEST_ARGS="-k notification or intervention"
```

---

## 3. コード重複

### 3.1 SearchResult クラスの重複定義

**状態**: ✅ 完了（R-05として完了）

**問題**: 同名のクラスが3箇所で定義されていた（解決済み）

#### 現状確認コマンド

```bash
grep -rn '^class SearchResult' src/
```

#### 影響ファイル

| ファイル | 行番号 | 型 | 用途 |
|---------|--------|-----|------|
| `src/search/provider.py` | 38 | Pydantic BaseModel | SERP結果（個別の検索結果） |
| `src/research/pipeline.py` | 30 | dataclass | パイプライン実行結果 |
| `src/research/executor.py` | 129 | dataclass | 検索実行結果 |

#### 改善案

| 現在の名前 | 改名案 | 理由 |
|-----------|--------|------|
| `search/provider.py::SearchResult` | `SERPResult` | SERP（検索エンジン結果ページ）の個別結果を表す |
| `research/executor.py::SearchResult` | `SearchExecutionResult` | 検索実行の集約結果 |
| `research/pipeline.py::SearchResult` | `SearchPipelineResult` または executor.py と統一 | パイプライン結果 |

#### R-05 着手手順

```bash
# 1. 影響範囲の確認
grep -rn 'from src.search.provider import.*SearchResult' src/ tests/
grep -rn 'from src.research.executor import.*SearchResult' src/ tests/
grep -rn 'from src.research.pipeline import.*SearchResult' src/ tests/

# 2. 改名順序（影響が小さい順）:
#    a. search/provider.py の SearchResult → SERPResult
#    b. research/executor.py の SearchResult → SearchExecutionResult
#    c. エイリアスで後方互換することは禁止、完全に移行

# 3. テスト実行
make test-unit
```

---

### 3.2 SearchOptions クラスの重複定義

**状態**: ✅ 完了（R-06として完了）

**問題**: 同名のクラスが2箇所で定義されていた（解決済み）

#### 現状確認コマンド

```bash
grep -rn '^class SearchOptions' src/
```

#### 影響ファイル

| ファイル | 行番号 | 型 | 用途 |
|---------|--------|-----|------|
| `src/search/provider.py` | 146 | Pydantic BaseModel | 検索プロバイダーオプション |
| `src/research/pipeline.py` | 105 | dataclass | パイプラインオプション |

#### 改善案

| 現在の名前 | 改名案 |
|-----------|--------|
| `search/provider.py::SearchOptions` | `SearchProviderOptions` または据え置き |
| `research/pipeline.py::SearchOptions` | `PipelineSearchOptions` |

#### R-06 着手手順

```bash
# 1. 影響範囲の確認
grep -rn 'from src.search.provider import.*SearchOptions' src/ tests/
grep -rn 'from src.research.pipeline import.*SearchOptions' src/ tests/

# 2. 改名とエイリアス追加
# 3. テスト実行
make test-unit
```

---

### 3.3 max_pages バリデーションの重複

**状態**: ✅ 完了（R-04 として完了）

→ **1.1 節を参照**（レガシーバリデーション削除 + スキーマ厳密化により解決）

---

### 3.4 Domain* クラスの散在

**問題**: `Domain` プレフィックスのクラスが13個のファイルに散在している

#### 現状確認コマンド

```bash
grep -rn '^class Domain' src/
```

#### 発見箇所

| クラス名 | ファイル |
|---------|---------|
| `DomainTorMetrics` | `src/utils/schemas.py` |
| `DomainDailyBudget` | `src/utils/schemas.py` |
| `DomainBudgetCheckResult` | `src/utils/schemas.py` |
| `DomainBlockReason` | `src/filter/source_verification.py` |
| `DomainVerificationState` | `src/filter/source_verification.py` |
| `DomainDailyBudgetManager` | `src/scheduler/domain_budget.py` |
| `DomainSearchStats` | `src/crawler/site_search.py` |
| `DomainCategory` | `src/utils/domain_policy.py` |
| `DomainPolicyConfigSchema` | `src/utils/domain_policy.py` |
| `DomainPolicy` | `src/utils/domain_policy.py` |
| `DomainPolicyManager` | `src/utils/domain_policy.py` |
| `DomainBFSCrawler` | `src/crawler/bfs.py` |
| `DomainIPv6Stats` | `src/crawler/ipv6_manager.py` |

#### 判断

**現状維持を推奨**。理由:
- 各クラスは所属モジュールの責務に合っている
- 相互依存が少なく、集約のメリットが小さい
- 集約すると逆に依存関係が複雑化する可能性

---

## 4. 優先順位付きアクションリスト

### HIGH

| ID | タスク | 見積もり | 前提 | 検証 |
|----|--------|---------|------|------|
| R-01 | `fetcher.py` を6ファイルに分割 | 4h | なし | ✅ 完了 （テストモジュールインポート対応済み）|
| R-02 | `mcp/server.py` を `mcp/tools/` に分割 | 3h | なし | ✅ 完了（テストモジュールインポート対応済み） |
| R-03 | `notification.py` を4ファイルに分割 | 2h | なし | ✅ 完了（テストモジュールインポート対応済み） |
| R-04 | max_pages バリデーションの重複削除 | 30min | なし | ✅ 完了 |

### MEDIUM

| ID | タスク | 見積もり | 前提 | 検証 |
|----|--------|---------|------|------|
| R-05 | `SearchResult` クラス改名 | 2h | なし | ✅ 完了 |
| R-06 | `SearchOptions` クラス改名 | 1h | なし | ✅ 完了 |
| R-07 | `Subquery` → `Search` 完全移行 | 3h | なし | ✅ 完了 |
| R-08 | `search_parsers.py` をエンジン別に分割 | 2h | なし | `make test-unit PYTEST_ARGS="-k parser"` |

### LOW

| ID | タスク | 見積もり | 前提 | 検証 |
|----|--------|---------|------|------|
| R-09 | Legacy mode コードの整理 | 2h | なし | ✅ 完了（2026-01-01） |


---

## 5. 共通の作業パターン

### 5.1 ファイル分割の標準手順

```bash
# 1. 現状の確認
grep -n '^class\|^def\|^async def' <target_file>

# 2. 依存関係の確認
grep -rn 'from <module> import' src/ tests/

# 3. 新ファイル作成（依存が少ないものから）
# 4. 元ファイルで re-export せず、完全にクリーンに移行する（後方互換性を排除）
# 5. 各ステップ後にテスト実行で移行を確認
make test-unit PYTEST_ARGS="-k <module_name>"

# 6. lint 確認
make lint

# 7. 最終確認
wc -l <new_files>
```

### 5.2 クラス改名の標準手順

```bash
# 1. 影響範囲の確認
grep -rn '<OldName>' src/ tests/

# 2. 改名
# 3. エイリアスは追加せず、完全にクリーンに移行する（後方互換性を排除）
# 4. テスト実行で移行を確認
make test-unit
```

---

## 6. 変更履歴

| 日付 | 更新者 | 内容 |
|------|--------|------|
| 2025-12-31 | Claude | 初版作成 |
| 2025-01-01 | Claude | 着手手順・検証コマンド追加、行番号更新 |
| 2025-01-01 | Claude | R-04 完了: max_pages レガシーバリデーション削除 + スキーマ厳密化 |
| 2025-01-01 | Claude | R-02/R-03 完了: モジュール分割完了、テストモジュールインポート対応完了 |
| 2026-01-01 | Claude | R-05/R-06/R-07 完了: SearchResult→SERPResult, SearchOptions→SearchProviderOptions, Subquery→Search完全移行 |
| 2026-01-01 | Claude | R-09 完了: Legacy mode コード削除（OllamaClient, legacy intervention, コメント改善） |
