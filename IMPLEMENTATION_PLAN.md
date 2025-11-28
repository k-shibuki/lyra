# 実装計画: Local Autonomous Deep Research Agent (Lancet)

## 概要
OSINTデスクトップリサーチを自律的に実行するローカルAIエージェントの実装計画。
**Podmanコンテナ環境**で稼働し、MCPを通じてCursorと連携する。

---

## Phase 1: プロジェクト基盤構築 ✅

### 1.1 プロジェクト構造 ✅
- [x] ディレクトリ構造の作成
  - [x] `src/` - メインソースコード
  - [x] `src/mcp/` - MCPサーバー実装
  - [x] `src/search/` - 検索エンジン連携
  - [x] `src/crawler/` - クローリング/取得機能
  - [x] `src/extractor/` - コンテンツ抽出
  - [x] `src/filter/` - フィルタリング/評価
  - [x] `src/report/` - レポート生成
  - [x] `src/scheduler/` - ジョブスケジューラ
  - [x] `src/storage/` - データストレージ
  - [x] `src/utils/` - ユーティリティ
  - [x] `config/` - 設定ファイル
  - [x] `data/` - データ保存ディレクトリ
  - [x] `logs/` - ログ保存
  - [x] `tests/` - テストコード

### 1.2 依存関係設定 ✅
- [x] `requirements.txt` の作成
- [x] `pyproject.toml` の作成
- [x] Dockerfile / Dockerfile.dev の作成
- [x] podman-compose.yml の作成

### 1.3 設定管理 ✅
- [x] `config/settings.yaml` - 基本設定
- [x] `config/engines.yaml` - 検索エンジン設定
- [x] `config/domains.yaml` - ドメインポリシー初期値
- [x] `config/searxng/settings.yml` - SearXNG設定
- [x] 環境変数管理（podman-compose.yml内）

### 1.4 データベーススキーマ ✅
- [x] SQLiteスキーマ設計 (`src/storage/schema.sql`)
  - [x] `tasks` テーブル
  - [x] `queries` テーブル
  - [x] `serp_items` テーブル
  - [x] `pages` テーブル
  - [x] `fragments` テーブル
    - [x] `heading_context`: 直近の見出し（単一文字列）
    - [x] `heading_hierarchy`: 見出し階層（JSON配列）
    - [x] `element_index`: 見出し配下での要素順序
    - [x] `fragment_type`: 要素種別（paragraph/heading/list/table/quote/figure/code）
  - [x] `claims` テーブル
  - [x] `edges` テーブル（エビデンスグラフ）
  - [x] `domains` テーブル（ドメインポリシー）
  - [x] `engine_health` テーブル
  - [x] `jobs` テーブル
  - [x] `cache_serp` テーブル
  - [x] `cache_fetch` テーブル
  - [x] `cache_embed` テーブル
  - [x] `event_log` テーブル
  - [x] `intervention_log` テーブル
- [x] FTS5全文検索設定

### 1.5 ロギング基盤 ✅
- [x] 構造化ログ（JSON）設定 - structlog
- [x] 因果トレース（cause_id）の実装
- [x] LogContext / CausalTrace ヘルパー

---

## Phase 2: MCPサーバー実装 ✅

### 2.1 MCPサーバー基盤 ✅
- [x] MCPプロトコル実装 (`src/mcp/server.py`)
- [x] ツール登録機構

### 2.2 MCPツール実装 ✅
- [x] `search_serp` - 検索実行
- [x] `fetch_url` - URL取得
- [x] `extract_content` - コンテンツ抽出
- [x] `rank_candidates` - パッセージランキング
- [x] `llm_extract` - LLM抽出
- [x] `nli_judge` - NLI判定
- [x] `notify_user` - ユーザー通知
- [x] `schedule_job` - ジョブスケジュール
- [x] `create_task` - タスク作成
- [x] `get_task_status` - タスク状態取得
- [x] `get_report_materials` - レポート素材提供（§2.1責任分界）
- [x] `get_evidence_graph` - エビデンスグラフ直接参照（§3.2.1）

### 2.3 エラーハンドリング ✅
- [x] タイムアウト管理
- [x] エラー応答フォーマット

---

## Phase 3: 検索機能実装 ✅

### 3.1 SearXNG連携 ✅
- [x] SearXNG Podmanコンテナ設定
- [x] SearXNG設定ファイル（settings.yml）
- [x] HTTP APIクライアント実装
- [x] レート制限

### 3.2 検索クエリ管理 ✅
- [x] 基本クエリ実行
- [x] SERP結果正規化
- [x] キャッシュ機能
- [x] クエリ多様化（同義語展開）- SudachiPy統合
- [x] 演算子マッピング（site:, filetype:, intitle:, exact, exclude, date_after, required）
- [x] 言語横断ミラークエリ（Ollama翻訳連携, §3.1.1）

### 3.3 エンジンヘルスチェック ✅
- [x] 基本メトリクス収集
- [x] サーキットブレーカ完全実装
- [x] EMA更新ロジック

---

## Phase 4: クローリング/取得機能 ✅

### 4.1 HTTPクライアント ✅
- [x] curl_cffi実装
- [x] ヘッダー整合
- [x] ETag/If-Modified-Since完全対応

### 4.2 ブラウザ自動化 ✅
- [x] Playwright CDP接続基盤
- [x] リソースブロッキング
- [x] ヘッドレス/ヘッドフル自動切替
- [x] ヒューマンライク操作

### 4.3 プリフライト判定 ✅
- [x] チャレンジ検知
- [x] 分岐ロジック

### 4.4 ネットワーク制御 ✅
- [x] レート制限
- [x] Tor連携（Stem）完全実装

### 4.5 アーカイブ保存 ✅
- [x] WARC保存 - warcio統合
- [x] スクリーンショット保存

---

## Phase 5: コンテンツ抽出 ✅

### 5.1 HTML抽出 ✅
- [x] trafilatura統合
- [x] フォールバック抽出器
- [x] メタデータ抽出

### 5.2 PDF抽出 ✅
- [x] PyMuPDF統合
- [x] OCR連携 (PaddleOCR + Tesseract フォールバック)

### 5.3 重複検出 ✅
- [x] MinHash実装 - datasketch統合、LSHインデックス
- [x] SimHash実装 - ハミング距離ベースの類似度検出
- [x] HybridDeduplicator - MinHash+SimHash組み合わせ

---

## Phase 6: フィルタリングと評価 ✅

### 6.1 多段評価パイプライン ✅
- [x] BM25ランキング
- [x] 埋め込み類似度
- [x] リランキング

### 6.2 ローカルLLM連携 ✅
- [x] Ollama統合
- [x] 二段LLMゲーティング

### 6.3 NLI ✅
- [x] tiny-DeBERTa実装
- [x] supports/refutes/neutral判定

### 6.4 エビデンスグラフ ✅
- [x] NetworkXグラフ構築
- [x] SQLite永続化
- [x] 引用ループ検出
- [x] ラウンドトリップ検出
- [x] セルフリファレンス検出
- [x] 引用ペナルティ計算
- [x] 一次資料比率算出

---

## Phase 7: スケジューラ実装 ✅

### 7.1 ジョブスケジューラ ✅
- [x] ジョブキュー実装
- [x] 優先度管理

### 7.2 スロット/排他制御 ✅
- [x] スロット定義
- [x] 排他ルール

### 7.3 予算制御 ✅
- [x] タスク総ページ数上限 (≤120/task, §3.1)
- [x] 時間上限 (≤20min GPU / ≤25min CPU, §3.1)
- [x] LLM処理時間比率制御 (≤30%, §3.1)
- [x] BudgetManager / TaskBudget クラス
- [x] JobScheduler への統合

---

## Phase 8: 通知/手動介入 ✅

### 8.1 通知システム ✅
- [x] Windowsトースト通知
- [x] Linux notify-send対応
- [x] WSL→Windows通知橋渡し

### 8.2 手動介入フロー【§3.6.2廃止→§3.6.1に統合】 ✅
- [x] 基本フロー実装
- [x] ウィンドウ前面化（CDP Page.bringToFront + OS API フォールバック）
- [x] ~~タイムアウト処理~~ → **廃止**（§3.6.1: ユーザー主導の完了報告のみ）
- [x] ~~要素ハイライト~~ → **廃止**（§3.6.1: DOM操作禁止）
- [x] ドメイン連続失敗追跡（3回失敗で当日スキップ、§3.1準拠）
- [x] クールダウン適用（明示的失敗時≥60分、§3.5準拠）
- [x] fetcher.pyへの統合（challenge検知→認証キューへエンキュー）
- [x] チャレンジタイプ検出（Cloudflare/CAPTCHA/Turnstile/hCaptcha等）
- [x] **§3.6.1安全運用方針適用**
  - CDP許可: `Page.bringToFront` のみ
  - CDP禁止: `Runtime.evaluate`, `DOM.*`, `Input.*`, `Emulation.*`
  - 完了検知: `complete_authentication` によるユーザー明示報告

### 8.3 認証待ちキュー（§3.6.1 推奨方式） ✅
- [x] `intervention_queue` テーブル（認証待ちキュー）
- [x] `InterventionQueue` クラス
  - [x] `enqueue()`: 認証待ちをキューに積む
  - [x] `get_pending()`: 認証待ち一覧を取得
  - [x] `get_pending_by_domain()`: ドメイン別にグループ化した認証待ちを取得
  - [x] `start_session()`: 認証セッションを開始（URL返却のみ、DOM操作なし）
  - [x] `complete()`: 認証完了を記録（単一キューアイテム）
  - [x] `complete_domain()`: ドメイン単位で認証を一括完了
  - [x] `skip()`: 認証をスキップ（キューID指定またはドメイン指定）
  - [x] `get_session_for_domain()`: 認証済みセッションを取得
- [x] MCPツール
  - [x] `get_pending_authentications`: 認証待ちキューを取得
  - [x] `get_pending_by_domain`: ドメイン別にグループ化した認証待ちを取得
  - [x] `start_authentication_session`: 認証セッションを開始（URL開く+前面化のみ）
  - [x] `complete_authentication`: 認証完了を通知（主たる完了検知手段）
  - [x] `complete_domain_authentication`: ドメイン単位で認証を一括完了
  - [x] `skip_authentication`: 認証をスキップ
  - [x] `skip_domain_authentication`: ドメイン単位でスキップ
- [x] `FetchResult` に `auth_queued`, `queue_id` フィールド追加
- [x] `BrowserFetcher.fetch()` に `queue_auth` パラメータ追加
- [x] **ドメインベース認証管理**（§3.6.1）
  - 同一ドメインの認証完了で複数タスクのキューを一括解決
  - 認証済みセッション（Cookie等）を同一ドメインで共有
  - ドメイン単位でのスキップ機能
- [x] **§3.6.1安全運用方針**
  - 認証セッション中はDOM操作（スクロール、ハイライト、フォーカス）禁止
  - ユーザーが自分でチャレンジを発見・解決
  - タイムアウトなし（ユーザー主導の完了報告）

---

## Phase 9: レポート生成 ✅

### 9.1 レポート構成 ✅
- [x] Markdownテンプレート
- [x] JSONフォーマット

### 9.2 引用管理 ✅
- [x] 出典リスト生成
- [x] 深いリンク生成 (§3.4準拠: アンカースラッグ生成、一次/二次資料分類)

---

## Phase 10: 自動適応/メトリクス ✅

### 10.1 メトリクス収集 ✅
- [x] `MetricsCollector` クラス - 包括的メトリクス収集
- [x] `TaskMetrics` - タスク単位のメトリクス追跡
- [x] `MetricValue` - EMAベースのメトリクス値管理
- [x] 検索品質メトリクス（収穫率、新規性、重複率、ドメイン多様性）
- [x] 露出・回避メトリクス（Tor利用率、ヘッドフル比率、304活用率、エラー率）
- [x] OSINT品質メトリクス（一次資料率、引用ループ率、矛盾率、タイムライン被覆率）

