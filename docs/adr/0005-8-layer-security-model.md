# ADR-0005: 8-Layer Security Model

## Status
Accepted

## Date
2024-XX-XX（プロジェクト開始時）

## Context

Lyraは外部コンテンツ（Webページ、検索結果）を取得し、ローカルLLMで処理する。この構造には複数の攻撃ベクトルが存在する：

| 攻撃ベクトル | 脅威 |
|-------------|------|
| プロンプトインジェクション | 悪意あるWebコンテンツがLLMの動作を改変 |
| データ漏洩 | システムプロンプトやセッション情報の流出 |
| 信頼性偽装 | 低品質ソースが高信頼として扱われる |
| 出力汚染 | LLM出力に不正なURL/コードが混入 |

従来の単層防御（入力サニタイズのみ等）では、一箇所の突破で全体が危殆化する。

## Decision

**8層の多層防御モデルを採用する。**

### 層構成

| 層 | 名称 | 目的 | 実装 |
|:--:|------|------|------|
| L1 | Network Isolation | LLMコンテナの隔離 | `podman-compose.yml` 内部ネットワーク |
| L2 | Input Sanitization | 入力の正規化・危険パターン除去 | `llm_security.py` |
| L3 | Session Tags | ランダム区切りで指示分離 | `llm_security.py` |
| L4 | Output Validation | 出力の検証、漏洩検知 | `llm_security.py` |
| L5 | Response Metadata | 全レスポンスに信頼度付与 | `response_meta.py` |
| L6 | Source Verification | エビデンスによる信頼度変動 | `source_verification.py` |
| L7 | Schema Validation | MCPレスポンスのホワイトリスト検証 | `response_sanitizer.py` |
| L8 | Secure Logging | ログからのプロンプト除去 | `secure_logging.py` |

### 各層の詳細

#### L1: Network Isolation
- Ollamaコンテナは内部専用ネットワークで動作
- 外部からの直接アクセス不可

#### L2: Input Sanitization
- Unicode正規化（NFKC）
- ゼロ幅文字の除去
- 危険パターンの検出・警告

```
検出パターン例:
- "ignore previous instructions"
- "system prompt"
- "上記の指示を無視"
```

#### L3: Session Tags
- セッションごとにランダムな区切りタグを生成
- システム指示とユーザー入力を分離

```
<LYRA-a7f3b2c1>システム指示</LYRA-a7f3b2c1>
入力: ...
```

#### L4: Output Validation
- 外部URL・IPアドレスのパターン検出
- システムプロンプト漏洩の検知（n-gramマッチング）
- LYRAタグの出力検知

#### L5: Response Metadata
- すべてのMCPレスポンスに信頼度情報を付与
- MCPクライアントが信頼度を考慮して判断可能

#### L6: Source Verification
- エビデンスグラフによる自動検証
- 信頼度の昇格（UNVERIFIED→LOW）・降格（→BLOCKED）

```
昇格条件: 独立ソース2件以上で裏付け
降格条件: 矛盾検出、または棄却率>30%
```

#### L7: Schema Validation
- MCPレスポンスをスキーマでホワイトリスト検証
- 未定義フィールドは除去
- LLM生成フィールドにはL4検証を適用

#### L8: Secure Logging
- ログにプロンプト内容を書き込まない
- 機密情報のマスキング

### Trust Levels

| レベル | 説明 | 例 |
|--------|------|-----|
| PRIMARY | 標準化団体、登録機関 | iso.org, ietf.org |
| GOVERNMENT | 政府機関 | .gov, .go.jp |
| ACADEMIC | 学術機関 | arxiv.org, pubmed.gov |
| TRUSTED | 信頼できるメディア | wikipedia.org |
| LOW | L6で昇格されたソース | 検証済み未知ドメイン |
| UNVERIFIED | 未知のドメイン | デフォルト |
| BLOCKED | 信頼できないと判定 | 矛盾/棄却されたソース |

## Consequences

### Positive
- **多層防御**: 1層の突破で全体が危殆化しない
- **透明性**: 各層の判断がログで追跡可能
- **段階的対応**: 脅威レベルに応じた対応（警告→ブロック）
- **信頼度の可視化**: MCPクライアントが品質を考慮可能

### Negative
- **複雑性**: 8層の管理・テストが必要
- **パフォーマンス**: 各層での処理オーバーヘッド
- **偽陽性リスク**: 正当なコンテンツがブロックされる可能性

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 単層防御（入力サニタイズのみ） | シンプル | 一点突破で全滅 | 却下 |
| 3層モデル（入力/処理/出力） | 中程度の複雑さ | 信頼度・検証が不足 | 却下 |
| 外部セキュリティサービス | 専門知識不要 | Zero OpEx違反、データ流出 | 却下 |

## References
- `src/filter/llm_security.py` - L2/L3/L4実装
- `src/filter/source_verification.py` - L6実装
- `src/mcp/response_sanitizer.py` - L7実装
- `src/mcp/response_meta.py` - L5実装
- `src/utils/secure_logging.py` - L8実装
- `podman-compose.yml` - L1実装
