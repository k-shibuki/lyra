# O.6 追加仕様違反調査結果

## 調査日: 2025-12-11

O.6の実装完了後、同様のパターンで他の仕様違反がないか調査した結果。

---

## 問題3: 認証待ちキューで保存されたセッションが後続リクエストで再利用されていない ✅ 実装完了

**実装完了日**: 2025-12-11  
**実装ファイル**: `src/crawler/fetcher.py:1086-1137`  
**検証スクリプト**: `tests/scripts/debug_auth_session_reuse_flow.py`

### 影響範囲

**影響箇所**:
- `src/crawler/fetcher.py:933` - `BrowserFetcher.fetch()`
- `src/search/browser_search_provider.py` - `BrowserSearchProvider.search()`（要確認）

### 現状の実装

```python
# src/crawler/fetcher.py:933-970
async def fetch(self, url: str, ...):
    domain = urlparse(url).netloc.lower()
    
    # 既存セッションのチェックなし
    browser, context = await self._ensure_browser(headful=headful, task_id=task_id)
    
    page = await context.new_page()
    # Cookie設定なしで直接ナビゲート
    response = await page.goto(url, ...)
    
    # 認証待ちが発生したらキューに積むだけ
    if _is_challenge_page(content, {}):
        if allow_intervention and queue_auth and task_id:
            queue = get_intervention_queue()
            queue_id = await queue.enqueue(...)  # キューに積むだけ
            return FetchResult(ok=False, reason="auth_required", ...)
```

### 問題点

1. **既存セッションのチェックなし**: `fetch()`の開始時に、`InterventionQueue.get_session_for_domain()`で既存の認証済みセッションをチェックしていない
2. **Cookie設定なし**: 認証待ちキューで保存されたCookieを、ブラウザのcontextに設定する処理がない
3. **再認証の発生**: 認証済みのドメインでも、毎回認証待ちが発生する可能性がある

### 仕様書の要件

- §3.6.1: "セッション共有: 認証済みCookie/セッションは同一ドメインの後続リクエストで自動再利用"
- §3.6.1: "ドメインベース認証管理: 同一ドメインの認証は1回の突破で複数タスク/URLに適用される"

### 修正提案

**方針**: `fetch()`の開始時に、認証待ちキューから既存セッションを取得し、Cookieをブラウザcontextに設定する

**実装箇所**:
- `src/crawler/fetcher.py:933` - `BrowserFetcher.fetch()`

**修正案**:
```python
async def fetch(self, url: str, ...):
    domain = urlparse(url).netloc.lower()
    
    # 認証待ちキューから既存セッションをチェック
    from src.utils.notification import get_intervention_queue
    queue = get_intervention_queue()
    existing_session = await queue.get_session_for_domain(domain, task_id=task_id)
    
    browser, context = await self._ensure_browser(headful=headful, task_id=task_id)
    
    # 既存セッションがあればCookieを設定
    if existing_session and existing_session.get("cookies"):
        cookies = existing_session["cookies"]
        # PlaywrightのCookie形式に変換
        playwright_cookies = [
            {
                "name": c.get("name"),
                "value": c.get("value"),
                "domain": c.get("domain", domain),
                "path": c.get("path", "/"),
                "expires": c.get("expires"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", True),
                "sameSite": c.get("sameSite", "Lax"),
            }
            for c in cookies
        ]
        await context.add_cookies(playwright_cookies)
        logger.info(
            "Applied stored authentication cookies",
            domain=domain,
            cookie_count=len(playwright_cookies),
        )
    
    page = await context.new_page()
    # ... 以下既存の処理
```

**注意点**:
- Cookieの有効期限チェックが必要
- サブドメイン対応（`.example.com`と`www.example.com`）
- `browser_search_provider.py`でも同様の処理が必要か確認

---

## 問題4: BrowserSearchProviderでのセッション再利用未実装（要確認）✅ 確認完了

**確認完了日**: 2025-12-15

### 確認結果

**現状の実装**:
- `BrowserSearchProvider._ensure_browser()`で既存のbrowser contextを再利用しCookieを保持
- `_sessions`辞書でエンジン別にセッションを管理
- 認証待ちキューからの直接取得は未実装

**結論**: 
- 検索エンジンは通常認証不要のため、現状の実装で仕様要件を満たしている
- 既存context再利用によりCookie/セッションは保持される（§3.6.1準拠）
- 認証が必要な特殊ケース（Googleログイン必須検索等）は、BrowserFetcherの認証待ちキュー機能で対応可能

### 影響範囲

**影響箇所**:
- `src/search/browser_search_provider.py` - `BrowserSearchProvider.search()`

---

## 問題5: start_session()でブラウザを開く処理が未実装 ✅ 実装完了

**実装完了日**: 2025-12-11  
**実装ファイル**: `src/utils/notification.py:1165-1200`, `src/crawler/fetcher.py:738-960` (Chrome自動起動)  
**検証スクリプト**: `tests/scripts/debug_start_session_browser_flow.py`, `tests/scripts/debug_chrome_auto_start.py`

### 影響範囲

**影響箇所**:
- `src/utils/notification.py:1077` - `InterventionQueue.start_session()`

### 現状の実装

```python
# src/utils/notification.py:1077
async def start_session(self, task_id: str, ...):
    # URLを返すだけで、ブラウザを開く処理がない
    return {
        "ok": True,
        "session_started": True,
        "count": len(items),
        "items": items,  # URLのリストのみ
    }
```

### 問題点

1. **ブラウザを開く処理がない**: `start_session()`はURLを返すだけで、実際にブラウザでURLを開く処理がない
2. **ウィンドウ前面化がない**: 仕様書では「認証待ちURLを開いてウィンドウを前面化するのみ」とあるが、実装されていない
3. **ユーザー手動操作が必要**: ユーザーが手動でブラウザを開く必要がある

### 仕様書の要件

- §3.6.1: "最小介入原則: 認証待ちURLを開いてウィンドウを前面化するのみ"
- §3.6.1: "CDPの安全運用: 許可: `Page.navigate`（URLを開く）、`Page.bringToFront`（前面化、OS API併用推奨）"

### 修正提案

**方針**: `start_session()`で、返されたURLをブラウザで開き、ウィンドウを前面化する

