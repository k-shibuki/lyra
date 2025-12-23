# ADR-0003: MCP over CLI / REST API

## Status
Accepted

## Date
2024-XX-XX（プロジェクト開始時）

## Context

LyraはAIアシスタント（Cursor AI、Claude Desktop等）から呼び出されるツールとして機能する。AIとツール間の通信方式として複数の選択肢がある：

| 方式 | 概要 |
|------|------|
| CLI | コマンドラインツールとして実行、stdoutで結果返却 |
| REST API | HTTPサーバーとして起動、JSONで通信 |
| MCP | Model Context Protocol、AIツール通信の標準プロトコル |

MCPは Anthropic が提唱するAI-ツール間通信の標準プロトコルで、以下の特徴を持つ：

- 型付きツールスキーマ（JSON Schema）
- 双方向通信（進捗通知、エラーハンドリング）
- セッション管理
- 複数のトランスポート（stdio、SSE）

## Decision

**MCPを採用する。**

### MCPの利点

| 観点 | CLI | REST API | MCP |
|------|-----|----------|-----|
| 型安全性 | △ stdout解析 | ○ JSON | ◎ JSON Schema |
| 進捗通知 | × | △ ポーリング | ◎ ネイティブ |
| エラー処理 | △ exit code | ○ HTTP status | ◎ 構造化エラー |
| AI統合 | △ 手動パース | △ 手動呼び出し | ◎ ネイティブ |
| セッション | × | △ 自前実装 | ◎ プロトコル標準 |

### 採用するMCPツール構成（9ツール）

| カテゴリ | ツール | 目的 |
|---------|--------|------|
| タスク管理 | `create_task` | タスク作成 |
| | `get_status` | 状態確認（sleep機能付き） |
| | `stop_task` | タスク終了 |
| 検索 | `queue_searches` | 検索キュー投入 |
| 素材 | `get_materials` | 主張・断片・グラフ取得 |
| 校正 | `calibrate` | モデル校正 |
| | `calibrate_rollback` | 校正ロールバック |
| 認証 | `get_auth_queue` | 認証待ちキュー取得 |
| | `resolve_auth` | 認証完了報告 |

### クライアント非依存

Lyraは標準MCP準拠であり、特定クライアントに依存しない：

| クライアント | 動作 |
|-------------|------|
| Cursor AI | OK |
| Claude Desktop | OK |
| Zed Editor | OK |
| その他MCP対応ツール | OK |

ただし、ADR-0001で述べた通り、クライアント側にはClaude/GPT-4クラスの推論能力が必要。

## Consequences

### Positive
- **標準準拠**: MCP対応クライアントなら何でも動作
- **型安全**: スキーマによるバリデーション
- **進捗通知**: 長時間処理の状況をリアルタイム通知可能
- **将来性**: MCPエコシステムの成長に伴う恩恵

### Negative
- **学習コスト**: MCP固有の概念（ツール、リソース、プロンプト）の理解が必要
- **デバッグ難**: stdioトランスポートはデバッグしづらい
- **エコシステム未成熟**: 2024年時点でツールやドキュメントが限定的

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| CLI | シンプル、デバッグ容易 | 型安全性なし、進捗通知困難 | 却下 |
| REST API | 言語非依存、既存ツール豊富 | サーバー管理必要、認証複雑 | 却下 |
| gRPC | 高性能、型安全 | AI統合の標準ではない | 却下 |

## References
- [Model Context Protocol](https://modelcontextprotocol.io/)
- `README.md` "Why MCP (Not CLI)?"
- `src/mcp/server.py` - MCPサーバー実装
