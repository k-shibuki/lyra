# ADR-0003: MCP over CLI / REST API

## Date
2025-11-05

## Context

Lyraの機能を外部に公開するインターフェースとして、以下の選択肢がある：

| 方式 | 概要 |
|------|------|
| CLI | コマンドラインツールとして提供 |
| REST API | HTTPサーバーとして提供 |
| MCP | Model Context Protocolサーバーとして提供 |
| Python Library | ライブラリとしてimport |

各方式の比較：

| 観点 | CLI | REST | MCP | Library |
|------|-----|------|-----|---------|
| LLM統合 | 困難 | 可能 | ネイティブ | 困難 |
| セットアップ | 簡単 | 中程度 | 簡単 | 簡単 |
| ステートフル | 困難 | 要実装 | 標準サポート | 可能 |
| ツール呼び出し | なし | 要定義 | 標準化済み | なし |
| 型安全性 | なし | OpenAPI | JSON Schema | Python型 |

## Decision

**MCPサーバーとして実装し、MCPクライアント（Claude Desktop等）から利用する。**

### MCPを選択した理由

1. **LLMネイティブ**: AIアシスタントとの統合を前提に設計されている
2. **ツール定義の標準化**: inputSchemaでパラメータを厳密に定義
3. **ステートフル通信**: 長時間の調査タスクを自然にサポート
4. **エコシステム**: Claude Desktop、Cline、Cursor等が対応

### 提供するツール（抜粋）

```python
@server.tool()
async def search(query: str, max_results: int = 10) -> SearchResult:
    """Web検索を実行し、結果を返す"""
    ...

@server.tool()
async def get_page(url: str) -> PageContent:
    """指定URLのページ内容を取得"""
    ...

@server.tool()
async def extract_claims(page_id: str, hypothesis: str) -> List[Claim]:
    """ページから仮説に関連する主張を抽出"""
    ...
```

### 通信方式

```
Claude Desktop / Cline
        │
        │ stdio (標準入出力)
        ▼
   Lyra MCP Server
```

- **stdio**: ローカル実行に最適、追加ポート不要
- プロセス間通信のオーバーヘッドは無視できるレベル

### クライアント要件

ADR-0002で述べた通り、クライアント側にはClaude/GPT-4クラスの推論能力が必要。MCPはこの前提に適合する：

- Claude Desktop: Claude 3.5 Sonnet / Opus
- Cline: 任意のLLM（推奨: Claude / GPT-4）
- Cursor: Claude / GPT-4

## Consequences

### Positive
- **即座のLLM統合**: Claude Desktopでそのまま動作
- **標準化されたインターフェース**: ツール定義の再発明不要
- **型安全なパラメータ**: JSON Schemaによる検証
- **非同期対応**: 長時間タスクの自然なサポート

### Negative
- **クライアント限定**: MCP対応クライアントが必要
- **デバッグ困難**: stdio通信のトレースが面倒
- **プロトコル制約**: MCPの仕様に縛られる

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| REST API | 汎用性高い | LLM統合を自前実装 | 却下 |
| CLI | シンプル | LLM統合困難 | 却下 |
| GraphQL | 柔軟なクエリ | 過剰、LLM統合なし | 却下 |
| gRPC | 高性能 | 複雑、LLM統合なし | 却下 |

## References
- `src/mcp/server.py` - MCPサーバー実装
- MCP仕様: https://modelcontextprotocol.io
- ADR-0002: Thinking-Working Separation
