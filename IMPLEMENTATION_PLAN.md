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
- [x] `generate_report` - レポート生成

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

### 8.2 手動介入フロー ✅
- [x] 基本フロー実装
- [x] タブ前面化（CDP Page.bringToFront + プラットフォーム別フォールバック）
- [x] タイムアウト処理完全化（3分SLA、§3.6準拠）
- [x] 要素ハイライト（CAPTCHA/Cloudflare等の対象要素を視覚的に強調）
- [x] ドメイン連続失敗追跡（3回失敗で当日スキップ、§3.1準拠）
- [x] クールダウン適用（タイムアウト時≥60分、§3.5準拠）
- [x] fetcher.pyへの統合（challenge検知→手動介入フロー自動呼び出し）
- [x] チャレンジタイプ検出（Cloudflare/CAPTCHA/Turnstile/hCaptcha等）

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
- [x] `get_exploration_status` MCPツール実装

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
- [x] 基本ユニットテスト（689件、全パス）
- [x] Phase 10テスト（メトリクス、ポリシー、リプレイ）
- [x] Phase 8テスト（通知/手動介入フロー）
- [x] Phase 9テスト（レポート生成、深いリンク生成）
- [x] Phase 11テスト（探索制御エンジン、責任分界検証）
- [x] OCRテスト修正（モック戦略改善）
- [x] 統合テスト（26件：パイプライン、エビデンスグラフ、スケジューラ等）
- [ ] 受け入れテスト（E2E）
- [ ] ミューテーションテスト

---

## Phase 16: 未実装機能 (Gap Analysis) ⏳

**requirements.md との詳細照合により特定された未実装項目。**
**優先度**: 🔴 高（E2E前に必須） / 🟡 中（MVP強化） / 🟢 低（将来拡張）

---

### 16.1 抗堪性・ステルス性 (§4.3) 🔴

#### 16.1.1 ネットワーク/IP層
- [ ] **IPv6運用** (§4.3)
  - v6→v4切替ロジック（ドメイン単位で成功率学習）
  - IPv6成功率メトリクス追跡
  - ハッピーアイボール風切替
- [ ] **DNS方針** (§4.3)
  - EDNS Client Subnet無効化
  - Tor経路時のDNSリーク防止（Privoxy経由）
  - DNSキャッシュTTL尊重
- [ ] **HTTP/3(QUIC)方針** (§4.3)
  - ブラウザ経由でのHTTP/3自然利用検知
  - HTTP/3提供サイトでのブラウザ経路比率自動増加

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
- [ ] **UCB1風予算再配分**
  - サブクエリごとの収穫率で予算を動的再配分
  - 探索木制御の最適化
- [ ] **クエリABテスト**
  - 表記ゆれ/助詞/語順バリアントの小規模A/B
  - 高収穫クエリのキャッシュ・再利用
- [ ] **ピボット探索（エンティティ拡張）** (§3.1.1)
  - 企業→子会社/役員/所在地/ドメイン
  - ドメイン→サブドメイン→証明書SAN→組織名
  - 個人→別名/ハンドル/所属

#### 16.2.2 インフラ/レジストリ連携 (§3.1.2, §3.1.3)
- [ ] **RDAP/WHOIS連携**
  - 公式Web/レジストリからHTML取得
  - 登録者/NS/更新履歴抽出
- [ ] **crt.sh連携**
  - 証明書透明性ログからSAN/発行者/発行時系列抽出
- [ ] **エンティティKB正規化**
  - 抽出した名称/所在地/識別子のKB格納
  - 別表記・住所正規化・同一性推定

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

#### 16.2.7 Chain-of-Density圧縮 (§3.3.1)
- [ ] **要約密度の向上**
  - 全主張に深いリンク・発見日時・抜粋を必須付与
  - 圧縮と引用の厳格化

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