**実装箇所**:
- `src/utils/notification.py:1077` - `InterventionQueue.start_session()`

**修正案**:
```python
async def start_session(self, task_id: str, ...):
    # ... 既存の処理（URL取得・in_progressマーク） ...
    
    # ブラウザでURLを開く（安全な方法で）
    if items:
        from src.search.browser_search_provider import BrowserSearchProvider
        provider = BrowserSearchProvider()
        await provider._ensure_browser()
        
        if provider._context:
            # 最初のURLを開く
            page = await provider._context.new_page()
            await page.goto(items[0]["url"], wait_until="domcontentloaded")
            
            # ウィンドウを前面化（安全な方法で）
            from src.utils.notification import get_intervention_manager
            manager = get_intervention_manager()
            await manager._bring_tab_to_front(page)
            
            logger.info(
                "Opened authentication URL in browser",
                url=items[0]["url"],
                total_count=len(items),
            )
    
    return {
        "ok": True,
        "session_started": True,
        "count": len(items),
        "items": items,
    }
```

**注意点**:
- 複数のURLがある場合、最初のURLのみ開く（ユーザーが手動で他のURLを開く想定）
- `Page.navigate`と`Page.bringToFront`のみ使用（DOM操作は禁止）
- OS APIでのウィンドウ前面化も併用

---

## 問題6: Chromeプロファイル名が仕様と不一致（要確認）✅ 確認完了

**確認完了日**: 2025-12-15

### 確認結果

**現状の実装**:
- WSL: `$env:LocalApplicationData\LyraChrome`
- Linux: `$HOME/.local/share/lyra-chrome`
- 専用の`--user-data-dir`を使用し、日常プロファイルから完全に分離

**結論**:
- 専用の`user-data-dir`（`LyraChrome`）により、日常プロファイルへの影響は遮断されている
- `--profile-directory`は未指定だが、専用ディレクトリを使用しているため機能的には問題なし
- 仕様書の`Profile-Research`は参考例であり、現在の実装で仕様の意図（研究用隔離）は達成されている

### 影響範囲

**影響箇所**:
- `scripts/chrome.sh:284` - Chrome起動スクリプト

### 仕様書の要件

- §3.2: "調査専用プロファイル運用: 研究専用のChromeプロファイルを`--user-data-dir`/`--profile-directory`で固定化（例: `--profile-directory="Profile-Research"`）"
- §4.3.1: "安全策: `Profile-Research`のみを対象、日常プロファイルへの影響を遮断"

---

## 問題7: LocalStorageの研究用隔離の確認（要確認）✅ 確認完了

**確認完了日**: 2025-12-15

### 確認結果

**現状の実装**:
- 専用の`user-data-dir`（`LyraChrome` / `lyra-chrome`）を使用
- Chromeは`user-data-dir`ごとに独立したCookie/LocalStorage/IndexedDBを保持

**結論**:
- 専用`user-data-dir`により、Cookie/LocalStorageは自動的に研究用として隔離されている
- 日常のブラウジングデータとは完全に分離されている
- **問題なし**

### 影響範囲

**影響箇所**:
- Chromeプロファイル設定全般

---

## 優先度

**問題3**: 🔴 高（仕様違反）
- §3.6.1の核心機能「セッション共有」が実装されていない
- 認証完了後も再認証が必要になり、運用効率が低下

**問題5**: 🔴 高（仕様違反）
- §3.6.1の「最小介入原則」に違反
- ユーザーが手動でブラウザを開く必要があり、UXが悪い

**問題4**: ✅ 確認完了
- 検索エンジンは認証不要のため現状で問題なし
- 既存context再利用によりCookie/セッション保持済み

**問題6**: ✅ 確認完了
- 専用`user-data-dir`で日常プロファイルから分離済み
- 機能的には問題なし

**問題7**: ✅ 確認完了
- 専用`user-data-dir`によりCookie/LocalStorageは自動隔離
- 問題なし

---

## 関連ファイル

| ファイル | 役割 | 修正内容 |
|---------|------|---------|
| `src/crawler/fetcher.py` | ブラウザフェッチャー | 既存セッション取得・Cookie設定 |
| `src/utils/notification.py` | 認証待ちキュー | start_session()でブラウザを開く処理追加 |
| `src/search/browser_search_provider.py` | ブラウザ検索プロバイダー | 既存セッション取得・Cookie設定（要確認） |
| `scripts/chrome.sh` | Chrome起動スクリプト | プロファイル名指定（要確認） |

---

## 問題8: BrowserSearchProviderでエンジン選択ロジックが未実装

### 影響範囲

**影響箇所**:
- `src/search/browser_search_provider.py:280` - `BrowserSearchProvider.search()`

### 現状の実装

```python
# src/search/browser_search_provider.py:280-283
# Determine engine to use
engine = self._default_engine
if options.engines:
    engine = options.engines[0]  # 単純に最初のエンジンを使用
```

### 問題点

1. **重み付け選択がない**: 仕様では「カテゴリ（ニュース/学術/政府/技術）で層別化し、過去の精度/失敗率/ブロック率で重みを学習」とあるが、実装されていない
2. **サーキットブレーカのチェックがない**: エンジンが`open`状態（クールダウン中）でも使用される可能性がある
3. **エンジンヘルスの記録がない**: 検索成功/失敗が`engine_health`テーブルに記録されていない
4. **カテゴリ別選択がない**: クエリのカテゴリに応じたエンジン選択が実装されていない
5. **ラストマイル・スロットの実装がない**: 「回収率の最後の10%を狙う限定枠としてGoogle/Braveを最小限開放」が実装されていない

### 仕様書の要件

- §3.1: "エンジン選択と重み付け: カテゴリ（ニュース/学術/政府/技術）で層別化し、過去の精度/失敗率/ブロック率で重みを学習"
- §3.1.4: "ヘルスチェック/サーキットブレーカ: 連続失敗≥2で`open`、成功1回で`half-open`→安定で`closed`"
- §3.1.4: "ヘルスの永続化: SQLiteの`engine_health`テーブルにEMA（1h/24h）を保持し、重み・QPS・探索枠を自動調整"
- §3.1: "ラストマイル・スロット: 回収率の最後の10%を狙う限定枠としてGoogle/Braveを最小限開放（厳格なQPS・回数・時間帯制御）"

### 修正提案