### 10.2 ポリシー自動更新 ✅
- [x] `PolicyEngine` - クローズドループ制御エンジン
- [x] `ParameterBounds` - パラメータ境界定義
- [x] `ParameterState` - ヒステリシス付きパラメータ状態管理
- [x] エンジン重み・QPS自動調整
- [x] ドメインheadful比率・Tor比率・クールダウン自動調整
- [x] 振動防止のためのヒステリシス（最小間隔300秒）

### 10.3 リプレイモード ✅
- [x] `DecisionLogger` - 決定ログ記録
- [x] `Decision` - 決定データ構造（10種類の決定タイプ）
- [x] `ReplayEngine` - 決定フロー再実行エンジン
- [x] `ReplaySession` - リプレイセッション管理
- [x] 決定比較・divergence検出
- [x] セッションレポート出力

### 10.4 永続化 ✅
- [x] `metrics_snapshot` テーブル - グローバルメトリクススナップショット
- [x] `task_metrics` テーブル - タスク別メトリクス
- [x] `policy_updates` テーブル - ポリシー更新履歴
- [x] `decisions` テーブル - 決定ログ
- [x] `replay_sessions` テーブル - リプレイセッション
- [x] メトリクスビュー（v_latest_metrics, v_recent_policy_updates, v_task_metrics_summary）

---

## Phase 11: 探索制御エンジン（Cursor AI主導） ✅

**設計方針**: §2.1に基づき、クエリ/サブクエリの設計はCursor AIが全面的に行う。
Lancetは設計支援情報の提供と実行に専念する（候補生成は行わない）。

### 11.1 設計支援情報の提供 ✅
- [x] `ResearchContext` クラス - 設計支援情報の構築
  - [x] エンティティ抽出（固有表現認識）
  - [x] 垂直テンプレート候補の提示
  - [x] 類似過去クエリの成功率取得
  - [x] 推奨エンジン/ドメインの算出
- [x] `get_research_context` MCPツール実装

### 11.2 サブクエリ実行エンジン ✅
- [x] `SubqueryExecutor` クラス - Cursor AI指定のサブクエリを実行
  - [x] 検索→取得→抽出→評価パイプライン
  - [x] 機械的展開（同義語・ミラークエリ・演算子付与）
  - [x] 結果サマリの生成
- [x] `execute_subquery` MCPツール実装

### 11.3 探索状態管理 ✅
- [x] `ExplorationState` クラス - タスク/サブクエリ状態の管理
  - [x] 充足度判定（§3.1.7.3: 独立ソース数 + 一次資料有無）
  - [x] 新規性スコア計算（§3.1.7.4: 直近k断片の新規率）
  - [x] 予算消費追跡（ページ数/時間）
  - [x] **メトリクスのみ返却**（`recommendations`フィールド削除済み）
- [x] `get_exploration_status` MCPツール実装
  - **重要**: 推奨なし。Cursor AIがメトリクスを基に次のアクションを判断する（§2.1責任分界準拠）

### 11.4 反証探索（機械パターン適用） ✅
- [x] `RefutationExecutor` クラス - Cursor AI指定の主張に対する反証検索
  - [x] 機械パターン適用（定型接尾辞の付与のみ）
  - [x] 反証結果のエビデンスグラフへの登録
  - [x] 信頼度調整（反証ゼロ時の減衰）
- [x] `execute_refutation` MCPツール実装

### 11.5 探索終了処理 ✅
- [x] `finalize_exploration` MCPツール実装
  - [x] 最終状態のDB記録
  - [x] 未充足サブクエリの明示
  - [x] フォローアップ候補の出力

---

## Phase 12: クローリング拡張 ✅

### 12.1 robots.txt / sitemap対応 ✅
- [x] `robots.txt` パーサーと遵守チェック（RobotsChecker）
- [x] `sitemap.xml` パーサーと重要URL抽出（SitemapParser）

### 12.2 ドメイン内BFS探索 ✅
- [x] 同一ドメイン深さ≤2のBFS探索（DomainBFSCrawler）
- [x] 見出し/目次/関連記事リンクの優先度付け（LinkExtractor）

### 12.3 サイト内検索UI自動操作 ✅
- [x] allowlistドメイン管理（config/domains.yaml連携）
- [x] フォーム自動検出と入力（SiteSearchManager）
- [x] 成功率/収穫率の学習反映（DomainSearchStats）

### 12.4 Wayback差分探索 ✅
- [x] アーカイブスナップショット取得（WaybackClient）
- [x] 見出し・要点・日付の差分抽出（ContentAnalyzer）
- [x] タイムライン構築（WaybackExplorer）

---

## Phase 13: 信頼度キャリブレーション ✅

### 13.1 確率校正 ✅
- [x] Platt/温度スケーリング実装（§3.3.4）
- [x] `llm_extract`/`nli_judge`への適用（Calibrator.calibrate）

### 13.2 評価と監視 ✅
- [x] Brierスコア計算
- [x] サンプル蓄積ベース再校正（閾値到達で自動再計算）
- [x] 3B→7B昇格判定との連動（EscalationDecider）

---

## Phase 14: テスト/検証 (部分完了)

### 14.1 テスト基盤 ✅
- [x] pytestマーカー設定（unit/integration/e2e/slow）
- [x] conftest.pyにマーカー自動付与フック
- [x] モックフィクスチャ（SearXNG、Ollama、Browser）
- [x] テストデータファクトリ

### 14.2 テストコード品質基準 ✅
- [x] §7.1.1 禁止パターンの定義と是正
- [x] §7.1.7 継続的検証基準の改訂
  - [x] カバレッジ監視指標（CIブロックなし）
  - [x] テスト分類と実行時間制約
  - [x] モック戦略の明文化

### 14.3 テスト実装

#### 14.3.1 完了済みテスト ✅
- [x] 基本ユニットテスト（689件、全パス）
- [x] Phase 10テスト（メトリクス、ポリシー、リプレイ）
- [x] Phase 8テスト（通知/手動介入フロー）
- [x] Phase 9テスト（レポート生成、深いリンク生成）
- [x] Phase 11テスト（探索制御エンジン、責任分界検証）
- [x] OCRテスト修正（モック戦略改善）
- [x] 統合テスト（26件：パイプライン、エビデンスグラフ、スケジューラ等）

#### 14.3.2 E2E設計方針（実装タスクはPhase 16.10へ移動）

> **実装タスク**: Phase 16.10 に統合済み（Phase 16.9完了後に実施）

##### 背景・保留理由

E2Eテストは外部サービス（検索エンジン）を実際に叩くため、以下のリスクがある：

- **bot検知**: DuckDuckGo/Brave/Qwant等はCAPTCHA/レート制限でブロックされやすい
- **IPリスク**: 開発環境のIPは検索エンジンからブロックされやすい
- **IP汚染**: テスト実行でホストIPが汚染され、**通常のブラウザ利用にも影響**（CAPTCHAが出る）

→ **低リスクなIP（自宅環境等）でE2E実装を進めるため、意図的に保留していた。**

##### コンセプトの整合性

Lancetは「Zero OpEx」を掲げつつ、IPブロックを完全回避することは困難。§2の「半自動運用」で以下を許容：

```
- CAPTCHA/ログイン等は手動解除を許容
- 認証待ちキューに積み、ユーザーの都合でバッチ処理
- 認証不要ソースを優先処理し、ユーザー介入回数を最小化
```

**つまり「ブロックされない」ではなく「ブロックされたら手動誘導」がコンセプト。**
この「手動誘導」が確実に機能することをE2Eで検証する必要がある。

##### テスト分類の棲み分け

| レイヤ | 外部依存 | 実行環境 | 目的 |
|--------|----------|----------|------|
| **unit** | なし（全モック） | どこでも | コードロジック検証 |
| **integration** | なし（全モック） | どこでも | コンポーネント連携検証 |
| **e2e** | あり（実サービス） | **低リスクIP限定** | 実環境での動作検証 |

##### E2Eの細分類（リスクベース）

| マーカー | リスク | 例 | デフォルト実行 |
|----------|--------|-----|---------------|
| `@e2e` | 低 | DB操作、ローカルOllama | ❌ 除外 |
| `@e2e @external` | 中 | 直接ブラウザ検索（mojeek等ブロック耐性エンジン） | ❌ 除外 |
| `@e2e @rate_limited` | 高 | DuckDuckGo/Google（ブロックされやすい） | ❌ 除外 |
| `@e2e @manual` | 特殊 | CAPTCHA解決フロー | ❌ 除外 |

---

## Phase 15: ドキュメント/運用 🔄

### 15.1 ドキュメント 🔄
- [ ] README.md（プロジェクト概要、セットアップ手順、アーキテクチャ図）
- [ ] LICENSE（検討中）
- [x] 本実装計画書
- [ ] 手動介入運用手順書（§6成果物: 認証待ちキュー運用、バッチ処理手順、スキップ判断基準）
- [ ] MCPツール仕様書（§6成果物: I/Oスキーマ、タイムアウト、リトライ方針）
- [ ] ジョブスケジューラ仕様書（§6成果物: スロット定義、排他ルール、予算制御）
- [ ] プロファイル健全性監査運用手順（§6成果物: 監査項目、自動修復フロー）

### 15.2 運用スクリプト ✅
- [x] `scripts/dev.sh` - 開発環境管理
- [x] `scripts/chrome.sh` - Chrome管理（check/start/stop/setup）
- [x] `scripts/test.sh` - テスト実行（run/check/get/kill）

---

## Phase 16: 未実装機能 (Gap Analysis) ⏳

**requirements.md との詳細照合により特定された未実装項目。**
**優先度**: 🔴 高（E2E前に必須） / 🟡 中（MVP強化） / 🟢 低（将来拡張）

---

### 16.1 抗堪性・ステルス性 (§4.3) 🔴

#### 16.1.1 ネットワーク/IP層
- [x] **IPv6運用** (§4.3) ✅
  - v6→v4切替ロジック（ドメイン単位で成功率学習）
  - IPv6成功率メトリクス追跡
  - ハッピーアイボール風切替（アドレスインターリーブ）
  - 実装: `src/crawler/ipv6_manager.py` (IPv6ConnectionManager, DomainIPv6Stats, IPv6Metrics)
  - DBスキーマ: `domains`テーブルにIPv6関連カラム14個追加
  - 設定: `config/settings.yaml` (ipv6セクション)
  - dns_policy.py統合: IPv6優先度制御メソッド追加
  - fetcher.py統合: IPv6メトリクス追跡
  - テスト: 64件（全パス、§7.1準拠）
- [x] **DNS方針** (§4.3) ✅
  - socks5h://によるTor経路時のDNSリーク防止（Privoxy不要）
  - EDNS Client Subnet無効化設定
  - DNSキャッシュTTL尊重
  - DNSリーク検出メトリクス
  - 実装: `src/crawler/dns_policy.py` (DNSPolicyManager, get_dns_policy_manager)
  - HTTPFetcher統合: socks5:// → socks5h://への変更
  - テスト: 37件（全パス）
- [x] **HTTP/3(QUIC)方針** (§4.3) ✅
  - ブラウザ経由でのHTTP/3自然利用検知
  - HTTP/3提供サイトでのブラウザ経路比率自動増加
  - 実装: `src/crawler/http3_policy.py` (HTTP3PolicyManager, ProtocolVersion, HTTP3DomainStats)
  - 設定: `config/settings.yaml` http3セクション追加
  - スキーマ: `domains`テーブルにHTTP/3関連カラム追加
  - テスト: 45件（全パス、§7.1準拠）

#### 16.1.2 トランスポート/TLS層
- [x] **sec-fetch-*ヘッダー整合** (§4.3) ✅
  - `sec-fetch-site`, `sec-fetch-mode`, `sec-fetch-dest`の遷移コンテキスト整合
  - SERP→記事遷移での自然なヘッダー生成
  - 実装: `src/crawler/sec_fetch.py`, HTTPFetcher統合
- [x] **sec-ch-ua*ヘッダー** (§4.3) ✅
  - Client Hintsヘッダーの適切な設定
  - 実装: `src/crawler/sec_fetch.py` (SecCHUAHeaders, generate_sec_ch_ua_headers)

