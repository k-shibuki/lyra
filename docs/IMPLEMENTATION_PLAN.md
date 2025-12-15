# 実装計画: Local Autonomous Deep Research Agent (Lancet)

## 1. ドキュメントの位置づけ

本ドキュメントは、Lancetプロジェクトの**実装計画書**である。

| ドキュメント | 役割 | 参照 |
|-------------|------|------|
| `docs/requirements.md` | 仕様書（要件定義） | §1-8で機能・非機能要件を定義 |
| `docs/PUBLICATION_PLAN.md` | 論文執筆準備メモ | SoftwareX投稿、ケーススタディ設計 |
| **`docs/IMPLEMENTATION_PLAN.md`**（本文書） | **実装計画書** | Phase別の実装状況・知見を管理 |

**システム概要**: 信頼性が高いデスクトップリサーチを自律的に実行するローカルAIエージェント。**Podmanコンテナ環境**で稼働し、MCPを通じてCursorと連携する。

---

## 2. 実装完成度サマリ（2025-12-11 更新）

| Phase | 内容 | ユニットテスト | E2E検証 | 状態 | セクション |
|-------|------|:-------------:|:-------:|:----:|:----------:|
| A-H | 基盤〜検索エンジン多様化 | ✅ | ✅ | 完了 | §4 |
| I | 保守性改善 | ✅ | - | 完了 | §5 |
| K.3 | セキュリティ（L1-L8） | ✅ | ✅ | 完了 | §5 |
| M | MCPリファクタリング | ✅ | ✅ | 完了 | §6 |
| N | E2Eケーススタディ | - | ⏳ | 進行中（N.2-5完了） | §6 |
| **O** | **ハイブリッド構成リファクタ** | ✅ | ✅ | **完了（O.2-O.3）** | §6 |

**現在のテスト数**: 2688件（全パス）

---

## 3. Phase構成とロードマップ

### 3.1 Phase一覧

| カテゴリ | Phase | 内容 | 状態 | セクション |
|---------|-------|------|:----:|:----------:|
| **コア実装** | A | 基盤構築 | ✅ | §4 |
| | B | 品質強化 | ✅ | §4 |
| | C | 検索経路再設計 | ✅ | §4 |
| | D | 抗堅性・ステルス性強化 | ✅ | §4 |
| | E | OSINT品質強化 | ✅ | §4 |
| | F | 追加機能 | ✅ | §4 |
| | G | テスト基盤 | ✅ | §4 |
| | H | 検索エンジン多様化 | ✅ | §4 |
| **保守・拡張** | I | 保守性改善 | ✅ | §5 |
| | J | 外部データソース統合 | ⏳ | §5 |
| | K | ローカルLLM強化 | 🔄 | §5 |
| **検証・リファクタ** | L | ドキュメント | ⏳ | §6 |
| | M | MCPツールリファクタリング | ✅ | §6 |
| | N | E2Eケーススタディ | ⏳ | §6 |
| | **O** | **ハイブリッド構成リファクタ** | ✅ | §6 |

### 3.2 優先度

#### MVP必須（初期リリース）
- Phase A-H: 基盤〜検索エンジン多様化 ✅
- Phase I: 保守性改善 ✅
- Phase K.3: プロンプトインジェクション対策 ✅
- Phase M: MCPツールリファクタリング ✅
- **Phase N: E2Eケーススタディ（論文投稿向け）⏳**

#### Phase 2（論文投稿後）
- Phase J: 外部データソース統合
- Phase K.1-K.2: モデル選択最適化、プロンプト外部化
- Phase L: ドキュメント

#### 将来の拡張
- クエリA/Bテスト（§3.1.1から削除済み）
- 変更検知/差分アラート
- IPv6/HTTP3の高度な学習

---

## 4. コア実装 (Phase A-H)

### Phase A: 基盤構築 ✅

#### A.1 プロジェクト基盤 ✅

| 項目 | 成果物 | 仕様参照 |
|------|--------|----------|
| プロジェクト構造 | `src/`, `config/`, `tests/` 等 | - |
| 依存関係 | `requirements.txt`, `pyproject.toml`, Dockerfile | - |
| 設定管理 | `config/settings.yaml`, `config/engines.yaml`, `config/domains.yaml` | - |
| データベース | SQLiteスキーマ (`src/storage/schema.sql`)、FTS5全文検索 | §5.1.2 |
| ロギング | 構造化ログ (structlog)、因果トレース (cause_id) | §4.6 |

#### A.2 MCPサーバー ✅

**MCPツール（11ツール）**: Phase Mで30個→11個に簡素化完了

| カテゴリ | ツール |
|---------|--------|
| タスク管理 | `create_task`, `get_status` |
| 調査実行 | `search`, `stop_task` |
| 成果物 | `get_materials` |
| 校正 | `calibrate`, `calibrate_rollback` |
| 認証キュー | `get_auth_queue`, `resolve_auth` |
| 通知 | `notify_user`, `wait_for_user` |

詳細は Phase M 参照。

#### A.3 検索機能 ✅

**当初設計（SearXNG経由）→ 廃止**: 詳細は「Phase C.1 検索経路の再設計」参照

**現在の実装（BrowserSearchProvider）**:
- Playwright CDP接続によるブラウザ直接検索
- 対応エンジン: DuckDuckGo, Mojeek, Qwant, Brave, Google, Ecosia, Startpage
- CAPTCHA検知→認証キュー連携

#### A.4 クローリング/取得 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| HTTPクライアント | curl_cffi (impersonate=chrome) | §4.3 |
| ブラウザ自動化 | Playwright CDP接続 | §3.2 |
| ヘッドフル切替 | 自動エスカレーション | §4.3 |
| Torプロキシ | Stem連携、Circuit更新 | §4.3 |
| アーカイブ保存 | WARC (warcio)、スクリーンショット | §4.3.2 |

#### A.5 コンテンツ抽出 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| HTML抽出 | trafilatura | §5.1 |
| PDF抽出 | PyMuPDF | §5.1.1 |
| OCR | PaddleOCR + Tesseract | §5.1.1 |
| 重複検出 | MinHash + SimHash | §3.3.1 |

#### A.6 フィルタリング/評価 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| BM25ランキング | rank-bm25 | §3.3 |
| 埋め込み | bge-m3 (ONNX/FP16) | §5.1 |
| リランキング | bge-reranker-v2-m3 | §5.1 |
| LLM抽出 | Ollama (Qwen2.5-3B/7B) | §5.1 |
| NLI判定 | tiny-DeBERTa | §3.3.1 |
| エビデンスグラフ | NetworkX + SQLite | §3.3.1 |

#### A.7 スケジューラ ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ジョブキュー | 優先度管理、スロット制御 | §3.2.2 |
| 排他制御 | gpu/browser_headful排他 | §3.2.2 |
| 予算制御 | ページ数/時間上限 | §3.1 |

**既定値（§3.2.2）**:
- `network_client`: 同時実行=4、ドメイン同時実行=1
- 優先度: serp(100) > prefetch(90) > extract(80) > embed(70) > rerank(60) > llm_fast(50) > llm_slow(40)
- タイムアウト: 検索30秒、取得60秒、LLM抽出120秒

#### A.8 通知/手動介入 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 通知 | Windows Toast / Linux notify-send | §3.6 |
| 認証待ちキュー | InterventionQueue | §3.6.1 |
| ウィンドウ前面化 | OS API (SetForegroundWindow) | §3.6.1 |
| ドメインベース認証 | 同一ドメイン一括解決 | §3.6.1 |

**§3.6.1安全運用方針**:
- CDP許可: `Page.navigate`, `Page.bringToFront`
- CDP禁止: `Runtime.evaluate`, `DOM.*`, `Input.*`, `Emulation.*`
- 完了検知: ユーザー明示報告のみ（DOM監視禁止）

**§2.1.5判断委譲の例外**:
- Cursor AI無応答時（300秒既定）: パイプライン安全停止、状態保存、復帰待機

#### A.9 レポート生成 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| テンプレート | Markdown / JSON | §3.4 |
| 引用管理 | 深いリンク生成、一次/二次分類 | §3.4 |

---

### Phase B: 品質強化 ✅

#### B.1 メトリクス/自動適応 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| メトリクス収集 | MetricsCollector, TaskMetrics | §4.6 |
| ポリシー自動更新 | PolicyEngine (EMA、ヒステリシス) | §4.6 |
| リプレイモード | DecisionLogger, ReplayEngine | §4.6 |

**ポリシー自動更新の既定値（§4.6）**:
- 周期補完: 60秒
- EMA係数: 短期α=0.3、長期α=0.1
- Tor利用上限: 20%
- パラメータ反転防止: 5分未満は反転させない

#### B.2 探索制御 ✅

**§2.1責任分界**: クエリ設計はCursor AI、Lancetは実行のみ

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 設計支援情報 | ResearchContext | §2.1.2 |
| サブクエリ実行 | SubqueryExecutor | §2.1.2 |
| 充足度判定 | ExplorationState | §3.1.7.3 |
| 反証探索 | RefutationExecutor (機械パターンのみ) | §3.1.7.5 |

#### B.3 クローリング拡張 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| robots.txt/sitemap | RobotsChecker, SitemapParser | §3.1.2 |
| ドメイン内BFS | DomainBFSCrawler | §3.1.2 |
| サイト内検索 | SiteSearchManager | §3.1.5 |
| Wayback差分 | WaybackExplorer | §3.1.6 |

#### B.4 信頼度キャリブレーション ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 確率校正 | Platt/温度スケーリング | §3.3.4 |
| デグレ検知 | Brierスコア監視 | §4.6.1 |
| ロールバック | CalibrationHistory | §4.6.1 |

---

### Phase C: 検索経路再設計 ✅

#### C.1 SearXNG廃止の背景

**問題**: SearXNGはサーバーサイドで動作するため、以下の技術的欠陥があった：

1. **Cookie/指紋使用不可**: ユーザーのブラウザセッションを使用できない
2. **bot検知されやすい**: Cookie/指紋なしの素のHTTPリクエスト
3. **CAPTCHA解決不可**: ユーザーがCAPTCHA解決しても、SearXNGにCookieは渡らない
4. **§3.6.1との矛盾**: 認証待ちキューの設計意図が成立しない

**根本原因**: SearXNGは「便利」だったが、抗堅性（§4.3）を犠牲にする設計だった。

#### C.2 新アーキテクチャ（BrowserSearchProvider）

```
┌──────────────┐    ┌──────────────┐
│ Lancet       │ →  │ Playwright   │ → DuckDuckGo等
│ (直接検索)   │    │ (ブラウザ)   │
│              │    │ Cookie: あり │
│              │    │ 指紋: あり   │    → 人間らしい
└──────────────┘    └──────────────┘
        │                  │
        ▼                  ▼
   検索結果パーサー   セッション転送（§3.1.2）
   (BeautifulSoup)    が検索にも適用可能
```

**実装完了項目**:
- `BrowserSearchProvider`: Playwright CDP接続、エンジン別URL構築、CAPTCHA検知→認証キュー連携
- `BaseSearchParser` + エンジン別パーサー: DuckDuckGo, Mojeek, Google, Brave, Qwant, Ecosia, Startpage
- `config/search_parsers.yaml`: セレクター外部化、AI修正用診断メッセージ

#### C.3 docs/requirements.md修正内容

**§3.2 エージェント実行機能**:
```
【旧】検索エンジン統合: ローカルで稼働するSearXNG（メタ検索エンジン）に対しクエリを送信

【新】検索エンジン統合: Playwright経由で検索エンジンを直接検索する
- ユーザーのブラウザプロファイル（Cookie/指紋）を使用
- 対応エンジン: DuckDuckGo, Google, Mojeek, Qwant, Brave
- CAPTCHA発生時は手動介入フロー（§3.6.1）に移行
- セッション転送（§3.1.2）が検索にも適用
```

**§4.3.3 ステルス設計方針** に追記:
```
- サーバーサイドサービス禁止:
  - SearXNG/公開SearXインスタンス等は使用しない
  - 理由: Cookie/指紋使用不可、CAPTCHA解決不可、IP汚染リスク
  - すべての検索・取得はブラウザ経由で実行
```

**§5.1 コアコンポーネント**:
```
【旧】Search Engine: SearXNG (Podmanコンテナ)

【新】Search Engine: Playwright経由の直接ブラウザ検索（BrowserSearchProvider）
- 対応エンジン: DuckDuckGo, Mojeek, Qwant, Brave, Google
- エンジンallowlist（既定）: DuckDuckGo, Mojeek, Qwant。Googleは低重み
```

---

### Phase D: 抗堅性・ステルス性強化 ✅

