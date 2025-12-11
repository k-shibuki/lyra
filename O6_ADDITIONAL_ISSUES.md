# O.6 追加仕様違反調査結果

## 調査日: 2025-12-11

O.6の実装完了後、同様のパターンで他の仕様違反がないか調査した結果。

---

## 問題3: 認証待ちキューで保存されたセッションが後続リクエストで再利用されていない

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

## 問題4: BrowserSearchProviderでのセッション再利用未実装（要確認）

### 影響範囲

**影響箇所**:
- `src/search/browser_search_provider.py` - `BrowserSearchProvider.search()`

### 確認事項

`BrowserSearchProvider.search()`でも、認証待ちキューから既存セッションを取得してCookieを設定する処理が必要か確認が必要。

検索エンジンは通常認証不要だが、一部の検索エンジン（例: Googleのログイン必須検索）では認証が必要な場合がある。

---

## 問題5: start_session()でブラウザを開く処理が未実装

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

## 問題6: Chromeプロファイル名が仕様と不一致（要確認）

### 影響範囲

**影響箇所**:
- `scripts/chrome.sh:284` - Chrome起動スクリプト

### 現状の実装

```bash
# scripts/chrome.sh:284
$dataDir = [Environment]::GetFolderPath('LocalApplicationData') + '\LancetChrome'
# --user-data-dirのみ指定、--profile-directory未指定
```

### 問題点

1. **プロファイル名未指定**: `--profile-directory="Profile-Research"`が指定されていない
2. **仕様との不一致**: 仕様書では「調査専用プロファイル」として`Profile-Research`を使うべきとある

### 仕様書の要件

- §3.2: "調査専用プロファイル運用: 研究専用のChromeプロファイルを`--user-data-dir`/`--profile-directory`で固定化（例: `--profile-directory="Profile-Research"`）"
- §4.3.1: "安全策: `Profile-Research`のみを対象、日常プロファイルへの影響を遮断"

### 確認事項

- 現在の実装では`LancetChrome`という専用ディレクトリを使っているため、プロファイル名の指定が不要かもしれない
- ただし、仕様書では明示的に`Profile-Research`を使うべきとあるため、確認が必要

---

## 問題7: LocalStorageの研究用隔離の確認（要確認）

### 影響範囲

**影響箇所**:
- Chromeプロファイル設定全般

### 確認事項

仕様書では「Cookie/LocalStorageを研究用に隔離」とあるが、現在の実装では専用プロファイル（`LancetChrome`）を使っているため、自動的に隔離されているはず。

明示的な確認が必要かどうかは要検討。

---

## 優先度

**問題3**: 🔴 高（仕様違反）
- §3.6.1の核心機能「セッション共有」が実装されていない
- 認証完了後も再認証が必要になり、運用効率が低下

**問題5**: 🔴 高（仕様違反）
- §3.6.1の「最小介入原則」に違反
- ユーザーが手動でブラウザを開く必要があり、UXが悪い

**問題4**: 🟡 中（要確認）
- 検索エンジンでの認証要件が不明確
- 実装が必要かどうか確認が必要

**問題6**: 🟡 中（要確認）
- プロファイル名の指定が必要かどうか確認が必要
- 現在の実装で問題ない可能性もある

**問題7**: 🟢 低（要確認）
- 専用プロファイルを使っているため、自動的に隔離されている可能性が高い

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

---

## 問題9: BrowserSearchProviderでエンジン別QPS制限が未実装

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

## 実装時期

Phase O.6完了後、別タスクとして実装推奨。

**優先順位**:
1. 問題3（セッション再利用）
2. 問題5（start_sessionでブラウザを開く）
3. 問題8（エンジン選択ロジック）
4. 問題9（エンジン別QPS制限）
5. 問題4, 6, 7（要確認事項の確認）

