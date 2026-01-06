# MCPサーバーログ分析レポート (2026-01-06)

## 📊 サマリー

| レベル | 件数 |
|--------|------|
| **ERROR** | 42件 |
| **WARNING** | 79件 |
| **合計** | 121件 |

---

## 🔴 ERROR (42件)

### 1. ML Server関連 (16件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `ML Server request failed after retries` | 8 | `src.ml_client` | NLIリクエストが3回のリトライ後に失敗 |
| `Job failed` (verify_nli) | 8 | `src.scheduler.jobs` | NLI検証ジョブが422エラーで失敗 |

**根本原因**: ML Server (`/nli` エンドポイント) が HTTP 422 (Unprocessable Content) を返却。入力データの形式に問題がある可能性。

### 2. 検索パーサー関連 (10件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `Required selector not found` | 5 | `src.search.parsers.base` | Braveの検索結果HTMLでtitleセレクタが見つからない |
| `Parser failure - AI repair suggested` | 3 | `src.search.parsers.base` | パーサーがHTML解析に失敗 |
| `Failed to create diagnostic report` | 2 | `src.search.parser_diagnostics` | 診断レポート作成時にコードバグ発生 |

**根本原因**: 
- Braveの検索結果HTML構造が変更された可能性
- `escaped_testid` 変数の未定義エラー (コードバグ)

### 3. ブラウザ/SERP検索関連 (16件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `Browser search error` | 10 | `src.search.browser_search_provider` | Mojeekでのブラウザ検索エラー |
| `Search failed: SERP error` | 3 | `src.research.executor` | SERP検索全体の失敗 |
| `All searches failed` | 3 | `src.research.executor` | すべての検索クエリが失敗 |

**根本原因**: Playwrightで「Target page, context or browser has been closed」エラーが発生。ブラウザコンテキストが予期せず閉じられている。

---

## 🟡 WARNING (79件)

### 1. ML Server関連 (32件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `ML Server HTTP error` (422) | 24 | `src.ml_client` | NLI呼び出し時の422エラー (リトライ含む) |
| `ML Server request error` | 8 | `src.ml_client` | 空のエラーでMLサーバーリクエスト失敗 |

### 2. タイムアウト関連 (14件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `Pipeline timeout - safe stop` | 11 | `src.research.pipeline` | 検索パイプラインが300秒でタイムアウト |
| `Timeout waiting for jobs to complete` | 3 | `src.scheduler.search_worker` | ジョブ完了待ちでタイムアウト |

### 3. 検索失敗関連 (22件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `Search failed` | 11 | `src.search.search_api` | 検索プロバイダーでの失敗 |
| `Browser search failed` | 8 | `src.research.pipeline` | SERPブラウザ検索の失敗 |
| `Parse failed on page` | 3 | `src.search.browser_search_provider` | ページ解析失敗 |

### 4. SQL実行エラー (9件)

| エラー内容 | 件数 | 説明 |
|----------|------|------|
| `near "LIMIT": syntax error` | 2 | 不正なSQLシンタックス |
| `no such column: c.source_fragment_id` | 2 | 存在しないカラム参照 |
| `no such column: status` | 1 | 存在しないカラム参照 |
| `interrupted` | 1 | SQL実行の中断 |
| その他 | 3 | その他のSQLエラー |

**根本原因**: 外部から実行されるSQLクエリにスキーマ不一致またはシンタックスエラー。

### 5. MCP/Tool関連 (2件)

| イベント | 件数 | Logger | 説明 |
|----------|------|--------|------|
| `Tool MCP error` (TASK_NOT_FOUND) | 2 | `__main__` | 存在しないタスクIDへのアクセス |

---

## 🎯 優先度別の対応推奨

### P1 高優先度 🔴
1. **ML Server 422エラー** - NLI入力バリデーションの確認とデバッグログ追加
2. **ブラウザコンテキスト閉鎖エラー** - Playwrightのブラウザライフサイクル管理の見直し

### P2 中優先度 🟠
3. **Braveパーサー更新** - 検索結果HTMLの構造変更に対応
4. **`escaped_testid` コードバグ修正** - `src.search.parser_diagnostics` の変数未定義修正

### P3 低優先度 🟡
5. **SQLエラーのドキュメント化** - 許容されるSQLスキーマのドキュメント整備
6. **タイムアウト設定調整** - 必要に応じてタイムアウト値の最適化

---

## 調査対象ファイル

- `src/ml_client.py` - ML Server通信
- `src/search/browser_search_provider.py` - ブラウザ検索
- `src/search/parsers/base.py` - パーサー基盤
- `src/search/parser_diagnostics.py` - 診断レポート生成
- `src/scheduler/jobs.py` - ジョブ管理

---

## 関連ログエントリ例

### ML Server 422エラー
```json
{"endpoint": "/nli", "status_code": 422, "attempt": 1, "event": "ML Server HTTP error", ...}
{"endpoint": "/nli", "max_retries": 3, "event": "ML Server request failed after retries", ...}
```

### ブラウザ閉鎖エラー
```json
{"engine": "mojeek", "error": "Page.goto: Target page, context or browser has been closed", "event": "Browser search error", ...}
```

### パーサー診断バグ
```json
{"engine": "brave", "error": "cannot access local variable 'escaped_testid' where it is not associated with a value", "event": "Failed to create diagnostic report", ...}
```