#### D.1 ネットワーク/IP層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| IPv6運用 | IPv6ConnectionManager | §4.3 |
| DNS方針 | DNSPolicyManager (socks5h://でリーク防止) | §4.3 |
| HTTP/3方針 | HTTP3PolicyManager | §4.3 |

#### D.2 トランスポート/TLS層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| sec-fetch-*ヘッダー | SecFetchHeaders | §4.3 |
| sec-ch-ua*ヘッダー | SecCHUAHeaders | §4.3 |

#### D.3 ブラウザ/JS層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| webdriverオーバーライド | stealth.py (STEALTH_JS) | §4.3 |
| undetected-chromedriverフォールバック | UndetectedChromeFetcher | §4.3 |
| viewportジッター | ViewportJitter | §4.3 |

#### D.4 プロファイル健全性監査 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 差分検知 | ProfileAuditor (UA/フォント/言語/指紋) | §4.3.1 |
| 自動修復 | attempt_repair (Chrome再起動等) | §4.3.1 |
| 監査ログ | JSONL形式 | §4.3.1 |

#### D.5 セッション移送 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| Cookie/ETag移送 | SessionTransferManager | §3.1.2 |
| 同一ドメイン制約 | capture_from_browser | §3.1.2 |

#### D.6 ブラウザ経路アーカイブ ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| CDXJ風メタデータ | CDXJGenerator | §4.3.2 |
| 簡易HAR生成 | HARGenerator | §4.3.2 |

#### D.7 ヒューマンライク操作 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| マウス軌跡 | MouseTrajectory (Bezier曲線) | §4.3.4 |
| タイピングリズム | HumanTyping (ガウス分布) | §4.3.4 |
| スクロール慣性 | InertialScroll (easing) | §4.3.4 |
| 設定外部化 | config/human_behavior.yaml | §4.3.4 |

---

### Phase E: OSINT品質強化 ✅

#### E.1 検索戦略 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| UCB1風予算再配分 | UCBAllocator | §3.1.1 |
| ピボット探索 | PivotExpander | §3.1.1 |

> **注意**: クエリA/Bテスト（ABTestExecutor）は§3.1.1から削除され、「将来の拡張」に移動した。

#### E.2 インフラ/レジストリ連携 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| RDAP/WHOIS | RDAPClient, WHOISParser | §3.1.2 |
| 証明書透明性 | CertTransparencyClient (crt.sh) | §3.1.2 |
| エンティティKB | EntityKB, NameNormalizer | §3.1.2 |

#### E.3 コンテンツ品質 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ページタイプ判定 | PageClassifier | §3.1.2 |
| 低品質検出 | ContentQualityAnalyzer | §3.3.3 |
| AI生成検出 | 23パターン + 文長均一性 | §3.3.3 |
| 時系列整合 | TemporalConsistencyChecker | §3.3.3 |

#### E.4 主張分析 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 問い→主張分解 | ClaimDecomposer | §3.3.1 |
| Chain-of-Density圧縮 | ChainOfDensityCompressor | §3.3.1 |

---

### Phase F: 追加機能 ✅

#### F.1 校正ロールバック ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| デグレ検知 | CalibrationHistory.check_degradation() | §4.6.1 |
| ロールバック | Calibrator.rollback() | §4.6.1 |
| 評価永続化 | calibration_evaluations テーブル | §4.6.1 |

#### F.2 プロセスライフサイクル ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ブラウザ破棄 | ProcessLifecycleManager | §4.2 |
| LLM解放 | OllamaClient.unload_model() | §4.2 |

#### F.3 半自動運用UX ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 認証待ち情報統合 | get_exploration_status に authentication_queue 追加 | §3.6.1 |
| 閾値アラート | warnings配列への追加 (≥3件で警告) | §3.6.1 |

#### F.4 タイムライン機能 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 主張タイムライン | ClaimTimeline, TimelineEvent | §3.4 |
| Wayback連携 | integrate_wayback_result() | §3.1.6 |
| カバレッジ算出 | get_timeline_coverage() | §7 |

#### F.5 Waybackフォールバック ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 自動フォールバック | fetcher.py統合 (403/CAPTCHA時) | §3.1.6 |
| 差分検出 | ArchiveDiffResult | §3.1.6 |
| 鮮度ペナルティ | apply_freshness_penalty() | §3.1.6 |

---

### Phase G: テスト基盤 ✅

#### G.1 テスト分類

| 分類 | マーカー | 外部依存 | 実行環境 |
|------|----------|----------|----------|
| unit | `@pytest.mark.unit` | なし | どこでも |
| integration | `@pytest.mark.integration` | モック | どこでも |
| e2e | `@pytest.mark.e2e` | 実サービス | 低リスクIP限定 |

**追加マーカー**:
- `@external`: 外部サービス使用（Mojeek, Qwant等）
- `@rate_limited`: レート制限厳しい（DuckDuckGo, Google等）
- `@manual`: 人手介入必須（CAPTCHA解決等）

#### G.2 テスト実行

**実行環境**:
- **WSL venv（推奨）**: `requirements-mcp.txt`で基本テスト実行可能
- **オプショナル依存関係**: ML/PDF/OCR機能のテストには追加依存関係が必要（§K.4参照）

```bash
# WSL venvから実行（推奨）
source .venv/bin/activate
pytest tests/ -m 'not e2e' --tb=short -q

# オプショナル依存関係をインストールする場合
pip install -r requirements-ml.txt

# 全テスト実行（devコンテナ内で実行）
podman exec lancet pytest tests/

# 簡潔な出力
podman exec lancet pytest tests/ --tb=no -q

# 特定ファイルのみ
podman exec lancet pytest tests/test_robots.py -v
```

**依存関係確認**（回帰テスト実行前）:
```bash
# ML関連依存関係の確認
python -c "import sentence_transformers, transformers, torch" 2>/dev/null && echo "ML deps OK" || echo "ML deps MISSING"

# PDF/OCR関連依存関係の確認
python -c "import fitz, PIL" 2>/dev/null && echo "PDF/OCR deps OK" || echo "PDF/OCR deps MISSING"
```

**現在のテスト数**: 2754件（依存関係インストール済み環境で全パス、依存関係不足時は17件失敗）

#### G.3 E2Eスクリプト（tests/scripts/）

| スクリプト | 検証内容 | 仕様 | 状態 |
|-----------|----------|------|:----:|
| `verify_duckduckgo_search.py` | DuckDuckGo検索、パーサー、セッション | §3.2 | ✅ 5/5 |
| `verify_ecosia_search.py` | Ecosia検索（Bing再販） | §3.2 | ✅ 4/4 |
| `verify_startpage_search.py` | Startpage検索（Google再販） | §3.2 | ✅ 4/4 |
| `verify_mojeek_search.py` | Mojeek検索（独立エンジン） | §3.2 | ✅ 4/4 |
| `verify_qwant_search.py` | Qwant検索（EU系） | §3.2 | ✅ 4/4 |
| `verify_brave_search.py` | Brave検索（独自インデックス） | §3.2 | ✅ 4/4 |
| `verify_google_search.py` | Google検索（高リスク） | §3.2 | ✅ 4/4 |
| `verify_bing_search.py` | Bing検索（高リスク） | §3.2 | ✅ 4/4 |
| `verify_captcha_flow.py` | CAPTCHA→通知→手動解決→継続 | §3.6.1 | ✅ |
| `verify_session_transfer.py` | ブラウザ→HTTP間セッション移送 | §3.1.2 | ✅ |
| `verify_search_then_fetch.py` | 検索→取得の一貫性 | §3.2 | ✅ |
| `verify_network_resilience.py` | IPv6、DNSリーク、304活用 | §7 | ✅ |
| `verify_profile_health.py` | プロファイル健全性、自動修復 | §7 | ✅ |

---

### Phase H: 検索エンジン多様化 ✅

#### H.1 実装状況マトリクス

| エンジン | 仕様書§3.2 | engines.yaml | パーサー | E2Eスクリプト | E2E検証 | 状態 |
|----------|:----------:|:------------:|:--------:|:-------------:|:-------:|------|
| DuckDuckGo | ✅ | ✅ | ✅ | ✅ | ✅ 5/5 | **完了** |
| Mojeek | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Google | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Brave | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Ecosia | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Startpage | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Bing | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |

#### H.2 E2E検証で判明した知見

##### H.2.1 MetaGer削除

**問題**: ログインゲートが存在し、全セレクターが失敗
**症状**: 検索結果ページにアクセスしても認証画面にリダイレクト
**決定**: エンジンから完全削除（ログインゲートはCAPTCHAと異なり回避困難）

**削除したファイル**:
- `config/engines.yaml`: metagerセクション
- `config/search_parsers.yaml`: metagerセクション
- `src/search/search_parsers.py`: MetaGerParserクラス
- `src/search/parser_config.py`: metagerフィールド
- `tests/test_search_parsers.py`: MetaGer関連テスト
- `tests/fixtures/search_html/metager_results.html`
- `tests/scripts/verify_metager_search.py`

##### H.2.2 セレクター保守の教訓

**問題**: Ecosia/Startpageのセレクターが実際のHTMLと不一致
**原因**: 検索エンジンはHTMLを予告なく変更する
**対策**:
1. E2E失敗時に`debug/search_html/`へHTML自動保存
2. `config/search_parsers.yaml`でセレクター外部化
3. 構造化ログで失敗セレクター名を明示

**Ecosia修正後のセレクター**:
```yaml
results_container: ".mainline__result-wrapper"
title: "a[data-test-id='result-link'], .result-title__heading"
url: "a[data-test-id='result-link']"
snippet: ".result__description"
```

**Startpage修正後のセレクター**:
```yaml
results_container: ".result"
title: ".wgl-title, .result-title"
url: "a.result-title, a.result-link"
snippet: ".description"
```

##### H.2.3 E2E検証で判明した追加問題

**Qwant地域制限**:
- 症状: 「Unfortunately we are not yet available in your country」
- 原因: Qwantは日本からのアクセスを制限している
- 対応: engines.yamlからQwantを削除（地域制限はCAPTCHAと異なり回避困難）

**Braveタイムアウト**: ✅ 修正済み
- 症状: `networkidle`待機で10秒タイムアウト
- 原因: BraveはJSで常時ネットワークリクエストを発生させる
- 対応: `networkidle`を5秒try後、`asyncio.sleep(2)`にフォールバック

**BrowserSearchProvider CDPフォールバック問題**: ✅ 修正済み
- 症状: Chromeが起動していない時に「CAPTCHA detected」と報告されていた
- 根本原因: CDP接続失敗時にヘッドレスフォールバックが発生（仕様違反）
- 修正内容:
  1. ヘッドレスフォールバックを削除（§4.3.3「実プロファイルの一貫性」に準拠）
  2. CDP接続失敗時は明確なエラーメッセージを返す
  3. エラーメッセージに`./scripts/chrome.sh start`の案内を含める
  4. `SearchResponse.connection_mode`フィールド追加（診断用）
- 変更ファイル:
  - `src/search/provider.py`: `SearchResponse`に`connection_mode`追加
  - `src/search/browser_search_provider.py`: フォールバック削除、`CDPConnectionError`追加
  - `tests/test_browser_search_provider.py`: CDP接続テスト追加

**Brave CAPTCHA誤検出問題**: ✅ 修正済み
- 症状: 正常な検索結果ページで「CAPTCHA detected」と誤報告
- 根本原因: `captcha_patterns`の`"captcha"`パターンがJS変数名（`captchacookiename`等）にマッチ
- 修正内容: `config/search_parsers.yaml`のBrave用パターンをより具体的に変更
  - `"captcha"` → `"please complete the captcha"`, `"verify you are human"`

**Bing URLデコード問題**: ✅ 修正済み
- 症状: Bing検索結果が0件として返される
- 根本原因: BingのリダイレクトURL（`u=a1aHR0cHM6...`）がbase64エンコードされているが、デコード処理が欠落
- 修正内容: `src/search/search_parsers.py`の`_clean_bing_url`にbase64デコード追加

##### H.2.4 E2Eスクリプトの共通修正

**問題1**: `SearchResponse`に`captcha_detected`属性がない
**修正**: `result.error`文字列から"CAPTCHA detected"を検索するヘルパー関数を追加
```python
def _is_captcha_detected(result: SearchResponse) -> tuple[bool, Optional[str]]:
    if result.error and "CAPTCHA detected" in result.error:
        match = re.search(r"CAPTCHA detected: (\w+)", result.error)
        captcha_type = match.group(1) if match else "unknown"
        return True, captcha_type
    return False, None
```

**問題2**: `FetchPolicy`クラスが存在しない
**修正**: `BrowserFetcher.fetch(headful=False)`に直接変更

**問題3**: `FetchResult.content`属性がない
**修正**: `result.html_path or result.content_hash`で判定

##### H.2.5 E2Eスクリプト作成の完了

**優先度中（E2Eカバレッジ向上）**:
- [x] `verify_mojeek_search.py`作成 ✅
- [x] ~~`verify_qwant_search.py`作成~~ → Qwant削除（地域制限、H.2.3参照）
- [x] `verify_brave_search.py`作成 ✅

**優先度低（高リスクエンジン）**:
- [x] `verify_google_search.py`作成 ✅（CAPTCHA高頻度）
- [x] `verify_bing_search.py`作成 ✅

**注**: Bingパーサー実装はH.1のマトリクスに反映済み。CDPフォールバック問題の修正はH.2.3に既に記載。

##### H.2.6 MCPサーバ経由での動作確認

---

#### G.4 実装の状況確認タスク

**目的**: 実装計画書の記述と実際の実装状況に不一致がないか定期的に確認する。

**確認項目**:

1. **依存関係の整合性**
   - 実装計画書で「依存関係不要」と記載されている機能のテストが、実際には依存関係を必要としていないか
   - テストコード内で直接インポートしている箇所がないか（モックを使う前にインポートが実行される）
   - オプショナルな依存関係の不足によるテスト失敗が適切に文書化されているか

2. **テスト実行環境の整合性**
   - WSL venvとコンテナ環境でのテスト実行結果が一致しているか
   - テストマーカー（`@pytest.mark.skip`等）が適切に設定されているか
   - E2Eテストが適切な環境で実行されているか

3. **実装計画書の更新**
   - 実装完了後の知見が実装計画書に反映されているか
   - 設計方針と実際の実装に不一致がないか
   - トラブルシューティング情報が追記されているか

**実行タイミング**:
- 新機能実装完了時
- 回帰テスト実行時
- 実装計画書の更新時

**実行方法**:
```bash
# 1. 回帰テスト実行
./scripts/test.sh run tests/

# 2. テスト結果確認
./scripts/test.sh check
./scripts/test.sh get

# 3. 失敗テストの原因分析
# - 依存関係の不足か（§G.2「依存関係確認」を参照）
# - 実装計画書との不一致か（§K.4.7参照）
# - バグか

# 4. 実装計画書の更新
# - 知見・トラブルシューティングセクションに追記
# - 設計方針との不一致を明記
# - 依存関係要件を更新
```

**チェックリスト**:
- [ ] 回帰テスト実行前に依存関係を確認（§G.2参照）
- [ ] テスト失敗の原因を分析（依存関係不足 / 実装計画書との不一致 / バグ）
- [ ] 実装計画書との不一致があれば、該当セクションに追記
- [ ] 依存関係要件が実装計画書に明記されているか確認
- [ ] テスト実行環境の違い（WSL venv / コンテナ）が文書化されているか確認

**過去の事例**:
- **Phase K.4**: MLモデルは別コンテナで実行される設計だが、テストコード内で直接インポートしているため、WSL venvにも依存関係が必要（§K.4.7参照）

- [x] **MCPツールハンドラ検証** ✅
  - `tests/scripts/verify_mcp_tools.py`作成
  - `search_serp`ツール経由での検索が正常動作することを確認
  - バグ修正: `search_parsers._classify_source`が文字列を返していた問題を修正（SourceTag Enumに変換）

---

## 5. 保守・拡張 (Phase I-K)

### Phase I: 保守性改善 ✅

#### I.1 プロバイダ抽象化 ✅

| プロバイダ | 実装 | 状態 |
|-----------|------|:----:|
| SearchProvider | BrowserSearchProvider | ✅ |
| LLMProvider | OllamaProvider | ✅ |
| BrowserProvider | PlaywrightProvider, UndetectedChromeProvider | ✅ |
| NotificationProvider | LinuxNotifyProvider, WindowsToastProvider, WSLBridgeProvider | ✅ |

#### I.2 設定・ポリシーの外部化 ✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| ドメインポリシー | DomainPolicyManager + config/domains.yaml | ✅ |
| 検索エンジン設定 | SearchEngineConfigManager + config/engines.yaml | ✅ |
| ステルス設定 | - | 未実装 |

#### I.3 汎用コンポーネント

| 項目 | 状態 |
|------|:----:|
| 汎用サーキットブレーカ | ✅ |
| 汎用リトライ/バックオフ | ✅ |
| 汎用キャッシュレイヤ | 未実装 |

##### I.3.1 汎用サーキットブレーカ ✅

**実装内容**:
- `src/utils/circuit_breaker.py`: 依存ゼロの軽量コア
  - `CircuitBreaker`: 同期版、スレッドセーフ（threading.Lock）
  - `CircuitState`: 共有enum（CLOSED/OPEN/HALF_OPEN）
  - `AsyncCircuitBreaker`: 非同期ラッパー（コンテキストマネージャ対応）
  - `CircuitBreakerError`: 例外クラス
- `src/search/circuit_breaker.py`: 共有enumを使用、検索固有機能は維持
  - EMAメトリクス（success_rate_1h, latency_ema, captcha_rate）
  - DB永続化（datetime基準cooldown）
  - 指数バックオフ（failure historyベース）

**テスト**: `tests/test_utils_circuit_breaker.py`（32件）

##### I.3.2 汎用リトライ/バックオフ ✅

**実装内容**:
- `src/utils/backoff.py`: 指数バックオフ計算ユーティリティ
  - `BackoffConfig`: 設定（base_delay, max_delay, exponential_base, jitter_factor）
  - `calculate_backoff()`: リトライ遅延計算（§4.3.5準拠）
  - `calculate_cooldown_minutes()`: クールダウン計算（§4.3, §3.1.4準拠）
  - `calculate_total_delay()`: 総遅延時間計算（タイムアウト見積もり用）
- `src/utils/api_retry.py`: 公式API専用リトライ（§3.1.3, §4.3.5準拠）
  - `APIRetryPolicy`: ポリシー設定（retryable_exceptions, retryable_status_codes）
  - `retry_api_call()`: 非同期リトライ関数
  - `@with_api_retry`: デコレータ
  - 事前設定ポリシー: `JAPAN_GOV_API_POLICY`, `ACADEMIC_API_POLICY`, `ENTITY_API_POLICY`
- `src/search/circuit_breaker.py`: 共通ユーティリティを使用するよう更新
  - `_calculate_cooldown()` → `calculate_cooldown_minutes()` を使用

**仕様書更新**: `docs/requirements.md` §4.3.5「リトライ戦略の分類」を追加
- エスカレーションパス（検索/取得向け）: 同一経路での単純リトライ禁止
- ネットワーク/APIリトライ（トランジェントエラー向け）: 公式APIのみ適用可

**テスト**: `tests/test_utils_backoff.py`（26件）、`tests/test_utils_api_retry.py`（28件）

#### I.4 パーサー自己修復（AI駆動）✅

**目的**: 検索エンジンのHTML変更に対してAIが自動修復

**既存基盤**:
- `debug/search_html/`: 失敗時のHTML自動保存
- `config/search_parsers.yaml`: セレクター外部化
- 構造化ログ: 失敗セレクター名を明示

**タスク**:
- [x] 失敗時ログ + HTML保存（既存）
- [x] AIフレンドリーな失敗ログ強化
- [x] 修正ワークフロー設計（Cursorカスタムコマンド）

**実装内容**:

| ファイル | 内容 |
|---------|------|
| `src/search/parser_diagnostics.py` | 診断レポート生成（HTMLAnalyzer, YAML fix生成） |
| `src/search/search_parsers.py` | 診断レポート統合（parse()失敗時に自動生成） |
| `.cursor/commands/parser-repair.md` | Cursorカスタムコマンド（/parser-repair） |
| `tests/test_parser_diagnostics.py` | ユニットテスト（30件） |

**機能**:
- `ParserDiagnosticReport`: 失敗セレクター、候補要素、YAML修正案を含む構造化レポート
- `HTMLAnalyzer`: HTML構造分析、結果コンテナ/タイトル/スニペット/URL候補検出
- `generate_yaml_fix()`: 修正案をYAML形式で生成
- `/parser-repair`コマンド: 最新の失敗HTMLを分析し修正ワークフローを実行

---

### Phase J: 外部データソース統合 ⏳

#### J.0 API仕様調査（優先）

| API | 調査項目 | 状態 |
|-----|----------|:----:|
| e-Stat | 認証、エンドポイント、レート制限 | 未着手 |
| 法令API（e-Gov） | 同上 | 未着手 |
| 国会会議録API | 同上 | 未着手 |
| gBizINFO | 同上 | 未着手 |
| EDINET | 同上 | 未着手 |
| OpenAlex | 同上 | 未着手 |
| Semantic Scholar | 同上 | 未着手 |
| Crossref | 同上 | 未着手 |
| Unpaywall | 同上 | 未着手 |
| Wikidata | 同上 | 未着手 |

#### J.1 日本政府API統合

**対象（§3.1.3）**:
- e-Stat API: 統計データ
- 法令API（e-Gov）: 法令全文検索
- 国会会議録API: 国会議事録
- gBizINFO API: 法人基本情報
- EDINET API: 有価証券報告書

#### J.2 学術API統合

**対象（§3.1.3、§5.1.1）**:
- OpenAlex API: 論文メタデータ/引用グラフ
- Semantic Scholar API: 論文/引用ネットワーク
- Crossref API: DOI/引用情報
- Unpaywall API: OA版論文リンク

#### J.3 エンティティ解決強化

**対象（§3.1.3）**:
- Wikidata API
- DBpedia SPARQL

#### J.4 特許API統合

**対象（§3.1.3拡充）**:
- USPTO PAIR API: 米国特許出願状況
- USPTO PTAB API: 審判部決定
- EPO OPS API: 欧州特許データ
- J-PlatPat: HTMLスクレイピング（API非公開）
- CNIPA: HTMLスクレイピング（中国特許）

| API | 調査項目 | 状態 |
|-----|----------|:----:|
| USPTO PAIR | 認証、レート制限 | 未着手 |
| USPTO PTAB | 同上 | 未着手 |
| EPO OPS | OAuth2認証 | 未着手 |
| J-PlatPat | セレクター設計 | 未着手 |
| CNIPA | 言語対応、セレクター | 未着手 |

#### J.5 防衛・調達情報連携

**対象（§3.1.3拡充）**:
- 防衛省装備庁: 調達公告（HTMLスクレイピング）
- 米DoD契約: SAM.gov（政府調達DB）
- DTIC: Defense Technical Information Center

| ソース | 方式 | 状態 |
|--------|------|:----:|
| 防衛省装備庁 | HTMLスクレイピング | 未着手 |
| SAM.gov | API（無料） | 未着手 |
| DTIC | HTMLスクレイピング | 未着手 |

---

### Phase K: ローカルLLM強化 🔄

#### K.1 3B単一モデル化 ✅

**目的**: ローカルLLMを3B/7Bの2モデル体制から3B単一モデルに変更し、コードを簡素化する。VRAM制約（8GB）を考慮し、3Bモデルを選択。

**変更内容**:
- [x] 仕様書・実装計画書修正: docs/requirements.mdとdocs/IMPLEMENTATION_PLAN.mdを更新
- [x] 設定ファイル修正: `config/settings.yaml`と`src/utils/config.py`を更新
- [x] LLMプロバイダー修正: `src/filter/ollama_provider.py`を更新
- [x] LLM抽出ロジック修正: `src/filter/llm.py`から`use_slow_model`と`should_promote_to_slow_model()`を削除
- [x] 主張分解修正: `src/filter/claim_decomposition.py`から`use_slow_model`を削除
- [x] ジョブスケジューラ修正: `src/scheduler/jobs.py`で`LLM_FAST`/`LLM_SLOW`を`LLM`に統合
- [x] Calibrator関連削除: `src/utils/calibration.py`から`EscalationDecider`を削除
- [x] 呼び出し側修正: `src/research/executor.py`等で`use_slow_model`を削除
- [x] テスト修正: `tests/`配下の`fast_model`/`slow_model`関連テストを修正

**VRAM使用量（推定）**:
- 3B（約2.5GB）+ 埋め込み（約1GB）+ リランカー（約1GB）+ NLI（約0.5GB）= 約5GB（余裕あり）

#### K.2 プロンプトテンプレート外部化 ⏳

- [ ] `config/prompts/`: Jinja2テンプレート
- [ ] PromptManager実装

#### K.3 プロンプトインジェクション対策 ✅

収集コンテンツに含まれる悪意あるプロンプトインジェクションからローカルLLMを防御する多層防御を実装する。

**防御層サマリ**:

| 層 | 目的 | 状態 |
|----|------|:----:|
| L1: ネットワーク分離 | LLMから外部への直接送信を遮断 | ✅ |
| L2: 入力サニタイズ | 危険パターンの除去 | ✅ |
| L3: タグ分離 | システム/ユーザープロンプトの分離 | ✅ |
| L4: 出力検証 | URL/IP/プロンプト断片の検出 | ✅ |
| L5: MCP応答メタデータ | 信頼度情報の付与 | ✅ |
| L6: ソース検証フロー | 自動昇格/降格 | ✅ |
| **L7: MCP応答サニタイズ** | Cursor AI経由流出防止 | ✅ |
| **L8: ログセキュリティ** | ログ/DB/エラーからの漏洩防止 | ✅ |

##### K.3.1 ネットワーク分離（L1）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| Ollama内部ネットワーク専用化 | `podman-compose.yml`修正 | ✅ |
| 外部ネットワークアクセス遮断 | `internal: true` 設定 | ✅ |
| ホストポート公開禁止 | `ports`セクション削除 | ✅ |

##### K.3.2 システムインストラクション分離（L3）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| セッションごとランダムタグ生成 | `src/filter/llm_security.py` | ✅ |
| タグのログ非出力 | ハッシュ先頭8文字のみDEBUG出力 | ✅ |
| プロンプトテンプレート改修 | `src/filter/llm.py` | ✅ |

##### K.3.3 入力サニタイズ（L2）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| Unicode NFKC正規化 | `sanitize_llm_input()` | ✅ |
| HTMLエンティティデコード | 同上 | ✅ |
| ゼロ幅文字除去 | 同上 | ✅ |
| 制御文字除去 | 同上 | ✅ |
| タグパターン除去 | `LANCET-`プレフィックスパターン | ✅ |
| 危険単語検出・警告 | ログ出力 | ✅ |
| 入力長制限 | 4000文字 | ✅ |

##### K.3.4 出力検証（L4）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| 外部URLパターン検出 | `validate_llm_output()` | ✅ |
| IPアドレスパターン検出 | 同上 | ✅ |
| 異常長出力切り捨て | 期待長の10倍超 | ✅ |
| **システムプロンプト断片検出** | `detect_prompt_leakage()` | ✅ |
| **断片マスク処理** | `mask_prompt_fragments()` | ✅ |

**実装内容（§4.4.1 L4強化）**:
- n-gram一致検出（連続20文字以上）
- タグ名パターン検出（`LANCET-`プレフィックス）
- 検出時のマスク処理（`[REDACTED]`置換）
- 検出イベントの監査ログ出力
- `LeakageDetectionResult`データクラス追加
- `OutputValidationResult`に`leakage_detected`, `leakage_result`, `was_masked`フィールド追加
- `LLMSecurityContext`に`_leakage_count`メトリクス追加
- `llm_extract()`に出力検証を統合

**変更ファイル:**
- `src/filter/llm_security.py`: `detect_prompt_leakage()`, `mask_prompt_fragments()` 追加
- `src/filter/llm.py`: 出力処理に断片検出を組み込み
- `tests/test_llm_security.py`: L4強化テスト22件追加

##### K.3.5 MCP応答メタデータ（L5）✅

全MCP応答に検証状態を付与し、Cursor AIが信頼度を判断可能にする。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| `_lancet_meta` 付与 | `src/mcp/response_meta.py` (新規) | ✅ |
| claim検証状態付与 | `source_trust_level`, `verification_status` | ✅ |
| `create_task` 応答拡張 | `src/mcp/server.py` | ✅ |
| `get_status` 応答拡張 | `src/mcp/server.py` | ✅ |

**実装内容:**
- `src/mcp/response_meta.py`: メタデータ生成ヘルパー
  - `VerificationStatus` enum: pending/verified/rejected
  - `LancetMeta` dataclass: timestamp, security_warnings, blocked_domains, unverified_domains
  - `ClaimMeta` dataclass: per-claim検証情報
  - `ResponseMetaBuilder`: 流暢なビルダーAPI
  - `attach_meta()`, `create_minimal_meta()`: ヘルパー関数
- `src/mcp/server.py`: `create_task`, `get_status`ハンドラーに`_lancet_meta`追加

**テスト:** `tests/test_response_meta.py` (16件)

##### K.3.6 ソース検証フロー（L6）✅

EvidenceGraph連携による自動検証と昇格/降格ロジック。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| 検証ロジック | `src/filter/source_verification.py` (新規) | ✅ |
| EvidenceGraph連携 | `calculate_claim_confidence`, `find_contradictions` 利用 | ✅ |
| 自動昇格（→LOW） | 独立ソース≥2, 矛盾なし | ✅ |
| 自動降格（→BLOCKED） | 矛盾検出/危険パターン | ✅ |
| ドメイン検証状態追跡 | `DomainVerificationState` | ✅ |

**実装内容:**
- `src/filter/source_verification.py`: ソース検証ロジック
  - `SourceVerifier` クラス: 検証の中心
  - `verify_claim()`: EvidenceGraphを使った検証
  - `_determine_verification_outcome()`: 昇格/降格判定
  - `DomainVerificationState`: ドメインごとの検証状態追跡
  - `build_response_meta()`: MCP応答メタデータ生成
- 検証ロジック:
  - 独立ソース≥2 + 矛盾なし → `VERIFIED`, `UNVERIFIED`→`LOW`に昇格
  - 矛盾検出 or 危険パターン → `REJECTED`, `BLOCKED`に降格
  - 証拠不足 → `PENDING`, trust level維持
- 信頼度の高いドメイン（TRUSTED以上）は自動ブロックしない

**テスト:** `tests/test_source_verification.py` (27件)

##### K.3.7 TrustLevel変更 ✅

`UNKNOWN` / `SUSPICIOUS` を廃止し、検証状態を明確にする。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| TrustLevel enum再定義 | `src/utils/domain_policy.py` | ✅ |
| 信頼度ウェイト更新 | `DEFAULT_TRUST_WEIGHTS` | ✅ |
| domains.yaml更新 | `config/domains.yaml` | ✅ |

**実装内容:**
- TrustLevel enum変更:
  - 廃止: `UNKNOWN`, `SUSPICIOUS`
  - 追加: `LOW` (検証済み低信頼), `UNVERIFIED` (未検証), `BLOCKED` (除外)
- 新しいウェイト:
  - PRIMARY: 1.0, GOVERNMENT: 0.95, ACADEMIC: 0.90, TRUSTED: 0.75
  - LOW: 0.40, UNVERIFIED: 0.30, BLOCKED: 0.0
- 影響範囲: `TrustLevel`は`domain_policy.py`内のみで使用されており、他ファイルの`UNKNOWN`は別のEnum

**変更ファイル:**
- `src/utils/domain_policy.py`: TrustLevel enum再定義, DEFAULT_TRUST_WEIGHTS更新
- `config/domains.yaml`: default trust_level を `"unverified"` に変更
- `tests/test_domain_policy.py`: テストの期待値更新

##### K.3.8 BLOCKED通知（InterventionQueue連携）✅

ドメインがBLOCKEDになった際の通知機能。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| `auth_type="domain_blocked"` 追加 | `src/utils/notification.py` | ✅ |
| BLOCKED時の通知呼び出し | `src/filter/source_verification.py` | ✅ |
| Cursor AIへの応答 | `domain_blocked` 情報を含める | ✅ |

**実装内容:**
- `InterventionType.DOMAIN_BLOCKED` enum追加
- `notify_user(event="domain_blocked")` でInterventionQueue.enqueue呼び出し
- `notify_domain_blocked()` 便利関数追加
- `SourceVerifier._queue_blocked_notification()` でキューイング
- `SourceVerifier.send_pending_notifications()` で非同期送信
- 重複防止（同一ドメインは1回のみ通知）
- テスト13件追加（notification: 5件, source_verification: 8件）

**影響ファイル:**
- `src/utils/notification.py`: InterventionQueue拡張（新auth_type追加）
- `src/filter/source_verification.py`: BLOCKED時の通知呼び出し

##### K.3.9 MCP応答サニタイズ（L7）✅

MCP応答がCursor AIに渡る前の最終サニタイズ。Cursor AI経由のシステムプロンプト流出を防止する。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| 応答スキーマ定義 | `src/mcp/schemas/` (JSONSchema) | ✅ |
| スキーマ検証 | `ResponseSanitizer.validate_schema()` | ✅ |
| 予期しないフィールド除去 | `ResponseSanitizer.strip_unknown_fields()` | ✅ |
| LLMフィールドのL4通過強制 | `ResponseSanitizer.sanitize_llm_fields()` | ✅ |
| エラー応答サニタイズ | `ResponseSanitizer.sanitize_error()` | ✅ |
| MCPハンドラへの統合 | `src/mcp/server.py` 各ハンドラの出口 | ✅ |

**設計方針**:
- allowlist方式: 定義済みフィールドのみ通過、未定義は除去
- LLM生成フィールド（`extracted_facts`, `claims`, `summary`等）は必ず`validate_llm_output()`を通過
- エラー応答は汎用化し、詳細は`error_id`でログ参照

**影響ファイル:**
- 新規 `src/mcp/response_sanitizer.py`: サニタイズロジック
- 新規 `src/mcp/schemas/`: 各MCPツールの応答スキーマ（JSONSchema）
- `src/mcp/server.py`: 全ハンドラの出口にサニタイズレイヤ追加

**スキーマ例（search）**:
```json
{
  "type": "object",
  "properties": {
    "ok": {"type": "boolean"},
    "search_id": {"type": "string"},
    "query": {"type": "string"},
    "status": {"enum": ["satisfied", "partial", "exhausted"]},
    "pages_fetched": {"type": "integer"},
    "useful_fragments": {"type": "integer"},
    "harvest_rate": {"type": "number"},
    "claims_found": {"type": "array"},
    "satisfaction_score": {"type": "number"},
    "novelty_score": {"type": "number"},
    "budget_remaining": {"type": "object"},
    "_lancet_meta": {"type": "object"}
  },
  "additionalProperties": false
}
```

##### K.3.10 ログセキュリティポリシー（L8）✅

ログ・DB・エラーメッセージからの情報漏洩防止。

| 項目 | 実装 | 状態 |
|------|------|:----:|
| LLM入出力ログのサマリ化 | `SecureLogger.log_llm_io()` | ✅ |
| 例外サニタイズ | `SecureLogger.log_exception()` | ✅ |
| DBへのプロンプト非保存 | `src/storage/` 確認済み（プロンプト保存なし） | ✅ |
| 監査ログ（検出イベント） | `AuditLogger.log_security_event()` | ✅ |
| structlog統合 | `sanitize_log_processor` | ✅ |

**ログ出力フォーマット**:
```python
# Before (禁止)
logger.debug("LLM input", prompt=full_prompt_text)

# After (許可)
logger.debug("LLM input", 
    prompt_hash="abc123...",
    prompt_length=1500,
    prompt_preview="..."  # 先頭100文字のみ
)
```

**例外サニタイズ例**:
```python
try:
    result = llm.extract(prompt)
except Exception as e:
    # 内部ログ（詳細あり）
    internal_logger.error("LLM extraction failed", 
        error_id="err_abc123",
        exception=str(e),
        traceback=traceback.format_exc()
    )
    # MCP応答（詳細なし）
    return {"ok": False, "error": "Internal processing error", "error_id": "err_abc123"}
```

**影響ファイル:**
- 新規 `src/utils/secure_logging.py`: `SecureLogger`, `AuditLogger`
- `src/filter/llm.py`: ログ出力をSecureLogger経由に変更
- `src/mcp/server.py`: 例外ハンドリングにサニタイズ適用
- `src/storage/`: プロンプト保存箇所の確認・修正

##### K.3.11 テスト

| 項目 | 実装 | 状態 |
|------|------|:----:|
| ユニットテスト（L2/L3/L4基本） | `tests/test_llm_security.py` | ✅ |
| ユニットテスト（L4強化: 断片検出） | `tests/test_llm_security.py` 追加 | ✅ |
| ユニットテスト（L5: MCP応答メタデータ） | `tests/test_response_meta.py` | ✅ (30件, 100%カバレッジ) |
| ユニットテスト（L6: ソース検証フロー） | `tests/test_source_verification.py` | ✅ (43件, 100%カバレッジ) |
| ユニットテスト（L7: MCP応答サニタイズ） | `tests/test_response_sanitizer.py` | ✅ (29件) |
| ユニットテスト（L8: ログセキュリティ） | `tests/test_secure_logging.py` | ✅ (27件) |
| E2E: ネットワーク分離検証 | Ollamaから外部通信不可を確認 | ✅ |
| E2E: LLM応答検証 | サニタイズ済みプロンプトでの正常動作 | ✅ |
| E2E: タグ分離効果検証 | インジェクション攻撃の影響確認 | ✅ |
| E2E: MCP応答流出検証 | プロンプト断片がMCP応答に含まれないことを確認 | ✅ |

**L7テスト観点**:
- スキーマ検証: 不正フィールドが除去されること
- LLMフィールド: プロンプト断片が検出・マスクされること
- エラー応答: スタックトレース・内部パスが含まれないこと
- 正常応答: 必要なフィールドが欠落しないこと

**L8テスト観点**:
- ログ出力: プロンプト本文が記録されないこと
- 例外処理: サニタイズ後のメッセージが安全であること
- 監査ログ: セキュリティイベントが記録されること

**注**: E2EテストはGPU環境で実行が必要。`tests/scripts/verify_llm_security.py`として実装予定。

#### K.4 MLモデルのネットワーク分離 ✅

**状態**: **実装完了・動作確認済み** - MLサーバーは正常に機能しており、E2Eテストで全機能を検証済み。

**目的**: 埋め込み・リランカー・NLIモデルをネットワーク分離し、セキュリティを強化する。

**背景**:
K.1の調査で以下が判明:
- 埋め込み（bge-m3）、リランカー（bge-reranker-v2-m3）、NLI（DeBERTa）はLancetコンテナ内で実行
- これらはHuggingFaceから初回ダウンロード後、外部アクセス不要
- Ollamaと同様にネットワーク分離すべき

**実装方針**:
- 埋め込み・リランカー・NLIを「MLコンテナ」に集約
- Ollamaと同じ`lancet-internal`ネットワーク（`internal: true`）に配置
- Lancetコンテナからのみアクセス可能に
- モデルはビルド時にダウンロードしてイメージに含める

**タスク**:
- [x] 仕様書にMLモデルのセキュリティ方針を追記（docs/requirements.md L1セクション）
- [x] MLコンテナ用Dockerfile作成（`Dockerfile.ml`）
- [x] `podman-compose.yml`にMLコンテナ追加（`lancet-ml`サービス）
- [x] `lancet-internal`ネットワーク追加（`internal: true`、Ollamaと共用）
- [x] 埋め込み・リランカー・NLIのAPI化（`src/ml_server/` FastAPI）
- [x] LancetコンテナからMLコンテナへの通信実装（`src/ml_client.py`）
- [x] 既存の`ranking.py`/`nli.py`をリモート呼び出しに対応
- [x] `.env`にML設定追加、`config.py`に`MLServerConfig`追加

**実装済みファイル**:
- `Dockerfile.ml` - MLサーバーコンテナ（ビルド時にモデルダウンロード）
- `requirements-ml.txt` - ML依存関係
- `scripts/download_models.py` - モデルダウンロードスクリプト
- `src/ml_server/` - FastAPIサーバー（embed/rerank/nli エンドポイント）
- `src/ml_client.py` - HTTPクライアント

**実装完了**:
- [x] MLサーバーの全機能が正常に動作（E2Eテストで検証済み）
  - 埋め込みAPI（bge-m3）: ✅ 動作確認済み
  - リランキングAPI（bge-reranker-v2-m3）: ✅ 動作確認済み
  - NLI API（nli-deberta-v3-xsmall/small）: ✅ 動作確認済み
  - オフラインモード: ✅ 動作確認済み（HuggingFace API呼び出しなし）
- [x] オフラインモードでのモデルロード問題の解決
  - 解決方法: `huggingface_hub.snapshot_download()`でモデルのローカルパスを取得し、`model_paths.json`に保存
  - `src/ml_server/model_paths.py`でパス管理モジュールを実装
  - 各サービス（embedding/reranker/nli）をローカルパス指定に変更
  - `download_models.py`を修正し、オフラインモードでも既存モデルからパスを取得可能に
- [x] テストコード作成
  - `tests/test_ml_server.py`: 32件のユニットテスト（model_paths, embedding, reranker, nli）
    - ML依存関係がない場合は適切にスキップ（12件スキップ、20件パス）
    - スキップメッセージでE2Eテストを推奨
  - `tests/test_ml_server_e2e.py`: E2Eテスト（API統合テスト、6件全てパス）
    - HTTP経由でMLサーバーを検証（推奨方法）
- [x] E2E動作確認
  - コンテナ内で動作確認済み
  - オフラインモードでモデルロード成功
  - 埋め込みAPI動作確認済み
  - リランキングAPI動作確認済み
  - NLI API動作確認済み
- [x] テスト戦略の改善
  - ML依存関係チェック機能を追加（`_HAS_SENTENCE_TRANSFORMERS`, `_HAS_TRANSFORMERS`）
  - スキップデコレータ（`@requires_sentence_transformers`, `@requires_transformers`）を追加
  - 明確なスキップメッセージでE2Eテストを推奨
  - E2Eテストフィクスチャの非同期対応を修正（イベントループ競合を解消）

**知見・トラブルシューティング**:

1. **オフラインモードでのモデルロード問題**
   - **問題**: `HF_HUB_OFFLINE=1`と`local_files_only=True`を設定しても、`sentence-transformers`や`transformers`がHuggingFace APIにアクセスを試みる
   - **原因**: モデル名（例: `BAAI/bge-m3`）を直接指定すると、ライブラリが内部でメタデータ取得のためAPIアクセスを試みる
   - **解決策**: 
     - `huggingface_hub.snapshot_download()`でモデルをダウンロードし、ローカルパスを取得
     - ローカルパスを`model_paths.json`に保存し、実行時にこのパスを直接使用
     - パスを直接指定することで、ライブラリがAPIアクセスを試みない
   - **実装**: `download_models.py`でオフラインモード時は`try_to_load_from_cache()`で既存キャッシュからパスを取得

2. **テストコード設計の知見**
   - **モックパッチのパス指定**: `src.ml_server.embedding.SentenceTransformer`ではなく、`sentence_transformers.SentenceTransformer`をパッチする必要がある（ライブラリのインポート元を直接パッチ）
   - **GPU関連のモック**: `SentenceTransformer`の`to("cuda")`呼び出しに対応するため、`mock_model.to = MagicMock(return_value=mock_model)`を設定
   - **ML依存関係のスキップ処理**: ML依存関係（`sentence_transformers`, `transformers`）がない場合、テストをスキップし、E2Eテストを推奨するメッセージを表示
     - `@requires_sentence_transformers` / `@requires_transformers` デコレータを実装
     - スキップメッセージで「Use E2E tests (test_ml_server_e2e.py) for ML validation」を明示
   - **E2Eテストの推奨**: MLサーバーの検証はE2Eテスト（HTTP経由）が推奨方法
     - アーキテクチャ: WSL (pytest) → localhost:8080 (proxy) → lancet-ml:8100 (ML Server)
     - 実際のHTTP通信を検証するため、より信頼性が高い
   - **FastAPIテストの分離**: メインコンテナにはFastAPIがインストールされていないため、FastAPI TestClientを使うテストは`@pytest.mark.skip`でスキップし、E2Eテストで代替
   - **非同期フィクスチャの修正**: E2Eテストのフィクスチャで`asyncio.run()`を使うとイベントループ競合が発生するため、`async def`フィクスチャにして`await client.close()`を使用

3. **既存テストの修正**
   - **問題**: `EmbeddingRanker`と`Reranker`のテストがリモートモード（`ml.use_remote=True`）を考慮していない
   - **解決策**: `use_remote=False`をモックしてローカルモードを強制し、ローカルモデルを使うテストとして実行
   - **影響**: 既存のテストロジックは維持しつつ、リモート/ローカルモードの切り替えに対応

4. **パフォーマンス最適化**
   - **空リスト時のモデルロード回避**: `encode()`や`rerank()`で空リストが渡された場合、早期リターンしてモデルロードをスキップ（`await self.load()`の前に`if not texts: return []`を配置）
   - **効果**: 不要なモデルロードを回避し、レスポンス時間を短縮

5. **Dockerビルド時の注意点**
   - `model_paths.json`の存在確認をDockerfileに追加（`RUN test -f /app/models/model_paths.json || exit 1`）
   - `/app/models`ディレクトリを事前に作成（`RUN mkdir -p /app/models`）
   - オフラインモードでのビルド時は、事前にモデルをキャッシュしておく必要がある

6. **回帰テストの結果と依存関係要件**
   - **注意**: 回帰テスト実行には、オプショナルな依存関係の確認が必要
   - **コア機能テスト**: WSL venv（`requirements-mcp.txt`）のみで実行可能
   - **オプショナル機能テスト**: 以下の依存関係が必要（インストールされていない場合はテストが失敗する）
     - **ML関連** (`requirements-ml.txt`): `sentence-transformers`, `transformers`, `torch`
       - 影響テスト: `tests/test_ml_server.py`（`import torch`等の直接インポート）
     - **PDF/OCR関連**: `PyMuPDF` (`fitz`), `Pillow` (`PIL`)
       - 影響テスト: `tests/test_extractor.py`（PDF抽出、OCR機能）
   - **実装状況**:
     - MLモデルは別コンテナ（`lancet-ml`）で実行される設計だが、テストコード内で直接インポートしているため、WSL venvにも依存関係が必要
     - モックを使用しているテストでも、インポート時に依存関係がチェックされるため、事前インストールが必要
   - **回帰テスト実行前の確認タスク**:
     - [x] ML依存関係チェック機能を実装（ML依存関係がない場合は適切にスキップ）
     - [x] E2Eテストを推奨方法として明確化（`test_ml_server_e2e.py`）
     - [ ] WSL venvにオプショナル依存関係がインストールされているか確認（オプショナル）
       ```bash
       # ML関連依存関係の確認（オプショナル - スキップされるが、ローカルでモックテストを実行する場合は必要）
       python -c "import sentence_transformers, transformers, torch" 2>/dev/null && echo "ML deps OK" || echo "ML deps MISSING"
       
       # PDF/OCR関連依存関係の確認
       python -c "import fitz, PIL" 2>/dev/null && echo "PDF/OCR deps OK" || echo "PDF/OCR deps MISSING"
       ```
     - **注意**: ML依存関係がなくても、`test_ml_server.py`は20件のテストがパスし、ML依存関係が必要な12件は適切にスキップされる
     - **推奨**: MLサーバーの検証は`pytest tests/test_ml_server_e2e.py -v -m e2e`を使用（ML依存関係不要）
   - **過去の回帰テスト結果**（依存関係インストール済み環境）:
     - 全2728テストが成功（4テストスキップ、23テスト除外）
     - 既存機能への影響なし
     - MLサーバーのテストは26件成功、4件スキップ（FastAPI TestClient関連）
   - **現在のテスト結果**（ML依存関係チェック実装後）:
     - `test_ml_server.py`: 20 passed, 12 skipped（ML依存関係チェックによる適切なスキップ）
     - `test_ml_server_e2e.py`: 6 passed（MLサーバーの全機能をHTTP経由で検証）
     - **ML実装は正常に機能**: E2Eテストで埋め込み・リランキング・NLIの全機能が動作確認済み

7. **テスト実行時の依存関係について（解決済み）**
   - **問題**: テストコード内で直接インポート（`import torch`, `from PIL import Image`等）しているため、モックを使う前にインポートが実行され、依存関係がインストールされていないと失敗する
   - **解決策**: ML依存関係チェック機能を実装し、依存関係がない場合はテストをスキップ
     - `_HAS_SENTENCE_TRANSFORMERS` / `_HAS_TRANSFORMERS` フラグで依存関係をチェック
     - `@requires_sentence_transformers` / `@requires_transformers` デコレータでスキップ
     - スキップメッセージでE2Eテストを推奨（`test_ml_server_e2e.py`）
   - **現在の動作**:
     - WSL venvで`pytest tests/test_ml_server.py`を実行すると、ML依存関係が必要なテスト（8件）はスキップされ、残り（20件）は正常にパス
     - E2Eテスト（`test_ml_server_e2e.py`）はML依存関係不要で、HTTP経由でMLサーバーを検証（6件全てパス）
     - **推奨**: MLサーバーの検証はE2Eテストを使用（`pytest tests/test_ml_server_e2e.py -v -m e2e`）
   - **影響範囲**:
     - `tests/test_ml_server.py`: ML依存関係が必要なテストはスキップ（`sentence-transformers`, `transformers`, `torch`）
     - `tests/test_extractor.py`: PDF/OCR関連テストは未対応（将来の改善案）
   - **テスト結果**:
     - Unit tests: 20 passed, 12 skipped（ML依存関係チェックによる適切なスキップ）
     - E2E tests: 6 passed（MLサーバーの全機能をHTTP経由で検証）
   - **実装計画書の更新**: 本セクションに追記し、Phase G.2にも注意事項を追加（§G.2、§G.4参照）

8. **セキュリティ対策: パス検証とサニタイズ**
   - **問題**: `model_paths.json`に不正なパス（パストラバーサル、許可外ディレクトリ）が含まれている場合のリスク
   - **対策**: `_validate_and_sanitize_path()`関数を実装
     - パスを絶対パスに正規化（`Path.resolve()`）
     - `/app/models/`配下であることを確認（`relative_to()`で検証）
     - パストラバーサル（`../`）を検出・拒否
   - **実装**: `get_model_paths()`でJSONから読み込んだ全てのパスを検証し、検証失敗時は`None`を返してフォールバック（モデル名使用）に切り替え
   - **テスト**: パストラバーサル攻撃と許可外ディレクトリへのアクセスを防ぐテストを追加
   - **リスク評価**: 低リスク（コンテナ内のファイルシステムへの書き込み権限が必要だが、防御的プログラミングとして実装）

---

## 6. 検証・文書・リファクタリング (Phase L, M, N)

> **注**: Phase M (MCPリファクタリング) は保守性改善の一環だが、Phase N (E2Eケーススタディ) の前提条件となるため、本セクションに配置。

### Phase L: ドキュメント ⏳

#### L.1 未作成ドキュメント

- [ ] README.md（プロジェクト概要、セットアップ手順）
- [ ] 手動介入運用手順書（§6成果物）
- [ ] MCPツール仕様書（§6成果物）
- [ ] ジョブスケジューラ仕様書（§6成果物）
- [ ] プロファイル健全性監査運用手順

---

### Phase M: MCPツールリファクタリング ✅

MCPツールを**30個から11個**に簡素化。実装完了、E2E検証は Phase N で実施。

#### M.1 設計方針

**目的**:
- Cursor AIの認知負荷低減（ツール選択の単純化）
- 低レベル操作の隠蔽（Cursor AIはパイプラインの詳細を知る必要がない）
- 責任分界の明確化（Cursor AI = 戦略、Lancet = 戦術）
- セキュリティ境界の明確化（公開APIを最小化）

**統一アーキテクチャ方針**:

MCPハンドラーは薄いラッパーとし、ロジックはドメインモジュールの統合API（action-based）に集約する。

```
MCPハンドラー (_handle_*)
    ↓ 薄いラッパー（引数変換・エラーハンドリングのみ）
ドメインモジュールの統合API (action-based)
    ↓
内部クラス・関数
```

#### M.2 新MCPツール一覧（11ツール）✅

| カテゴリ | ツール | 機能 | 実装 | テスト |
|---------|--------|------|:----:|:------:|
| タスク管理 | `create_task` | タスク作成 | ✅ | ✅ |
| タスク管理 | `get_status` | 統合状態取得 | ✅ | ✅ (11件) |
| 調査実行 | `search` | 検索パイプライン | ✅ | ✅ (18件) |
| 調査実行 | `stop_task` | タスク終了 | ✅ | ✅ |
| 成果物 | `get_materials` | レポート素材取得 | ✅ | ✅ |
| 校正 | `calibrate` | 校正操作（5 action） | ✅ | ✅ (26件) |
| 校正 | `calibrate_rollback` | ロールバック | ✅ | ✅ (13件) |
| 認証キュー | `get_auth_queue` | 認証待ちリスト | ✅ | ✅ (19件) |
| 認証キュー | `resolve_auth` | 認証完了報告 | ✅ | ✅ |
| 通知 | `notify_user` | ユーザー通知 | ✅ | ✅ (21件) |
| 通知 | `wait_for_user` | ユーザー入力待機 | ✅ | ✅ |

#### M.3 実装状況 ✅

| 項目 | 状態 |
|------|:----:|
| 11個の新ツール定義（`src/mcp/server.py`） | ✅ |
| 11個のハンドラー実装（`_handle_*`） | ✅ |
| `SearchPipeline`（`src/research/pipeline.py`） | ✅ |
| 用語統一（subquery → search） | ✅ |
| エラーコード体系（`src/mcp/errors.py`） | ✅ |
| 旧ツール定義の削除（29個 → 0個） | ✅ |

#### M.4 内部パイプライン ✅

低レベル操作はMCPから隠蔽され、`search`ツールから自動的に呼び出される。

```python
# src/research/pipeline.py: SearchPipeline.execute()
1. search_serp: 検索エンジンへのクエリ実行
2. fetch_url: URL取得（並列）
3. extract_content: テキスト抽出
4. rank_candidates: ランキング
5. llm_extract: 事実/主張抽出
6. nli_judge: 反証モードの場合のみ
7. 状態更新
```

#### M.5 テスト状況 ✅

| ファイル | 対象 | 件数 |
|---------|------|:----:|
| `test_mcp_errors.py` | エラーコード体系 | 21件 |
| `test_calibrate_rollback.py` | `calibrate_rollback` | 13件 |
| `test_mcp_get_status.py` | `get_status` | 11件 |
| `test_mcp_calibrate.py` | `calibrate`（5 action） | 26件 |
| `test_mcp_search.py` | `search`, `get_materials` | 18件 |
| `test_mcp_auth.py` | `get_auth_queue`, `resolve_auth` | 19件 |
| `test_mcp_notification.py` | `notify_user`, `wait_for_user` | 21件 |

**E2E検証**: Phase N で実施予定

#### M.6 残作業

| 項目 | 状態 | 備考 |
|------|:----:|------|
| Cursor AI無応答ハンドリング（§2.1.5） | ⏳ | 300秒タイムアウト→状態保存→待機 |
| DBスキーマ列名変更（subquery→search） | ⏳ | 既存データ考慮、将来マイグレーション |

---

### Phase N: E2Eケーススタディ（論文投稿向け）⏳🔴優先

論文投稿に必要な「動くソフトウェア」の実証。**E2E環境確認 → MCPツール疎通確認 → ケーススタディ実施** の順で進める。

#### N.1 目的

| 観点 | 目的 |
|------|------|
| **統合動作確認** | Phase A-M の成果が連結して動作することの実証 |
| ケーススタディ | 論文に記載する具体的な使用例の作成 |
| OSS価値の実証 | 透明性・監査可能性・再現性の確保 |

#### N.2 E2E実行環境確認 ✅

**目的**: 実環境で各コンポーネントが正しく動作することを確認

**実装**: `tests/scripts/verify_environment.py`

| 確認項目 | 方法 | 状態 |
|---------|------|:----:|
| Podmanコンテナ起動 | コンテナ内からの実行確認 | ✅ |
| Chrome CDP接続 | Playwright CDP接続（15秒タイムアウト） | ✅ |
| Ollama LLM起動 | OllamaProvider.get_health() | ✅ |
| コンテナ間通信 | lancet → ollama (内部ネットワーク) | ✅ |
| 検索エンジン疎通 | CDP依存、スキップ可能 | ✅ |
| トースト通知 | NotificationProviderRegistry | ✅ |

**検証結果（2025-12-10）**:
- Container Environment: ✓ PASS
- Ollama LLM: ✓ PASS（モデル2つ利用可能）
- Container Network: ✓ PASS
- Chrome CDP: 環境依存（WSL→Windowsポートプロキシ設定要）
- Notification: 環境依存（コンテナ内からpowershell不可）

**手順**:
```bash
# 1. 全サービス起動
./scripts/dev.sh up

# 2. Chrome リモートデバッグモード起動（Windows側）
./scripts/chrome.sh start

# 3. 環境確認スクリプト実行
podman exec lancet python tests/scripts/verify_environment.py

# 4. 検索テスト（Chrome接続後）
podman exec lancet python tests/scripts/verify_duckduckgo_search.py
```

#### N.3 MCPツール疎通確認 ✅

**目的**: 11個の新MCPツールが実環境で正しく動作することを確認

| ツール | 確認内容 | 状態 |
|--------|---------|:----:|
| `create_task` | タスクがDBに作成される | ✅ |
| `get_status` | タスク状態が正しく返る | ✅ |
| `search` | 検索パイプラインが完走する | ✅ |
| `stop_task` | タスクが終了し統計が返る | ✅ |
| `get_materials` | エビデンスグラフが構築される | ✅ |
| `calibrate` | 校正サンプルが登録される | ✅ |
| `get_auth_queue` | 認証待ちが取得できる | ✅ |
| `resolve_auth` | 認証完了が記録される | ✅ |
| `notify_user` | トースト通知が表示される | ✅ |
| `wait_for_user` | ユーザー入力待機が動作する | ✅ |

**ハイブリッド構成でのChrome CDP接続**:

ハイブリッド構成（Phase O）では、MCPサーバーがWSL上で直接実行されるため、Chrome接続が簡素化されます。

1. **Chrome起動**:
   ```bash
   ./scripts/chrome.sh start
   # WSL→Windows Chromeに直接接続（localhost:9222）
   ```

2. **MCPサーバー起動**（Cursorが自動実行）:
   ```bash
   ./scripts/mcp.sh
   ```

3. **テスト実行**:
   ```bash
   # venvから直接実行（推奨）
   source .venv/bin/activate
   python tests/scripts/verify_mcp_integration.py

   # 基本モード（Chrome CDP不要）
   python tests/scripts/verify_mcp_integration.py --basic
   ```

**検証結果（2025-12-11）**:
- 全11ツール: ✅ PASS（フル検証）
- Chrome CDP接続: ✅ PASS（WSL直接接続）
- プロキシ接続: ✅ PASS（localhost:8080経由）

#### N.4 セキュリティE2E ✅

Phase K.3 の防御層が統合環境で正しく動作することを確認。

**実装**: `tests/scripts/verify_llm_security.py`

| 層 | 確認内容 | 状態 |
|----|---------|:----:|
| L1 | Ollamaから外部通信不可（`internal: true`ネットワーク） | ✅ |
| L2/L3/L4 | サニタイズ済みプロンプトでLLM正常動作 | ✅ |
| L5 | MCP応答に`_lancet_meta`が含まれる | ✅ |
| L6 | ソース検証フロー動作確認 | ✅ |
| L7 | 予期しないフィールドが除去される | ✅ |
| L8 | ログにプロンプト本文が含まれない | ✅ |

**検証結果（2025-12-10）**:
- L1: ネットワーク設定で`internal: true`確認済み
- L2/L3/L4: タグパターン除去、危険パターン検出、出力検証が正常動作
- L5: `create_task`/`get_status`に`_lancet_meta`付与確認
- L6: `DomainVerificationState`とレスポンスメタ生成が正常動作
- L7: 不明フィールド除去、LLMコンテンツサニタイズが正常動作
- L8: ハッシュ/長さ/プレビューのみ記録、センシティブ内容マスク確認

**手順**:
```bash
podman exec lancet python tests/scripts/verify_llm_security.py
```

#### N.5 Chrome CDP接続エラーハンドリング改善 ✅

**問題**: MCP `search` ツール実行時にChrome CDPが未接続の場合、`status: "running"` が返され、Cursor AIに失敗の原因が伝わらない。

**解決**: Chrome自動起動機能を実装。CDP未接続時は `./scripts/chrome.sh start` を自動実行し、UXを改善。

##### N.5.1 問題分析

**データフロー**:
```
_handle_search() (server.py)
  → search_action() (pipeline.py)
  → SearchPipeline.execute()
  → _execute_normal_search()
  → SearchExecutor.execute() (executor.py)
  → _execute_search()
  → search_serp() (search_api.py)
  → _search_with_provider()
  → BrowserSearchProvider.search() ← CDPエラー発生点
```

**問題点**:
| 箇所 | 問題 |
|------|------|
| `BrowserSearchProvider.search()` | `CDPConnectionError` を `SearchResponse(error=...)` に変換 |
| `_search_with_provider()` | エラー時に警告ログ→空リスト返却、エラー情報は伝播せず |
| `SearchExecutor.execute()` | 初期値 `status="running"` のまま、SERP結果0件でも更新されない場合あり |
| `_handle_search()` | `search_action()` の結果をそのまま返却、CDP未接続でも `"running"` が返る |

**根本原因**:
- Chrome CDP未接続は**致命的なインフラ障害**だが、パイプラインはこれを「検索結果0件」と同等に扱う
- Cursor AIには「何が問題か」「どう対処すべきか」が伝わらない

##### N.5.2 解決策設計

**方針**: CDP未接続は**検索パイプラインの前提条件未充足**として、明確なエラーコードで即座に報告する。

**タスク一覧**:

| ID | 項目 | 状態 |
|----|------|:----:|
| N.5.2-1 | MCPエラーコード `CHROME_NOT_READY` 追加 | ✅ |
| N.5.2-2 | `search` ハンドラにCDP事前チェック追加 | ✅ |
| N.5.2-3 | Chrome自動起動機能の実装 | ✅ |
| N.5.2-4 | docs/requirements.md §3.2.1 に仕様追記 | ✅ |
| N.5.2-5 | E2Eテスト（CDP未接続→自動起動→検索成功の確認） | ✅ |

**設計詳細**:

1. **MCPエラーコード追加** (`src/mcp/errors.py`):
   ```python
   CHROME_NOT_READY = "CHROME_NOT_READY"
   """Chrome CDP is not connected.
   Auto-start was attempted but failed."""
   
   class ChromeNotReadyError(MCPError):
       """Raised when Chrome CDP connection is not available after auto-start attempt."""
   ```

2. **Chrome自動起動機能** (`src/mcp/server.py`):
   - `_ensure_chrome_ready()` ヘルパー関数を追加
   - 起動フロー:
     1. CDP接続チェック（`http://localhost:{port}/json/version`）
     2. 未接続の場合、`subprocess.run()` で `./scripts/chrome.sh start` を実行
     3. 最大15秒間、0.5秒間隔でCDP接続をポーリング
     4. 接続成功 → `True` を返却（検索続行）
     5. 接続失敗 → `ChromeNotReadyError` を発生

   ```python
   async def _ensure_chrome_ready(self, port: int = 9222, timeout: float = 15.0) -> bool:
       """Ensure Chrome CDP is ready, auto-starting if needed."""
       # 1. Check if already connected
       if await self._check_cdp_connection(port):
           return True
       
       # 2. Auto-start Chrome
       script_path = Path(__file__).parent.parent.parent / "scripts" / "chrome.sh"
       result = subprocess.run([str(script_path), "start"], capture_output=True, text=True)
       
       # 3. Wait for CDP connection
       start_time = time.monotonic()
       while time.monotonic() - start_time < timeout:
           if await self._check_cdp_connection(port):
               return True
           await asyncio.sleep(0.5)
       
       # 4. Failed
       raise ChromeNotReadyError("Auto-start failed")
   ```

3. **CDP事前チェック統合** (`_handle_search()`):
   - 検索パイプライン開始前に `await self._ensure_chrome_ready()` を呼び出し
   - 自動起動の結果をログに記録

4. **エラーメッセージ**（自動起動失敗時）:
   ```json
   {
     "ok": false,
     "error_code": "CHROME_NOT_READY",
     "error": "Chrome CDP is not connected. Auto-start failed. Check: ./scripts/chrome.sh diagnose",
     "details": {
       "auto_start_attempted": true,
       "hint": "Verify Chrome is installed and WSL2 mirrored networking is enabled"
     }
   }
   ```

5. **docs/requirements.md更新** (§3.2.1): ✅ 完了
   - `search` ツールの前提条件にChrome自動起動を明記
   - 自動起動のフロー・タイムアウト・エラー応答を定義

##### N.5.3 実装方針

- **自動起動を行う**: CDP未接続時、Lancetは `./scripts/chrome.sh start` を自動実行してChromeを起動する
  - UX最優先: Lancetを使う以上Chrome CDP接続は必須であり、ユーザーに毎回手動起動を求めるのはUX上許容できない
  - ハイブリッド構成（Phase O）により、WSL→Windows Chromeへの直接接続が可能
- **エラーは自動起動失敗時のみ**: 自動起動を試行し、成功すれば検索を続行。失敗した場合のみ `CHROME_NOT_READY` エラーを報告
- **事前チェック**: パイプライン開始前に `_ensure_chrome_ready()` で接続確認・自動起動を行い、検索途中での失敗を防止
- **既存フロー保持**: `BrowserSearchProvider` 内部のエラーハンドリングは変更せず、MCPハンドラ層で自動起動を対処

#### N.6 ケーススタディ（CS-1）

**シナリオ**: リラグルチド（Liraglutide）の安全性情報収集

| 項目 | 内容 |
|------|------|
| 対象 | FDA/PMDA/EMA横断での安全性情報 |
| クエリ例 | "liraglutide FDA safety alert", "リラグルチド PMDA 安全性速報" |
| 期待成果 | 複数ソースからの情報収集、エビデンスグラフ構築 |

**実施手順**:
```
1. タスク作成
   - Cursor AI: create_task("リラグルチドの安全性情報調査")

2. 検索クエリ実行（Cursor AI主導）
   - search(task_id, "liraglutide FDA safety alert")
   - search(task_id, "リラグルチド PMDA 安全性速報")
   - get_status(task_id) で進捗確認

3. 反証探索
   - search(task_id, "liraglutide adverse events", refute=true)

4. 成果物取得
   - get_materials(task_id)
   - エビデンスグラフの可視化

5. 記録整理
   - スクリーンショット、ログ、図表作成
```

#### N.7 成功基準

| 基準 | 閾値 | 測定方法 |
|------|------|---------|
| パイプライン完走 | 全ステップ成功 | ログのcause_id連結確認 |
| エビデンスグラフ構築 | ≥5件の主張-断片-ソース関係 | `get_materials`の返却値 |
| 検索エンジン多様化 | ≥3エンジンから結果取得 | 検索ログ |
| エラーなし完了 | 未処理例外ゼロ | ログ確認 |

#### N.8 記録項目

| 項目 | 形式 | 用途 |
|------|------|------|
| 実行ログ | JSONL | 再現性、因果トレース |
| スクリーンショット | PNG | 論文図表、デモ |
| エビデンスグラフ | JSON/GraphML | 論文図表 |
| 実行時間・リソース | メトリクス | 性能評価 |
| WARC/PDF | アーカイブ | 監査可能性の実証 |

#### N.9 OSS価値の実証ポイント

論文で強調すべき「OSS + ローカル完結」の価値:

| 価値 | 実証方法 |
|------|---------|
| **透明性** | 全コードがGitHubで公開、監査可能 |
| **セキュリティ** | 検索クエリ・収集情報が外部サーバーに送信されない |
| **再現性** | 同一環境で同一結果が得られる |
| **カスタマイズ性** | ドメインポリシー・検索エンジン設定が変更可能 |

**商用ツールとの差別化**:
- Perplexity/ChatGPT: クエリがサーバーに送信される
- Google Deep Research: 収集情報がGoogleに蓄積される
- Lancet: **すべてローカル完結、ログは手元にのみ存在**

---

### Phase O: ハイブリッド構成リファクタリング ✅

MCPサーバーをWSL側で直接実行し、ネットワーク構成を簡素化する。

#### O.1 設計動機

**旧構成の問題点**:
- コンテナ→Windows Chromeへの接続が複雑（socat、host-gateway必須）
- Chrome自動起動がコンテナからは困難
- WSL2 mirrored networkingへの強い依存
- execution_mode分岐によるコード複雑化

**新構成（ハイブリッド）の利点**:
- WSL→Windows Chromeが直接接続（localhost:9222）
- socatポートフォワード不要
- Chrome自動起動が容易（`chrome.sh start`を直接実行）
- コンテナはOllama/ML Serverのみ（ネットワーク分離維持）
- execution_mode分岐不要（常にWSLモード）

#### O.2 実装完了項目 ✅

| 項目 | ファイル | 状態 |
|------|---------|:----:|
| プロキシサーバー | `src/proxy/server.py` | ✅ |
| MCP起動スクリプト | `scripts/mcp.sh` | ✅ |
| 軽量依存関係 | `requirements-mcp.txt` | ✅ |
| 設定拡張 | `src/utils/config.py`, `.env` | ✅ |
| OllamaProviderプロキシ対応 | `src/filter/ollama_provider.py` | ✅ |
| MLClientプロキシ対応 | `src/ml_client.py` | ✅ |
| podman-compose更新 | `podman-compose.yml` | ✅ |
| E2E動作確認 | プロキシ経由接続確認 | ✅ |

#### O.3 リファクタリング計画（完全削除・簡素化）⏳

ハイブリッド構成により不要になった複雑なネットワーク設定と実行モード分岐を**すべて削除**する。

##### O.3.1 socat関連コード完全削除

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `scripts/chrome.sh` | `start_socat`, `stop_socat`, `check_socat`関数削除（L232-309） | ~78行 | 高 |
| `scripts/chrome.sh` | `get_status`内のsocatチェック削除（L327-336） | ~10行 | 高 |
| `scripts/chrome.sh` | `start_chrome_wsl`内のsocat起動削除（L371-384） | ~14行 | 高 |
| `scripts/chrome.sh` | `stop_chrome`内のsocat停止削除（L499-502） | ~4行 | 高 |
| `scripts/chrome.sh` | `SOCAT_PID_FILE`定数削除（L47） | 1行 | 高 |
| `scripts/common.sh` | `SOCAT_PORT`定数削除（L81） | 1行 | 高 |
| `src/mcp/errors.py` | `ChromeNotReadyError`の`is_podman`パラメータとsocatヒント削除（L328-336） | ~9行 | 高 |
| `src/mcp/server.py` | `is_podman`検出コード削除（L806-811） | ~6行 | 高 |
| `src/search/browser_search_provider.py` | socatヒント削除（L201-208） | ~8行 | 中 |
| `src/crawler/playwright_provider.py` | socatヒント削除（L157-160） | ~4行 | 中 |
| `src/crawler/fetcher.py` | socatヒント削除（L765-768） | ~4行 | 中 |
| `tests/test_mcp_errors.py` | `test_podman_environment`テスト削除（L420-433） | ~14行 | 中 |

**合計削除行数**: ~152行

##### O.3.2 host-gateway関連完全削除

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `podman-compose.yml` | `extra_hosts`設定削除（L23-24） | 2行 | 高 |
| `config/settings.yaml` | `10.255.255.254`コメント削除（L133-135） | 3行 | 低 |

**合計削除行数**: ~5行

##### O.3.3 execution_mode分岐完全削除

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `src/utils/config.py` | `execution_mode`フィールド削除、常にプロキシ経由に固定（L226-232） | ~7行 | 高 |
| `src/filter/ollama_provider.py` | execution_mode分岐削除、常にプロキシURL使用（L89-95） | ~7行 | 高 |
| `src/ml_client.py` | execution_mode分岐削除、常にプロキシURL使用（L31-37） | ~7行 | 高 |
| `.env` | `LANCET_EXECUTION_MODE`設定削除（L7-9） | 3行 | 高 |
| `.env` | コンテナモード用コメント削除（L24-28） | 5行 | 中 |
| `scripts/mcp.sh` | `LANCET_EXECUTION_MODE`設定削除（L130） | 1行 | 高 |
| `tests/test_ml_server_e2e.py` | execution_mode関連テスト確認・修正 | - | 中 |

**合計削除行数**: ~30行

##### O.3.4 コンテナ検出コード削除

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `src/mcp/server.py` | `/.dockerenv`検出コード削除（L806） | 1行 | 高 |
| `src/search/browser_search_provider.py` | コンテナ検出コード削除（L201-203） | ~3行 | 中 |
| `src/crawler/playwright_provider.py` | コンテナ検出コード削除（L157-159） | ~3行 | 中 |
| `src/crawler/fetcher.py` | コンテナ検出コード削除（L765-767） | ~3行 | 中 |

**合計削除行数**: ~10行

##### O.3.5 ポート設定簡素化

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `.env` | `CHROME_PORT`コメント簡素化（9222固定、L19-21） | 3行 | 低 |
| `config/settings.yaml` | ポートオーバーライドコメント削除（L132-135） | 4行 | 低 |
| `.env.example` | socatポート設定削除（L13, L47-48） | 3行 | 中 |
| `.env.example` | セクション名「CONTAINER NETWORKING (Required for Podman)」を「CONTAINER NETWORKING (Internal services)」に変更（L16） | 1行 | 低 |

**合計削除行数**: ~10行

##### O.3.6 スクリプト更新

| ファイル | 変更内容 | 行数 | 優先度 |
|---------|---------|:----:|:------:|
| `config/cursor-mcp.json` | `podman exec`経由をWSL経由（`./scripts/mcp.sh`）に変更 | 全体 | **最高** |
| `Dockerfile` | CMDを`src.proxy.server`に変更（L89） | 1行 | 高 |
| `scripts/dev.sh` | コンテナネットワーキング関連コメント削除（L145） | 1行 | 中 |
| `scripts/dev.sh` | フォールバック設定のコメント更新（L55-56） | 2行 | 低 |
| `scripts/test.sh` | WSL直接実行オプション追加（コンテナ実行は削除） | - | 高 |
| `scripts/mcp.sh` | `LANCET_EXECUTION_MODE`設定削除（L130） | 1行 | 高 |
| `tests/scripts/verify_environment.py` | コンテナ検出コード削除または更新（L101-114） | ~14行 | 中 |
| `tests/scripts/*.py` | Usageコメントの`podman exec`をWSL venv経由に変更 | ~16ファイル | 中 |

**合計削除行数**: ~20行 + 16ファイルのコメント更新

**変更内容**:
- **`cursor-mcp.json`**: `podman exec` → `bash` + `./scripts/mcp.sh`（最重要）
- `Dockerfile`: CMDを`src.mcp.server`から`src.proxy.server`に変更
- `dev.sh`: 「container networking」コメントを「proxy server」に変更
- `test.sh`: `podman exec`経由のテスト実行を削除し、WSL venv経由に統一
- `mcp.sh`: `LANCET_EXECUTION_MODE`設定削除（常にWSLモード）
- `verify_environment.py`: コンテナ検出は残すが、WSL実行時の説明を追加
- E2Eテストスクリプト: Usageコメントの`podman exec lancet python`を`python`（WSL venv経由）に変更

##### O.3.7 ドキュメント更新

| ファイル | 変更内容 | 優先度 |
|---------|---------|:------:|
| `docs/requirements.md` | execution_mode説明削除、常にWSLモードに統一 | 高 |
| `docs/IMPLEMENTATION_PLAN.md` | 旧構成関連説明削除 | 中 |
| `README.md`（未作成） | セットアップ手順からsocat/host-gateway削除 | 中 |
| `.env.example` | コメント更新（WSLハイブリッド構成の説明） | 中 |

#### O.4 実装タスクリスト

**Phase O.2（基盤実装）**: ✅ 完了
- [x] プロキシサーバー実装
- [x] MCP起動スクリプト
- [x] 設定拡張
- [x] OllamaProvider/MLClientプロキシ対応

**Phase O.3（リファクタリング）**: ✅ 完了
- [x] O.3.1: socat関連コード完全削除（~152行）
- [x] O.3.2: host-gateway関連完全削除（~5行）
- [x] O.3.3: execution_mode分岐完全削除（~30行）
- [x] O.3.4: コンテナ検出コード削除（~10行）
- [x] O.3.5: ポート設定簡素化（~10行）
- [x] O.3.6: スクリプト更新（~20行 + 16ファイル）
- [x] O.3.7: ドキュメント更新

**合計削除行数**: ~227行 + 16ファイルのコメント更新

**最重要**: `config/cursor-mcp.json`の変更（Cursor IDEがMCPサーバーを起動する設定）

#### O.5 影響範囲

**削除される機能**:
- コンテナ内MCP実行モード（`LANCET_EXECUTION_MODE=container`）
- socatポートフォワード機能
- host-gateway経由のChrome接続
- コンテナ検出による条件分岐

**残る機能**:
- WSL上でのMCPサーバー実行（唯一の実行モード）
- プロキシ経由のOllama/ML Server接続
- WSL→Windows Chrome直接接続（localhost:9222）

**移行手順**:
1. `.env`から`LANCET_EXECUTION_MODE`を削除
2. venvを作成し、`requirements-mcp.txt`をインストール
3. `./scripts/mcp.sh`でMCPサーバー起動（Cursorが自動実行）

#### O.6 認証維持要件の調査結果（別タスク）✅ 完了

**調査日**: 2025-12-11  
**実装完了日**: 2025-12-11  
**調査目的**: Phase O.3完了後、仕様書§3.6.1「認証待ちキュー」および§4.3.3「実プロファイル活用」の要件が満たされているか検証

**実装内容**:
- [x] 問題1: 既存contextの再利用ロジック追加（3ファイル）
- [x] 問題2: resolve_authでのCookie取得・保存実装
- [x] InterventionQueue.get_item()メソッド追加
- [x] テストコード追加（71件→test_intervention_queue.py, test_mcp_auth.py）

##### O.6.1 問題概要

Phase O.3の変更自体は認証維持に直接影響しないが、**既存実装に以下の問題が存在**することが判明：

| 問題 | 影響 | 仕様違反箇所 |
|------|------|-------------|
| **問題1**: `new_context()`による新規context作成 | 既存プロファイルのCookieが引き継がれない | §3.2, §4.3.3 |
| **問題2**: `resolve_auth`でCookie取得・保存が未実装 | 認証完了後もセッションが再利用されない | §3.6.1 |

##### O.6.2 詳細調査結果

###### 問題1: `new_context()`による新規context作成

**影響箇所**:
- `src/search/browser_search_provider.py:206` - `BrowserSearchProvider._ensure_browser()`
- `src/crawler/playwright_provider.py:165` - `PlaywrightProvider._get_browser_and_context()`
- `src/crawler/fetcher.py:780` - `BrowserFetcher._ensure_browser()`

**現状の実装**:
```python
# すべての箇所で同様のパターン
self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
self._context = await self._browser.new_context(...)  # 常に新規作成
```

**問題点**:
1. `connect_over_cdp()`で接続した後、`browser.contexts`を確認せずに`new_context()`を呼び出している
2. 既存のChromeプロファイルのcontext（ユーザーが手動で認証したCookieを含む）が無視される
3. 新しいcontextはプロファイルのCookieを共有するが、**既存のタブ/ウィンドウのCookieとは別セッション**になる可能性がある

**仕様書の要件**:
- §3.2: "Windows側Chromeの実プロファイルをpersistent contextで利用"
- §4.3.3: "実プロファイル活用: Windows側Chromeのユーザープロファイルを用い、フォント/Canvas/Audio等の指紋を一貫化"
- §3.6.1: "セッション共有: 認証済みCookie/セッションは同一ドメインの後続リクエストで自動再利用"

**Playwrightの動作**:
- `connect_over_cdp()`で接続した場合、`browser.contexts`には既存のcontextが含まれる可能性がある
- Chromeが`--remote-debugging-port`で起動された場合、デフォルトでは既存のcontextが存在しない場合もある
- `new_context()`で作成したcontextは、そのプロファイルのCookieを共有するが、**既存のタブ/ウィンドウのCookieとは別セッション**になる可能性がある

###### 問題2: `resolve_auth`でCookie取得・保存が未実装

**影響箇所**:
- `src/mcp/server.py:1200, 1222` - `_handle_resolve_auth()`

**現状の実装**:
```python
# mcp/server.py:1200
if action == "complete":
    result = await queue.complete(queue_id, success=success)  # session_dataなし

# mcp/server.py:1222
if action == "complete":
    result = await queue.complete_domain(domain, success=success)  # session_dataなし
```

**問題点**:
1. `resolve_auth`が呼ばれた時点で、ブラウザからCookieを取得していない
2. `complete()`/`complete_domain()`は`session_data`パラメータを受け取るが、呼び出し側で`None`を渡している
3. 認証完了後もセッション情報が保存されず、次回同じドメインにアクセスする際に再度認証が必要になる

**既存の実装**:
- `src/utils/notification.py:1223` - `complete()`は`session_data`を受け取る
- `src/utils/notification.py:1278` - `complete_domain()`も`session_data`を受け取る
- `src/utils/notification.py:1488` - `get_session_for_domain()`でセッション取得は実装済み
- `src/crawler/session_transfer.py:371` - `capture_from_browser()`でCookie取得は実装済み

**仕様書の要件**:
- §3.6.1: "セッション共有: 認証済みCookie/セッションは同一ドメインの後続リクエストで自動再利用"
- §3.6.1: "ドメインベース認証管理: 同一ドメインの認証は1回の突破で複数タスク/URLに適用される"

**認証待ちキューのフロー**:
1. 認証待ち発生 → `InterventionQueue.enqueue()`でキューに積む
2. `start_session()`でURLを返す（ブラウザを開く処理はない）
3. ユーザーが手動でブラウザを開いて認証
4. `resolve_auth`で完了報告 → **Cookie取得・保存が未実装**

##### O.6.3 修正提案

###### 修正1: 既存contextの再利用

**方針**: `connect_over_cdp()`で接続した後、既存のcontextがあれば優先的に使用する

**実装箇所**:
- `src/search/browser_search_provider.py:206`
- `src/crawler/playwright_provider.py:165`
- `src/crawler/fetcher.py:780`

**修正案**:
```python
# 修正前
self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
self._context = await self._browser.new_context(...)

# 修正後
self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)

# 既存のcontextを確認
existing_contexts = self._browser.contexts
if existing_contexts:
    # 既存のcontextを使用（プロファイルのCookieが維持される）
    self._context = existing_contexts[0]
    logger.info("Reusing existing browser context", context_count=len(existing_contexts))
else:
    # 既存のcontextがない場合のみ新規作成
    self._context = await self._browser.new_context(...)
    logger.info("Created new browser context")
```

**注意点**:
- Chromeが`--remote-debugging-port`で起動された場合、デフォルトでは既存のcontextが存在しない場合もある
- 既存のcontextを使用する場合、viewport設定などが異なる可能性がある
- 複数のcontextが存在する場合、どれを使用するか決定する必要がある（最初のcontextを使用するか、URLに基づいて選択するか）

###### 修正2: `resolve_auth`でCookie取得・保存

**方針**: 認証完了時にブラウザからCookieを取得し、セッション転送マネージャーに保存する

**実装箇所**:
- `src/mcp/server.py:1151` - `_handle_resolve_auth()`

**修正案**:
```python
# 修正前
if action == "complete":
    result = await queue.complete(queue_id, success=success)

# 修正後
if action == "complete":
    # 認証完了時、ブラウザからCookieを取得
    session_data = await _capture_auth_session(queue_id, domain)
    result = await queue.complete(queue_id, success=success, session_data=session_data)
```

**新規関数**:
```python
async def _capture_auth_session(queue_id: str, domain: str) -> dict | None:
    """Capture session data from browser after authentication.
    
    Args:
        queue_id: Queue item ID.
        domain: Domain name.
        
    Returns:
        Session data dict or None.
    """
    from src.utils.notification import get_intervention_queue
    from src.crawler.session_transfer import get_session_transfer_manager
    
    queue = get_intervention_queue()
    item = await queue.get_item(queue_id)
    if not item:
        return None
    
    url = item.get("url")
    if not url:
        return None
    
    # ブラウザからCookieを取得
    # 注意: 認証待ちURLを開いたcontextを特定する必要がある
    # 現状、start_session()でブラウザを開いていないため、実装が必要
    
    # 暫定案: 既存のcontextからCookieを取得
    from src.search.browser_search_provider import BrowserSearchProvider
    provider = BrowserSearchProvider()
    await provider._ensure_browser()
    
    if provider._context:
        cookies = await provider._context.cookies([url])
        session_data = {
            "cookies": [dict(c) for c in cookies],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        return session_data
    
    return None
```

**注意点**:
- 認証待ちURLを開いたcontextを特定する必要がある
- 現状、`start_session()`でブラウザを開いていないため、認証待ちURLを開く処理を追加する必要がある可能性がある
- または、ユーザーが手動で開いたブラウザタブからCookieを取得する方法を検討する必要がある

##### O.6.4 影響範囲

**Phase O.3の変更による影響**: なし（既存の問題）

**修正による影響**:
- `BrowserSearchProvider`, `PlaywrightProvider`, `BrowserFetcher`のcontext管理ロジック変更
- `resolve_auth`の実装変更
- 認証待ちキューのフロー変更（ブラウザを開く処理の追加が必要な可能性）

##### O.6.5 優先度

**優先度**: 🔴 高（仕様違反）

**理由**:
- §3.6.1「セッション共有」は認証待ちキューの核心機能
- 認証完了後もセッションが再利用されないと、ユーザー介入回数が増加し、運用効率が低下する
- §4.3.3「実プロファイル活用」はステルス性の根幹

**実装時期**: Phase O完了後、別タスクとして実装

##### O.6.6 追加仕様違反調査結果 ✅ 完了

**調査日**: 2025-12-11  
**実装完了日**: 2025-12-11  
**調査目的**: O.6実装完了後、同様のパターンで他の仕様違反がないか確認

**実装完了項目**:
- [x] 問題3: 認証待ちキューで保存されたセッションが後続リクエストで再利用されていない ✅
- [x] 問題5: `start_session()`でブラウザを開く処理が未実装 ✅
- [x] 問題12: セッション転送が実装されているが適用されていない ✅

**実装詳細**:
- **問題3**: `BrowserFetcher.fetch()`で`InterventionQueue.get_session_for_domain()`を呼び出し、Cookieを`context.add_cookies()`で適用（`src/crawler/fetcher.py:1086-1137`）
- **問題5**: `InterventionQueue.start_session()`で`BrowserFetcher._ensure_browser(headful=True)`を呼び出し、ブラウザでURLを開く処理を実装。Chrome自動起動機能も実装（`src/utils/notification.py:1165-1200`, `src/crawler/fetcher.py:738-960`）
- **問題12**: `fetch_url()`で初回はブラウザ経由、2回目以降はHTTPクライアント経由（304キャッシュ）を実装（`src/crawler/fetcher.py:1896-1955`）

**検証スクリプト**:
- `tests/scripts/debug_auth_session_reuse_flow.py` - 問題3の検証
- `tests/scripts/debug_start_session_browser_flow.py` - 問題5の検証
- `tests/scripts/debug_chrome_auto_start.py` - Chrome自動起動機能の検証
- `tests/scripts/debug_session_transfer_flow.py` - 問題12の検証

**詳細**: `docs/O6_ADDITIONAL_ISSUES.md`を参照

##### O.6.7 関連ファイル

| ファイル | 役割 | 修正内容 |
|---------|------|---------|
| `src/search/browser_search_provider.py` | ブラウザ検索プロバイダー | context再利用ロジック追加 |
| `src/crawler/playwright_provider.py` | Playwrightプロバイダー | context再利用ロジック追加 |
| `src/crawler/fetcher.py` | ブラウザフェッチャー | context再利用ロジック追加 |
| `src/mcp/server.py` | MCPサーバー | `resolve_auth`でCookie取得・保存 |
| `src/utils/notification.py` | 認証待ちキュー | ブラウザを開く処理の追加（検討） |
| `src/crawler/session_transfer.py` | セッション転送マネージャー | 既存実装を活用 |

---

## 7. 開発環境

### 7.1 起動方法

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

### 7.2 コンテナ構成（ハイブリッド構成）

**WSL側（venv）**:
- MCPサーバー（Cursor IDEとstdioで通信）
- Playwright（Chrome CDP接続）

**コンテナ側**:
- `lancet` - プロキシサーバー（Ollama/ML Serverへのアクセス）
- `lancet-ml` - 埋め込み/リランカー/NLI
- `lancet-ollama` - ローカルLLM (GPU対応)
- `lancet-tor` - Torプロキシ

**注意**: SearXNGは廃止済み（Phase C参照）

### 7.3 テスト実行

**WSL側（venv使用・推奨）**:
```bash
cd /home/statuser/lancet
source .venv/bin/activate
pytest tests/ -m 'not e2e' --tb=short -q
```

**コンテナ側（従来方式）**:
```bash
podman exec lancet pytest tests/ -m 'not e2e' --tb=short -q
```

Phase G.2 も参照。

### 7.4 E2E検証環境セットアップ（ハイブリッド構成）

#### 7.4.1 初回セットアップ

1. **WSL2 mirrored networkingを有効化**
   - `%USERPROFILE%\.wslconfig`に以下を追加:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
   - WSLを再起動: `wsl.exe --shutdown`

2. **venv作成**
   ```bash
   cd /home/statuser/lancet
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-mcp.txt
   playwright install chromium
   ```

3. **専用Chromeプロファイル作成**（Googleアカウント未ログイン推奨）

#### 7.4.2 起動手順

```bash
# 1. コンテナ起動（Ollama/ML Server/プロキシ）
./scripts/dev.sh up

# 2. Chrome起動（自動またはMCPから自動起動）
./scripts/chrome.sh start

# 3. MCPサーバー起動（Cursorが自動実行）
# または手動: ./scripts/mcp.sh
```

#### 7.4.3 テスト実行

```bash
# venvからテスト（推奨）
source .venv/bin/activate
python tests/scripts/verify_duckduckgo_search.py

# プロキシ接続確認
curl http://localhost:8080/health
```

### 7.5 外部依存

- Ollama (Podmanコンテナで起動、GPUパススルー)
- Chrome (Windows側で起動、リモートデバッグ)
- nvidia-container-toolkit (GPU使用時に必要)

**ハイブリッド構成ではsocat不要**: MCPサーバーがWSL上で直接実行されるため、localhost:9222でChromeに接続

---

## 8. 注意事項

### 8.1 技術的制約

- VRAM≤8GB維持（RTX 4060 Laptop）
- WSL2メモリ32GB内で動作
- 商用API/有料サービス使用禁止

### 8.2 リスク軽減

- Cloudflare/Turnstile: 手動誘導UX＋クールダウン/スキップ自動化
- VRAM圧迫: マイクロバッチ/候補上限自動調整
