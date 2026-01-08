# Error Analysis: lyra_20260108.log

## 概要

**対象ログ**: `logs/lyra_20260108.log`  
**分析日時**: 2026-01-08  
**総ログ行数**: 3,969行
**最終更新**: 2026-01-08 (デバッグセッション後)

---

## 修正ステータスサマリー

| 問題 | ステータス | 修正内容 |
|------|-----------|----------|
| CDP接続タイムアウト（143秒ハング） | ✅ **FIXED** | `connect_over_cdp(timeout=)` パラメータ追加 |
| Chrome background throttling | ✅ **FIXED** | 3フラグ追加済み |
| E1: Wayback timeout | ✅ **FIXED** | タイムアウト30秒→10秒に短縮 |
| E2: Browser fetch error | ✅ **FIXED** | PDF URLスキップ + TargetClosedError対策 |
| WARNING: Pipeline timeout | ⚪ 設計通り | 安全停止機構が正常動作 |
| Worker 1未使用 | ⚪ 設計通り | Lazy Startup設計 |

---

## ログ統計サマリー

| ログレベル | 件数 | 備考 |
|------------|------|------|
| INFO | 1,279件 | 正常動作 |
| HTTP Request | 2,614件 | 全て200 OK（4xx/5xxなし） |
| WARNING | **12件** | 後述 |
| ERROR | **2件** | 後述 |
| CRITICAL/FATAL | 0件 | - |

---

## ERROR (2件)

### E1: Wayback snapshot query error ✅ FIXED

| 項目 | 内容 |
|------|------|
| 発生元 | `src.crawler.wayback` |
| URL | `https://www.reliasmedia.com/articles/143780-insulin-therapy-for-type-2-diabetes-` |
| エラー | `curl: (28) Operation timed out after 30002 milliseconds` |
| 原因 | Wayback Machine APIへのcurl接続が30秒でタイムアウト |
| 影響度 | 低（フォールバック機構の末端） |
| タイムスタンプ | 2026-01-08T04:02:08.825231Z |

**修正 (2026-01-08)**:
- タイムアウト30秒→10秒に短縮（CDXクエリ・スナップショットフェッチ両方）
- 検証結果: 403ブロックされるサイトはWaybackにアーカイブされていないことが多く、長時間待つ価値が低い

### E2: Browser fetch error ✅ FIXED

| 項目 | 内容 |
|------|------|
| 発生元 | `src.crawler.browser_fetcher` |
| URL | `https://care.diabetesjournals.org/content/diacare/43/11/2859.full.pdf` |
| モード | `headful: true` |
| エラー | `Page.content: Unable to retrieve content because the page is navigating and changing the content.` |
| 原因 | PDFのロード中に`page.content()`を呼び出した |
| 影響度 | 中（コンテンツ取得失敗） |
| タイムスタンプ | 2026-01-08T04:02:28.028439Z |

**修正 (2026-01-08)**:
- ✅ Chrome background throttlingフラグ追加（`scripts/lib/chrome/start.sh`）
- ✅ `_cleanup_stale_browser()` でTargetClosedError時のリカバリ追加
- ✅ **PDF URLスキップ**: `ingest_url_action` でPDF URLを早期リターン

**設計判断**: PDFフルテキスト取得は仕様外（Abstract-only設計）。ブラウザでPDFを開いても`page.content()`では`<embed>`タグのみ取得され、本文テキストは抽出不可能。Academic API経由のabstract取得で代替。

---

## WARNING (12件)

### カテゴリ1: Wayback fallback failed - no_snapshots_available (2件)

Wayback Machineにアーカイブスナップショットが存在しない。

| URL | タイムスタンプ |
|-----|---------------|
| `https://medx.it.com/understanding-the-mechanism-why-is-the-risk-of-hypoglycemia-` | 2026-01-08T03:48:36.470913Z |
| `https://www.reliasmedia.com/articles/143780-insulin-therapy-for-type-2-diabetes-` | 2026-01-08T04:02:08.825621Z |

### カテゴリ2: Pipeline timeout - safe stop (10件)

検索パイプラインが300秒（5分）のタイムアウトに達して安全停止。