#### 16.1.3 ブラウザ/JS層
- [x] **navigator.webdriverオーバーライド** (§4.3) ✅
  - `stealth.js`相当の最小限プロパティオーバーライド
  - 実装: `src/crawler/stealth.py` (STEALTH_JS, CDP_STEALTH_JS)
- [x] **undetected-chromedriverフォールバック** (§4.3) ✅
  - Cloudflare強/Turnstile時のフォールバック経路
  - 実装: `src/crawler/undetected.py` (UndetectedChromeFetcher)
  - BrowserFetcher統合: 自動エスカレーション（captcha_rate > 0.5 または block_score > 5）
  - 設定: `config/settings.yaml` (browser.undetected_chromedriver)
  - Dockerfile更新: Google Chrome + selenium依存関係追加
  - テスト: 27件（全パス）
- [x] **viewportジッター** (§4.3) ✅
  - 狭幅ジッター適用（ヒステリシスあり）
  - 実装: `src/crawler/stealth.py` (ViewportJitter, ViewportJitterConfig)

#### 16.1.4 プロファイル健全性監査 (§4.3.1) ✅
- [x] **タスク開始時チェック**
  - UA/メジャーバージョン差分検知
  - フォントセット差分検知
  - 言語/タイムゾーン差分検知
  - Canvas/Audio指紋差分検知
  - 実装: `src/crawler/profile_audit.py` (ProfileAuditor, FINGERPRINT_JS)
- [x] **自動修復**
  - Chrome再起動フラグ
  - フォント再同期推奨
  - プロファイル再作成（バックアップから復元）
  - 実装: `src/crawler/profile_audit.py` (RepairAction, attempt_repair)
- [x] **監査ログ**
  - 差分・修復内容・再試行回数の構造化記録
  - JSONL形式の監査ログファイル
  - 実装: `src/crawler/profile_audit.py` (_log_audit)
  - BrowserFetcher統合: ブラウザ初期化時に自動健全性チェック
  - テスト: 30件（全パス）

#### 16.1.5 セッション移送ユーティリティ (§3.1.2) ✅
- [x] **ブラウザ→HTTPクライアント移送**
  - Cookie/ETag/UA/Accept-Languageの安全な移送
  - 同一ドメイン限定制約
  - Referer/sec-fetch-*整合維持
  - 実装: `src/crawler/session_transfer.py` (SessionTransferManager, SessionData, CookieData)
  - capture_from_browser: Playwrightからセッションをキャプチャ
  - generate_transfer_headers: HTTPクライアント用ヘッダー生成
  - テスト: 35件（全パス）

#### 16.1.6 ブラウザ経路アーカイブ保存 (§4.3.2) ✅
- [x] **CDXJ風メタデータ**
  - 主要リソースのURL/ハッシュ一覧
  - 実装: `src/crawler/browser_archive.py` (CDXJGenerator, url_to_surt)
- [x] **簡易HAR生成**
  - CDPのNetworkイベントから生成
  - 実装: `src/crawler/browser_archive.py` (HARGenerator, NetworkEventCollector)
- [x] **BrowserFetcherへの統合**
  - ネットワークイベント収集とアーカイブ保存
  - FetchResultにcdxj_path/har_pathフィールド追加
  - テスト: 37件（全パス）

---

### 16.2 OSINT品質強化 (§3.1, §3.3) 🟡

#### 16.2.1 検索戦略 (§3.1.1)
- [x] **UCB1風予算再配分** ✅
  - サブクエリごとの収穫率で予算を動的再配分
  - 探索木制御の最適化
  - 実装: `src/research/ucb_allocator.py` (UCBAllocator, SubqueryArm)
  - UCB1スコア計算（exploration/exploitation balance）
  - ExplorationStateとの統合（get_dynamic_budget, get_ucb_scores等）
  - テスト: 45件（全パス）
- [x] **クエリABテスト** ✅
  - 表記ゆれ/助詞/語順バリアントの小規模A/B
  - 高収穫クエリのキャッシュ・再利用
  - 実装: `src/search/ab_test.py`
    - `QueryVariantGenerator` - クエリバリアント生成（表記ゆれ/助詞/語順）
    - `ABTestExecutor` - A/Bテスト実行・収穫率比較
    - `HighYieldQueryCache` - 高収穫パターンのキャッシュ
  - DBスキーマ: `query_ab_tests`, `query_ab_variants`, `high_yield_queries`
  - テスト: 38件（全パス）
- [x] **ピボット探索（エンティティ拡張）** ✅
  - 企業→子会社/役員/所在地/ドメイン
  - ドメイン→サブドメイン→証明書SAN→組織名
  - 個人→別名/ハンドル/所属
  - 実装: `src/research/pivot.py`
    - `PivotExpander` - エンティティ拡張ロジック
    - `PivotSuggestion` - ピボット提案データ構造
    - `PivotType`, `EntityType` - 列挙型
    - `detect_entity_type` - エンティティタイプ自動検出
  - ResearchContext統合: `get_context()`に`pivot_suggestions`フィールド追加
  - テスト: 33件（全パス）

#### 16.2.2 インフラ/レジストリ連携 (§3.1.2, §3.1.3)
- [x] **RDAP/WHOIS連携** ✅
  - 公式Web/レジストリからHTML取得
  - 登録者/NS/更新履歴抽出
  - 実装: `src/crawler/rdap_whois.py` (RDAPClient, WHOISParser, WHOISRecord)
  - 複数エンドポイント対応: IANA, ARIN, RIPE, APNIC, JPRS, ICANN lookup
  - キャッシュ機能、バッチ処理対応
  - テスト: 22件（全パス）
- [x] **crt.sh連携** ✅
  - 証明書透明性ログからSAN/発行者/発行時系列抽出
  - 実装: `src/crawler/crt_transparency.py` (CertTransparencyClient, CertificateInfo, CertTimeline)
  - 関連ドメイン発見、証明書タイムライン構築
  - テスト: 22件（全パス）
- [x] **ResearchContext統合** ✅
  - `get_context()`に`registry_info`フィールド追加
  - ドメインエンティティに対する自動WHOIS/CT検索
  - 実装: `src/research/context.py` (_get_registry_info, RegistryInfo)
- [x] **エンティティKB正規化** ✅
  - 抽出した名称/所在地/識別子のKB格納
  - 別表記・住所正規化・同一性推定
  - 実装: `src/storage/entity_kb.py` (EntityKB, NameNormalizer, AddressNormalizer, IdentifierNormalizer)
  - 統合: `src/crawler/entity_integration.py` (EntityExtractor, WHOIS/CT連携)
  - テスト: 71件（全パス）

#### 16.2.3 ページタイプ判定 (§3.1.2) ✅
- [x] **自動分類ロジック**
  - 記事/ナレッジ/掲示/フォーラム/ログイン壁/一覧の判定
  - 抽出・遷移戦略の切替
  - 実装: `src/extractor/page_classifier.py` (PageClassifier, PageType, ClassificationResult)
  - HTML構造・URL・セマンティック特徴に基づくスコアリング
  - テスト: 28件（全パス）

#### 16.2.4 低品質/生成コンテンツ抑制 (§3.1.1, §3.3.3) ✅
- [x] **ContentQualityAnalyzer実装**
  - 実装: `src/extractor/quality_analyzer.py`
  - 特徴量: テキスト統計、構造特徴、リンク密度、広告密度、n-gram反復、文均一性(burstiness/uniformity)
- [x] **アグリゲータ/AI生成検出**
  - AIパターンマッチ（23パターン: "it's important to note", "let's delve into"等）
  - 文長均一性・burstinessスコアによる検出
  - 二段品質ゲート: ルールベース(高速) → LLM(曖昧時のみ)
- [x] **SEOスパム検出**
  - キーワード密度、アフィリエイトリンク、CTA過剰検出
  - クリックベイト、テンプレ重複、スクレイパーサイト検出
- [x] **ペナルティ適用**
  - 検出問題に応じたスコア減衰（最大80%減）
  - 品質スコア0.0〜1.0で評価
- テスト: 40件（全パス）

#### 16.2.5 時系列整合チェック (§3.3.3) ✅
- [x] **主張時点 vs ページ更新日の不整合検出**
  - 古い主張の信頼度減衰
  - タイムスタンプ整合性検証
  - 実装: `src/filter/temporal_consistency.py` (TemporalConsistencyChecker, DateExtractor)
  - 日付抽出: ISO形式、日本語形式（令和/平成）、月名形式
  - 一貫性レベル: consistent/uncertain/stale/inconsistent
  - 信頼度減衰: 年数に応じた指数減衰、5年以上でstale判定
  - テスト: 45件（全パス）

#### 16.2.6 問い→主張分解 (§3.3.1) ✅
- [x] **原子主張への分解**
  - スキーマ: `claim_id`, `text`, `expected_polarity`, `granularity`
  - LLMまたはルールベースでの分解ロジック
  - 実装: `src/filter/claim_decomposition.py`
    - `ClaimDecomposer` クラス（LLM/ルールベース両対応）
    - `AtomicClaim` データ構造（§3.3.1スキーマ準拠）
    - `ClaimPolarity`, `ClaimGranularity`, `ClaimType` 列挙型
  - MCPツール: `decompose_question`
    - 入力: `question`, `use_llm?`, `use_slow_model?`
    - 出力: `{claims[], decomposition_method, success}`
    - **注意**: `llm_extract`とは入力形式が異なる（passages[] vs question: string）ため独立ツールとして実装
  - テスト: 36件（全パス）

#### 16.2.7 Chain-of-Density圧縮 (§3.3.1) ✅
- [x] **要約密度の向上**
  - 全主張に深いリンク・発見日時・抜粋を必須付与
  - 圧縮と引用の厳格化
  - 実装: `src/report/chain_of_density.py`
    - `ChainOfDensityCompressor` - 反復的密度向上
    - `CitationInfo` - 必須引用情報（deep_link, discovered_at, excerpt）
    - `DenseClaim` - 引用完全性検証付き主張
    - LLM/ルールベース両対応
  - MCPツール: `compress_with_chain_of_density`
  - テスト: 30件（全パス、§7.1準拠）

---

### 16.3 信頼度・校正強化 (§3.3.4, §4.6.1) 🟡

#### 16.3.1 校正ロールバック (§4.6.1) ✅
- [x] **デグレ検知**
  - Brierスコア悪化の検出（5%閾値超過で検知）
  - 実装: `CalibrationHistory.check_degradation()`
- [x] **直近パラメータへのロールバック**
  - 校正パラメータ履歴の保持（最大10件/ソース）
  - 自動ロールバック機構（デグレ検知時に自動発動）
  - 手動ロールバック対応（バージョン指定可）
  - 実装: `src/utils/calibration.py`
    - `CalibrationHistory` クラス
    - `RollbackEvent` データ構造
    - `Calibrator.rollback()` / `rollback_to_version()`
  - MCPツール: `rollback_calibration`, `get_calibration_history`, `get_rollback_events`, `get_calibration_stats`
  - テスト: 61件（全パス）

#### 16.3.2 評価データ永続化・取得 (§4.6.1) ✅
- [x] **評価データの永続化**
  - SQLiteスキーマ拡張（`calibration_evaluations`テーブル）
  - 評価結果のDB保存機能
- [x] **評価データ取得機能**
  - 評価履歴の構造化データ返却
  - 信頼度-精度曲線用ビンデータ返却
- [x] **MCPツール**
  - `save_calibration_evaluation`: 評価実行・保存
  - `get_calibration_evaluations`: 評価履歴取得
  - `get_reliability_diagram_data`: ビンデータ取得
  - `add_calibration_sample`: フィードバック送信（Cursor AI→Lancet）
  - `get_calibration_stats`: 校正状態確認
  - `rollback_calibration`: ロールバック実行
- [x] **責任分界準拠のリファクタ**
  - `generate_report` → `get_report_materials`（素材提供のみ）
  - `get_evidence_graph`: エビデンスグラフ直接参照