**方針**: `BrowserSearchProvider.search()`で、重み付け・サーキットブレーカ・カテゴリ別選択を実装する

**実装箇所**:
- `src/search/browser_search_provider.py:260` - `BrowserSearchProvider.search()`

**修正案**:
```python
async def search(self, query: str, options: SearchOptions | None = None) -> SearchResponse:
    # ... 既存の処理 ...
    
    # エンジン選択ロジック（重み付け・サーキットブレーカ考慮）
    from src.search.circuit_breaker import check_engine_available, record_engine_result
    from src.search.engine_config import get_engine_config_manager
    
    config_manager = get_engine_config_manager()
    
    # カテゴリ判定（簡易版）
    category = self._detect_category(query)
    
    # 利用可能なエンジンを取得（サーキットブレーカ考慮）
    if options.engines:
        candidate_engines = options.engines
    else:
        # カテゴリに応じたエンジン選択
        candidate_engines = config_manager.get_engines_for_category(category)
        if not candidate_engines:
            candidate_engines = config_manager.get_default_engines()
    
    # 重み付け・サーキットブレーカでフィルタリング
    available_engines = []
    for engine_name in candidate_engines:
        if await check_engine_available(engine_name):
            engine_config = config_manager.get_engine(engine_name)
            if engine_config and engine_config.is_available:
                available_engines.append((engine_name, engine_config.weight))
    
    if not available_engines:
        # ラストマイル・スロットを試行
        lastmile_engines = config_manager.get_lastmile_engines()
        for engine_name in lastmile_engines:
            if await check_engine_available(engine_name):
                engine_config = config_manager.get_engine(engine_name)
                if engine_config and engine_config.is_available:
                    available_engines.append((engine_name, engine_config.weight))
                    break  # ラストマイルは1つだけ
    
    if not available_engines:
        return SearchResponse(
            results=[],
            query=query,
            provider=self.name,
            error="No available engines",
            elapsed_ms=0,
        )
    
    # 重み付けで選択（簡易版: 重みの高い順）
    available_engines.sort(key=lambda x: x[1], reverse=True)
    engine = available_engines[0][0]
    
    # ... 検索実行 ...
    
    # エンジンヘルスの記録
    try:
        if response.ok:
            await record_engine_result(engine, success=True, latency_ms=elapsed_ms)
        else:
            is_captcha = parse_result.is_captcha if 'parse_result' in locals() else False
            await record_engine_result(engine, success=False, latency_ms=elapsed_ms, is_captcha=is_captcha)
    except Exception as e:
        logger.warning("Failed to record engine result", engine=engine, error=str(e))
    
    return response
```

**注意点**:
- カテゴリ判定は簡易版で実装（クエリ内容から推定）
- 重み付け選択は簡易版（重みの高い順）で実装し、後で学習機能を追加
- ラストマイル・スロットは回収率の判定が必要（別途実装）

**実装状況（2025-12-15）**:
- ✅ カテゴリ判定（`_detect_category()`）: 実装完了
- ✅ カテゴリ別エンジン選択（`get_engines_for_category()`）: 実装完了
- ✅ サーキットブレーカによるフィルタリング（`check_engine_available()`）: 実装完了
- ✅ 重み付け選択（静的設定）: 実装完了
- ✅ エンジンヘルス記録（`record_engine_result()`）: 実装完了
- ✅ 動的重み学習（過去の精度/失敗率/ブロック率による重み調整）: **実装完了**
- ❌ ラストマイル・スロット: 未実装（問題13で実装予定）

### 動的重み学習の実装（完了）

**目的**: 過去の精度/失敗率/ブロック率を基にエンジンの重みを動的に調整する

**仕様書の要件**:
- §3.1.1: "カテゴリ（ニュース/学術/政府/技術）で層別化し、過去の精度/失敗率/ブロック率で重みを学習"
- §3.1.4: "ヘルスの永続化: SQLiteの`engine_health`テーブルにEMA（1h/24h）を保持し、重み・QPS・探索枠を自動調整"
- §4.6: "ポリシー自動更新（高頻度クローズドループ制御）: イベント駆動: 各リクエスト/クエリ完了時に即時フィードバック（成功/失敗/ブロック種別/レイテンシをEMAに反映）"

**実装完了（2025-12-15）**:

| ファイル | 変更内容 |
|---------|----------|
| `src/utils/schemas.py` | `EngineHealthMetrics`, `DynamicWeightResult` Pydanticモデル追加 |
| `src/storage/database.py` | `get_engine_health_metrics()` メソッド追加 |
| `src/utils/policy_engine.py` | `calculate_dynamic_weight()`, `get_dynamic_engine_weight()` メソッド追加 |
| `src/search/browser_search_provider.py` | `search()`で動的重みを使用するよう修正 |
| `docs/sequences/dynamic_weight_flow.md` | シーケンス図作成 |
| `tests/test_policy_engine.py` | `TestDynamicWeightCalculation` クラス追加（11テスト） |
| `tests/test_browser_search_provider.py` | `TestDynamicWeightUsage` クラス追加（3テスト） |
| `tests/scripts/debug_dynamic_weight_flow.py` | デバッグスクリプト作成 |

**重み計算式**:
```
success_factor = 0.6 * success_rate_1h + 0.4 * success_rate_24h
captcha_penalty = 1.0 - (captcha_rate * 0.5)
latency_factor = 1.0 / (1.0 + median_latency_ms / 1000.0)
raw_weight = base_weight * success_factor * captcha_penalty * latency_factor
```

**時間減衰（48時間でデフォルト回帰）**:
```
confidence = max(0.1, 1.0 - (hours_since_use / 48))
final_weight = confidence * raw_weight + (1 - confidence) * base_weight
```

| 経過時間 | メトリクス反映 | デフォルト反映 |
|----------|---------------|---------------|
| 0-6時間 | 87-100% | 0-13% |
| 12時間 | 75% | 25% |
| 24時間 | 50% | 50% |
| 48時間以上 | 10% | 90% |

**テスト実行**:
```bash
# ユニットテスト
pytest tests/test_policy_engine.py::TestDynamicWeightCalculation -v

# 統合テスト
pytest tests/test_browser_search_provider.py::TestDynamicWeightUsage -v

# デバッグスクリプト
python tests/scripts/debug_dynamic_weight_flow.py
```

