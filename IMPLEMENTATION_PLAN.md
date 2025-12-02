# 実装計画: Local Autonomous Deep Research Agent (Lancet)

## 概要

OSINTデスクトップリサーチを自律的に実行するローカルAIエージェント。
**Podmanコンテナ環境**で稼働し、MCPを通じてCursorと連携する。

---

## Phase A: 基盤構築 ✅

### A.1 プロジェクト基盤 ✅

| 項目 | 成果物 | 仕様参照 |
|------|--------|----------|
| プロジェクト構造 | `src/`, `config/`, `tests/` 等 | - |
| 依存関係 | `requirements.txt`, `pyproject.toml`, Dockerfile | - |
| 設定管理 | `config/settings.yaml`, `config/engines.yaml`, `config/domains.yaml` | - |
| データベース | SQLiteスキーマ (`src/storage/schema.sql`)、FTS5全文検索 | §5.1.2 |
| ロギング | 構造化ログ (structlog)、因果トレース (cause_id) | §4.6 |

### A.2 MCPサーバー ✅

| ツール | 機能 | 仕様参照 |
|--------|------|----------|
| `search_serp` | 検索実行 | §3.2.1 |
| `fetch_url` | URL取得 | §3.2.1 |
| `extract_content` | コンテンツ抽出 | §3.2.1 |
| `rank_candidates` | パッセージランキング | §3.2.1 |
| `llm_extract` | LLM抽出 | §3.2.1 |
| `nli_judge` | NLI判定 | §3.2.1 |
| `get_report_materials` | レポート素材提供 | §2.1 |
| `get_evidence_graph` | エビデンスグラフ参照 | §3.2.1 |

**探索制御ツール（§2.1責任分界準拠）**:
- `get_research_context`: 設計支援情報の提供（候補生成なし）
- `execute_subquery`: サブクエリ実行
- `get_exploration_status`: 探索状態（メトリクスのみ、推奨なし）
- `execute_refutation`: 反証探索（機械パターン適用）
- `finalize_exploration`: 探索終了

**認証キューツール（§3.6.1）**:
- `get_pending_authentications`, `get_pending_by_domain`
- `start_authentication_session`, `complete_authentication`, `complete_domain_authentication`
- `skip_authentication`, `skip_domain_authentication`

### A.3 検索機能 ✅

**当初設計（SearXNG経由）→ 廃止**: 詳細は「Phase C.1 検索経路の再設計」参照

**現在の実装（BrowserSearchProvider）**:
- Playwright CDP接続によるブラウザ直接検索
- 対応エンジン: DuckDuckGo, Mojeek, Qwant, Brave, Google, Ecosia, Startpage
- CAPTCHA検知→認証キュー連携

### A.4 クローリング/取得 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| HTTPクライアント | curl_cffi (impersonate=chrome) | §4.3 |
| ブラウザ自動化 | Playwright CDP接続 | §3.2 |
| ヘッドフル切替 | 自動エスカレーション | §4.3 |
| Torプロキシ | Stem連携、Circuit更新 | §4.3 |
| アーカイブ保存 | WARC (warcio)、スクリーンショット | §4.3.2 |

### A.5 コンテンツ抽出 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| HTML抽出 | trafilatura | §5.1 |
| PDF抽出 | PyMuPDF | §5.1.1 |
| OCR | PaddleOCR + Tesseract | §5.1.1 |
| 重複検出 | MinHash + SimHash | §3.3.1 |

### A.6 フィルタリング/評価 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| BM25ランキング | rank-bm25 | §3.3 |
| 埋め込み | bge-m3 (ONNX/FP16) | §5.1 |
| リランキング | bge-reranker-v2-m3 | §5.1 |
| LLM抽出 | Ollama (Qwen2.5-3B/7B) | §5.1 |
| NLI判定 | tiny-DeBERTa | §3.3.1 |
| エビデンスグラフ | NetworkX + SQLite | §3.3.1 |