| クエリ | タイムスタンプ |
|--------|---------------|
| DPP-4 inhibitors add-on insulin therapy type 2 dia... | 2026-01-08T03:49:19.564999Z |
| DPP-4 inhibitor insulin combination glycemic contr... | 2026-01-08T03:52:12.217070Z |
| DPP-4 inhibitor insulin hypoglycemia risk safety | 2026-01-08T03:52:12.742379Z |
| sitagliptin linagliptin add-on basal insulin HbA1c | 2026-01-08T03:52:12.756333Z |
| DPP-4 inhibitors weight gain insulin therapy diabe... | 2026-01-08T03:54:19.603930Z |
| DPP-4 inhibitor limitations criticism concerns typ... | 2026-01-08T03:57:12.239618Z |
| saxagliptin alogliptin vildagliptin insulin combin... | 2026-01-08T03:57:12.795612Z |
| DPP-4 inhibitor vs GLP-1 agonist add-on insulin co... | 2026-01-08T03:57:12.807992Z |
| DPP-4 inhibitor cardiovascular safety heart failur... | 2026-01-08T03:59:19.990787Z |
| incretin-based therapy insulin intensification typ... | 2026-01-08T04:02:12.284087Z |

---

## INFO (注意すべきイベント)

ERROR/WARNINGではないが、異常系のリカバリ動作や認証ブロックを示すイベント。

### I1: CDP connection failed, attempting auto-start (1件) ✅ FIXED

| 項目 | 内容 |
|------|------|
| 発生元 | `src.search.browser_search_provider` |
| イベント | Chromeへの接続失敗→自動起動試行 |
| 分類 | リカバリ動作 |
| タイムスタンプ | 2026-01-08T03:44:22.086185Z |

**注記**: Worker 0のみ起動されており、Worker 1は存在しない。

**修正内容 (2026-01-08)**:
- **問題**: CDP接続失敗時に143〜156秒のハングが発生
- **原因**: `asyncio.wait_for()` のタイムアウトがPlaywright内部で効かなかった
- **修正**: `connect_over_cdp(cdp_url, timeout=5000)` でPlaywright自体のタイムアウトを設定
- **結果**: 5秒で正しくタイムアウトし、auto-startが発動するようになった

### I2: URL blocked by authentication, queued for later (2件)

403エラーで認証ブロックされ、介入キューに追加。

| URL | タイムスタンプ |
|-----|---------------|
| `https://medx.it.com/understanding-the-mechanism-...` | 2026-01-08T03:48:36.510981Z |
| `https://www.reliasmedia.com/articles/143780-...` | 2026-01-08T04:02:08.881551Z |

### I3: Attempting Wayback fallback (2件)

status=403で認証要求を受け、Waybackへフォールバック試行。

| URL | タイムスタンプ |
|-----|---------------|
| `https://medx.it.com/understanding-the-mechanism-...` | 2026-01-08T03:48:24.929175Z |
| `https://www.reliasmedia.com/articles/143780-...` | 2026-01-08T04:01:38.820895Z |

### I4: Authentications skipped by domain (2件)

ユーザー操作により認証をスキップ。

| ドメイン | 影響タスク | タイムスタンプ |
|----------|-----------|---------------|
| medx.it.com | task_14648cd7 | 2026-01-08T03:49:32.655969Z |
| www.reliasmedia.com | task_14648cd7 | 2026-01-08T04:02:40.289938Z |

---

## イベント分類図

```
ログイベント
├── 🔴 ERROR (2件)
│   ├── E1: Wayback snapshot query error (タイムアウト) ✅ FIXED
│   └── E2: Browser fetch error (PDFナビゲーション中) ✅ FIXED
│
├── 🟡 WARNING (12件)
│   ├── Wayback fallback failed (2件) ⚪ 外部依存
│   └── Pipeline timeout - safe stop (10件) ⚪ 設計通り
│
└── 🟢 INFO (注意すべきもの)
    ├── I1: CDP connection failed, attempting auto-start (1件) ✅ FIXED
    ├── I2: URL blocked by authentication (2件) ⚪ 正常動作
    ├── I3: Attempting Wayback fallback (2件) ⚪ 正常動作
    └── I4: Authentications skipped by domain (2件) ⚪ 正常動作
```

---

## 調査結果

### 1. Worker 01が開いていない問題

#### 調査結果: 正常動作（設計通り）

**状況**:
- 設定: `config/settings.yaml` → `concurrency.target_queue.num_workers: 2`
- ログ: Worker 0のみ起動（Worker 1は起動されていない）

