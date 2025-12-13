# 認証セッション再利用フロー（問題3）

## 概要

認証待ちキューで保存されたセッションを後続リクエストで再利用するフロー。

## デバッグ前のシーケンス図

```mermaid
sequenceDiagram
    participant BrowserFetcher
    participant InterventionQueue
    participant BrowserContext
    participant Page
    
    Note over BrowserFetcher: fetch(url, task_id)
    BrowserFetcher->>BrowserFetcher: domain = urlparse(url).netloc.lower()
    
    BrowserFetcher->>InterventionQueue: get_session_for_domain(domain, task_id)
    Note over InterventionQueue: 既存の認証済みセッションを検索
    InterventionQueue-->>BrowserFetcher: existing_session: dict | None
    
    alt existing_session exists and has cookies
        BrowserFetcher->>BrowserFetcher: Convert cookies to Playwright format
        BrowserFetcher->>BrowserContext: add_cookies(playwright_cookies)
        Note over BrowserContext: Cookieをcontextに設定
        BrowserContext-->>BrowserFetcher: cookies added
    end
    
    BrowserFetcher->>BrowserContext: new_page()
    BrowserContext-->>BrowserFetcher: page: Page
    
    BrowserFetcher->>Page: goto(url)
    Page-->>BrowserFetcher: response: Response
    
    alt challenge detected
        BrowserFetcher->>InterventionQueue: enqueue(task_id, url, domain, auth_type)
        InterventionQueue-->>BrowserFetcher: queue_id: str
        BrowserFetcher-->>BrowserFetcher: return FetchResult(ok=False, reason="auth_required")
    else success
        BrowserFetcher-->>BrowserFetcher: return FetchResult(ok=True)
    end
```

## データ型

- `existing_session: dict | None`
  - `cookies: list[dict]` - Cookie情報のリスト
  - `domain: str` - ドメイン名
  - `completed_at: str` - 認証完了時刻（ISO形式）

- `playwright_cookies: list[dict]`
  - `name: str` - Cookie名
  - `value: str` - Cookie値
  - `domain: str` - ドメイン
  - `path: str` - パス（デフォルト: "/"）
  - `expires: float | None` - 有効期限（Unix timestamp）
  - `httpOnly: bool` - HttpOnlyフラグ
  - `secure: bool` - Secureフラグ
  - `sameSite: str` - SameSite属性（"Lax", "Strict", "None"）

## 非同期処理

- `get_session_for_domain()`: `async def` - データベースクエリ
- `add_cookies()`: `async def` - Playwright API呼び出し
- `goto()`: `async def` - ページナビゲーション

## エラーハンドリング

- `existing_session`が`None`の場合: Cookie設定をスキップして通常フロー継続
- Cookie変換エラー: ログ出力してスキップ、通常フロー継続
- `add_cookies()`エラー: ログ出力してスキップ、通常フロー継続

---

## デバッグ後のシーケンス図（実装完了版）

**実装状況**: ✅ 実装完了・動作確認済み

**変更点**:
- `BrowserFetcher.fetch()`内で`InterventionQueue.get_session_for_domain()`を呼び出し
- ドメインベースでセッション検索（`task_id`による絞り込みは削除）
- CookieをPlaywright形式に変換して`context.add_cookies()`で適用

```mermaid
sequenceDiagram
    participant BrowserFetcher
    participant InterventionQueue
    participant BrowserContext
    participant Page
    
    Note over BrowserFetcher: fetch(url, task_id)
    BrowserFetcher->>BrowserFetcher: domain = urlparse(url).netloc.lower()
    
    BrowserFetcher->>InterventionQueue: get_session_for_domain(domain)
    Note over InterventionQueue: ドメインベースで検索<br/>(task_idによる絞り込みなし)
    InterventionQueue->>InterventionQueue: SELECT * FROM intervention_queue<br/>WHERE domain = ? AND status = 'completed'<br/>ORDER BY completed_at DESC LIMIT 1
    InterventionQueue-->>BrowserFetcher: existing_session: SessionData | None
    
    alt existing_session exists and has cookies
        BrowserFetcher->>BrowserFetcher: Convert cookies to Playwright format
        Note over BrowserFetcher: CookieData → playwright cookie dict<br/>(name, value, domain, path, expires, etc.)
        BrowserFetcher->>BrowserContext: add_cookies(playwright_cookies)
        Note over BrowserContext: Cookieをcontextに設定
        BrowserContext-->>BrowserFetcher: cookies added
        BrowserFetcher->>BrowserFetcher: logger.info("Applied stored authentication cookies")
    end
    
    BrowserFetcher->>BrowserContext: new_page()
    BrowserContext-->>BrowserFetcher: page: Page
    
    BrowserFetcher->>Page: goto(url)
    Page-->>BrowserFetcher: response: Response
    
    alt challenge detected
        BrowserFetcher->>InterventionQueue: enqueue(task_id, url, domain, auth_type)
        InterventionQueue-->>BrowserFetcher: queue_id: str
        BrowserFetcher-->>BrowserFetcher: return FetchResult(ok=False, reason="auth_required")
    else success
        BrowserFetcher->>BrowserFetcher: capture_browser_session(context, url, headers)
        BrowserFetcher-->>BrowserFetcher: return FetchResult(ok=True)
    end
```

**実装ファイル**:
- `src/crawler/fetcher.py`: `BrowserFetcher.fetch()` (1080-1137行)
- `src/utils/notification.py`: `InterventionQueue.get_session_for_domain()` (返却型: `SessionData`)

**検証**:
- ✅ `tests/scripts/debug_auth_session_reuse_flow.py`で動作確認済み

