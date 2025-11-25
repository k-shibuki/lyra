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

## Phase 3: 検索機能実装 (部分完了)

### 3.1 SearXNG連携 ✅
- [x] SearXNG Podmanコンテナ設定
- [x] SearXNG設定ファイル（settings.yml）
- [x] HTTP APIクライアント実装
- [x] レート制限

### 3.2 検索クエリ管理 (一部)
- [x] 基本クエリ実行
- [x] SERP結果正規化
- [x] キャッシュ機能
- [x] クエリ多様化（同義語展開）- SudachiPy統合
- [ ] 言語横断ミラークエリ
- [ ] 演算子マッピング（site:, filetype:等）

### 3.3 エンジンヘルスチェック ✅
- [x] 基本メトリクス収集
- [x] サーキットブレーカ完全実装
- [x] EMA更新ロジック

---

## Phase 4: クローリング/取得機能 (部分完了)

### 4.1 HTTPクライアント ✅
- [x] curl_cffi実装
- [x] ヘッダー整合
- [x] ETag/If-Modified-Since完全対応

### 4.2 ブラウザ自動化 (一部)
- [x] Playwright CDP接続基盤
- [x] リソースブロッキング
- [ ] ヘッドレス/ヘッドフル自動切替
- [ ] ヒューマンライク操作

### 4.3 プリフライト判定 ✅
- [x] チャレンジ検知
- [x] 分岐ロジック

### 4.4 ネットワーク制御 (一部)
- [x] レート制限
- [ ] Tor連携（Stem）完全実装

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
- [ ] OCR連携

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

### 7.3 予算制御
- [ ] タスク総ページ数上限
- [ ] LLM処理時間比率制御

---

## Phase 8: 通知/手動介入 (部分完了)

### 8.1 通知システム ✅
- [x] Windowsトースト通知
- [x] Linux notify-send対応

### 8.2 手動介入フロー
- [x] 基本フロー実装
- [ ] タブ前面化
- [ ] タイムアウト処理完全化

---

## Phase 9: レポート生成 ✅

### 9.1 レポート構成 ✅
- [x] Markdownテンプレート
- [x] JSONフォーマット

### 9.2 引用管理 ✅
- [x] 出典リスト生成
- [ ] 深いリンク生成

---

## Phase 10: 自動適応/メトリクス

- [ ] メトリクス収集
- [ ] ポリシー自動更新
- [ ] リプレイモード

---

## Phase 11: テスト/検証 (部分完了)

### 11.1 テスト基盤 ✅
- [x] pytestマーカー設定（unit/integration/e2e/slow）
- [x] conftest.pyにマーカー自動付与フック
- [x] モックフィクスチャ（SearXNG、Ollama、Browser）
- [x] テストデータファクトリ

### 11.2 テストコード品質基準 ✅
- [x] §7.1.1 禁止パターンの定義と是正
- [x] §7.1.7 継続的検証基準の改訂
  - [x] カバレッジ監視指標（CIブロックなし）
  - [x] テスト分類と実行時間制約
  - [x] モック戦略の明文化

### 11.3 テスト実装
- [x] 基本ユニットテスト（219件）
- [ ] 統合テスト拡充
- [ ] 受け入れテスト
- [ ] ミューテーションテスト

---

## Phase 12: ドキュメント/運用 ✅

### 12.1 ドキュメント ✅
- [x] README.md
- [x] 本実装計画書

### 12.2 運用スクリプト ✅
- [x] `scripts/dev.sh` - 開発環境管理
- [x] `scripts/start-chrome.sh` - Chrome起動（Windows側）

---

## 進捗トラッキング

| Phase | 状態 | 進捗 |
|-------|------|------|
| Phase 1: 基盤構築 | ✅ | 100% |
| Phase 2: MCPサーバー | ✅ | 100% |
| Phase 3: 検索機能 | 🔄 | 90% |
| Phase 4: クローリング | 🔄 | 80% |
| Phase 5: コンテンツ抽出 | ✅ | 90% |
| Phase 6: フィルタリング | ✅ | 95% |
| Phase 7: スケジューラ | ✅ | 90% |
| Phase 8: 通知/手動介入 | 🔄 | 60% |
| Phase 9: レポート生成 | ✅ | 80% |
| Phase 10: 自動適応 | ⏳ | 0% |
| Phase 11: テスト | 🔄 | 60% |
| Phase 12: ドキュメント | ✅ | 95% |

**凡例**: ✅ 完了 / 🔄 進行中 / ⏳ 未着手

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

### 外部依存
- Ollama (ホスト側で起動)
- Chrome (Windows側で起動、リモートデバッグ)

---

## 注意事項

### 技術的制約
- VRAM≤8GB維持（RTX 4060 Laptop）
- WSL2メモリ32GB内で動作
- 商用API/有料サービス使用禁止

### リスク軽減
- Cloudflare/Turnstile: 手動誘導UX＋クールダウン/スキップ自動化
- VRAM圧迫: マイクロバッチ/候補上限自動調整
