# ADR-0007: Human-in-the-Loop Authentication

## Date
2025-11-25

## Context

学術リソースの多くは認証が必要：

| リソース | 認証方式 | 自動化の難易度 |
|----------|----------|----------------|
| 大学図書館 | SSO/Shibboleth | 非常に困難 |
| IEEE/ACM | 機関認証 or 個人 | 困難 |
| 一般Webサイト | Cookie/Session | 中程度 |
| CAPTCHA保護サイト | 画像/行動認証 | 非常に困難 |

自動認証突破の問題点：

| 問題 | 詳細 |
|------|------|
| 法的リスク | 利用規約違反、不正アクセス |
| 倫理的問題 | CAPTCHAは人間確認が目的 |
| 技術的困難 | 最新CAPTCHAは突破困難 |
| コスト | 解決サービスは有料（ADR-0001違反） |

また、ADR-0001（Zero OpEx）の制約により、有償のCAPTCHA解決サービスは使用できない。

## Decision

**認証はユーザーに委ね、認証済みセッションを再利用する（Human-in-the-Loop方式）。**

### アーキテクチャ

```
[認証が必要なURL検出]
         │
         ▼
[認証キューに追加]
         │
         ▼
[ユーザーに通知] ──────────────────┐
         │                         │
         ▼                         │ ユーザー操作
[ユーザーがブラウザで認証] ◄───────┘
         │
         ▼
[認証済みCookieを取得]
         │
         ▼
[バッチ処理で未取得ページを処理]
```

### 認証キューの設計

```python
@dataclass
class AuthRequest:
    url: str
    domain: str
    reason: str  # "login_required", "captcha", "paywall"
    created_at: datetime
    status: str  # "pending", "authenticated", "skipped"

# MCPツール: 認証待ちリストを取得
@server.tool()
async def get_pending_auth() -> List[AuthRequest]:
    """認証が必要なURLのリストを返す"""
    return await db.get_pending_auth_requests()
```

### ユーザーワークフロー

1. **調査開始**: ユーザーがLyraで調査を開始
2. **認証検出**: 認証が必要なページを検出、キューに追加
3. **通知**: MCPクライアント経由で「認証が必要」と通知
4. **手動認証**: ユーザーが通常のブラウザで認証
5. **Cookie取得**: Lyraが認証済みCookieを取得
6. **再取得**: 認証後、ページを再クロール

### Cookie取得方法

```python
# Playwrightでユーザーのブラウザプロファイルを参照
async def get_authenticated_session(domain: str) -> BrowserContext:
    # ユーザーのChrome/Firefoxプロファイルからcookieを読み取り
    user_data_dir = get_user_browser_profile()
    context = await browser.new_context(
        storage_state=f"{user_data_dir}/cookies.json"
    )
    return context
```

### バッチ処理

認証後、同じドメインの未取得ページをまとめて処理：

```python
async def process_authenticated_domain(domain: str):
    pending_pages = await db.get_pending_pages(domain)
    auth_context = await get_authenticated_session(domain)

    for page_url in pending_pages:
        content = await fetch_with_context(page_url, auth_context)
        await process_page(content)
```

### CAPTCHAの扱い

| 状況 | 対応 |
|------|------|
| 初回CAPTCHA | ユーザーに解決を依頼 |
| 頻繁なCAPTCHA | リクエスト間隔を広げる |
| 常時CAPTCHA | そのサイトを警告付きでスキップ |

```python
if captcha_detected(response):
    await add_to_auth_queue(
        url=url,
        reason="captcha",
        message="CAPTCHAが検出されました。手動で解決してください。"
    )
    return PendingResult(status="awaiting_human")
```

## Consequences

### Positive
- **法的安全性**: 自動突破を行わない
- **Zero OpEx**: 有償サービス不使用
- **確実性**: 人間が解決するので確実
- **透明性**: ユーザーが何にアクセスしているか把握

### Negative
- **待機時間**: ユーザー操作まで進行停止
- **UX負荷**: ユーザーに認証作業が発生
- **完全自動化不可**: 人間介入が必須

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| CAPTCHA解決サービス | 自動化 | 有料、倫理的問題 | 却下 |
| ヘッドレスブラウザ偽装 | 一部成功 | 検出リスク、いたちごっこ | 却下 |
| 認証スキップ | シンプル | 重要リソースにアクセス不可 | 却下 |
| プロキシサービス | 自動化 | 有料、規約違反リスク | 却下 |

## References
- `src/storage/schema.sql` - `intervention_queue`テーブル（認証キュー）
- `src/crawler/session_transfer.py` - セッション転送
- `src/mcp/server.py` - `get_auth_queue`, `resolve_auth` MCPツール
- ADR-0001: Local-First / Zero OpEx
- ADR-0006: 8-Layer Security Model