- **注意**: レポート生成はCursor AIの責任（§4.6.1責任分界に準拠）
- **テスト**: 113件（全パス）

---

### 16.4 プロセス管理 (§4.2) ✅

#### 16.4.1 プロセスライフサイクル ✅
- [x] **ブラウザインスタンス破棄**
  - タスク完了ごとのKill
  - メモリリーク防止
  - 実装: `src/utils/lifecycle.py` (ProcessLifecycleManager, cleanup_task)
  - BrowserFetcherへの統合: リソース登録と自動クリーンアップ
- [x] **LLMプロセス破棄**
  - Ollamaコンテキスト解放
  - 実装: `src/utils/lifecycle.py` (OLLAMA_SESSION リソースタイプ)
  - `src/filter/llm.py` (OllamaClient.unload_model, cleanup_llm_for_task)
  - 設定: `unload_on_task_complete` オプション追加
  - テスト: 29件（全パス）

---

### 16.5 補助OSS (§5.1.1) 🟢

#### 16.5.1 PDF構造解析
- [ ] **GROBID統合**
  - 参考文献・セクション構造の抽出強化

#### 16.5.2 ベクトル検索
- [ ] **faiss-gpu**
  - 大規模コーパス時の高速検索
- [ ] **sqlite-vec/hnswlib**
  - 近傍検索の強化

#### 16.5.3 Privoxy
- [ ] **Tor経由DNS解決**
  - DNSリーク防止のためのPrivoxy設定

---

### 16.6 受け入れ基準対応 (§7) 🔴

#### 16.6.1 未測定メトリクス
以下の受け入れ基準は測定基盤が未整備：
- [x] `IPv6成功率≥80%` - IPv6ConnectionManager.metrics.ipv6_success_rateで測定可能 ✅
- [x] `DNSリーク検出0件` - DNSPolicyManager.metrics.leaks_detectedで測定可能 ✅
- [x] `プロファイル健全性チェック成功率≥99%` - 監査機能実装済み
- [x] `自動修復成功率≥90%` - 修復機能実装済み
- [x] `v4↔v6自動切替成功率≥80%` - IPv6ConnectionManager.metrics.switch_success_rateで測定可能 ✅

#### 16.6.2 E2Eテスト前提条件
E2Eテストを有効に実施するための前提：
- [x] プロファイル健全性監査の基本実装 ✅
- [x] セッション移送ユーティリティ ✅
- [x] sec-fetch-*ヘッダー整合 ✅
- [x] sec-ch-ua*ヘッダー ✅
- [x] ブラウザ経路アーカイブ保存 ✅
- [x] プロセスライフサイクル管理 ✅

---

### 16.7 半自動運用UX改善 (§2, §3.6) ✅

**完了**: 認証待ち情報がget_exploration_statusに統合され、Cursor AIが
ユーザーに判断を仰ぐタイミングを適切に認識できるようになった。

#### 16.7.1 認証待ち情報のステータス統合 ✅
- [x] **`get_exploration_status`への認証待ち情報追加**
  - `authentication_queue.pending_count`: 認証待ち総数
  - `authentication_queue.high_priority_count`: 高優先度（一次資料）の数
  - `authentication_queue.domains`: 認証待ちドメイン一覧
  - `authentication_queue.oldest_queued_at`: 最古のキュー時刻
  - `authentication_queue.by_auth_type`: 認証タイプ別カウント
  - 実装: `src/research/state.py` (ExplorationState.get_status, _get_authentication_queue_summary)
  - 実装: `src/utils/notification.py` (InterventionQueue.get_authentication_queue_summary)
  - 目的: Cursor AIが探索状況確認時に認証待ちを認識し、ユーザーに判断を仰げる

#### 16.7.2 三者責任分界の明確化 ✅
- [x] **`requirements.md` §3.6.1 への追記**
  - 三者責任分界テーブル（既存）
  - authentication_queue詳細フィールドの説明
  - 閾値アラートの説明
- [x] **優先度決定ロジックの明記**
  - デフォルト: ソース種別から推定（一次資料=high、二次資料=medium、その他=low）
  - `execute_subquery`のオプションでCursor AIが明示指定可能

#### 16.7.3 認証待ち閾値アラート ✅
- [x] **認証待ち数に応じた警告レベル**
  - `[warning]`: 認証待ち≥3件
  - `[critical]`: 認証待ち≥5件 または 高優先度≥2件
  - `get_exploration_status`の`warnings`配列に含める
  - 実装: `src/research/state.py` (_generate_auth_queue_alerts)
- [x] **探索ブロック検知**
  - 認証待ちにより一次資料アクセスがブロックされている場合の明示

#### 16.7.4 認証フロー改善 ✅
- [x] **`execute_subquery`戻り値への認証待ち情報追加**
  - `auth_blocked_urls`: 認証待ちでブロックされたURL数
  - `auth_queued_count`: 今回キューに追加された数
  - 実装: `src/research/executor.py` (SubqueryResult, _fetch_and_extract)
  - Cursor AIが即座に認識し、次のアクションを判断可能
- [x] **`FetchResult`の認証待ち理由の詳細化**
  - `auth_type`: cloudflare/captcha/turnstile/hcaptcha/login
  - `estimated_effort`: 認証の推定難易度（low/medium/high）
  - 実装: `src/crawler/fetcher.py` (FetchResult, _estimate_auth_effort)

---

### 16.8 タイムライン機能（§3.4, §7） ✅

**目的**: 重要主張ごとに初出/更新/訂正/撤回のタイムラインを付与
**受け入れ基準**: タイムライン付与率≥90%（§7）

#### 16.8.1 主張タイムライン構築
- [x] `ClaimTimeline`クラス（`src/filter/claim_timeline.py`）
  - イベント種別: first_appeared/updated/corrected/retracted/confirmed
  - データ: timestamp, source_url, evidence_fragment_id, wayback_snapshot_url
  - 信頼度調整（撤回ペナルティ、確認ボーナス）
  - 実装: `ClaimTimeline`, `TimelineEvent`, `TimelineEventType`, `ClaimTimelineManager`
- [x] Wayback差分との連携（Phase 12.4 WaybackExplorer統合）
  - `integrate_wayback_result()`: Wayback結果からタイムライン自動構築
  - first_appeared/updated イベントの自動検出
- [x] タイムライン付与率メトリクス（`src/utils/metrics.py`）
  - 既存の`TIMELINE_COVERAGE`と`claims_with_timeline`を活用
  - `get_timeline_coverage()`: タスク別カバレッジ算出
- [x] レポートへのタイムライン出力（`src/report/generator.py`）
  - Markdownレポート: 撤回/訂正警告、主要主張のタイムライン表示
  - JSONレポート: タイムライン統計情報を含む
  - `get_report_materials()`: タイムラインカバレッジ率を返却
- テスト: 47件（全パス、§7.1準拠）

---

### 16.9 検索経路の再設計（SearXNG廃止→直接ブラウザ検索） 🔴🔴 最優先

#### 背景と問題

**現状の設計（SearXNG経由）の技術的欠陥**:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Lancet       │ →  │ SearXNG      │ →  │ DuckDuckGo   │
│              │    │ (サーバー    │    │ 等           │
│ Cookie: なし │    │  サイド)     │    │              │
│ 指紋: なし   │    │ Cookie: なし │    │ → bot判定 → │
│              │    │ 指紋: なし   │    │ → CAPTCHA   │
└──────────────┘    └──────────────┘    └──────────────┘
                           │
                           ▼
                    手動介入が効かない
                    （Cookie移送不可）
```

1. **SearXNGはサーバーサイドで動作**: ユーザーのCookie/指紋を使用できない
2. **bot検知されやすい**: Cookie/指紋なしの素のHTTPリクエスト
3. **CAPTCHA解決が効かない**: ユーザーがブラウザでCAPTCHA解決しても、SearXNGにCookieは渡らない
4. **§3.6.1手動介入の前提が崩壊**: 検索エンジンに対するセッション転送が技術的に不可能
5. **抗堅性（§4.3）との矛盾**: 検索と取得で抗堅性設計が分断

**根本原因**: SearXNGは「便利」だったが、抗堅性を犠牲にする設計だった。

#### 目的

**検索経路を直接ブラウザ検索に一本化し、抗堅性を確保する。**

- 検索も取得も同じブラウザ経由で実行
- Cookie/指紋の一貫性を維持
- CAPTCHA発生時に手動介入が効く
- セッション転送（§3.1.2）が検索にも適用可能

#### あるべき姿（技術的にベスト）

```
┌──────────────┐    ┌──────────────┐
│ Lancet       │ →  │ Playwright   │ → DuckDuckGo等
│ (直接検索)   │    │ (ブラウザ)   │
│              │    │              │
│              │    │ Cookie: あり │
│              │    │ 指紋: あり   │    → 人間らしい
│              │    │              │    → CAPTCHA時は手動解決可
└──────────────┘    └──────────────┘
        │                  │
        ▼                  ▼
   検索結果パーサー   セッション転送（§3.1.2）
   (BeautifulSoup)    が検索にも適用可能
```

---

#### 要件定義書（requirements.md）修正

**§3.2 エージェント実行機能（Python）**:

```markdown
【旧】
- 検索エンジン統合: ローカルで稼働するSearXNG（メタ検索エンジン）に対しクエリを送信し、結果を取得する。

【新】
- 検索エンジン統合: Playwright経由で検索エンジンを直接検索する。
  - ユーザーのブラウザプロファイル（Cookie/指紋）を使用し、人間らしい検索を実現
  - 対応エンジン: DuckDuckGo, Google, Bing, mojeek（検索結果パーサー実装）
  - CAPTCHA発生時は手動介入フロー（§3.6.1）に移行し、解決後に検索を継続
  - セッション転送（§3.1.2）が検索にも適用され、抗堅性を確保

【廃止】SearXNG:
- 理由: サーバーサイドで動作するため、ユーザーのCookie/指紋を使用できない。
  bot検知されやすく、CAPTCHA発生時の手動介入（§3.6.1）が技術的に効かない。
  抗堅性（§4.3）の設計意図と矛盾するため廃止。
```

**§3.1.2 セッション移送ユーティリティ 追記**:

```markdown
【追記】
- 検索への適用: 検索も取得もブラウザ経由で実行するため、セッション移送が全経路で有効。
  検索エンジンでCAPTCHA解決後のセッションは、同一エンジンへの後続検索で再利用可能。
```

**§4.3 抗堅性・ステルス性 追記**:

```markdown
【追記】
- 検索経路の一本化: 検索も取得も同じブラウザ経由で実行し、抗堅性設計を一貫させる。
  サーバーサイドのメタ検索エンジン（SearXNG等）は使用しない。