### A.7 スケジューラ ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ジョブキュー | 優先度管理、スロット制御 | §3.2.2 |
| 排他制御 | gpu/browser_headful排他 | §3.2.2 |
| 予算制御 | ページ数/時間上限 | §3.1 |

### A.8 通知/手動介入 ✅

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

### A.9 レポート生成 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| テンプレート | Markdown / JSON | §3.4 |
| 引用管理 | 深いリンク生成、一次/二次分類 | §3.4 |

---

## Phase B: 品質強化 ✅

### B.1 メトリクス/自動適応 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| メトリクス収集 | MetricsCollector, TaskMetrics | §4.6 |
| ポリシー自動更新 | PolicyEngine (EMA、ヒステリシス) | §4.6 |
| リプレイモード | DecisionLogger, ReplayEngine | §4.6 |

### B.2 探索制御 ✅

**§2.1責任分界**: クエリ設計はCursor AI、Lancetは実行のみ

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 設計支援情報 | ResearchContext | §2.1.2 |
| サブクエリ実行 | SubqueryExecutor | §2.1.2 |
| 充足度判定 | ExplorationState | §3.1.7.3 |
| 反証探索 | RefutationExecutor (機械パターンのみ) | §3.1.7.5 |

### B.3 クローリング拡張 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| robots.txt/sitemap | RobotsChecker, SitemapParser | §3.1.2 |
| ドメイン内BFS | DomainBFSCrawler | §3.1.2 |
| サイト内検索 | SiteSearchManager | §3.1.5 |
| Wayback差分 | WaybackExplorer | §3.1.6 |

### B.4 信頼度キャリブレーション ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 確率校正 | Platt/温度スケーリング | §3.3.4 |
| デグレ検知 | Brierスコア監視 | §4.6.1 |
| ロールバック | CalibrationHistory | §4.6.1 |

---

## Phase C: 検索経路再設計 ✅

### C.1 SearXNG廃止の背景

**問題**: SearXNGはサーバーサイドで動作するため、以下の技術的欠陥があった：

1. **Cookie/指紋使用不可**: ユーザーのブラウザセッションを使用できない
2. **bot検知されやすい**: Cookie/指紋なしの素のHTTPリクエスト
3. **CAPTCHA解決不可**: ユーザーがCAPTCHA解決しても、SearXNGにCookieは渡らない
4. **§3.6.1との矛盾**: 認証待ちキューの設計意図が成立しない

**根本原因**: SearXNGは「便利」だったが、抗堅性（§4.3）を犠牲にする設計だった。

### C.2 新アーキテクチャ（BrowserSearchProvider）

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

### C.3 requirements.md修正内容

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

## Phase D: 抗堅性・ステルス性強化 ✅