詳細な実装については `docs/sequences/dynamic_weight_flow.md` を参照。

---

## 問題9: BrowserSearchProviderでエンジン別QPS制限が未実装 ✅ 実装完了

**実装完了日**: 2025-12-15  
**実装ファイル**: `src/search/browser_search_provider.py:155-158` (_last_search_times追加), `src/search/browser_search_provider.py:311-339` (_rate_limit拡張), `src/search/browser_search_provider.py:484` (search呼び出し修正)  
**検証スクリプト**: `tests/scripts/debug_engine_qps_flow.py`  
**シーケンス図**: `docs/sequences/engine_qps_flow.md`

### 影響範囲

**影響箇所**:
- `src/search/browser_search_provider.py:252` - `BrowserSearchProvider._rate_limit()`

### 現状の実装

```python
# src/search/browser_search_provider.py:252-258
async def _rate_limit(self) -> None:
    """Apply rate limiting between searches."""
    async with self._rate_limiter:
        elapsed = time.time() - self._last_search_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_search_time = time.time()
```

### 問題点

1. **エンジン別QPS制限がない**: すべてのエンジンで同じ`_min_interval`を使用している
2. **エンジン設定のQPSが反映されていない**: `config/engines.yaml`で定義されたエンジン別QPS（例: DuckDuckGo=0.2, Google=0.05）が使用されていない

### 仕様書の要件

- §3.1: "エンジン別レート制御（並列度=1、厳格QPS）とサーキットブレーカ（故障切替・冷却）を実装"
- §4.3: "エンジン/ドメイン別レート制御の明確化: エンジンQPS≤0.25（1リクエスト/4s）、ドメインQPS≤0.2、並列度=1を原則"

### 修正提案

**方針**: `_rate_limit()`で、エンジン別のQPS制限を適用する

**実装箇所**:
- `src/search/browser_search_provider.py:252` - `BrowserSearchProvider._rate_limit()`

**修正案**:
```python
async def _rate_limit(self, engine: str | None = None) -> None:
    """Apply rate limiting between searches (per-engine QPS)."""
    from src.search.engine_config import get_engine_config_manager
    
    config_manager = get_engine_config_manager()
    
    # エンジン別QPSを取得
    if engine:
        engine_config = config_manager.get_engine(engine)
        if engine_config:
            min_interval = engine_config.min_interval
        else:
            min_interval = self._min_interval  # フォールバック
    else:
        min_interval = self._min_interval
    
    # エンジン別の最終検索時刻を追跡
    engine_key = engine or "default"
    if engine_key not in self._last_search_times:
        self._last_search_times[engine_key] = 0
    
    elapsed = time.time() - self._last_search_times[engine_key]
    if elapsed < min_interval:
        await asyncio.sleep(min_interval - elapsed)
    
    self._last_search_times[engine_key] = time.time()
```

**注意点**:
- `_last_search_times`を`dict[str, float]`に変更し、エンジン別に追跡
- `search()`メソッドで`_rate_limit(engine)`を呼び出す

---

## 問題10: Tor日次利用上限のチェックが未実装 ✅ 実装完了

**実装完了日**: 2025-12-15  
**実装ファイル**: 
- `src/utils/schemas.py`: `TorUsageMetrics`, `DomainTorMetrics` Pydanticモデル追加
- `src/utils/metrics.py`: `get_today_tor_metrics()`, `get_domain_tor_metrics()`, `record_request()`, `record_tor_usage()` メソッド追加
- `src/crawler/fetcher.py`: `_can_use_tor()` ヘルパー関数追加、`fetch_url()` に日次上限チェック統合

**検証スクリプト**: `tests/scripts/debug_tor_daily_limit_flow.py`  
**シーケンス図**: `docs/sequences/tor_daily_limit_flow.md`

### 影響範囲

**影響箇所**:
- `src/crawler/fetcher.py:1729` - `fetch_url()`でのTor使用判定
- `src/utils/policy_engine.py:496` - `PolicyEngine._adjust_domain_policy()`

### 現状の実装

```python
# src/crawler/fetcher.py:1729-1742
# Handle 403/429 - try Tor circuit renewal
if not result.ok and result.status in (403, 429) and not use_tor:
    logger.info("HTTP error, trying with Tor", url=url[:80], status=result.status)
    
    tor_controller = await get_tor_controller()
    if await tor_controller.renew_circuit(domain):
        result = await _http_fetcher.fetch(
            url,
            referer=context.get("referer"),
            use_tor=True,  # 日次上限チェックなし
            ...
        )
```

### 問題点

1. **日次利用上限のチェックなし**: Torを使用する前に、日次の利用上限（`max_usage_ratio: 0.20`）をチェックしていない
2. **利用状況の追跡なし**: Tor使用回数や割合を追跡するメトリクスがない
3. **グローバル上限の適用なし**: ドメイン別の`tor_usage_ratio`はあるが、グローバルな日次上限のチェックがない

### 仕様書の要件

- §4.3: "ドメイン単位のTor粘着（15分）と日次のTor利用上限（割合/回数）を適用"
- §7: "Tor利用率: 全取得に占めるTor経路の割合≤20%（日次上限とドメイン別上限を両方満たすこと）"

### 修正提案

**方針**: Torを使用する前に、日次の利用上限をチェックし、上限を超えている場合はTorを使用しない

**実装箇所**:
- `src/crawler/fetcher.py:1729` - `fetch_url()`でのTor使用判定
- `src/utils/metrics.py` - Tor使用メトリクスの追跡

