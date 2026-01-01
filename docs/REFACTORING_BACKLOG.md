# リファクタリングバックログ

本ドキュメントは、コードベース分析により特定されたレガシーパターン、分割すべきモジュール、コード重複を網羅的に記載する。

---

## 1. レガシーパターン・命名の揺れ

### 1.1 max_pages → budget_pages 移行

**状態**: 部分的に完了（バリデーションは実装済み、完全廃止は未完了）

**概要**: タスク/検索のページ予算を表すパラメータ名が `max_pages` から `budget_pages` に変更された。現在は互換性バリデーションで旧キーを拒否している。

#### 影響ファイル一覧

| ファイル | 行番号 | 内容 | 対応状況 |
|---------|--------|------|---------|
| `src/mcp/server.py` | 1051-1056 | `budget.max_pages` 拒否バリデーション | ✅ 実装済み |
| `src/mcp/server.py` | 1347-1349 | `options.max_pages` 拒否バリデーション | ✅ 実装済み |
| `src/research/pipeline.py` | 1540-1542 | `options.max_pages` 拒否バリデーション | ✅ 実装済み |

#### 残タスク

- [ ] 3箇所のバリデーションロジックを共通関数に抽出
- [ ] クライアント側での旧キー使用がないか確認
- [ ] 将来的にバリデーション自体を削除（十分な移行期間後）

---

### 1.2 serp_max_pages（SERP用パラメータ）

**状態**: 正式採用済み（`max_pages` とは別概念）

**概要**: SERP（検索結果ページ）のページネーション用パラメータ。`budget_pages`（クロール予算）とは別の概念として正式に定義されている。

#### 使用ファイル一覧

| ファイル | 用途 |
|---------|------|
| `src/search/provider.py:167` | `SearchOptions.serp_max_pages` フィールド定義 |
| `src/search/search_api.py:589,690,722` | SERP取得関数のパラメータ |
| `src/search/pagination_strategy.py:20` | ページネーション設定 |
| `src/research/pipeline.py:116` | パイプラインオプション |
| `src/research/executor.py:263,283,485` | 検索実行時の受け渡し |
| `src/search/browser_search_provider.py:1031,1042` | ブラウザ検索プロバイダー |

#### 関連テスト

| ファイル | テスト数 |
|---------|---------|
| `tests/test_serp_max_pages_propagation.py` | 4 テスト |
| `tests/test_search_provider.py` | 10 テスト（serp_max_pages関連） |
| `tests/test_pagination_strategy.py` | 複数テスト |

**結論**: これはレガシーではなく、正式なパラメータ。対応不要。

---

### 1.3 Subquery → Search 用語統一

**状態**: 移行中（エイリアスで互換性維持）

**概要**: 内部用語が `subquery` から `search` に統一された。現在はエイリアスで後方互換性を維持しているが、完全移行が未完了。

#### エイリアス定義箇所

| ファイル | 行番号 | エイリアス |
|---------|--------|-----------|
| `src/research/__init__.py` | 17-19, 44-46, 51-52 | 全エイリアスのエクスポート |
| `src/research/state.py` | 41-42, 219-220, 492-535, 681-682 | `SubqueryState`, `SubqueryStatus` 等 |
| `src/research/executor.py` | 189-190, 1090-1091 | `SubqueryResult`, `SubqueryExecutor` |
| `src/research/ucb_allocator.py` | 82-83, 220-221, 491-492 | `SubqueryArm`, メソッドエイリアス |

#### 旧用語使用箇所（要移行）

| ファイル | 行番号 | 内容 |
|---------|--------|------|
| `src/research/ucb_allocator.py` | 131, 149-150, 171 | `min_budget_per_subquery` パラメータ |
| `src/research/ucb_allocator.py` | 538, 553 | JSON読み込み時の互換性処理 |
| `src/research/refutation.py` | 32-33, 150-185, 203 | `subquery_id`, `target_type="subquery"` |
| `src/research/context.py` | 4-5, 146, 199 | docstring内の "subquery" |
| `src/research/pipeline.py` | 5 | docstring内の "subquery" |
| `src/research/state.py` | 768, 957 | コメント内の "subquery" |

