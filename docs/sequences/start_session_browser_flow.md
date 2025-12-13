# start_sessionブラウザ起動フロー（問題5）

## 概要

`InterventionQueue.start_session()`で認証待ちURLをブラウザで開き、ウィンドウを前面化するフロー。

## デバッグ前のシーケンス図

```mermaid
sequenceDiagram
    participant MCPHandler
    participant InterventionQueue
    participant BrowserSearchProvider
    participant BrowserContext
    participant Page
    participant InterventionManager
    
    Note over MCPHandler: start_session(task_id)
    MCPHandler->>InterventionQueue: start_session(task_id, queue_ids, priority_filter)
    
    InterventionQueue->>InterventionQueue: Get pending items from DB
    InterventionQueue->>InterventionQueue: Mark items as in_progress
    
    alt items exist
        InterventionQueue->>BrowserSearchProvider: _ensure_browser()
        BrowserSearchProvider->>BrowserContext: Get or create context
        BrowserContext-->>BrowserSearchProvider: context: BrowserContext
        
        BrowserSearchProvider-->>InterventionQueue: context available
        
        InterventionQueue->>BrowserContext: new_page()
        BrowserContext-->>InterventionQueue: page: Page
        
        InterventionQueue->>Page: goto(items[0]["url"], wait_until="domcontentloaded")
        Note over Page: 最初のURLのみ開く
        Page-->>InterventionQueue: navigation completed
        
        InterventionQueue->>InterventionManager: _bring_tab_to_front(page)
        Note over InterventionManager: CDP + OS APIで前面化
        InterventionManager-->>InterventionQueue: window brought to front
        
        InterventionQueue->>InterventionQueue: logger.info("Opened authentication URL")
    end
    
    InterventionQueue-->>MCPHandler: {ok: True, session_started: True, count, items}
```

## データ型

- `items: list[dict]`
  - `id: str` - キューID
  - `url: str` - 認証待ちURL
  - `domain: str` - ドメイン名
  - `auth_type: str` - 認証タイプ（"captcha", "login", etc.）
  - `priority: str` - 優先度（"high", "medium", "low"）

- 戻り値: `dict[str, Any]`
  - `ok: bool` - 成功フラグ
  - `session_started: bool` - セッション開始フラグ
  - `count: int` - 処理アイテム数
  - `items: list[dict]` - 処理アイテムリスト

## 非同期処理

- `start_session()`: `async def` - データベース操作とブラウザ操作
- `_ensure_browser()`: `async def` - ブラウザコンテキスト取得
- `new_page()`: `async def` - ページ作成
- `goto()`: `async def` - ページナビゲーション
- `_bring_tab_to_front()`: `async def` - ウィンドウ前面化

## エラーハンドリング

- `items`が空の場合: `session_started=False`で返却
- `_ensure_browser()`エラー: ログ出力してURLのみ返却（手動操作にフォールバック）
- `goto()`エラー: ログ出力してURLのみ返却
- `_bring_tab_to_front()`エラー: ログ出力して続行（URLは開かれている）

## 安全運用ポリシー

- `Page.navigate`のみ使用（DOM操作は禁止）
- `Page.bringToFront`とOS API併用で前面化
- 複数URLがある場合、最初のURLのみ開く（ユーザーが手動で他のURLを開く想定）

---

## デバッグ後のシーケンス図（実装完了版）

**実装状況**: ✅ 実装完了・動作確認済み

**変更点**:
- `InterventionQueue.start_session()`が`BrowserFetcher._ensure_browser(headful=True)`を呼び出し
- `BrowserFetcher._ensure_browser()`がChrome自動起動機能を実装（CDP接続失敗時に`chrome.sh start`を自動実行）
- Chrome自動起動後、最大15秒間CDP接続を待機（0.5秒間隔でポーリング）

```mermaid
sequenceDiagram
    participant MCPHandler
    participant InterventionQueue
    participant BrowserFetcher
    participant chrome.sh
    participant ChromeCDP
    participant BrowserContext
    participant Page
    participant InterventionManager
    
    Note over MCPHandler: start_session(task_id)
    MCPHandler->>InterventionQueue: start_session(task_id, priority_filter)
    
    InterventionQueue->>InterventionQueue: Get pending items from DB
    InterventionQueue->>InterventionQueue: Mark items as in_progress
    
    alt items exist
        InterventionQueue->>BrowserFetcher: _ensure_browser(headful=True, task_id=task_id)
        
        BrowserFetcher->>BrowserFetcher: Try CDP connection<br/>(http://localhost:9222)
        
        alt CDP connection fails (timeout/error)
            BrowserFetcher->>BrowserFetcher: _auto_start_chrome()
            BrowserFetcher->>chrome.sh: subprocess_exec("chrome.sh", "start")
            chrome.sh->>ChromeCDP: Start Chrome with remote debugging
            ChromeCDP-->>chrome.sh: Chrome started
            chrome.sh-->>BrowserFetcher: Process completed (returncode=0)
            
            BrowserFetcher->>BrowserFetcher: Wait for CDP connection<br/>(max 15s, 0.5s interval)
            loop Polling (every 0.5s)
                BrowserFetcher->>ChromeCDP: connect_over_cdp(url)
                alt Connection succeeds
                    ChromeCDP-->>BrowserFetcher: browser: Browser
                    BrowserFetcher->>BrowserFetcher: logger.info("Connected to Chrome via CDP after auto-start")
                else Connection fails
                    ChromeCDP-->>BrowserFetcher: Exception
                    BrowserFetcher->>BrowserFetcher: sleep(0.5s)
                end
            end
        else CDP connection succeeds
            ChromeCDP-->>BrowserFetcher: browser: Browser
        end
        
        BrowserFetcher->>BrowserContext: Get or create context
        BrowserContext-->>BrowserFetcher: context: BrowserContext
        
        BrowserFetcher-->>InterventionQueue: browser, context
        
        InterventionQueue->>BrowserContext: new_page()
        BrowserContext-->>InterventionQueue: page: Page
        
        InterventionQueue->>Page: goto(items[0]["url"], wait_until="domcontentloaded", timeout=10000)
        Note over Page: 最初のURLのみ開く
        Page-->>InterventionQueue: navigation completed
        
        InterventionQueue->>InterventionManager: _bring_tab_to_front(page)
        Note over InterventionManager: CDP Page.bringToFront + OS APIで前面化
        InterventionManager-->>InterventionQueue: window brought to front
        
        InterventionQueue->>InterventionQueue: logger.info("Opened authentication URL in browser")
    end
    
    InterventionQueue-->>MCPHandler: {ok: True, session_started: True, count, items}
```

**実装ファイル**:
- `src/utils/notification.py`: `InterventionQueue.start_session()` (1100-1200行)
- `src/crawler/fetcher.py`: `BrowserFetcher._ensure_browser()` (738-900行), `BrowserFetcher._auto_start_chrome()` (905-960行)

**Chrome自動起動の詳細**:
- CDP接続タイムアウト: 5秒
- `chrome.sh start`実行タイムアウト: 30秒
- CDP接続待機: 最大15秒、0.5秒間隔でポーリング
- 自動起動失敗時: ローカルヘッドフルブラウザを起動（フォールバック）

**検証**:
- ✅ `tests/scripts/debug_start_session_browser_flow.py`で動作確認済み
- ✅ `tests/scripts/debug_chrome_auto_start.py`でChrome自動起動機能を検証済み

