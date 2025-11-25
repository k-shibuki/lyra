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

## Phase 5: コンテンツ抽出 (部分完了)

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

## Phase 6: フィルタリングと評価 (部分完了)

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
- [x] 基本ユニットテスト（519件、全パス）
- [x] Phase 10テスト（メトリクス、ポリシー、リプレイ）
- [x] Phase 8テスト（通知/手動介入フロー）
- [x] Phase 9テスト（レポート生成、深いリンク生成）
- [x] Phase 11テスト（探索制御エンジン、責任分界検証、25件）
- [x] OCRテスト修正（モック戦略改善）
- [ ] 統合テスト拡充
- [ ] 受け入れテスト
- [ ] ミューテーションテスト

---

## Phase 15: ドキュメント/運用 ✅

### 15.1 ドキュメント ✅
- [x] README.md
- [x] 本実装計画書

### 15.2 運用スクリプト ✅
- [x] `scripts/dev.sh` - 開発環境管理
- [x] `scripts/start-chrome.sh` - Chrome起動（Windows側）

---

## 進捗トラッキング

| Phase | 状態 | 進捗 |
|-------|------|------|
| Phase 1: 基盤構築 | ✅ | 100% |
| Phase 2: MCPサーバー | ✅ | 100% |
| Phase 3: 検索機能 | ✅ | 100% |
| Phase 4: クローリング | ✅ | 100% |
| Phase 5: コンテンツ抽出 | ✅ | 100% |
| Phase 6: フィルタリング | ✅ | 95% |
| Phase 7: スケジューラ | ✅ | 100% |
| Phase 8: 通知/手動介入 | ✅ | 100% |
| Phase 9: レポート生成 | ✅ | 100% |
| Phase 10: 自動適応 | ✅ | 100% |
| **Phase 11: 探索制御エンジン** | ✅ | **100%** |
| **Phase 12: クローリング拡張** | ✅ | **100%** |
| **Phase 13: 信頼度キャリブレーション** | ✅ | **100%** |
| Phase 14: テスト | 🔄 | 85% |
| Phase 15: ドキュメント | ✅ | 95% |

**凡例**: ✅ 完了 / 🔄 進行中 / ⏳ 未着手

**注意**: Phase 12-13 は requirements.md §3.1.2, §3.1.5, §3.1.6, §3.3.4 で定義された拡張機能であり、MVPに対する強化として位置づけられます。

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
- 全689件、約6秒で完了
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