#### 公開エイリアス一覧

```python
# src/research/__init__.py で定義
SubqueryState = SearchState
SubqueryStatus = SearchStatus
SubqueryExecutor = SearchExecutor
SubqueryResult = SearchResult
SubqueryArm = SearchArm
```

#### 残タスク

- [ ] `min_budget_per_subquery` → `min_budget_per_search` に改名
- [ ] `refutation.py` の `subquery_id` → `search_id` に改名
- [ ] docstring/コメントの更新
- [ ] 外部利用者がいないことを確認後、エイリアスを deprecated 警告付きに変更

---

### 1.4 Legacy Mode コード

**状態**: 残存（削除計画なし）

#### 発見箇所

| ファイル | 行番号 | 内容 |
|---------|--------|------|
| `src/crawler/fetcher.py` | 133-135 | `# Convert to legacy format: (position, delay_seconds)` |
| `src/crawler/fetcher.py` | 163-165 | `# Convert to legacy format: (x, y) only` |
| `src/crawler/fetcher.py` | 1432-1434 | `Immediate intervention (legacy mode)` |
| `src/crawler/fetcher.py` | 2383 | `Browser Headless (legacy path)` |
| `src/filter/llm.py` | 221, 650 | `Ollama client (legacy)` |

#### 残タスク

- [ ] 各 legacy コードの使用状況を確認
- [ ] 削除可能なものは削除、必要なものは正式化

---

## 2. 分割すべき大規模モジュール

### 2.1 ファイルサイズ一覧（500行以上）

| ファイル | 行数 | 優先度 |
|---------|------|--------|
| `src/crawler/fetcher.py` | 2826 | **HIGH** |
| `src/mcp/server.py` | 2343 | **HIGH** |
| `src/filter/evidence_graph.py` | 1843 | MEDIUM |
| `src/search/browser_search_provider.py` | 1662 | MEDIUM |
| `src/utils/notification.py` | 1636 | **HIGH** |
| `src/utils/nli_calibration.py` | 1622 | MEDIUM |
| `src/storage/entity_kb.py` | 1615 | MEDIUM |
| `src/research/pipeline.py` | 1607 | MEDIUM |
| `src/extractor/page_classifier.py` | 1446 | LOW |
| `src/search/search_api.py` | 1406 | MEDIUM |
| `src/extractor/quality_analyzer.py` | 1372 | LOW |
| `src/crawler/wayback.py` | 1370 | LOW |
| `src/storage/database.py` | 1307 | LOW |
| `src/search/search_parsers.py` | 1206 | MEDIUM |
| `src/utils/notification_provider.py` | 1199 | LOW |
| `src/utils/domain_policy.py` | 1112 | LOW |
| `src/research/executor.py` | 1091 | LOW |
| `src/report/generator.py` | 1075 | LOW |
| `src/utils/policy_engine.py` | 1026 | LOW |
| `src/research/state.py` | 1023 | LOW |

---

### 2.2 fetcher.py（2826行）分割計画

**現状構造**:

| クラス/関数 | 行番号 | 責務 |
|------------|--------|------|
| `HumanBehavior` | 90 | 人間らしい振る舞いシミュレーション |
| `TorController` | 196 | Tor接続制御 |
| `get_tor_controller()` | 326 | Torコントローラー取得 |
| `_can_use_tor()` | 338 | Tor使用可否判定 |
| `FetchResult` | 409 | フェッチ結果データクラス |
| `RateLimiter` | 520 | レート制限 |
| `HTTPFetcher` | 573 | HTTP通信（curl-cffi） |
| `BrowserFetcher` | 807 | ブラウザ自動化（Playwright） |
| `_is_challenge_page()` | 1723 | チャレンジページ検出 |
| `_detect_challenge_type()` | 1797 | チャレンジ種類判定 |
| `_estimate_auth_effort()` | 1853 | 認証労力推定 |
| `_save_content()` | 1881 | コンテンツ保存 |
| `_save_warc()` | 1915 | WARC保存 |
| `_get_http_status_text()` | 1998 | HTTPステータステキスト |
| `_save_screenshot()` | 2032 | スクリーンショット保存 |
| `fetch_url()` | 2063 | メインエントリポイント |
| `_fetch_url_impl()` | 2132 | フェッチ実装 |
| `_update_domain_headful_ratio()` | 2726 | ドメイン統計更新 |
| `_update_domain_wayback_success()` | 2771 | Wayback統計更新 |

**分割案**:

| 新ファイル | 移動対象 | 行数（推定） |
|-----------|---------|-------------|
| `crawler/http_fetcher.py` | `HTTPFetcher`, `RateLimiter` | ~500 |
| `crawler/browser_fetcher.py` | `BrowserFetcher` | ~900 |
| `crawler/tor_controller.py` | `TorController`, `get_tor_controller`, `_can_use_tor` | ~150 |
| `crawler/challenge_detector.py` | `_is_challenge_page`, `_detect_challenge_type`, `_estimate_auth_effort` | ~150 |
| `crawler/fetch_result.py` | `FetchResult` | ~100 |
| `crawler/fetcher.py` | `fetch_url`, `_fetch_url_impl`, ユーティリティ | ~1000 |

**依存関係**:
```
fetcher.py
├── http_fetcher.py
├── browser_fetcher.py
│   └── human_behavior.py (既存)
├── tor_controller.py
├── challenge_detector.py
└── fetch_result.py
```

---

### 2.3 mcp/server.py（2343行）分割計画

**現状構造**: 28個の関数、10個のMCPツールハンドラーが混在

**分割案**:

| 新ファイル | 移動対象 | 責務 |
|-----------|---------|------|
| `mcp/tools/task.py` | `_handle_create_task`, `_handle_get_status`, `_handle_stop_task` | タスク管理 |
| `mcp/tools/search.py` | `_handle_queue_searches` | 検索実行 |
| `mcp/tools/materials.py` | `_handle_get_materials` | マテリアル取得 |
| `mcp/tools/calibration.py` | `_handle_calibration_metrics`, `_handle_calibration_rollback` | キャリブレーション |
| `mcp/tools/auth.py` | `_handle_get_auth_queue`, `_handle_resolve_auth` | 認証キュー |
| `mcp/tools/feedback.py` | `_handle_feedback` | フィードバック |
| `mcp/helpers.py` | `_get_exploration_state`, `_get_metrics_from_db`, 他ヘルパー | 共通ヘルパー |
| `mcp/server.py` | ツール定義、ディスパッチ、サーバー起動 | エントリポイント |

**移動対象の詳細**:

| 関数 | 現在行 | 移動先 |
|------|--------|--------|
| `_get_exploration_state` | 970-992 | `mcp/helpers.py` |
| `_clear_exploration_state` | 995-998 | `mcp/helpers.py` |
| `_get_metrics_from_db` | 1006-1101 | `mcp/helpers.py` |
| `_get_search_queue_status` | 1104-1189 | `mcp/helpers.py` |
| `_get_pending_auth_info` | 1192-1248 | `mcp/helpers.py` |
| `_get_domain_overrides` | 1251-1294 | `mcp/helpers.py` |
| `_handle_create_task` | 1297-1353 | `mcp/tools/task.py` |
| `_handle_get_status` | 1356-1563 | `mcp/tools/task.py` |
| `_handle_queue_searches` | 1571-1707 | `mcp/tools/search.py` |
| `_check_chrome_cdp_ready` | 1710-1737 | `mcp/helpers.py` |
| `_handle_stop_task` | 1745-1820 | `mcp/tools/task.py` |
| `_cancel_search_queue_jobs` | 1823-1890 | `mcp/tools/task.py` |
| `_cancel_auth_queue_for_task` | 1893-1923 | `mcp/tools/task.py` |
| `_handle_get_materials` | 1931-1969 | `mcp/tools/materials.py` |
| `_handle_calibration_metrics` | 1977-2001 | `mcp/tools/calibration.py` |
| `_handle_calibration_rollback` | 2004-2087 | `mcp/tools/calibration.py` |
| `_handle_get_auth_queue` | 2095-2153 | `mcp/tools/auth.py` |
| `_capture_auth_session_cookies` | 2156-2264 | `mcp/tools/auth.py` |
| `_handle_resolve_auth` | 2267-2447 | `mcp/tools/auth.py` |
| `_requeue_awaiting_auth_jobs` | 2455-2494 | `mcp/tools/auth.py` |
| `_reset_circuit_breaker_for_engine` | 2497-2522 | `mcp/tools/auth.py` |
| `_handle_feedback` | 2537-2560 | `mcp/tools/feedback.py` |

---

### 2.4 utils/notification.py（1636行）分割計画

**現状構造**:

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

**分割案**:

| 新ファイル | 移動対象 | 行数（推定） |
|-----------|---------|-------------|
| `utils/intervention_types.py` | `InterventionStatus`, `InterventionType`, `InterventionResult` | ~80 |
| `utils/intervention_manager.py` | `InterventionManager`, 関連関数 | ~450 |
| `utils/batch_notification.py` | `BatchNotificationManager`, 関連関数 | ~130 |
| `utils/intervention_queue.py` | `InterventionQueue`, `get_intervention_queue` | ~850 |
| `utils/notification.py` | 公開インターフェース、re-export | ~100 |

---

## 3. コード重複

### 3.1 SearchResult クラスの重複定義

**問題**: 同名のクラスが3箇所で定義されている

| ファイル | 行番号 | 型 | 用途 |
|---------|--------|-----|------|
| `src/search/provider.py` | 38 | Pydantic BaseModel | SERP結果（個別の検索結果） |
| `src/research/pipeline.py` | 30 | dataclass | パイプライン実行結果 |
| `src/research/executor.py` | 129 | dataclass | 検索実行結果 |

**改善案**:

| 現在の名前 | 改名案 | 理由 |
|-----------|--------|------|
| `search/provider.py::SearchResult` | `SERPResult` | SERP（検索エンジン結果ページ）の個別結果を表す |
| `research/executor.py::SearchResult` | `SearchExecutionResult` | 検索実行の集約結果 |
| `research/pipeline.py::SearchResult` | `SearchPipelineResult` または executor.py と統一 | パイプライン結果 |

**影響範囲**:

`search/provider.py::SearchResult` の使用箇所:
```
src/search/provider.py
src/search/search_api.py
src/search/search_parsers.py
src/search/browser_search_provider.py
tests/test_search_provider.py
tests/test_search_parsers.py
```

`research/executor.py::SearchResult` の使用箇所:
```
src/research/executor.py
src/research/pipeline.py（import）
tests/test_research_executor.py
```

`research/pipeline.py::SearchResult` の使用箇所:
```
src/research/pipeline.py
src/mcp/server.py（間接）
```

---

### 3.2 SearchOptions クラスの重複定義

**問題**: 同名のクラスが2箇所で定義されている

| ファイル | 行番号 | 型 | 用途 |
|---------|--------|-----|------|
| `src/search/provider.py` | 146 | Pydantic BaseModel | 検索プロバイダーオプション |
| `src/research/pipeline.py` | 105 | dataclass | パイプラインオプション |

**改善案**:

| 現在の名前 | 改名案 |
|-----------|--------|
| `search/provider.py::SearchOptions` | `SearchProviderOptions` または据え置き |
| `research/pipeline.py::SearchOptions` | `PipelineSearchOptions` |

---

### 3.3 max_pages バリデーションの重複

