# セッション転送フロー（問題12）

## 概要

ブラウザで取得したセッションをHTTPクライアントに転送するフロー。初回はブラウザ経由、2回目以降はHTTPクライアントで304再訪。

## デバッグ前のシーケンス図

### 初回取得（ブラウザ経由）

```mermaid
sequenceDiagram
    participant fetch_url
    participant BrowserFetcher
    participant BrowserContext
    participant Page
    participant SessionTransferManager
    
    Note over fetch_url: fetch_url(url) - 初回
    fetch_url->>BrowserFetcher: fetch(url, ...)
    
    BrowserFetcher->>BrowserContext: new_page()
    BrowserContext-->>BrowserFetcher: page: Page
    
    BrowserFetcher->>Page: goto(url)
    Page-->>BrowserFetcher: response: Response
    
    alt fetch successful
        BrowserFetcher->>BrowserFetcher: Extract response_headers
        BrowserFetcher->>SessionTransferManager: capture_browser_session(context, url, response_headers)
        
        SessionTransferManager->>BrowserContext: cookies()
        BrowserContext-->>SessionTransferManager: browser_cookies: list[dict]
        
        SessionTransferManager->>SessionTransferManager: Create SessionData
        Note over SessionTransferManager: Cookie, ETag, Last-Modifiedを保存
        SessionTransferManager-->>BrowserFetcher: session_id: str
        
        BrowserFetcher->>BrowserFetcher: logger.debug("Captured browser session")
    end
    
    BrowserFetcher-->>fetch_url: FetchResult(ok=True, ...)
```

### 2回目以降（HTTPクライアント経由）

```mermaid
sequenceDiagram
    participant fetch_url
    participant HTTPFetcher
    participant SessionTransferManager
    
    Note over fetch_url: fetch_url(url) - 2回目以降
    fetch_url->>HTTPFetcher: fetch(url, ...)
    
    HTTPFetcher->>SessionTransferManager: get_transfer_headers(url, include_conditional=True)
    
    SessionTransferManager->>SessionTransferManager: Find session for domain
    SessionTransferManager->>SessionTransferManager: Build transfer headers
    Note over SessionTransferManager: Cookie, ETag, If-None-Match,<br/>Last-Modified, If-Modified-Since
    SessionTransferManager-->>HTTPFetcher: TransferResult(ok=True, headers={...})
    
    HTTPFetcher->>HTTPFetcher: headers.update(transfer_result.headers)
    HTTPFetcher->>HTTPFetcher: HTTP request with transfer headers
    
    alt 304 Not Modified
        HTTPFetcher-->>fetch_url: FetchResult(ok=True, status=304, from_cache=True)
    else 200 OK
        HTTPFetcher-->>fetch_url: FetchResult(ok=True, status=200)
    end
```

## データ型

### SessionData（内部）
- `domain: str` - 登録可能ドメイン
- `cookies: list[CookieData]` - Cookie情報
- `etag: str | None` - ETag
- `last_modified: str | None` - Last-Modified
- `user_agent: str | None` - User-Agent
- `accept_language: str` - Accept-Language
- `last_url: str | None` - 最後にアクセスしたURL（Referer用）
- `created_at: float` - 作成時刻（Unix timestamp）
- `last_used_at: float` - 最終使用時刻（Unix timestamp）

### TransferResult
- `ok: bool` - 成功フラグ
- `session_id: str | None` - セッションID
- `headers: dict[str, str]` - 転送ヘッダー
  - `Cookie: str` - Cookieヘッダー
  - `If-None-Match: str` - ETag（条件付きリクエスト）
  - `If-Modified-Since: str` - Last-Modified（条件付きリクエスト）
  - `User-Agent: str` - User-Agent
  - `Accept-Language: str` - Accept-Language
- `reason: str | None` - エラー理由

## 非同期処理

- `capture_browser_session()`: `async def` - ブラウザコンテキストからセッション取得
- `cookies()`: `async def` - Playwright API呼び出し
- `get_transfer_headers()`: `def` - 同期的なヘッダー生成（内部でセッション検索）

## エラーハンドリング

- `capture_browser_session()`エラー: ログ出力して`None`を返却、通常フロー継続
- `get_transfer_headers()`でセッションが見つからない場合: `TransferResult(ok=False, reason="no_session_for_domain")`を返却
- セッション転送ヘッダー適用エラー: ログ出力して通常ヘッダーのみでリクエスト

## 初回/2回目以降の判定

