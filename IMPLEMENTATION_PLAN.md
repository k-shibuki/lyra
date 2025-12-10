# 実装計画: Local Autonomous Deep Research Agent (Lancet)

## 概要

信頼性が高いデスクトップリサーチを自律的に実行するローカルAIエージェント。
**Podmanコンテナ環境**で稼働し、MCPを通じてCursorと連携する。

---

## 実装完成度サマリ（2025-12-09 更新）

| Phase | 内容 | ユニットテスト | E2E検証 | 状態 |
|-------|------|:-------------:|:-------:|:----:|
| A-H | 基盤〜検索エンジン多様化 | ✅ | ✅ | 完了 |
| I | 保守性改善 | ✅ | - | I.4残 |
| K.3 | セキュリティ（L1-L8） | ✅ | ⏳ | 実装完了、E2E未検証 |
| M | MCPリファクタリング | ✅ | ⏳ | 実装完了、E2E未検証 |
| **N** | **E2Eケーススタディ** | - | ⏳ | **次タスク** |

**現在のテスト数**: 2641件（全パス）

---

## Phase優先度

### MVP必須（初期リリース）
- Phase A-H: 基盤〜検索エンジン多様化 ✅
- Phase K.3: プロンプトインジェクション対策 ✅
- Phase M: MCPツールリファクタリング ✅
- **Phase N: E2Eケーススタディ（論文投稿向け）⏳**

### Phase 2（論文投稿後）
- Phase I.4: パーサー自己修復（AI駆動）
- Phase J: 外部データソース統合
- Phase K.1-K.2: モデル選択最適化、プロンプト外部化
- Phase L: ドキュメント

### 将来の拡張
- クエリA/Bテスト（§3.1.1から削除済み）
- 変更検知/差分アラート
- IPv6/HTTP3の高度な学習

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

**既定値（§3.2.2）**:
- `network_client`: 同時実行=4、ドメイン同時実行=1
- 優先度: serp(100) > prefetch(90) > extract(80) > embed(70) > rerank(60) > llm_fast(50) > llm_slow(40)
- タイムアウト: 検索30秒、取得60秒、LLM抽出120秒

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

**§2.1.5判断委譲の例外**:
- Cursor AI無応答時（300秒既定）: パイプライン安全停止、状態保存、復帰待機

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

**ポリシー自動更新の既定値（§4.6）**:
- 周期補完: 60秒
- EMA係数: 短期α=0.3、長期α=0.1
- Tor利用上限: 20%
- パラメータ反転防止: 5分未満は反転させない

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
| ピボット探索 | PivotExpander | §3.1.1 |

> **注意**: クエリA/Bテスト（ABTestExecutor）は§3.1.1から削除され、「将来の拡張」に移動した。

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
# 全テスト実行（devコンテナ内で実行）
podman exec lancet pytest tests/

# 簡潔な出力
podman exec lancet pytest tests/ --tb=no -q