```

---

#### 影響範囲

**変更が必要なファイル（検索部分のみ）**:

| ファイル | 変更内容 | 工数 |
|---------|---------|------|
| `src/search/browser_search_provider.py` | **新規作成**: Playwright経由の検索 | 大 |
| `src/search/search_parsers.py` | **新規作成**: 検索結果HTMLパーサー | 大 |
| `src/search/searxng.py` | 廃止予定マーク、後方互換維持 | 小 |
| `src/search/searxng_provider.py` | 廃止予定マーク | 小 |
| `src/search/provider.py` | BrowserSearchProvider登録 | 小 |
| `src/search/__init__.py` | エクスポート変更 | 小 |
| `src/search/engine_config.py` | パーサー設定追加 | 中 |
| `tests/test_browser_search.py` | **新規作成**: ユニットテスト | 中 |
| `tests/test_search_parsers.py` | **新規作成**: パーサーテスト | 中 |
| `tests/test_e2e.py` | 検索テスト修正 | 小 |
| `podman-compose.yml` | SearXNGコンテナ削除（最終段階） | 小 |
| `requirements.md` | §3.2, §3.1.2, §4.3 修正 | 小 |

**変更不要（インターフェース維持）**:

| ファイル | 理由 |
|---------|------|
| `src/mcp/server.py` | `search_serp()`インターフェース維持 |
| `src/scheduler/jobs.py` | 同上 |
| `src/research/executor.py` | 同上 |
| `src/research/refutation.py` | 同上 |
| `src/search/ab_test.py` | 同上 |
| `src/main.py` | 同上 |
| その他50,000行 | 検索以外は影響なし |

---

#### 実装タスク

**Phase 16.9.1: プロトタイプ検証** ✅
- [x] DuckDuckGo 1エンジンでプロトタイプ実装
- [x] Playwright経由の検索動作確認
- [x] CAPTCHA発生→手動解決→検索継続のフロー検証（InterventionManager連携実装済み）
- [x] セッション転送が効くことを確認（BrowserSearchSession実装済み）

**Phase 16.9.2: BrowserSearchProvider実装** ✅
- [x] `BrowserSearchProvider` クラス
  - `BaseSearchProvider` 継承
  - Playwrightセッション管理
  - ブラウザプロファイル使用（CDP接続対応）
  - CAPTCHA検知→InterventionQueue連携
- [x] `search(query, options) -> SearchResponse`
  - エンジン別URL構築
  - 検索実行
  - 結果パース
  - セッション情報保存

**Phase 16.9.3: 検索結果パーサー実装** ✅
- [x] `SearchResultParser` 基底クラス（`BaseSearchParser`）
- [x] `DuckDuckGoParser` - DDG結果パース
- [x] `GoogleParser` - Google結果パース
- [x] `MojeekParser` - mojeek結果パース
- [x] `QwantParser`, `BraveParser` - 追加エンジン対応
- [x] パーサーレジストリ（エンジン→パーサー対応）
- [x] セレクタ外部化（`config/search_parsers.yaml`）
- [x] AI修正用診断メッセージ設計

**Phase 16.9.4: 統合・移行** ✅
- [x] `SearchProviderRegistry` にBrowserSearchProvider登録
- [x] デフォルトプロバイダをBrowserSearchProviderに変更（`search.use_browser`フラグ）
- [x] `searxng.py`, `searxng_provider.py` を廃止予定マーク
- [x] 新規テスト追加（53件全パス）
- [x] 全テスト回帰なし（2097件パス）

**Phase 16.9.5: SearXNG完全廃止（最終段階）** ✅
- [x] SearXNGコンテナ削除（podman-compose.yml）
- [x] SearXNG関連コード削除
  - `src/search/searxng.py` から `SearXNGClient` クラス削除
  - `src/search/searxng_provider.py` 削除
  - `config/searxng/` ディレクトリ削除
  - `tests/conftest.py` から SearXNG モック削除
  - `tests/test_search.py` から `TestSearXNGClient`, `TestSearchSerp` 削除
- [x] ドキュメント更新

**Phase 16.9.6: SearXNG残存コード完全削除** ✅ 
- [x] `config/engines.yaml`: `searxng:`セクション削除、エンジンポリシーをルートレベルに移動
- [x] `src/search/engine_config.py`: `SearXNGSettingsSchema`クラス削除、`get_searxng_*`メソッド削除
- [x] `scripts/dev.sh`: SearXNG起動メッセージ・環境変数削除
- [x] Google/Bing: `disabled: true`削除、低重み（priority=10, weight=0.1）でlastmile運用に変更
- [x] テスト修正: `test_engine_config.py`, `test_search_provider.py`, `test_sec_fetch.py`
- [x] コメント整理: 全ファイルからSearXNG言及を削除
- [x] 静的解析: `grep -ri "searxng" src/ tests/ config/ scripts/` で残存ゼロを確認
- [x] 全テストパス確認

---

#### テスト計画

**ユニットテスト（モック使用）** ✅:
- [x] `test_browser_search_provider.py` (22テスト)
  - `test_search_success`: 基本検索
  - `test_captcha_detection`: CAPTCHA検知
  - `test_search_timeout`: タイムアウト処理
  - `test_health_status_*`: ヘルスステータス検証
  - `test_session_*`: セッション管理
- [x] `test_search_parsers.py` (31テスト)
  - `test_duckduckgo_parser_*`: DDGパース（HTMLフィクスチャ使用）
  - `test_mojeek_parser_*`: mojeekパース
  - `test_empty_html`: 空HTML耐性
  - `test_malformed_html`: 不正HTML耐性
  - `test_captcha_detection_patterns`: CAPTCHAパターン検知
  - `test_source_classification`: ソース分類

**E2Eテスト（低リスクIP環境で実施）** → Phase 16.10へ:
- [x] `test_browser_search_e2e`: 実際の検索動作 ✅ **手動検証完了（2024-11-28）**
- [ ] `test_captcha_resolution_flow`: CAPTCHA解決フロー（今回はCAPTCHA発生せず）
- [ ] `test_search_then_fetch`: 検索→取得の一貫性

**手動E2E検証結果（2024-11-28）**:

| 項目 | 結果 | 備考 |
|------|------|------|
| CDP接続 | ✅ 成功 | Windows Chrome 142.0へ接続 |
| DuckDuckGo検索 | ✅ 成功 | 5件取得、3.4秒、bot検知なし |
| パーサー | ✅ 成功 | 10件パース → 5件返却 |
| Stealth偽装 | ✅ 機能 | bot検知されず検索成功 |
| セッション管理 | ✅ 機能 | BrowserSearchSession作成、CAPTCHA=0 |
| CAPTCHA誘導 | ⏳ 未検証 | 今回はCAPTCHA発生せず |
| セッション転送 | ⏳ 未検証 | 検索のみのため未使用 |

**AIエージェントによるWSL2からの検証環境セットアップ手順**:

1. **専用Chromeプロファイル作成**（Googleアカウント未ログイン推奨）

2. **⚠️ 重要: すべてのChromeを完全終了**
   ```powershell
   Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
   ```
   > **注意**: 既存のChromeプロセスが残っていると、新規起動が既存インスタンスに統合され、
   > リモートデバッグポートが開かない。タスクマネージャーでchromeプロセスが0であることを確認。

3. **Chromeをリモートデバッグモードで起動**（PowerShell）:
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 "--user-data-dir=C:\Users\<USERNAME>\AppData\Local\Google\Chrome\User Data" --profile-directory=Profile-Research
   ```
   > **注意**: `--remote-debugging-address=0.0.0.0`は不要。ポートプロキシで対応する。

4. **起動確認**（Windows側で実行）:
   ```powershell
   curl http://localhost:9222/json/version
   ```
   → JSONが返れば成功。失敗する場合は手順2に戻る。

5. **ポートフォワーディング設定**（初回のみ、管理者PowerShell）:
   ```powershell
   # WSL2ゲートウェイIP確認（WSL2側で実行: ip route | grep default | awk '{print $3}'）
   # 例: 172.29.224.1
   
   # ポートプロキシ設定
   netsh interface portproxy add v4tov4 listenaddress=<WSL2_GATEWAY_IP> listenport=9222 connectaddress=127.0.0.1 connectport=9222
   
   # ファイアウォールルール
   New-NetFirewallRule -DisplayName "Chrome Debug WSL2" -Direction Inbound -LocalPort 9222 -Protocol TCP -Action Allow
   ```

6. **環境変数設定**（初回のみ、`.env`ファイル）:
   ```bash
   # .env.example を .env にコピーして編集
   cp .env.example .env
   # WSL2ゲートウェイIPを設定
   echo "LANCET_BROWSER__CHROME_HOST=<WSL2_GATEWAY_IP>" >> .env
   ```
   ※ `settings.yaml`は変更不要（`.env`が優先される）

7. **コンテナ再起動**（初回のみ、`.env`反映）: `./scripts/dev.sh down && ./scripts/dev.sh up`

8. **テスト実行**: `podman exec lancet python tests/scripts/verify_browser_search.py`

**トラブルシューティング**:

| 症状 | 原因 | 対処 |
|------|------|------|
| `curl localhost:9222` が失敗 | 既存Chromeが残っている | 手順2ですべてのChromeを終了 |
| `netstat`で127.0.0.1:9222が見えない | 同上 | 同上 |
| WSL2から接続できない | ポートプロキシ未設定 | 手順5を実行 |
| Podmanから接続できない | `.env`未設定 or コンテナ未再起動 | 手順6,7を実行 |

---

#### 成功基準

| 基準 | 目標 |
|------|------|
| **CAPTCHA対応** | 手動解決後の検索継続率 100% |
| **セッション転送** | 検索でもセッション再利用が機能 |
| **抗堅性** | 検索・取得で一貫したCookie/指紋使用 |
| **後方互換** | `search_serp()`インターフェース維持 |
| **テスト** | 既存テスト + 新規テスト全パス |

---

#### ロールバック計画

SearXNGは最終段階まで残すため、問題発生時は以下で対応：

1. `SearchProviderRegistry` のデフォルトを`SearXNGProvider`に戻す
2. `config/settings.yaml` に `search.use_browser: false` フラグ追加
3. フラグに応じてプロバイダを切り替え

---

### 16.10 E2Eテスト設計・実装 ✅

> **依存**: Phase 16.9（検索経路の再設計）完了後に実施
> **背景**: Phase 14.3.2 参照

#### 16.10.1 テスト基盤設計 ✅

##### E2Eテストの技術方針（pytest vs スクリプト）

| 分類 | 方式 | 配置 | 実行方法 | 用途 |
|------|------|------|----------|------|
| **自動E2E** | pytest | `tests/test_e2e_*.py` | `pytest -m e2e` | モック可能、CI実行可 |
| **手動検証** | スクリプト | `tests/scripts/verify_*.py` | `python tests/scripts/verify_*.py` | 対話的、人が実行 |

**pytest方式を選ぶ基準**:
- 外部サービスをモック可能
- 対話的操作が不要
- CI/CDで自動実行したい
- フィクスチャ・アサーションを再利用したい

**スクリプト方式を選ぶ基準**:
- CAPTCHA解決など手動介入が必須
- 実行環境（IP、Chromeプロファイル）に強く依存
- 実行タイミングを人が制御する必要がある
- CIから除外すべき（IP汚染リスク）

##### テスト分類ガイドライン ✅

- [x] **unit/integration/e2eの境界定義**（`tests/conftest.py`冒頭のdocstring）
  - unit: 単一クラス/関数、外部依存なし（<1s/test）
  - integration: 複数コンポーネント連携、外部はモック（<5s/test）
  - e2e: 実サービス使用（低リスクIP環境限定）
- [x] **各マーカーの意味と使用基準**
  - `@pytest.mark.unit`: デフォルト実行、高速（マーカーなしテストは自動付与）
  - `@pytest.mark.integration`: デフォルト実行、中速
  - `@pytest.mark.e2e`: デフォルト除外、`pytest -m e2e`で明示実行
  - `@pytest.mark.slow`: デフォルト除外、`pytest -m slow`で明示実行

##### リスクベースマーカー ✅

- [x] **追加マーカー実装**（`tests/conftest.py`, `pyproject.toml`）
  - `@external`: 外部サービス使用（Mojeek, Qwant等ブロック耐性高）
  - `@rate_limited`: レート制限厳しい（DuckDuckGo, Google等）
  - `@manual`: 人手介入必須（CAPTCHA解決等）
- [x] **pyproject.toml設定**
  - デフォルト: `addopts = "-m 'not e2e and not slow'"`
  - E2E実行: `pytest -m e2e`
  - 全テスト: `pytest -m ""`
- [x] **全テストファイルへのpytestmark付与**（2024-11-28完了）
  - 43ファイルにファイルレベルの`pytestmark`を追加
  - unit: 1929テスト / integration: 123テスト / e2e: 17テスト
  - テスト実行スクリプト `scripts/test.sh` 作成

##### E2E実行環境 ✅

- [x] **低リスクIP環境の要件**
  - 自宅回線（固定IP推奨）
  - VPN（信頼性の高いもの）
  - 検索エンジンからブロックされていないIP
- [x] **実行前チェックリスト**
  - IP確認（`curl ifconfig.me`）
  - エンジン健全性確認（手動で1件検索）
  - Chromeプロファイル準備

#### 16.10.2 pytest E2E（自動実行可能） ✅