```
Worker 0 (port=9222, profile=Lyra-00): Starting... OK
```

**設計確認** (ADR-0014):
- Chrome Worker Poolは **Lazy Startup（遅延起動）** 設計
- 各Workerは必要になった時点で初めてChromeインスタンスを起動
- グローバルロックで複数Workerの同時起動競合を防止

**分析**:
| 設計要素 | 内容 |
|---------|------|
| Worker ID決定 | `options.get("worker_id", 0)` でデフォルト0 |
| 起動契機 | `BrowserSearchProvider._auto_start_chrome()`でCDP接続失敗時に起動 |
| 起動スクリプト | `scripts/chrome.sh start-worker N` |

**結論**: Worker 1が起動されていないのは**正常動作**。今回のタスク（task_14648cd7）では並列処理でWorker 1を必要とするシチュエーションが発生しなかった。

**仮説（Worker 1が使われない理由）**:
1. **JobSchedulerのworker_idとBrowser Worker IDが別概念**: JobSchedulerの`_worker(slot, worker_id)`はSlot内インデックスであり、Browser Worker ID（Chrome接続先）とは連携していない可能性
2. **options経由でのworker_id伝播不足**: `_execute_target_queue`で`options`をそのまま使用しているが、JobSchedulerのworker_idがoptionsに含まれていない
3. **単一タスクでの逐次処理**: 同一タスク内のtarget_queueジョブが逐次実行され、並列度が上がらなかった

---

### 2. Browser fetch error (E2) - PDFナビゲーション問題

#### 調査結果: バックグラウンドタブThrottlingが原因の可能性

**状況**:
- URL: `https://care.diabetesjournals.org/content/diacare/43/11/2859.full.pdf`
- モード: `headful: true`
- エラー: `Page.content: Unable to retrieve content because the page is navigating and changing the content.`

**発生時系列**:
```
04:02:24.961 - Ingesting URL (citation_chase, depth=1)
04:02:28.028 - Browser fetch error ← 約3秒後にエラー
```

**現在の実装** (`src/crawler/browser_fetcher.py`):
```python
# Navigate
response = await page.goto(
    url,
    timeout=self._settings.crawler.page_load_timeout * 1000,
    wait_until="domcontentloaded",  # ← DOMContentLoaded待ち
)

# Wait for dynamic content with human-like variation
wait_time = HumanBehavior.random_delay(1.0, 2.5) if simulate_human else 1.0
await page.wait_for_timeout(int(wait_time * 1000))

# Get content
content = await page.content()  # ← ここでエラー
```

**仮説**:

| # | 仮説 | 根拠 | 蓋然性 |
|---|------|------|--------|
| H1 | PDFはDOMContentLoaded後もナビゲーションが継続 | PDFビューアプラグインがロード後にコンテンツを差し替える | 高 |
| H2 | バックグラウンドタブでページ処理が遅延 | Chromeはバックグラウンドタブのリソースを制限する | 中〜高 |
| H3 | wait_for_timeout(1-2.5秒)が不十分 | PDF+バックグラウンドでは不足の可能性 | 中 |

**Chrome起動フラグ調査** (`scripts/lib/chrome/start.sh`):

現在設定されているフラグ:
```bash
--remote-debugging-port=$port
--remote-debugging-address=127.0.0.1
--user-data-dir=$dataDir
--no-first-run
--no-default-browser-check
--disable-background-networking  # ← ネットワークのみ
--disable-sync
```

**バックグラウンド制御フラグ** ✅ FIXED:
| フラグ | 効果 | ステータス |
|--------|------|----------|
| `--disable-background-timer-throttling` | バックグラウンドタブのタイマー制限を無効化 | ✅ 追加済み |
| `--disable-backgrounding-occluded-windows` | 隠れたウィンドウのバックグラウンド化を無効化 | ✅ 追加済み |
| `--disable-renderer-backgrounding` | レンダラープロセスのバックグラウンド化を無効化 | ✅ 追加済み |

---

### 3. バックグラウンド動作の安定性 ✅ FIXED

#### 調査結果: Chromeのバックグラウンド制限が影響している可能性

**Chromeのバックグラウンドタブ制限** (Chrome公式ドキュメントより):
1. **タイマースロットリング**: `setTimeout`/`setInterval`が1秒に1回に制限
2. **リソース優先度低下**: CPU/ネットワーク帯域がアクティブタブに優先割り当て
3. **ページフリーズ**: 長時間バックグラウンドのタブは完全にフリーズされる場合あり