# 特定ファイルのみ
podman exec lancet pytest tests/test_robots.py -v
```

**現在のテスト数**: 2641件（全パス）

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
| 汎用リトライ/バックオフ | ✅ |
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

#### I.3.2 汎用リトライ/バックオフ ✅

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

**仕様書更新**: `requirements.md` §4.3.5「リトライ戦略の分類」を追加
- エスカレーションパス（検索/取得向け）: 同一経路での単純リトライ禁止
- ネットワーク/APIリトライ（トランジェントエラー向け）: 公式APIのみ適用可

**テスト**: `tests/test_utils_backoff.py`（26件）、`tests/test_utils_api_retry.py`（28件）

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

### J.4 特許API統合

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

### J.5 防衛・調達情報連携

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

## Phase K: ローカルLLM強化 🔄

### K.3 プロンプトインジェクション対策（§4.4.1）🔴優先

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

#### K.3-1 ネットワーク分離（L1）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| Ollama内部ネットワーク専用化 | `podman-compose.yml`修正 | ✅ |
| 外部ネットワークアクセス遮断 | `internal: true` 設定 | ✅ |
| ホストポート公開禁止 | `ports`セクション削除 | ✅ |

#### K.3-2 システムインストラクション分離（L3）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| セッションごとランダムタグ生成 | `src/filter/llm_security.py` | ✅ |
| タグのログ非出力 | ハッシュ先頭8文字のみDEBUG出力 | ✅ |
| プロンプトテンプレート改修 | `src/filter/llm.py` | ✅ |

#### K.3-3 入力サニタイズ（L2）✅

| 項目 | 実装 | 状態 |
|------|------|:----:|
| Unicode NFKC正規化 | `sanitize_llm_input()` | ✅ |
| HTMLエンティティデコード | 同上 | ✅ |
| ゼロ幅文字除去 | 同上 | ✅ |
| 制御文字除去 | 同上 | ✅ |
| タグパターン除去 | `LANCET-`プレフィックスパターン | ✅ |
| 危険単語検出・警告 | ログ出力 | ✅ |
| 入力長制限 | 4000文字 | ✅ |

#### K.3-4 出力検証（L4）✅

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

#### K.3-5 MCP応答メタデータ（L5）✅

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

#### K.3-6 ソース検証フロー（L6）✅

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

#### K.3-7 TrustLevel変更 ✅

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

#### K.3-8 BLOCKED通知（InterventionQueue連携）✅

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

#### K.3-9 MCP応答サニタイズ（L7）✅

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

#### K.3-10 ログセキュリティポリシー（L8）✅

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

#### K.3 テスト

| 項目 | 実装 | 状態 |
|------|------|:----:|
| ユニットテスト（L2/L3/L4基本） | `tests/test_llm_security.py` | ✅ |
| ユニットテスト（L4強化: 断片検出） | `tests/test_llm_security.py` 追加 | ✅ |
| ユニットテスト（L5: MCP応答メタデータ） | `tests/test_response_meta.py` | ✅ (30件, 100%カバレッジ) |
| ユニットテスト（L6: ソース検証フロー） | `tests/test_source_verification.py` | ✅ (43件, 100%カバレッジ) |
| ユニットテスト（L7: MCP応答サニタイズ） | `tests/test_response_sanitizer.py` | ✅ (29件) |
| ユニットテスト（L8: ログセキュリティ） | `tests/test_secure_logging.py` | ✅ (27件) |
| E2E: ネットワーク分離検証 | Ollamaから外部通信不可を確認 | ⏳ |
| E2E: LLM応答検証 | サニタイズ済みプロンプトでの正常動作 | ⏳ |
| E2E: タグ分離効果検証 | インジェクション攻撃の影響確認 | ⏳ |
| E2E: MCP応答流出検証 | プロンプト断片がMCP応答に含まれないことを確認 | ⏳ |

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

### K.1 モデル選択最適化 ⏳

- [ ] `config/llm_models.yaml`: タスク別モデル設定
- [ ] OllamaProvider拡張: `select_model(task)`

### K.2 プロンプトテンプレート外部化 ⏳

- [ ] `config/prompts/`: Jinja2テンプレート
- [ ] PromptManager実装

---

## Phase L: ドキュメント ⏳

### L.1 未作成ドキュメント

- [ ] README.md（プロジェクト概要、セットアップ手順）
- [ ] 手動介入運用手順書（§6成果物）
- [ ] MCPツール仕様書（§6成果物）
- [ ] ジョブスケジューラ仕様書（§6成果物）
- [ ] プロファイル健全性監査運用手順

---

## Phase M: MCPツールリファクタリング ✅

MCPツールを**30個から11個**に簡素化。実装完了、E2E検証は Phase N で実施。

### M.1 設計方針

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

### M.2 新MCPツール一覧（11ツール）✅

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

### M.3 実装状況 ✅

| 項目 | 状態 |
|------|:----:|
| 11個の新ツール定義（`src/mcp/server.py`） | ✅ |
| 11個のハンドラー実装（`_handle_*`） | ✅ |
| `SearchPipeline`（`src/research/pipeline.py`） | ✅ |
| 用語統一（subquery → search） | ✅ |
| エラーコード体系（`src/mcp/errors.py`） | ✅ |
| 旧ツール定義の削除（29個 → 0個） | ✅ |

### M.4 内部パイプライン ✅

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

### M.5 テスト状況 ✅

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

### M.6 残作業

| 項目 | 状態 | 備考 |
|------|:----:|------|
| Cursor AI無応答ハンドリング（§2.1.5） | ⏳ | 300秒タイムアウト→状態保存→待機 |
| DBスキーマ列名変更（subquery→search） | ⏳ | 既存データ考慮、将来マイグレーション |

---

## Phase N: E2Eケーススタディ（論文投稿向け）⏳🔴優先

論文投稿に必要な「動くソフトウェア」の実証。**E2E環境確認 → MCPツール疎通確認 → ケーススタディ実施** の順で進める。

### N.1 目的

| 観点 | 目的 |
|------|------|
| **統合動作確認** | Phase A-M の成果が連結して動作することの実証 |
| ケーススタディ | 論文に記載する具体的な使用例の作成 |
| OSS価値の実証 | 透明性・監査可能性・再現性の確保 |

### N.2 タスク一覧（優先順）

| ID | 項目 | 内容 | 状態 |
|----|------|------|:----:|
| **N.2-1** | **E2E実行環境確認** | Chrome CDP、Ollama、コンテナ間通信 | ✅ |
| **N.2-2** | **MCPツール疎通確認** | `create_task` → `search` → `get_materials` | ⏳ |
| N.2-3 | セキュリティE2E | L1-L8の統合動作確認 | ⏳ |
| N.2-4 | CS-1シナリオ設計 | リラグルチド安全性情報 | ⏳ |
| N.2-5 | CS-1実施・記録 | 実際の検索・収集・可視化 | ⏳ |
| N.2-6 | 論文向け図表作成 | エビデンスグラフ、フロー図 | ⏳ |

### N.3 E2E実行環境確認（N.2-1）✅

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

### N.4 MCPツール疎通確認（N.2-2）⏳

**目的**: 11個の新MCPツールが実環境で正しく動作することを確認

| ツール | 確認内容 | 状態 |
|--------|---------|:----:|
| `create_task` | タスクがDBに作成される | ⏳ |
| `get_status` | タスク状態が正しく返る | ⏳ |
| `search` | 検索パイプラインが完走する | ⏳ |
| `stop_task` | タスクが終了し統計が返る | ⏳ |
| `get_materials` | エビデンスグラフが構築される | ⏳ |
| `calibrate` | 校正サンプルが登録される | ⏳ |
| `get_auth_queue` | 認証待ちが取得できる | ⏳ |
| `resolve_auth` | 認証完了が記録される | ⏳ |
| `notify_user` | トースト通知が表示される | ⏳ |
| `wait_for_user` | ユーザー入力待機が動作する | ⏳ |

**手順**:
```bash
# MCPツール疎通確認スクリプト
podman exec lancet python tests/scripts/verify_mcp_integration.py
```

### N.5 セキュリティE2E（N.2-3）⏳

Phase K.3 の防御層が統合環境で正しく動作することを確認。

| 層 | 確認内容 | 状態 |
|----|---------|:----:|
| L1 | Ollamaから外部通信不可 | ⏳ |
| L2/L3/L4 | サニタイズ済みプロンプトでLLM正常動作 | ⏳ |
| L5/L6 | MCP応答に`_lancet_meta`が含まれる | ⏳ |
| L7 | 予期しないフィールドが除去される | ⏳ |
| L8 | ログにプロンプト本文が含まれない | ⏳ |

### N.6 ケーススタディ（CS-1）

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

### N.7 成功基準

| 基準 | 閾値 | 測定方法 |
|------|------|---------|
| パイプライン完走 | 全ステップ成功 | ログのcause_id連結確認 |
| エビデンスグラフ構築 | ≥5件の主張-断片-ソース関係 | `get_materials`の返却値 |
| 検索エンジン多様化 | ≥3エンジンから結果取得 | 検索ログ |
| エラーなし完了 | 未処理例外ゼロ | ログ確認 |

### N.8 記録項目

| 項目 | 形式 | 用途 |
|------|------|------|
| 実行ログ | JSONL | 再現性、因果トレース |
| スクリーンショット | PNG | 論文図表、デモ |
| エビデンスグラフ | JSON/GraphML | 論文図表 |
| 実行時間・リソース | メトリクス | 性能評価 |
| WARC/PDF | アーカイブ | 監査可能性の実証 |

### N.9 OSS価値の実証ポイント

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

Phase G.2 参照。

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