### 16.5 補助OSS/任意機能 (§5.1.1) 🟢

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
- [ ] `IPv6成功率≥80%` - IPv6未実装のため測定不可
- [ ] `DNSリーク検出0件` - DNS方針未実装のため測定不可
- [x] `プロファイル健全性チェック成功率≥99%` - 監査機能実装済み
- [x] `自動修復成功率≥90%` - 修復機能実装済み
- [ ] `v4↔v6自動切替成功率≥80%` - IPv6未実装のため測定不可

#### 16.6.2 E2Eテスト前提条件
E2Eテストを有効に実施するための前提：
- [x] プロファイル健全性監査の基本実装 ✅
- [x] セッション移送ユーティリティ ✅
- [x] sec-fetch-*ヘッダー整合 ✅
- [x] sec-ch-ua*ヘッダー ✅
- [x] ブラウザ経路アーカイブ保存 ✅
- [x] プロセスライフサイクル管理 ✅

---

## Phase 15: ドキュメント/運用 ✅

### 15.1 ドキュメント ✅
- [ ] README.md
- [x] 本実装計画書

### 15.2 運用スクリプト ✅
- [x] `scripts/dev.sh` - 開発環境管理
- [x] `scripts/start-chrome.sh` - Chrome起動（Windows側）

---

## 進捗トラッキング

| Phase | 状態 | 進捗 | 備考 |
|-------|------|------|------|
| Phase 1: 基盤構築 | ✅ | 100% | |
| Phase 2: MCPサーバー | ✅ | 100% | |
| Phase 3: 検索機能 | ✅ | 100% | |
| Phase 4: クローリング | ✅ | 100% | |
| Phase 5: コンテンツ抽出 | ✅ | 100% | |
| Phase 6: フィルタリング | ✅ | 100% | |
| Phase 7: スケジューラ | ✅ | 100% | |
| Phase 8: 通知/手動介入 | ✅ | 100% | |
| Phase 9: レポート生成 | ✅ | 100% | |
| Phase 10: 自動適応 | ✅ | 100% | |
| Phase 11: 探索制御エンジン | ✅ | 100% | |
| Phase 12: クローリング拡張 | ✅ | 100% | |
| Phase 13: 信頼度キャリブレーション | ✅ | 100% | |
| Phase 14: テスト | 🔄 | 95% | E2E/ミューテーション未完 |
| Phase 15: ドキュメント | 🔄 | 75% | Phase 14/16完了後に整備|
| **Phase 16: 未実装機能** | 🔄 | 60% | **20項目残り** |

**凡例**: ✅ 完了 / 🔄 進行中 / ⏳ 未着手

### Phase 16 優先度別サマリ

| 優先度 | 項目数 | 主要カテゴリ |
|--------|--------|--------------|
| 🔴 高（E2E前必須） | 8項目 | IPv6/DNS/HTTP3 |
| 🟡 中（MVP強化: E2E前推奨） | 13項目 | ピボット探索、RDAP/crt.sh、評価可視化 |
| 🟢 低（将来拡張） | 7項目 | GROBID、faiss-gpu、Privoxy |

### 完了済み（Phase 16）
- sec-fetch-*ヘッダー整合、sec-ch-ua*ヘッダー
- navigator.webdriverオーバーライド、viewportジッター
- プロファイル健全性監査、セッション移送ユーティリティ
- ブラウザ経路アーカイブ保存
- プロセスライフサイクル管理（ブラウザ/LLM破棄）
- ページタイプ判定（記事/ナレッジ/フォーラム/ログイン壁/一覧）
- undetected-chromedriverフォールバック（Cloudflare強/Turnstile対策）
- 時系列整合チェック（主張時点 vs ページ更新日の不整合検出、信頼度減衰）
- **校正ロールバック**（デグレ検知、パラメータ履歴保持、自動ロールバック）

**注意**: Phase 16はGap Analysisにより特定された残課題です。

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
- 全1049件（ユニット1023件 + 統合26件）、約15秒で完了
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