**修正案**:
```python
# Tor使用前のチェック
async def _can_use_tor(domain: str | None = None) -> bool:
    """Check if Tor can be used based on daily limits.
    
    Per §4.3: Check both global daily limit and domain-specific limit.
    
    Args:
        domain: Optional domain for domain-specific check.
        
    Returns:
        True if Tor can be used.
    """
    from src.utils.metrics import get_metrics_collector
    from src.utils.config import get_settings
    
    settings = get_settings()
    max_usage_ratio = settings.tor.max_usage_ratio  # 0.20
    
    collector = get_metrics_collector()
    
    # Get today's Tor usage metrics
    today_metrics = collector.get_today_metrics()
    total_requests = today_metrics.get("total_requests", 0)
    tor_requests = today_metrics.get("tor_requests", 0)
    
    if total_requests == 0:
        return True  # No requests yet today
    
    # Check global daily limit
    current_ratio = tor_requests / total_requests
    if current_ratio >= max_usage_ratio:
        logger.debug(
            "Tor daily limit reached",
            current_ratio=current_ratio,
            max_ratio=max_usage_ratio,
        )
        return False
    
    # Check domain-specific limit if domain provided
    if domain:
        domain_metrics = collector.get_domain_metrics(domain)
        domain_total = domain_metrics.get("total_requests", 0)
        domain_tor = domain_metrics.get("tor_requests", 0)
        
        if domain_total > 0:
            domain_ratio = domain_tor / domain_total
            domain_policy = await get_domain_policy(domain)
            domain_max_ratio = domain_policy.tor_usage_ratio
            
            if domain_ratio >= domain_max_ratio:
                logger.debug(
                    "Tor domain limit reached",
                    domain=domain,
                    current_ratio=domain_ratio,
                    max_ratio=domain_max_ratio,
                )
                return False
    
    return True

# fetch_url()での使用
if not result.ok and result.status in (403, 429) and not use_tor:
    if await _can_use_tor(domain):
        # Tor使用可能
        tor_controller = await get_tor_controller()
        if await tor_controller.renew_circuit(domain):
            result = await _http_fetcher.fetch(..., use_tor=True)
            # Tor使用を記録
            collector.record_tor_usage(domain)
    else:
        logger.info("Tor daily limit reached, skipping Tor escalation")
```

**注意点**:
- Tor使用メトリクスの追跡を`MetricsCollector`に追加
- 日次リセットの処理（日付変更時にカウンターをリセット）
- ドメイン別とグローバルの両方の上限をチェック

---

## 問題11: 時間帯・日次の予算上限が未実装 ✅ 実装完了

**実装完了日**: 2025-12-15  
**実装ファイル**: 
- `src/utils/schemas.py`: `DomainDailyBudget`, `DomainBudgetCheckResult` Pydanticモデル追加
- `src/scheduler/domain_budget.py`: `DomainDailyBudgetManager` クラス新規作成
- `src/utils/domain_policy.py`: `max_requests_per_day`, `max_pages_per_day` フィールド追加
- `config/domains.yaml`: 日次予算設定追加
- `src/crawler/fetcher.py`: `fetch_url()` に日次予算チェック統合

**検証スクリプト**: `tests/scripts/debug_domain_daily_budget_flow.py`  
**シーケンス図**: `docs/sequences/domain_daily_budget_flow.md`

### 実装内容

#### ドメイン別日次予算上限（IPアドレスブロック防止）

| 設定 | デフォルト | 説明 |
|-----|----------|-----|
| `max_requests_per_day` | 200 | ドメインごとの日次リクエスト上限 |
| `max_pages_per_day` | 100 | ドメインごとの日次ページ上限 |

#### 主要機能

1. **日次予算チェック**: `fetch_url()` でリクエスト前に予算チェック
2. **自動日付リセット**: 日付変更時にカウンターを自動リセット
3. **ドメイン別設定**: `config/domains.yaml` でドメイン別の上限オーバーライド可能
4. **フェイルオープン**: 予算チェックエラー時はリクエストを許可

#### 仕様書の要件との対応

- §4.3: "時間帯・日次の予算上限を設定" → **日次予算を実装**
- §4.3: "期間・時間帯のスロット化（夜間/休日は保守的）" → **スコープ外**（ユーザー指示: 夜間/休日の概念は不要、IPブロック防止が目的）

### テスト実行

```bash
# ユニットテスト
pytest tests/test_domain_budget.py -v

# デバッグスクリプト
python tests/scripts/debug_domain_daily_budget_flow.py
```

---

## 実装時期

Phase O.6完了後、別タスクとして実装推奨。

## 問題12: セッション転送が実装されているが適用されていない ✅ 実装完了

**実装完了日**: 2025-12-11  
**実装ファイル**: `src/crawler/fetcher.py:1896-1955` (fetch_url), `src/crawler/fetcher.py:1200-1250` (BrowserFetcher), `src/crawler/fetcher.py:509-710` (HTTPFetcher)  
**検証スクリプト**: `tests/scripts/debug_session_transfer_flow.py`

### 影響範囲

**影響箇所**:
- `src/crawler/fetcher.py:1070` - `BrowserFetcher.fetch()`でのセッションキャプチャ
- `src/crawler/fetcher.py:1702` - `HTTPFetcher.fetch()`でのセッション転送ヘッダー適用
- `src/crawler/fetcher.py:1605` - `fetch_url()`での初回ブラウザ→HTTPクライアント移行

### 現状の実装

```python
# src/crawler/fetcher.py:1070-1120
async def fetch(self, url: str, ...):
    # ... ブラウザで取得 ...
    
    # セッションキャプチャの処理がない
    # capture_browser_session()が呼ばれていない
    
    return FetchResult(...)

# src/crawler/fetcher.py:1702-1708
async def fetch(self, url: str, ...):
    # HTTPクライアントで取得
    # セッション転送ヘッダーの適用がない
    # get_transfer_headers()が呼ばれていない
    
    result = await _http_fetcher.fetch(url, ...)
```

### 問題点

1. **ブラウザセッションのキャプチャなし**: `BrowserFetcher.fetch()`で成功した取得後に、`capture_browser_session()`が呼ばれていない
2. **HTTPクライアントでのセッション転送ヘッダー適用なし**: `HTTPFetcher.fetch()`で、`get_transfer_headers()`を使用してセッション転送ヘッダーを適用していない
3. **初回ブラウザ→HTTPクライアント移行の未実装**: 仕様では「初回はブラウザ経由、2回目以降はHTTPクライアントで304再訪」とあるが、このロジックが実装されていない

### 仕様書の要件

- §3.1.2: "初回取得の指紋整合: 静的ページであっても初回アクセスは原則ブラウザ経由（ヘッドレス）で実施し、Cookie/ETag/LocalStorage/指紋を自然に確立"
- §3.1.2: "2回目以降はHTTPクライアント（`curl_cffi`）でETag/If-None-Match・Last-Modified/If-Modified-Sinceを活用し軽量再訪"
- §3.1.2: "セッション移送ユーティリティ: 初回ブラウザで確立したCookie/ETag/UA/Accept-LanguageをHTTPクライアントへ安全に移送（同一ドメイン限定）"