- [x] **`test_e2e.py`**: 包括的E2Eテスト（17テスト）
  - `TestSearchToReportPipeline`: 検索→取得→抽出→レポート（4テスト）
  - `TestAuthenticationQueueFlow`: 認証待ちキュー（8テスト）
  - `TestInterventionManagerFlow`: 手動介入フロー（2テスト）
  - `TestCompleteResearchFlow`: 完全リサーチワークフロー（1テスト）
  - `TestLLMIntegration`: Ollama連携（2テスト）

#### 16.10.3 手動検証スクリプト（tests/scripts/） ✅

対話的操作や特殊な実行環境が必要なテスト。pytestではなくスタンドアロンスクリプトとして実装。

| スクリプト | 検証内容 | 仕様 | 状態 |
|-----------|----------|------|------|
| `verify_browser_search.py` | CDP接続、検索動作、Stealth、セッション管理 | §3.2 | ✅ 完了 |
| `verify_captcha_flow.py` | CAPTCHA検知→通知→手動解決→継続 | §3.6.1 | ✅ 完了 |
| `verify_session_transfer.py` | ブラウザ→HTTPクライアント間のセッション移送 | §3.1.2 | ✅ 完了 |
| `verify_search_then_fetch.py` | 検索→取得の一貫性（同一セッション維持） | §3.2 | ✅ 完了 |
| `verify_network_resilience.py` | 回復力、IPv6、DNSリーク、304活用 | §7 | ✅ 完了 |
| `verify_profile_health.py` | プロファイル健全性、自動修復 | §7 | ✅ 完了 |

**§7受け入れ基準とのマッピング**:

| 受け入れ基準 | 数値目標 | 検証スクリプト |
|-------------|---------|---------------|
| スクレイピング成功率 | ≥95% | `verify_search_then_fetch.py` |
| 回復力 | ≥70% | `verify_network_resilience.py` |
| CAPTCHA検知 | 100% | `verify_captcha_flow.py` |
| 通知成功率 | ≥99% | `verify_captcha_flow.py` |
| 前面化成功率 | ≥95% | `verify_captcha_flow.py` |
| 304活用率 | ≥70% | `verify_network_resilience.py`, `verify_session_transfer.py` |
| Referer整合率 | ≥90% | `verify_session_transfer.py` |
| IPv6成功率 | ≥80% | `verify_network_resilience.py` |
| DNSリーク | 0件 | `verify_network_resilience.py` |
| 健全性チェック | ≥99% | `verify_profile_health.py` |
| 自動修復 | ≥90% | `verify_profile_health.py` |

**実行方法**:
```bash
# Chromeをリモートデバッグモードで起動（Windows側）
# → IMPLEMENTATION_PLAN.md 16.9「検証環境セットアップ手順」参照

# スクリプト実行
podman exec lancet python tests/scripts/verify_browser_search.py
podman exec lancet python tests/scripts/verify_network_resilience.py
```

#### 16.10.4 モック化戦略（CI安定化） 🟢

将来の拡張として検討。現時点ではE2Eテストは手動実行を前提とする。

- [ ] **VCR/レコード再生方式の導入**
  - `tests/fixtures/vcr_cassettes/`に外部レスポンス保存
  - 検索結果HTMLのスナップショット
  - Ollamaレスポンスのスナップショット
- [ ] **フォールバック機構**
  - `LANCET_USE_MOCK_SERVICES=1`でモック切替
  - CIではモック使用、ローカルE2Eでは実サービス

#### 16.10.5 その他 🟢

- [ ] ミューテーションテスト（月次実施予定）

---

### 16.11 ヒューマンライク操作強化 ✅ (§4.3.4)

**目的**: bot検知回避のためのより自然な操作パターンの実装。

**設計原則**:
- ステルス機能（`stealth.py`）から分離し、操作パターンを専門に扱う
- 設定外部化により調整可能に

#### 16.11.1 マウス軌跡自然化
- [x] `MouseTrajectory`クラス: Bezier曲線による自然な軌跡生成
  - 開始点・終了点間の制御点をランダム化
  - 移動速度の加減速（始点で加速、終点で減速）
  - 微細なジッター（ノイズ）の付与
- [x] 実装: `src/crawler/human_behavior.py`

#### 16.11.2 タイピングリズム
- [x] `HumanTyping`クラス: 自然なタイピング模倣
  - キー間遅延: ガウス分布（平均100ms, σ=30ms）
  - 句読点後の長い間（200-400ms）
  - 稀なタイポ模倣（1%確率でバックスペース＋再入力）
- [x] 実装: `src/crawler/human_behavior.py`

#### 16.11.3 スクロール慣性
- [x] `InertialScroll`クラス: 慣性付きスクロール
  - イージング関数（ease-out）による自然な減速
  - スクロール量のばらつき
  - 中間停止の確率的挿入
- [x] 実装: `src/crawler/human_behavior.py`

#### 16.11.4 設定外部化
- [x] `config/human_behavior.yaml`: パラメータ外部化
  - マウス速度範囲、ジッター幅
  - タイピング速度分布
  - スクロールイージング係数
- [x] ホットリロード対応

**成果物**:
- `src/crawler/human_behavior.py` ✅
- `config/human_behavior.yaml` ✅
- テスト: `tests/test_human_behavior.py` ✅

---

### 16.12 Waybackフォールバック強化 ✅ (§3.1.6)

**目的**: 403/CAPTCHAブロック時にWayback Machineから代替コンテンツを取得。

**既存**: `src/crawler/wayback.py` - 基本的なWayback取得実装済み

#### 16.12.1 自動フォールバック統合 ✅
- [x] `fetcher.py`への統合
  - 403/CAPTCHA検知時に自動Wayback参照
  - 最新スナップショット優先、なければ直近3件を試行
  - フォールバック成功率をドメインポリシーに反映
- [x] `FetchResult`拡張
  - `is_archived: bool`: アーカイブからの取得か
  - `archive_date: datetime | None`: アーカイブ日時
  - `archive_url: str | None`: 元のWayback URL
  - `freshness_penalty: float`: 鮮度ペナルティ（0.0-1.0）

#### 16.12.2 差分検出強化 ✅
- [x] 見出し・要点レベルの差分検出
  - 現行版とアーカイブ版の見出し比較
  - 大幅な差分がある場合はタイムラインに明示
  - `ArchiveDiffResult`データクラス
  - `compare_with_current()`メソッド
- [x] 信頼度スコアへの鮮度ペナルティ適用
  - `apply_freshness_penalty()`関数
  - タイムライン新イベントタイプ: CONTENT_MODIFIED, CONTENT_MAJOR_CHANGE, ARCHIVE_ONLY

**成果物**:
- `src/crawler/fetcher.py`（拡張）✅
- `src/crawler/wayback.py`（拡張）✅
- `src/filter/claim_timeline.py`（拡張）✅
- テスト: `tests/test_wayback_fallback.py` ✅

---

### 16.13 検索エンジン多様化 ✅

**目的**: 検索エンジンの選択肢を増やし、ブロック耐性と情報多様性を向上。

**設計原則（Phase 16.9の教訓）**:
- すべての検索はBrowserSearchProvider経由（ブラウザ直接アクセス）
- サーバーサイドサービス禁止（SearXNG/公開SearXインスタンス等）
- 理由: Cookie/指紋使用不可、CAPTCHA解決不可、IP汚染リスク

#### 16.13.1 追加エンジン（ブラウザ経由のみ） ✅
- [x] `ecosia`: Bing再販、比較的緩い
  - `config/engines.yaml`: priority=4, weight=0.5
  - `config/search_parsers.yaml`: パーサー定義
  - 実装: `EcosiaParser` クラス
- [x] `metager`: ドイツ、ブロック耐性高い
  - priority=4, weight=0.4
  - 実装: `MetaGerParser` クラス
- [x] `startpage`: Google再販（プライバシー重視）
  - priority=5, weight=0.3
  - 実装: `StartpageParser` クラス

#### 16.13.2 パーサー実装 ✅
- [x] 各エンジンの検索結果パーサー
  - `EcosiaParser`: Bing互換セレクタ、CAPTCHA検知
  - `MetaGerParser`: ドイツ語/英語対応、リダイレクトURL処理
  - `StartpageParser`: Google互換セレクタ、プロキシURL処理
- [x] 実装: `src/search/search_parsers.py`（既存ファイルに追加）
- [x] 設定: `config/search_parsers.yaml`（3エンジン追加）
- [x] パーサーレジストリ更新（8エンジン対応）

#### 16.13.3 除外
- 公開SearXインスタンス（searx.be等）→ サーバーサイド問題のため除外
- `yandex`: 将来拡張として保留（優先度低）

#### 16.13.4 スキーマ拡張 ✅
- [x] `SearchParsersConfigSchema`: ecosia/metager/startpage フィールド追加
- [x] `ParserConfigManager._load_config()`: 新エンジンのパース対応

**成果物**:
- `config/engines.yaml`（更新: 3エンジン追加、operator_mapping拡張）
- `config/search_parsers.yaml`（更新: 3エンジン定義追加）
- `src/search/search_parsers.py`（更新: 3パーサークラス追加）
- `src/search/parser_config.py`（更新: スキーマ拡張）
- テスト: `tests/test_search_parsers.py`（拡張: 31テスト追加、計62件）
- HTMLフィクスチャ: `tests/fixtures/search_html/`（3ファイル追加）

---

## Phase 17: 保守性・拡張性改善 ⏳

**目的**: 外部依存の変更に対する耐性向上と、将来の機能拡張を容易にするためのリファクタリング。

**重要**: リファクタタスクの完了基準は「**既存コードへの移行完了**」までを含む。
基盤実装のみで完了とせず、全呼び出し箇所が新しい抽象化を経由するまで継続すること。

---

### 17.1 プロバイダ抽象化 🔴

外部サービスへの直接依存を抽象化し、実装の切り替えを容易にする。
**完了基準**: Protocol/Registry実装 + 全呼び出し箇所のProvider経由への移行。

#### 17.1.1 SearchProvider抽象化 ✅
- [x] `SearchProvider` プロトコル/ABC定義
  - `search(query, options) -> SearchResponse`
  - `get_health() -> HealthStatus`
- [x] `SearchResult`, `SearchResponse`, `SearchOptions` データクラス
- [x] `SearXNGProvider` 実装（現行コードのリファクタ）
- [x] `SearchProviderRegistry` プロバイダ登録・切替機構
  - プロバイダ登録/解除
  - デフォルトプロバイダ管理
  - フォールバック機構付き検索
- [x] `search_serp`関数への統合（`use_provider=True`がデフォルト）
- [x] テスト: 59件（全パス、§7.1準拠）
- 実装: `src/search/provider.py`, `src/search/searxng_provider.py`
- [x] **既存コードのProvider経由への移行（完了）**
  - `src/mcp/server.py`: `from src.search import search_serp`
  - `src/scheduler/jobs.py`: `from src.search import search_serp`
  - `src/research/refutation.py`: `from src.search import search_serp`
  - `src/search/ab_test.py`: `from src.search import search_serp`
  - `src/main.py`: `from src.search import search_serp`
  - `src/research/executor.py`: `from src.search import search_serp`
  - `src/search/__init__.py`: エクスポート整理完了

#### 17.1.2 LLMProvider抽象化 ✅
- [x] `LLMProvider` プロトコル/ABC定義
  - `generate(prompt, options) -> LLMResponse`
  - `chat(messages, options) -> LLMResponse`
  - `embed(texts) -> EmbeddingResponse`
  - `get_model_info(model) -> ModelInfo`
  - `list_models() -> list[ModelInfo]`
  - `get_health() -> LLMHealthStatus`
  - `unload_model(model) -> bool`