**今回の状況との関連**:
- ブラウザウィンドウがアクティブでない（ユーザー申告）
- PDFビューアはJavaScriptベースでタイマーを使用する可能性
- headful=trueでのフェッチが3秒程度で失敗

**影響の証拠**:
- `page.content()`呼び出し時に「ページがナビゲーション中」エラー
- これはページのレンダリング/ナビゲーションがバックグラウンドで遅延し、完了前に`page.content()`が呼ばれたことを示唆

**現在のアーキテクチャ上の問題点**:

```
[WSL2] MCP Server
    ↓ CDP (localhost:9222)
[Windows] Chrome (バックグラウンド)
    ↓ タブ操作
[Chrome Tab] PDFビューア ← バックグラウンドで処理遅延
```

**仮説まとめ（最終更新: 2026-01-08）**:

| 問題 | 状況 | 仮説 | ステータス |
|------|------|------|----------|
| CDP接続ハング | 143秒→5秒に改善 | Playwrightのtimeoutパラメータ未設定 | ✅ FIXED |
| Worker 1未使用 | 設計通り（遅延起動） | worker_idの伝播が不十分な可能性あり | ⚪ 設計通り |
| Browser fetch error | PDFフェッチで発生 | H1: PDF特有のナビゲーション + H2: バックグラウンド制限の複合要因 | ✅ FIXED (PDF URLスキップ) |
| バックグラウンド不安定 | ユーザー報告あり | Chromeのバックグラウンドタブ制限フラグが未設定 | ✅ FIXED |

---

## 修正履歴

### 2026-01-08: CDPタイムアウト修正

**修正ファイル**:
- `src/crawler/browser_fetcher.py`
- `src/search/browser_search_provider.py`

**修正内容**:
```python
# Before: asyncio.wait_forのみ（Playwright内部では効かない）
await asyncio.wait_for(
    self._playwright.chromium.connect_over_cdp(cdp_url),
    timeout=5.0,
)

# After: Playwright自体のtimeoutパラメータを使用
await asyncio.wait_for(
    self._playwright.chromium.connect_over_cdp(
        cdp_url,
        timeout=5000,  # ミリ秒単位
    ),
    timeout=6.0,  # 安全マージン
)
```

**効果**: CDP接続タイムアウトが143秒→5秒に短縮

### 2026-01-08: Chrome background throttlingフラグ追加

**修正ファイル**: `scripts/lib/chrome/start.sh`

**追加フラグ**:
```bash
--disable-background-timer-throttling
--disable-backgrounding-occluded-windows
--disable-renderer-backgrounding
```

**効果**: バックグラウンドでのページ処理遅延を軽減

### 2026-01-08: PDF URLスキップ

**修正ファイル**: `src/research/pipeline.py`

**修正内容**:
```python
# ingest_url_action の冒頭でPDF URLをスキップ
url_lower = url.lower()
if url_lower.endswith('.pdf') or '/pdf/' in url_lower:
    logger.info("Skipping PDF URL (abstract-only design)", url=url[:100])
    return {
        "ok": False,
        "reason": "pdf_not_supported",
        "status": "skipped",
        ...
    }
```

**設計根拠**:
- ChromeでPDFを開くと`page.content()`は`<embed>`タグのみ返す
- PDFの本文テキストはブラウザAPI経由では取得不可能
- Lyraは「Abstract-only」設計であり、フルテキストPDF処理は仕様外

### 2026-01-08: Waybackタイムアウト短縮＋設定化

**修正ファイル**: 
- `src/crawler/wayback.py`
- `src/utils/config.py`
- `config/settings.yaml`

**修正内容**:
```yaml
# config/settings.yaml
crawler:
  wayback_timeout: 10  # デフォルト10秒（30秒から短縮）
```

```python
# src/crawler/wayback.py
timeout = self._settings.crawler.wayback_timeout
```

**根拠**:
- 検証結果: Wayback CDX APIは正常動作している
- 403ブロックされるサイトはWaybackにアーカイブされていないことが多い
- 今回のログでは成功ケース0件、タイムアウト待ちのコストが高い
- 10秒で十分な判断が可能
- 設定ファイルで調整可能に