### 修正提案

**方針**: ブラウザ取得後にセッションをキャプチャし、HTTPクライアント取得時にセッション転送ヘッダーを適用する

**実装箇所**:
- `src/crawler/fetcher.py:1070` - `BrowserFetcher.fetch()`でのセッションキャプチャ
- `src/crawler/fetcher.py:1702` - `HTTPFetcher.fetch()`でのセッション転送ヘッダー適用
- `src/crawler/fetcher.py:1605` - `fetch_url()`での初回ブラウザ→HTTPクライアント移行ロジック

**修正案**:
```python
# BrowserFetcher.fetch()でのセッションキャプチャ
async def fetch(self, url: str, ...):
    # ... 既存の取得処理 ...
    
    if result.ok:
        # セッションをキャプチャ
        from src.crawler.session_transfer import capture_browser_session
        
        response_headers = {}
        if response:
            response_headers = dict(response.headers)
        
        session_id = await capture_browser_session(
            context,
            url,
            response_headers,
        )
        
        if session_id:
            logger.debug(
                "Captured browser session",
                url=url[:80],
                session_id=session_id,
            )
    
    return result

# HTTPFetcher.fetch()でのセッション転送ヘッダー適用
async def fetch(self, url: str, ...):
    # セッション転送ヘッダーを取得
    from src.crawler.session_transfer import get_transfer_headers
    
    transfer_result = get_transfer_headers(url, include_conditional=True)
    
    if transfer_result.ok:
        # セッション転送ヘッダーを適用
        if headers is None:
            headers = {}
        headers.update(transfer_result.headers)
        
        logger.debug(
            "Applied session transfer headers",
            url=url[:80],
            session_id=transfer_result.session_id,
        )
    
    # ... 既存のHTTPリクエスト処理 ...
```

**注意点**:
- 初回取得はブラウザ経由、2回目以降はHTTPクライアント経由の判定ロジックが必要
- セッション転送は同一ドメイン限定（既に実装済み）
- ETag/Last-Modifiedの条件付きリクエストを優先

---

## 問題13: ラストマイルスロットの判定ロジックが未実装 ✅ 実装完了

**実装完了日**: 2025-12-15  
**実装ファイル**: 
- `src/search/browser_search_provider.py:400-575` (`_should_use_lastmile()`, `_select_lastmile_engine()`, `search()` 修正)
- `src/research/state.py:537-560` (`get_overall_harvest_rate()` 追加)
- `src/utils/schemas.py:104-130` (`LastmileCheckResult` モデル追加)
- `src/storage/schema.sql:253-264` (`lastmile_usage` テーブル追加)

**検証スクリプト**: `tests/scripts/debug_lastmile_slot_flow.py`  
**シーケンス図**: `docs/sequences/lastmile_slot_flow.md`

### 実装内容

#### 1. `LastmileCheckResult` Pydanticモデル
```python
class LastmileCheckResult(BaseModel):
    should_use_lastmile: bool  # Whether to use lastmile engine
    reason: str                # Reason for decision
    harvest_rate: float        # Current harvest rate (0.0-1.0)
    threshold: float = 0.9     # Threshold for lastmile activation
```

#### 2. `ExplorationState.get_overall_harvest_rate()`
```python
def get_overall_harvest_rate(self) -> float:
    """Calculate overall harvest rate across all searches."""
    if not self._searches:
        return 0.0
    total_useful = sum(s.useful_fragments for s in self._searches.values())
    total_pages = sum(s.pages_fetched for s in self._searches.values())
    return total_useful / max(1, total_pages)
```

#### 3. `BrowserSearchProvider._should_use_lastmile()`
```python
def _should_use_lastmile(self, harvest_rate: float, threshold: float = 0.9) -> LastmileCheckResult:
    """Check if lastmile engine should be used based on harvest rate."""
    if harvest_rate >= threshold:
        return LastmileCheckResult(should_use_lastmile=True, ...)
    return LastmileCheckResult(should_use_lastmile=False, ...)
```

#### 4. `BrowserSearchProvider._select_lastmile_engine()`
- Circuit breaker チェック
- 日次使用制限チェック (daily_limit)
- 厳格な QPS 制限適用

#### 5. `search()` メソッド拡張
- `harvest_rate` パラメータを追加
- `harvest_rate >= 0.9` の場合、ラストマイルエンジンを選択

### 厳格な制御

| エンジン | QPS | Daily Limit |
|---------|-----|-------------|
| brave | 0.1 | 50 |
| google | 0.05 | 10 |
| bing | 0.05 | 10 |

### テスト実行

```bash
# ユニットテスト
pytest tests/test_browser_search_provider.py::TestLastmileSlotSelection -v

# 回収率テスト
pytest tests/test_research.py::TestGetOverallHarvestRate -v

# デバッグスクリプト
python tests/scripts/debug_lastmile_slot_flow.py
```

---

## 問題14: プロファイル健全性監査の自動実行が未実装 ✅ 実装完了

**実装完了日**: 2025-12-11  
**実装ファイル**: `src/crawler/fetcher.py:927-975`, `src/crawler/fetcher.py:877, 923`, `src/search/browser_search_provider.py:248-290`, `src/search/browser_search_provider.py:231`  
**検証スクリプト**: `tests/scripts/debug_profile_health_audit_flow.py`

### 影響範囲

**影響箇所**:
- `src/crawler/fetcher.py:743` - `BrowserFetcher._ensure_browser()`でのブラウザセッション初期化
- `src/search/browser_search_provider.py:168` - `BrowserSearchProvider._ensure_browser()`でのブラウザセッション初期化
- `src/mcp/server.py:810` - `_handle_search()`でのタスク開始時（実装不要: ブラウザセッション初期化時に自動実行されるため）

### 現状の実装

```python
# src/crawler/fetcher.py:719-852
async def _ensure_browser(self, headful: bool = False, task_id: str | None = None):
    # ブラウザセッション初期化
    browser, context = await self._get_browser_and_context(headful)
    
    # プロファイル健全性監査の呼び出しがない
    # perform_health_check()が呼ばれていない
```

### 問題点