### D.1 ネットワーク/IP層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| IPv6運用 | IPv6ConnectionManager | §4.3 |
| DNS方針 | DNSPolicyManager (socks5h://でリーク防止) | §4.3 |
| HTTP/3方針 | HTTP3PolicyManager | §4.3 |

### D.2 トランスポート/TLS層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| sec-fetch-*ヘッダー | SecFetchHeaders | §4.3 |
| sec-ch-ua*ヘッダー | SecCHUAHeaders | §4.3 |

### D.3 ブラウザ/JS層 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| webdriverオーバーライド | stealth.py (STEALTH_JS) | §4.3 |
| undetected-chromedriverフォールバック | UndetectedChromeFetcher | §4.3 |
| viewportジッター | ViewportJitter | §4.3 |

### D.4 プロファイル健全性監査 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 差分検知 | ProfileAuditor (UA/フォント/言語/指紋) | §4.3.1 |
| 自動修復 | attempt_repair (Chrome再起動等) | §4.3.1 |
| 監査ログ | JSONL形式 | §4.3.1 |

### D.5 セッション移送 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| Cookie/ETag移送 | SessionTransferManager | §3.1.2 |
| 同一ドメイン制約 | capture_from_browser | §3.1.2 |

### D.6 ブラウザ経路アーカイブ ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| CDXJ風メタデータ | CDXJGenerator | §4.3.2 |
| 簡易HAR生成 | HARGenerator | §4.3.2 |

### D.7 ヒューマンライク操作 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| マウス軌跡 | MouseTrajectory (Bezier曲線) | §4.3.4 |
| タイピングリズム | HumanTyping (ガウス分布) | §4.3.4 |
| スクロール慣性 | InertialScroll (easing) | §4.3.4 |
| 設定外部化 | config/human_behavior.yaml | §4.3.4 |

---

## Phase E: OSINT品質強化 ✅

### E.1 検索戦略 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| UCB1風予算再配分 | UCBAllocator | §3.1.1 |
| クエリABテスト | ABTestExecutor | §3.1.1 |
| ピボット探索 | PivotExpander | §3.1.1 |

### E.2 インフラ/レジストリ連携 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| RDAP/WHOIS | RDAPClient, WHOISParser | §3.1.2 |
| 証明書透明性 | CertTransparencyClient (crt.sh) | §3.1.2 |
| エンティティKB | EntityKB, NameNormalizer | §3.1.2 |

### E.3 コンテンツ品質 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ページタイプ判定 | PageClassifier | §3.1.2 |
| 低品質検出 | ContentQualityAnalyzer | §3.3.3 |
| AI生成検出 | 23パターン + 文長均一性 | §3.3.3 |
| 時系列整合 | TemporalConsistencyChecker | §3.3.3 |

### E.4 主張分析 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 問い→主張分解 | ClaimDecomposer | §3.3.1 |
| Chain-of-Density圧縮 | ChainOfDensityCompressor | §3.3.1 |

---

## Phase F: 追加機能 ✅

### F.1 校正ロールバック ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| デグレ検知 | CalibrationHistory.check_degradation() | §4.6.1 |
| ロールバック | Calibrator.rollback() | §4.6.1 |
| 評価永続化 | calibration_evaluations テーブル | §4.6.1 |

### F.2 プロセスライフサイクル ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| ブラウザ破棄 | ProcessLifecycleManager | §4.2 |
| LLM解放 | OllamaClient.unload_model() | §4.2 |

### F.3 半自動運用UX ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 認証待ち情報統合 | get_exploration_status に authentication_queue 追加 | §3.6.1 |
| 閾値アラート | warnings配列への追加 (≥3件で警告) | §3.6.1 |

### F.4 タイムライン機能 ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 主張タイムライン | ClaimTimeline, TimelineEvent | §3.4 |
| Wayback連携 | integrate_wayback_result() | §3.1.6 |
| カバレッジ算出 | get_timeline_coverage() | §7 |

### F.5 Waybackフォールバック ✅

| 機能 | 実装 | 仕様参照 |
|------|------|----------|
| 自動フォールバック | fetcher.py統合 (403/CAPTCHA時) | §3.1.6 |
| 差分検出 | ArchiveDiffResult | §3.1.6 |
| 鮮度ペナルティ | apply_freshness_penalty() | §3.1.6 |

---

## Phase G: テスト基盤 ✅

### G.1 テスト分類

| 分類 | マーカー | 外部依存 | 実行環境 |
|------|----------|----------|----------|
| unit | `@pytest.mark.unit` | なし | どこでも |
| integration | `@pytest.mark.integration` | モック | どこでも |
| e2e | `@pytest.mark.e2e` | 実サービス | 低リスクIP限定 |

**追加マーカー**:
- `@external`: 外部サービス使用（Mojeek, Qwant等）
- `@rate_limited`: レート制限厳しい（DuckDuckGo, Google等）
- `@manual`: 人手介入必須（CAPTCHA解決等）

### G.2 テスト実行

```bash
# ユニット + 統合（CIデフォルト）
./scripts/test.sh run tests/

# E2Eのみ
pytest -m e2e

# 全テスト
pytest -m ""
```

**現在のテスト数**: 2201件（全パス）

### G.3 E2Eスクリプト（tests/scripts/）

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

## Phase H: 検索エンジン多様化 ✅

### H.1 実装状況マトリクス

| エンジン | 仕様書§3.2 | engines.yaml | パーサー | E2Eスクリプト | E2E検証 | 状態 |
|----------|:----------:|:------------:|:--------:|:-------------:|:-------:|------|
| DuckDuckGo | ✅ | ✅ | ✅ | ✅ | ✅ 5/5 | **完了** |
| Mojeek | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Google | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Brave | ✅ | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Ecosia | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Startpage | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |
| Bing | - | ✅ | ✅ | ✅ | ✅ 4/4 | **完了** |

### H.2 E2E検証で判明した知見

#### H.2.1 MetaGer削除

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

#### H.2.2 セレクター保守の教訓

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

#### H.2.3 E2E検証で判明した追加問題

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

#### H.2.4 E2Eスクリプトの共通修正

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

### H.3 残作業

#### 優先度高（仕様書§3.2準拠）
- [x] **Bingパーサー実装** ✅
  - `config/search_parsers.yaml`にbing定義追加
  - `src/search/search_parsers.py`にBingParser追加
  - `src/search/parser_config.py`にbingフィールド追加
  - `tests/test_search_parsers.py`にBingテスト追加

#### 優先度中（E2Eカバレッジ向上）
- [x] `verify_mojeek_search.py`作成 ✅
- [x] ~~`verify_qwant_search.py`作成~~ → Qwant削除（地域制限）
- [x] `verify_brave_search.py`作成 ✅

#### 優先度低（高リスクエンジン）
- [x] `verify_google_search.py`作成 ✅（CAPTCHA高頻度）
- [x] `verify_bing_search.py`作成 ✅

#### 技術的課題
- [x] **CDPフォールバック問題の修正** ✅
  - ヘッドレスフォールバック削除（仕様§4.3.3準拠）
  - CDP接続失敗時は明確なエラー + `chrome.sh`案内
  - `SearchResponse.connection_mode`フィールド追加

#### 確認事項
- [x] **MCPサーバ経由での動作確認** ✅
  - `tests/scripts/verify_mcp_tools.py`作成（MCPツールハンドラ検証）
  - `search_serp`ツール経由での検索が正常動作することを確認
  - バグ修正: `search_parsers._classify_source`が文字列を返していた問題を修正（SourceTag Enumに変換）

---

## Phase I: 保守性改善 🔄

### I.1 プロバイダ抽象化 ✅

| プロバイダ | 実装 | 状態 |
|-----------|------|:----:|
| SearchProvider | BrowserSearchProvider | ✅ |
| LLMProvider | OllamaProvider | ✅ |
| BrowserProvider | PlaywrightProvider, UndetectedChromeProvider | ✅ |
| NotificationProvider | LinuxNotifyProvider, WindowsToastProvider, WSLBridgeProvider | ✅ |

### I.2 設定・ポリシーの外部化 ✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| ドメインポリシー | DomainPolicyManager + config/domains.yaml | ✅ |
| 検索エンジン設定 | SearchEngineConfigManager + config/engines.yaml | ✅ |
| ステルス設定 | - | 未実装 |

### I.3 汎用コンポーネント

| 項目 | 状態 |
|------|:----:|
| 汎用サーキットブレーカ | ✅ |
| 汎用リトライ/バックオフ | 未実装 |
| 汎用キャッシュレイヤ | 未実装 |

#### I.3.1 汎用サーキットブレーカ ✅

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

### I.4 パーサー自己修復（AI駆動）

**目的**: 検索エンジンのHTML変更に対してAIが自動修復

**既存基盤**:
- `debug/search_html/`: 失敗時のHTML自動保存
- `config/search_parsers.yaml`: セレクター外部化
- 構造化ログ: 失敗セレクター名を明示

**タスク**:
- [x] 失敗時ログ + HTML保存（既存）
- [ ] AIフレンドリーな失敗ログ強化
- [ ] 修正ワークフロー設計（Cursorカスタムコマンド or 会話ベース）

---

## Phase J: 外部データソース統合 ⏳

### J.0 API仕様調査（優先）

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

### J.1 日本政府API統合

**対象（§3.1.3）**:
- e-Stat API: 統計データ
- 法令API（e-Gov）: 法令全文検索
- 国会会議録API: 国会議事録
- gBizINFO API: 法人基本情報
- EDINET API: 有価証券報告書

### J.2 学術API統合

**対象（§3.1.3、§5.1.1）**:
- OpenAlex API: 論文メタデータ/引用グラフ
- Semantic Scholar API: 論文/引用ネットワーク
- Crossref API: DOI/引用情報
- Unpaywall API: OA版論文リンク

### J.3 エンティティ解決強化

**対象（§3.1.3）**:
- Wikidata API
- DBpedia SPARQL

---

## Phase K: ローカルLLM強化 ⏳

### K.1 モデル選択最適化

- [ ] `config/llm_models.yaml`: タスク別モデル設定
- [ ] OllamaProvider拡張: `select_model(task)`

### K.2 プロンプトテンプレート外部化

- [ ] `config/prompts/`: Jinja2テンプレート
- [ ] PromptManager実装

### K.3 プロンプトインジェクション対策

- [ ] 対策の検討・  立案
- [ ] コンテナの独立（不要なソースコードやツールをマウントしない）
- [ ] 内部ネットワーク化
- [ ] サニタイズ
- [ ] テンプレートによるインジェクションの無視

---

## Phase L: ドキュメント ⏳

### L.1 未作成ドキュメント

- [ ] README.md（プロジェクト概要、セットアップ手順）
- [ ] 手動介入運用手順書（§6成果物）
- [ ] MCPツール仕様書（§6成果物）
- [ ] ジョブスケジューラ仕様書（§6成果物）
- [ ] プロファイル健全性監査運用手順

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
- `lancet-tor` - Torプロキシ
- `lancet-ollama` - ローカルLLM (GPU対応)

**注意**: SearXNGは廃止済み（Phase C参照）

### テスト実行

```bash
# 全テスト実行（devコンテナ内で実行）
podman exec lancet pytest tests/

# 簡潔な出力
podman exec lancet pytest tests/ --tb=no -q

# 特定ファイルのみ
podman exec lancet pytest tests/test_robots.py -v
```

### E2E検証環境セットアップ（WSL2→Windows Chrome）

1. **専用Chromeプロファイル作成**（Googleアカウント未ログイン推奨）

2. **すべてのChromeを完全終了**
   ```powershell
   Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
   ```

3. **Chromeをリモートデバッグモードで起動**
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 "--user-data-dir=C:\Users\<USERNAME>\AppData\Local\Google\Chrome\User Data" --profile-directory=Profile-Research
   ```

4. **ポートフォワーディング設定**（初回のみ、管理者PowerShell）
   ```powershell
   netsh interface portproxy add v4tov4 listenaddress=<WSL2_GATEWAY_IP> listenport=9222 connectaddress=127.0.0.1 connectport=9222
   New-NetFirewallRule -DisplayName "Chrome Debug WSL2" -Direction Inbound -LocalPort 9222 -Protocol TCP -Action Allow
   ```

5. **環境変数設定**（`.env`ファイル）
   ```bash
   echo "LANCET_BROWSER__CHROME_HOST=<WSL2_GATEWAY_IP>" >> .env
   ```

6. **テスト実行**
   ```bash
   podman exec lancet python tests/scripts/verify_duckduckgo_search.py
   ```

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

---