- `fetch_url()`でキャッシュチェック
- キャッシュが存在し、ETag/Last-Modifiedがある場合: HTTPクライアント経由
- キャッシュが存在しない、またはETag/Last-Modifiedがない場合: ブラウザ経由

---

## デバッグ後のシーケンス図（実装完了版）

**実装状況**: ✅ 実装完了・動作確認済み

**変更点**:
- `fetch_url()`で初回はブラウザ経由、2回目以降はHTTPクライアント経由（304キャッシュ）を実装
- `BrowserFetcher.fetch()`が成功時に`capture_browser_session()`を呼び出し
- `HTTPFetcher.fetch()`が`get_transfer_headers()`でセッション転送ヘッダーを取得して適用

### 初回取得（ブラウザ経由） - 実装版

```mermaid
sequenceDiagram
    participant fetch_url
    participant BrowserFetcher
    participant BrowserContext
    participant Page
    participant SessionTransferManager
    
    Note over fetch_url: fetch_url(url) - 初回<br/>has_previous_browser_fetch = False
    fetch_url->>fetch_url: Check cache entry
    fetch_url->>fetch_url: has_previous_browser_fetch = False<br/>(no ETag/Last-Modified)
    
    fetch_url->>BrowserFetcher: fetch(url, task_id=task_id)
    
    BrowserFetcher->>BrowserContext: new_page()
    BrowserContext-->>BrowserFetcher: page: Page
    
    BrowserFetcher->>Page: goto(url)
    Page-->>BrowserFetcher: response: Response
    
    alt fetch successful
        BrowserFetcher->>BrowserFetcher: Extract response_headers<br/>(ETag, Last-Modified, etc.)
        BrowserFetcher->>SessionTransferManager: capture_browser_session(context, url, response_headers)
        
        SessionTransferManager->>BrowserContext: cookies()
        BrowserContext-->>SessionTransferManager: browser_cookies: list[dict]
        
        SessionTransferManager->>SessionTransferManager: Create SessionData<br/>(domain, cookies, etag, last_modified, user_agent)
        SessionTransferManager->>SessionTransferManager: Store in memory cache
        SessionTransferManager-->>BrowserFetcher: session_id: str
        
        BrowserFetcher->>BrowserFetcher: logger.info("Session captured from browser")
    end
    
    BrowserFetcher-->>fetch_url: FetchResult(ok=True, etag=..., last_modified=...)
    fetch_url->>fetch_url: Save to cache_fetch table<br/>(etag, last_modified, content_hash)
```

### 2回目以降（HTTPクライアント経由） - 実装版

```mermaid
sequenceDiagram
    participant fetch_url
    participant HTTPFetcher
    participant SessionTransferManager
    
    Note over fetch_url: fetch_url(url) - 2回目以降<br/>has_previous_browser_fetch = True
    fetch_url->>fetch_url: Check cache entry
    fetch_url->>fetch_url: has_previous_browser_fetch = True<br/>(ETag or Last-Modified exists)
    
    fetch_url->>HTTPFetcher: fetch(url, cached_etag=..., cached_last_modified=...)
    
    HTTPFetcher->>SessionTransferManager: get_transfer_headers(url, include_conditional=True)
    
    SessionTransferManager->>SessionTransferManager: Find session for domain<br/>(domain = urlparse(url).netloc.lower())
    SessionTransferManager->>SessionTransferManager: Build transfer headers
    Note over SessionTransferManager: Cookie, ETag → If-None-Match,<br/>Last-Modified → If-Modified-Since,<br/>User-Agent, Accept-Language
    SessionTransferManager-->>HTTPFetcher: TransferResult(ok=True, headers={...})
    
    HTTPFetcher->>HTTPFetcher: headers.update(transfer_result.headers)
    HTTPFetcher->>HTTPFetcher: HTTP request with transfer headers<br/>(If-None-Match, If-Modified-Since)
    
    alt 304 Not Modified
        HTTPFetcher-->>fetch_url: FetchResult(ok=True, status=304, from_cache=True)
    else 200 OK
        HTTPFetcher-->>fetch_url: FetchResult(ok=True, status=200)
    end
```

**実装ファイル**:
- `src/crawler/fetcher.py`: `fetch_url()` (1793-1950行), `BrowserFetcher.fetch()` (1200-1250行), `HTTPFetcher.fetch()` (509-710行)
- `src/crawler/session_transfer.py`: `capture_browser_session()`, `get_transfer_headers()`

**検証**:
- ✅ `tests/scripts/debug_session_transfer_flow.py`で動作確認済み