1. **タスク開始時の監査なし**: `_handle_search()`や`create_task()`でタスク開始時に`perform_health_check()`が呼ばれていない
2. **ブラウザセッション初期化時の監査なし**: `_ensure_browser()`でブラウザセッション初期化時に`perform_health_check()`が呼ばれていない
3. **定期検査の未実装**: UAメジャーバージョンの追従とフォントセットの一貫性の定期検査が実装されていない

### 仕様書の要件

- §4.3.1: "高頻度チェック: タスク開始時およびブラウザセッション初期化時にUA/メジャーバージョン、フォントセット、言語/タイムゾーン、Canvas/Audio指紋の差分検知を実行"
- §4.3: "UAメジャーバージョンの追従とフォントセットの一貫性を定期検査（差分検知時は自動修正）"

### 修正提案

**方針**: タスク開始時とブラウザセッション初期化時にプロファイル健全性監査を自動実行する

**実装箇所**:
- `src/crawler/fetcher.py:719` - `BrowserFetcher._ensure_browser()`
- `src/search/browser_search_provider.py:168` - `BrowserSearchProvider._ensure_browser()`
- `src/mcp/server.py:810` - `_handle_search()`でのタスク開始時

**実装内容**:
- `BrowserFetcher._perform_health_audit()`メソッドを追加（`src/crawler/fetcher.py:927-975`）
- `BrowserFetcher._ensure_browser()`内で、context作成後に`_perform_health_audit()`を呼び出し（headful/headless両方）
- `BrowserSearchProvider._perform_health_audit()`メソッドを追加（`src/search/browser_search_provider.py:248-290`）
- `BrowserSearchProvider._ensure_browser()`内で、新しいcontext作成時に`_perform_health_audit()`を呼び出し

**実装の特徴**:
- 監査は最小限のページ（`about:blank`）で実行してパフォーマンス影響を最小化
- 自動修復が有効な場合、修復後に再監査を実行
- 監査ログを構造化記録
- 監査失敗時も非ブロッキングで通常フローを継続
- `BrowserSearchProvider`では、既存のcontextを再利用する場合は監査をスキップ（新しいcontext作成時のみ実行）

---

## 問題15: ヒューマンライク操作の完全な適用が未実装 ✅ 実装完了

---

## 問題16: エンジン正規化レイヤが未実装

### 影響範囲

**影響箇所**:
- `src/search/browser_search_provider.py` - `BrowserSearchProvider.search()`でのクエリ正規化
- `src/search/search_api.py` - `search_serp()`でのクエリ正規化
- 新規モジュール: `src/search/query_normalizer.py`（新規作成）

### 現状の実装

```python
# src/search/browser_search_provider.py
# クエリをそのまま使用（エンジン別の正規化なし）
search_url = parser.build_search_url(query)
```

```yaml
# config/engines.yaml
operator_mapping:
  site:
    default: "site:{domain}"
    google: "site:{domain}"
    bing: "site:{domain}"
    # ... 定義はあるが使用されていない
```

### 問題点

1. **エンジン別の演算子対応差が吸収されていない**: 各エンジンで演算子（`site:`, `filetype:`, `intitle:`等）の構文が異なるが、統一的な正規化処理がない
2. **期間指定の対応差が吸収されていない**: `after:`や`before:`などの期間指定がエンジンによって異なるが、正規化処理がない
3. **フレーズ検索の対応差が吸収されていない**: 引用符（`"..."`）の扱いがエンジンによって異なるが、正規化処理がない
4. **設定ファイルの`operator_mapping`が未使用**: `config/engines.yaml`に定義されているが、実際のコードで使用されていない

### 仕様書の要件

- §3.1.1: "エンジン正規化レイヤ: フレーズ/演算子/期間指定等の対応差を吸収するクエリ正規化を実装（エンジン別に最適化）"
- §3.1.4: "エンジン正規化: クエリ正規化: 演算子・期間指定・引用・`site:` のエンジン差を吸収するマッピングテーブルを適用"

### 修正提案

**方針**: エンジン別のクエリ正規化モジュールを実装し、`config/engines.yaml`の`operator_mapping`を活用する

**実装箇所**:
- 新規: `src/search/query_normalizer.py` - クエリ正規化モジュール
- `src/search/browser_search_provider.py` - `search()`メソッドで正規化を適用
- `src/search/search_api.py` - `search_serp()`で正規化を適用

**修正案**:

```python
# src/search/query_normalizer.py（新規作成）
from typing import Optional
from src.search.engine_config import get_engine_config_manager

class QueryNormalizer:
    """Normalize search queries for different engines."""
    
    def __init__(self):
        self.config_manager = get_engine_config_manager()
    
    def normalize(self, query: str, engine: str) -> str:
        """Normalize query for specific engine.
        
        Args:
            query: Original query string
            engine: Target engine name
            
        Returns:
            Normalized query string
        """
        config = self.config_manager.get_config()
        mapping = config.operator_mapping
        
        # 演算子の正規化
        normalized = query
        
        # site:演算子の正規化
        if "site:" in normalized:
            site_pattern = r'site:(\S+)'
            matches = re.findall(site_pattern, normalized)
            for domain in matches:
                engine_syntax = mapping.get("site", {}).get(engine, mapping.get("site", {}).get("default", f"site:{domain}"))
                normalized = normalized.replace(f"site:{domain}", engine_syntax.format(domain=domain))
        
        # filetype:演算子の正規化
        if "filetype:" in normalized:
            filetype_pattern = r'filetype:(\S+)'
            matches = re.findall(filetype_pattern, normalized)
            for filetype in matches:
                engine_syntax = mapping.get("filetype", {}).get(engine, mapping.get("filetype", {}).get("default", f"filetype:{filetype}"))
                normalized = normalized.replace(f"filetype:{filetype}", engine_syntax.format(type=filetype))
        
        # intitle:演算子の正規化（対応エンジンのみ）
        if "intitle:" in normalized:
            intitle_pattern = r'intitle:(\S+)'
            matches = re.findall(intitle_pattern, normalized)
            for text in matches:
                if engine in mapping.get("intitle", {}):
                    engine_syntax = mapping.get("intitle", {}).get(engine)
                    normalized = normalized.replace(f"intitle:{text}", engine_syntax.format(text=text))
                else:
                    # 対応していないエンジンでは削除または警告
                    logger.warning(f"Engine {engine} does not support intitle: operator")
                    normalized = normalized.replace(f"intitle:{text}", text)
        
        # 期間指定の正規化（after:, before:）
        if "after:" in normalized:
            after_pattern = r'after:(\S+)'
            matches = re.findall(after_pattern, normalized)
            for date in matches:
                if engine in mapping.get("date_after", {}):
                    engine_syntax = mapping.get("date_after", {}).get(engine)
                    if engine_syntax:
                        normalized = normalized.replace(f"after:{date}", engine_syntax.format(date=date))
                else:
                    # 対応していないエンジンでは削除または警告
                    logger.warning(f"Engine {engine} does not support after: operator")
                    normalized = normalized.replace(f"after:{date}", "")
        
        # 引用符の正規化（フレーズ検索）
        if '"' in normalized:
            # エンジンによって引用符の扱いが異なる場合の正規化
            # 現状はそのまま使用（エンジンが対応していると仮定）
            pass
        
        return normalized
```