- [x] `LLMOptions`, `ChatMessage`, `LLMResponse`, `EmbeddingResponse`, `ModelInfo`, `LLMHealthStatus` データクラス
- [x] `OllamaProvider` 実装（現行コードのリファクタ）
- [x] `LLMProviderRegistry` プロバイダ登録・切替・フォールバック機構
- [x] 既存`llm.py`関数との後方互換性維持（OllamaClientラッパー）
- [x] **既存コードの移行完了**: `llm.py`が後方互換レイヤーとしてProvider内部使用
- [x] テスト: 62件（全パス、§7.1準拠）
- 将来の拡張候補: `LlamaCppProvider`, `VLLMProvider`
- 実装: `src/filter/provider.py`, `src/filter/ollama_provider.py`
- 影響範囲: `src/filter/llm.py`

#### 17.1.3 BrowserProvider抽象化 ✅
- [x] `BrowserProvider` プロトコル/ABC定義
  - `navigate(url, options) -> PageResult`
  - `execute_script(script) -> Any`
  - `get_cookies() -> list[Cookie]`
  - `set_cookies(cookies) -> None`
  - `take_screenshot(path, full_page) -> str | None`
  - `get_health() -> BrowserHealthStatus`
  - `close() -> None`
- [x] `BrowserOptions`, `PageResult`, `Cookie`, `BrowserHealthStatus` データクラス
- [x] `PlaywrightProvider` 実装（現行コードのリファクタ）
- [x] `UndetectedChromeProvider` 実装（現行コードのリファクタ）
- [x] `BrowserProviderRegistry` プロバイダ登録・切替・フォールバック機構
- [x] 既存`fetcher.py`との後方互換性維持（`use_provider`ポリシーオプション）
- [x] **既存コードの移行完了**: `fetcher.py`がProvider内部使用
- [x] テスト: 44件（全パス、§7.1準拠）
- 実装: `src/crawler/browser_provider.py`, `src/crawler/playwright_provider.py`, `src/crawler/undetected_provider.py`
- 影響範囲: `src/crawler/fetcher.py`

#### 17.1.4 NotificationProvider抽象化 ✅
- [x] `NotificationProvider` プロトコル/ABC定義
- [x] `NotificationResult`, `NotificationOptions`, `NotificationHealthStatus` データクラス
- [x] `LinuxNotifyProvider` 実装（notify-send）
- [x] `WindowsToastProvider` 実装（PowerShell UWP Toast）
- [x] `WSLBridgeProvider` 実装（WSL-Windows橋渡し）
- [x] `NotificationProviderRegistry` プロバイダ登録・切替・フォールバック機構
- [x] プラットフォーム自動検出と切替
- [x] 既存`InterventionManager.send_toast()`との後方互換性維持
- [x] **既存コードの移行完了**: `notification.py`がProvider内部使用
- [x] テスト: 74件（全パス、§7.1準拠）
- 実装: `src/utils/notification_provider.py`
- 影響範囲: `src/utils/notification.py`

---

### 17.2 設定・ポリシーの外部化 🟡

ハードコードされた設定やポリシーを外部設定化し、コード変更なしで調整可能にする。
**完了基準**: 外部設定ファイル + Manager実装 + 全ハードコード箇所の置換。

#### 17.2.1 ドメインポリシー完全外部化 ✅
- [x] `config/domains.yaml` への一元化（基盤実装）
  - 実装: `src/utils/domain_policy.py` (DomainPolicyManager)
  - pydanticモデルによるスキーマ定義・バリデーション
  - allowlist/graylist/denylist/cloudflare_sites/internal_search_templatesの統合管理
- [x] ホットリロード対応（再起動不要）
  - ファイル変更検知（watch_interval設定可能）
  - リロードコールバック機構
- [x] ポリシースキーマのバリデーション強化
  - TrustLevel/SkipReason列挙型
  - QPS/headful_ratio等の範囲バリデーション
  - ドメインパターンマッチング（glob/suffix対応）
- [x] 検索エンジン/サーキットブレーカ設定の外部化
  - `config/domains.yaml`: search_engine_policy, policy_bounds セクション追加
  - `SearchEnginePolicySchema`, `PolicyBoundsSchema` スキーマ追加
  - `get_search_engine_*()`, `get_circuit_breaker_*()`, `get_policy_bounds()` メソッド追加
- [x] 既存コードのDomainPolicyManager統合（完了）
  - `src/crawler/fetcher.py`: RateLimiter がドメイン別 QPS を Manager 経由で取得
  - `src/search/searxng.py`, `searxng_provider.py`: min_interval を Manager から取得
  - `src/crawler/site_search.py`: site_search_qps を Manager から取得
  - `src/utils/policy_engine.py`: DEFAULT_BOUNDS を遅延ロード化、config から取得
  - `src/search/circuit_breaker.py`: cooldown_min/max を Manager から取得
- テスト: 88件（全パス、§7.1準拠）

#### 17.2.2 検索エンジン設定の動的管理 ✅
- [x] `SearchEngineConfigManager` 実装（`src/search/engine_config.py`）
  - Pydanticスキーマによる設定バリデーション
  - ホットリロード対応（DomainPolicyManagerと同パターン）
  - エンジン/カテゴリ/演算子マッピング/直接ソースの一元管理
- [x] エンジン追加/削除のYAML変更のみ対応
  - `config/engines.yaml` の engines セクションで完結
  - コード変更不要でエンジン追加/削除/設定変更が可能
- [x] エンジン正規化ルール（operator_mapping）の外部化
  - `config/engines.yaml` の operator_mapping セクションで定義
  - エンジン別の演算子構文を設定可能
- [x] 既存コードの移行完了
  - `QueryOperatorProcessor`: SearchEngineConfigManager経由でoperator_mapping取得
  - `SearXNGProvider`: SearchEngineConfigManager経由でhost/timeout取得
  - `src/search/__init__.py`: エクスポート追加
- [x] テスト: 50件（全パス、§7.1準拠）

#### 17.2.3 ステルス設定の外部化
- [ ] User-Agent/ヘッダーパターンのYAML管理
- [ ] 指紋パラメータの設定ファイル化

---

### 17.3 汎用コンポーネントの抽出 🟡

特定用途に実装されているパターンを汎用化し、再利用可能にする。
**完了基準**: 汎用実装 + 既存の個別実装を汎用版に置換。

#### 17.3.1 汎用サーキットブレーカ
- [ ] `CircuitBreaker[T]` ジェネリック実装
  - 現状: エンジン専用の実装
- [ ] 任意のリソース（ドメイン、API、外部サービス）に適用可能
- [ ] 状態遷移のイベント発行

#### 17.3.2 汎用リトライ/バックオフ
- [ ] `RetryPolicy` 設定クラス
- [ ] デコレータ/コンテキストマネージャ形式
- [ ] 現行の個別実装を統一

#### 17.3.3 汎用キャッシュレイヤ 🟢

**目的**: 既存の個別キャッシュ実装を統一インターフェースで抽象化。

##### 17.3.3.1 抽象化
- [ ] `CacheProvider` プロトコル定義
  ```python
  class CacheProvider(Protocol[K, V]):
      def get(self, key: K) -> V | None: ...
      def set(self, key: K, value: V, ttl: int | None = None) -> None: ...
      def delete(self, key: K) -> bool: ...
      def exists(self, key: K) -> bool: ...
      def clear(self, pattern: str | None = None) -> int: ...
  ```
- [ ] `CacheConfig`データクラス
  - `max_size: int | None`: 最大エントリ数
  - `default_ttl: int`: デフォルトTTL（秒）
  - `eviction_policy: Literal["lru", "ttl"]`

##### 17.3.3.2 実装
- [ ] `SQLiteCache`: 既存SQLiteテーブルのラッパー
  - serp_cache, fetch_cache, embed_cache対応
  - TTL/サイズ制限の統一管理
- [ ] `CacheRegistry`: キャッシュプロバイダの登録・取得

##### 17.3.3.3 既存キャッシュの移行
- [ ] `serp_cache`（キー: 正規化クエリ＋エンジン, TTL=24h）
- [ ] `fetch_cache`（キー: URL＋ETag, TTL=7d）
- [ ] `embed_cache`/`rerank_cache`（キー: テキストハッシュ, TTL=7d）

**成果物**:
- `src/utils/cache.py`
- テスト: `tests/test_cache.py`

---

### 17.4 アーキテクチャ改善 🟢

将来の大規模拡張に備えた構造的改善（優先度低）。

#### 17.4.1 戦略パターンの適用
- [ ] 取得戦略（HTTP/Browser/Tor）のStrategy化
- [ ] 抽出戦略（HTML/PDF/OCR）のStrategy化
- [ ] 現状の条件分岐を戦略オブジェクトに置換

#### 17.4.2 イベント駆動アーキテクチャ
- [ ] 内部イベントバス導入
- [ ] パイプライン処理のイベントベース化
- [ ] プラグイン/フック機構の基盤

#### 17.4.3 依存性注入の強化
- [ ] DIコンテナ導入（例: `dependency-injector`）
- [ ] テスト時のモック注入簡易化
- [ ] コンポーネント間結合度の低減

---

### 17.5 外部依存の追従容易化 🟡

壊れやすい外部依存への対策を構造化する。

#### 17.5.1 バージョン追従スクリプト
- [ ] Chrome/Chromium バージョン検出と互換性チェック
- [ ] curl_cffi impersonate設定の自動更新検知
- [ ] SearXNGエンジン設定のdrift検出

#### 17.5.2 互換性テストスイート
- [ ] 外部サービス互換性の定期チェックテスト
- [ ] Cloudflare対策の動作確認テスト
- [ ] モデル出力形式の互換性テスト

### 17.6 テストの品質向上 🟡

すべてのテストが品質基準を満たす、意味のあるテストになっているか検証し、テストでカバーしていない重要な機能があるか確かめ、修正する。

#### 17.6.1 計画策定
- [ ] テストのリファクタリング計画を策定する

---

## Phase 18: 外部データソース統合 🟡

**目的**: 無料API/データソースを活用し、OSINT品質を向上。

**API vs 検索エンジンの違い**:
- 公式API（e-Stat, OpenAlex等）: 正当な利用として認められ、bot検知問題なし
- 検索エンジン: bot検知が厳しく、ブラウザ経由が必須

---

### 18.0 API仕様調査・ドキュメント化 🔴

**目的**: 実装前に各APIの仕様を調査し、実装可能性と制約を確認。

**前提**: このフェーズは18.1以降の実装に先立って完了する必要がある。

#### 18.0.1 調査項目

各APIについて以下を確認・ドキュメント化:

| 項目 | 内容 |
|------|------|
| **認証** | APIキー要否、取得方法、無料枠の制限 |
| **エンドポイント** | ベースURL、主要エンドポイント一覧 |
| **レート制限** | リクエスト/秒、日次上限、バースト許容 |
| **レスポンス形式** | JSON/XML、ページネーション方式、文字コード |
| **利用規約** | 商用利用可否、帰属表示要件、禁止事項 |
| **安定性** | API廃止リスク、バージョニングポリシー、SLA |
| **サンプル** | リクエスト/レスポンス例の収集 |

#### 18.0.2 日本政府API調査

- [ ] **e-Stat API**
  - appId登録手順
  - 統計表検索/データ取得のエンドポイント
  - レート制限（未公開の場合は実測）
- [ ] **法令API（e-Gov）**
  - 認証不要の確認
  - 法令検索/条文取得エンドポイント
- [ ] **国会会議録API**
  - 認証方式
  - 検索パラメータ仕様
- [ ] **gBizINFO API**
  - 認証方式（要APIキー？）
  - 法人検索エンドポイント
- [ ] **EDINET API**
  - 認証方式
  - 開示書類検索/取得エンドポイント

#### 18.0.3 学術API調査

- [ ] **OpenAlex API**
  - 認証不要、polite poolの仕様（mailto推奨）
  - Works/Authors/Institutionsエンドポイント
  - レート制限（10 req/s polite, 100 req/s with key）
- [ ] **Semantic Scholar API**
  - APIキー取得手順（推奨）
  - Paper/Author検索エンドポイント
  - レート制限
- [ ] **Crossref API**
  - polite pool仕様（mailto推奨）
  - Works検索/DOI解決エンドポイント
- [ ] **Unpaywall API**
  - email必須の確認
  - DOI→OAリンク取得エンドポイント