**問題**: 同じバリデーションロジックが3箇所で実装されている

| ファイル | 行番号 | コード |
|---------|--------|--------|
| `src/mcp/server.py` | 1051-1056 | `if "max_pages" in budget_config: raise InvalidParamsError(...)` |
| `src/mcp/server.py` | 1347-1349 | `if "max_pages" in options: raise InvalidParamsError(...)` |
| `src/research/pipeline.py` | 1540-1542 | `if "max_pages" in options: raise ValueError(...)` |

**改善案**:

```python
# src/mcp/validation.py（新規）
def validate_no_legacy_max_pages(config: dict, param_path: str) -> None:
    """Reject legacy max_pages key.

    Args:
        config: Configuration dict to validate.
        param_path: Parameter path for error message (e.g., "budget", "options").

    Raises:
        InvalidParamsError: If max_pages key is present.
    """
    if "max_pages" in config:
        raise InvalidParamsError(
            f"{param_path}.max_pages is no longer supported; use {param_path}.budget_pages",
            param_name=f"{param_path}.budget_pages",
            expected="integer",
        )
```

---

### 3.4 Domain* クラスの散在

**問題**: `Domain` プレフィックスのクラスが13個のファイルに散在している

| クラス名 | ファイル | 行番号 |
|---------|---------|--------|
| `DomainTorMetrics` | `src/utils/schemas.py` | 293 |
| `DomainDailyBudget` | `src/utils/schemas.py` | 334 |
| `DomainBudgetCheckResult` | `src/utils/schemas.py` | 385 |
| `DomainBlockReason` | `src/filter/source_verification.py` | 57 |
| `DomainVerificationState` | `src/filter/source_verification.py` | 106 |
| `DomainDailyBudgetManager` | `src/scheduler/domain_budget.py` | 32 |
| `DomainSearchStats` | `src/crawler/site_search.py` | 94 |
| `DomainCategory` | `src/utils/domain_policy.py` | 46 |
| `DomainPolicyConfigSchema` | `src/utils/domain_policy.py` | 339 |
| `DomainPolicy` | `src/utils/domain_policy.py` | 369 |
| `DomainPolicyManager` | `src/utils/domain_policy.py` | 479 |
| `DomainBFSCrawler` | `src/crawler/bfs.py` | 393 |
| `DomainIPv6Stats` | `src/crawler/ipv6_manager.py` | 100 |

**改善案**:

1. `src/domain/` パッケージを作成し、ドメイン関連クラスを集約
2. または、現状維持（各モジュールの責務に合っている場合）

**判断基準**:
- 相互依存が多い → 集約すべき
- 各モジュール内で完結 → 現状維持

---

## 4. 優先順位付きアクションリスト

### HIGH（次のスプリント）

| ID | タスク | 見積もり |
|----|--------|---------|
| R-01 | `fetcher.py` を6ファイルに分割 | 4h |
| R-02 | `mcp/server.py` を `mcp/tools/` に分割 | 3h |
| R-03 | `notification.py` を4ファイルに分割 | 2h |
| R-04 | `max_pages` バリデーション共通化 | 30m |

### MEDIUM（今後1-2ヶ月）

| ID | タスク | 見積もり |
|----|--------|---------|
| R-05 | `SearchResult` クラス改名 | 2h |
| R-06 | `SearchOptions` クラス改名 | 1h |
| R-07 | `Subquery` → `Search` 完全移行 | 3h |
| R-08 | `search_parsers.py` をエンジン別に分割 | 2h |

### LOW（将来）

| ID | タスク | 見積もり |
|----|--------|---------|
| R-09 | Legacy mode コードの整理 | 2h |
| R-10 | Domain* クラスの整理検討 | 1h |
| R-11 | deprecated エイリアスに警告追加 | 1h |

---

## 5. 変更履歴

| 日付 | 更新者 | 内容 |
|------|--------|------|
| 2025-12-31 | Claude | 初版作成 |