**使用例**:

```python
# src/search/browser_search_provider.py
from src.search.query_normalizer import QueryNormalizer

normalizer = QueryNormalizer()

# エンジン選択後、クエリを正規化
normalized_query = normalizer.normalize(query, engine)
search_url = parser.build_search_url(normalized_query)
```

**注意点**:
- `config/engines.yaml`の`operator_mapping`を活用
- エンジンが対応していない演算子は削除または警告ログを出力
- 正規化失敗率が閾値超過の場合はエンジンを自動降格（§3.1.4準拠）
- 非互換検知: 正規化失敗率が閾値超過で当該エンジンを自動降格（重み低下）しログを残す

**実装ステップ**:
1. `src/search/query_normalizer.py`を作成
2. `config/engines.yaml`の`operator_mapping`を読み込む処理を実装
3. 各演算子の正規化ロジックを実装
4. `BrowserSearchProvider.search()`で正規化を適用
5. `search_api.search_serp()`で正規化を適用
6. 正規化失敗率の監視とエンジン降格ロジックを実装

---

**実装完了日**: 2025-12-11  
**実装ファイル**: `src/crawler/fetcher.py:1360-1382`, `src/search/browser_search_provider.py:385-410`  
**検証スクリプト**: `tests/scripts/debug_human_behavior_flow.py`

### 影響範囲

**影響箇所**:
- `src/crawler/fetcher.py:1360` - `BrowserFetcher.fetch()`でのヒューマンライク操作
- `src/search/browser_search_provider.py:385` - `BrowserSearchProvider.search()`でのヒューマンライク操作

### 現状の実装

```python
# src/crawler/fetcher.py:1124-1126
# Simulate human reading behavior
if simulate_human:
    await self._human_behavior.simulate_reading(page, len(content_bytes))
# マウス軌跡、タイピングリズム、スクロール慣性の適用がない
```

### 問題点

1. **マウス軌跡の適用なし**: `HumanBehaviorSimulator.move_mouse()`や`move_to_element()`が実際に呼ばれていない
2. **タイピングリズムの適用なし**: `HumanBehaviorSimulator.type_text()`が実際に呼ばれていない
3. **スクロール慣性の適用が不完全**: `simulate_reading()`は呼ばれているが、`InertialScroll`の完全な機能が適用されていない可能性がある

### 仕様書の要件

- §4.3.4: "マウス軌跡自然化: Bezier曲線による自然な軌跡生成、微細なジッター付与"
- §4.3.4: "タイピングリズム: ガウス分布ベースの遅延、句読点後の長い間、稀なタイポ模倣"
- §4.3.4: "スクロール慣性: 慣性付きスクロール、easing関数による自然な減速"
- §4.3: "ヒューマンライク操作: ランダム化された視線移動/ホイール慣性/待機時間分布を適用（CDPで制御）"

### 修正提案

**方針**: ページナビゲーション時にマウス軌跡、タイピングリズム、スクロール慣性を完全に適用する

**実装箇所**:
- `src/crawler/fetcher.py:1124` - `BrowserFetcher.fetch()`
- `src/search/browser_search_provider.py` - `BrowserSearchProvider.search()`

**修正案**:
```python
# BrowserFetcher.fetch()でのヒューマンライク操作の完全適用
if simulate_human:
    # スクロール慣性を適用
    await self._human_behavior.simulate_reading(page, len(content_bytes))
    
    # マウス軌跡を適用（ページ内の主要要素に移動）
    try:
        # ページ内の主要リンクや要素にマウスを移動
        links = await page.query_selector_all("a, button, input")
        if links:
            target_link = random.choice(links[:5])  # 最初の5つから選択
            await self._human_behavior.move_to_element(page, target_link)
    except Exception as e:
        logger.debug("Mouse movement skipped", error=str(e))
    
    # タイピングリズムは検索フォームや入力欄がある場合に適用
    # （現在のfetch()では通常は不要）
```

**注意点**:
- マウス軌跡はページ内の主要要素（リンク、ボタン）に適用
- タイピングリズムは検索フォームや入力欄がある場合にのみ適用
- スクロール慣性は`simulate_reading()`で既に適用されているが、完全性を確認

---

**優先順位**:
1. ~~問題3（セッション再利用）~~ ✅ 完了
2. ~~問題5（start_sessionでブラウザを開く）~~ ✅ 完了
3. ~~問題12（セッション転送の適用）~~ ✅ 完了
4. ~~問題14（プロファイル健全性監査の自動実行）~~ ✅ 完了
5. ~~問題15（ヒューマンライク操作の完全な適用）~~ ✅ 完了
6. ~~問題8（エンジン選択ロジック + 動的重み学習）~~ ✅ 完了
7. ~~問題13（ラストマイルスロット判定）~~ ✅ 完了
8. ~~問題9（エンジン別QPS制限）~~ ✅ 完了
9. ~~問題16（エンジン正規化レイヤ）~~ ✅ 実装済み（`transform_query_for_engine`）
10. ~~問題10（Tor日次利用上限）~~ ✅ 完了（2025-12-15）
11. ~~問題11（ドメイン別日次予算上限）~~ ✅ 完了（2025-12-15）
12. ~~問題4, 6, 7（要確認事項の確認）~~ ✅ 確認完了（2025-12-15）