#### 18.0.4 エンティティAPI調査

- [ ] **Wikidata API**
  - 認証不要の確認
  - wbsearchentities/wbgetentitiesエンドポイント
  - SPARQL endpointの仕様
- [ ] **DBpedia SPARQL**
  - 認証不要の確認
  - SPARQLクエリ例の収集
  - 日本語DBpediaの状況

#### 18.0.5 成果物

- [ ] `docs/api_specifications/` ディレクトリ作成
  - `government_jp.md`: 日本政府API仕様まとめ
  - `academic.md`: 学術API仕様まとめ
  - `entity.md`: エンティティAPI仕様まとめ
- [ ] 各APIのサンプルリクエスト/レスポンス（JSON）
- [ ] 実装優先度の見直し（調査結果に基づく）

**完了基準**: 全APIの仕様がドキュメント化され、実装上の制約（認証、レート制限等）が明確になっていること。

---

### 18.1 日本政府・公的機関API統合 🔴

**目的**: 日本の公的データソースへの構造化アクセス。

#### 18.1.1 DataSourceProviderプロトコル
- [ ] `DataSourceProvider` プロトコル定義
  - `search(query, options) -> list[DataSourceResult]`
  - `get_metadata(id) -> DataSourceMetadata`
  - `get_content(id) -> DataSourceContent`
- [ ] `DataSourceResult`, `DataSourceMetadata` データクラス

#### 18.1.2 e-Stat API統合
- [ ] `EStatClient`: e-Stat APIクライアント
  - 統計表検索（getStatsList）
  - 統計データ取得（getStatsData）
  - メタ情報取得（getMetaInfo）
- [ ] 実装: `src/datasource/government_jp.py`

#### 18.1.3 法令API（e-Gov）統合
- [ ] `ElawsClient`: 法令API クライアント
  - 法令全文検索
  - 条文取得
  - 法令一覧取得
- [ ] 実装: `src/datasource/government_jp.py`

#### 18.1.4 国会会議録API統合
- [ ] `KokkaiClient`: 国会会議録 APIクライアント
  - 会議録検索
  - 発言者検索
- [ ] 実装: `src/datasource/government_jp.py`

#### 18.1.5 gBizINFO API統合
- [ ] `GBizClient`: gBizINFO APIクライアント
  - 法人基本情報取得
  - 認定・届出情報
- [ ] 実装: `src/datasource/government_jp.py`

#### 18.1.6 ResearchContext統合
- [ ] `get_research_context`で適用可能データソースを提案
  - クエリからエンティティ抽出（企業名→gBizINFO、法令→Elaws等）
  - 利用可能データソースのリスト化

**成果物**:
- `src/datasource/__init__.py`
- `src/datasource/government_jp.py`
- `config/datasources.yaml`
- テスト: `tests/test_government_jp.py`

---

### 18.2 学術API統合 🔴

**目的**: 学術論文メタデータと引用ネットワークへのアクセス。

#### 18.2.1 OpenAlex API統合
- [ ] `OpenAlexClient`: OpenAlex APIクライアント
  - Works検索（論文メタデータ）
  - Authors検索
  - Institutions検索
  - Cited_by/References取得
- [ ] 実装: `src/datasource/academic.py`

#### 18.2.2 Semantic Scholar API統合
- [ ] `SemanticScholarClient`: S2 APIクライアント
  - 論文検索
  - 引用/被引用ネットワーク
  - 著者情報
- [ ] 実装: `src/datasource/academic.py`

#### 18.2.3 Crossref API統合
- [ ] `CrossrefClient`: Crossref APIクライアント
  - DOI解決
  - 引用情報取得
- [ ] 実装: `src/datasource/academic.py`

#### 18.2.4 Unpaywall API統合
- [ ] `UnpaywallClient`: Unpaywall APIクライアント
  - OA版論文リンク取得
- [ ] 実装: `src/datasource/academic.py`

#### 18.2.5 エビデンスグラフ統合
- [ ] エビデンスグラフに`cites_academic`エッジ追加
  - 学術論文からの引用関係
  - 被引用数・影響力スコアの反映

**成果物**:
- `src/datasource/academic.py`
- `src/filter/evidence_graph.py`（拡張）
- テスト: `tests/test_academic.py`

---

### 18.3 ファクトチェックソース連携 🟡

**目的**: 既存のファクトチェック結果を探索に活用。

#### 18.3.1 ファクトチェック検索
- [ ] `FactCheckSearcher`: ファクトチェックサイト検索
  - **ブラウザ経由でアクセス**（サーバーサイド問題回避）
  - 対象: Snopes, FactCheck.org, PolitiFact, FIJ（日本）
  - 主張に対する既存ファクトチェック結果を検索
- [ ] 実装: `src/datasource/factcheck.py`

#### 18.3.2 ResearchContext統合
- [ ] 主張に関連するファクトチェック結果を提案
  - 類似主張の既存検証結果
  - 評価（True/False/Mixed等）の取得

**成果物**:
- `src/datasource/factcheck.py`
- テスト: `tests/test_factcheck.py`

---

### 18.4 エンティティ解決強化 🟡

**目的**: エンティティの正規化と曖昧性解消。

**既存**: `src/storage/entity_kb.py` - 基本的なエンティティKB

#### 18.4.1 Wikidata API統合
- [ ] `WikidataResolver`: Wikidata APIクライアント
  - エンティティ検索（wbsearchentities）
  - エンティティ詳細取得（wbgetentities）
  - 同義語/別名の取得
- [ ] 実装: `src/datasource/entity_resolver.py`

#### 18.4.2 DBpedia SPARQL統合
- [ ] `DBpediaResolver`: DBpedia SPARQLクライアント
  - エンティティ検索
  - 関連エンティティの取得
  - 日本語・英語の対応付け
- [ ] 実装: `src/datasource/entity_resolver.py`

#### 18.4.3 entity_kb.py拡張
- [ ] `EntityResolver`クラス追加
  - 複数ソース（Wikidata, DBpedia, ローカルKB）からの統合解決
  - 信頼度スコア付きの候補返却
- [ ] 既存エンティティKBとの統合

**成果物**:
- `src/datasource/entity_resolver.py`
- `src/storage/entity_kb.py`（拡張）
- テスト: `tests/test_entity_resolver.py`

---

## Phase 19: LLM/分析強化 🟢

**目的**: ローカルLLMの効率的な活用と分析パイプラインの強化。

---

### 19.1 モデル選択最適化 🟢

**目的**: タスク特性に応じた最適なモデルの自動選択。

#### 19.1.1 設定外部化
- [ ] `config/llm_models.yaml`: タスク別モデル設定
  ```yaml
  models:
    fast:
      name: "qwen2.5:3b-instruct-q4_K_M"
      tasks: [extraction, classification, ner]
      max_tokens: 512
    medium:
      name: "qwen2.5:7b-instruct-q5_K_M"
      tasks: [claim_decompose, quality_evaluation]
      max_tokens: 1024
    slow:
      name: "llama3.1:8b-instruct-q6_K"
      tasks: [complex_reasoning, summarization]
      max_tokens: 2048
  task_mapping:
    extraction: fast
    claim_decompose: medium
    nli: fast
    quality: medium
    summary: slow
  ```

#### 19.1.2 OllamaProvider拡張
- [ ] `select_model(task: str) -> str`: タスクに応じたモデル選択
- [ ] モデル切替のオーバーヘッド最小化
  - 頻繁に使うモデルは常駐
  - 使用頻度の低いモデルは遅延ロード

**成果物**:
- `config/llm_models.yaml`
- `src/filter/ollama_provider.py`（拡張）
- テスト: `tests/test_model_selection.py`

---

### 19.2 プロンプトテンプレート外部化 🟢

**目的**: LLMプロンプトの外部管理と改善サイクルの容易化。

#### 19.2.1 テンプレートディレクトリ
- [ ] `config/prompts/` ディレクトリ作成
  - `extraction.yaml`: 事実/主張抽出プロンプト
  - `claim_decompose.yaml`: 問い→主張分解プロンプト
  - `nli.yaml`: スタンス推定プロンプト
  - `quality.yaml`: コンテンツ品質評価プロンプト
  - `summary.yaml`: 要約プロンプト

#### 19.2.2 テンプレート形式
- [ ] Jinja2テンプレート対応
- [ ] Few-shot例の外部管理
  ```yaml
  template: |
    Given the following passage, extract key facts.
    
    {% for example in few_shot_examples %}
    Example {{ loop.index }}:
    Input: {{ example.input }}
    Output: {{ example.output }}
    {% endfor %}
    
    Input: {{ passage }}
    Output:
  few_shot_examples:
    - input: "..."
      output: "..."
  ```

#### 19.2.3 PromptManager実装
- [ ] `PromptManager`クラス
  - テンプレートのロード・キャッシュ
  - 変数置換
  - バージョン管理

**成果物**:
- `config/prompts/`（新規ディレクトリ）
- `src/filter/prompt_manager.py`
- テスト: `tests/test_prompt_manager.py`

---

## 実装優先度サマリ

| Phase | 項目 | 優先度 | 工数 | 依存関係 |
|-------|------|--------|------|----------|
| 18.0 | API仕様調査・ドキュメント化 | 高 | 小** | なし |
| 18.1 | 政府API統合 | 高 | 中 | 18.0 |
| ~~16.12~~ | ~~Waybackフォールバック強化~~ | ~~高~~ | ~~小~~ | ~~なし~~ | **✅完了** |
| 18.2 | 学術API統合 | 高 | 中 | 18.0 |
| ~~16.11~~ | ~~ヒューマンライク操作~~ | ~~中~~ | ~~中~~ | ~~なし~~ | **✅完了** |
| 18.3 | ファクトチェック連携 | 中 | 小 | なし |
| 16.13 | 検索エンジン多様化 | 中 | 小 | なし |
| 18.4 | エンティティ解決強化 | 中 | 中 | 18.1, 18.2 |
| 17.3.3 | 汎用キャッシュレイヤ | 低 | 中 | なし |
| 19.1 | LLMモデル選択最適化 | 低 | 小 | なし |
| 19.2 | プロンプトテンプレート外部化 | 低 | 小 | 19.1 |

**注意**: Phase 18.0は18.1/18.2/18.4の前提条件。API仕様が確定するまで実装に着手しない。

---

## 開発環境

### 起動方法
```bash
# 全サービス起動
./scripts/dev.sh up

# 開発シェル
./scripts/dev.sh shell

# ログ確認
./scripts/dev.sh logs

# 停止
./scripts/dev.sh down
```

### コンテナ構成
- `lancet` - メイン開発コンテナ
- `lancet-searxng` - SearXNG検索エンジン
- `lancet-tor` - Torプロキシ
- `lancet-ollama` - ローカルLLM (GPU対応)

### テスト実行
```bash
# 全テスト実行（devコンテナ内で実行）
podman exec lancet pytest tests/

# 簡潔な出力
podman exec lancet pytest tests/ --tb=no -q

# 特定ファイルのみ
podman exec lancet pytest tests/test_robots.py -v

# テスト収集のみ（dry-run）
podman exec lancet pytest tests/ --co -q
```

**注意**:
- ローカル環境ではなく必ず `podman exec lancet` 経由で実行する
- 全1986件（ユニット + 統合）、約31秒で完了
- IDE連携ツールからの実行は出力バッファリングで結果取得に失敗する場合あり
  → ファイルリダイレクト推奨: `podman exec lancet pytest tests/ > /tmp/result.txt`

### 外部依存
- Ollama (Podmanコンテナで起動、GPUパススルー)
- Chrome (Windows側で起動、リモートデバッグ)
- nvidia-container-toolkit (GPU使用時に必要)

---

## 注意事項

### 技術的制約
- VRAM≤8GB維持（RTX 4060 Laptop）
- WSL2メモリ32GB内で動作
- 商用API/有料サービス使用禁止

### リスク軽減
- Cloudflare/Turnstile: 手動誘導UX＋クールダウン/スキップ自動化
- VRAM圧迫: マイクロバッチ/候補上限自動調整
