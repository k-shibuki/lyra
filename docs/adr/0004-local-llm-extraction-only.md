# ADR-0004: Local LLM for Extraction Only

## Date
2025-11-08

## Context

LyraはWebページから情報を抽出し、構造化する必要がある。具体的なタスク：

| タスク | 入力 | 出力 |
|--------|------|------|
| 主張抽出 | ページテキスト + 仮説 | 関連する主張のリスト |
| NLI判定 | 前提テキスト + 仮説 | SUPPORTS / REFUTES / NEUTRAL |
| エンティティ抽出 | テキスト | 人名、組織名、日付等 |
| 要約 | 長文 | 短い要約 |

これらにはLLMが有効だが、ADR-0001（Zero OpEx）の制約により商用API（GPT-4、Claude API）は使用できない。

一方、ADR-0002で規定した通り、**戦略的判断（クエリ設計、探索方針）はMCPクライアントが担当**する。ローカルLLMがこれらを担当すると品質が低下する。

## Decision

**ローカルLLM（Qwen2.5-3B）を「機械的な抽出・分類タスク」のみに使用する。**

### 使用するタスク（許可）

| タスク | モデル使用方法 |
|--------|----------------|
| NLI判定 | 3クラス分類（SUPPORTS/REFUTES/NEUTRAL） |
| 主張抽出 | 構造化出力（JSON） |
| 要約生成 | 圧縮タスク |

### 使用しないタスク（禁止）

| タスク | 理由 |
|--------|------|
| 検索クエリ設計 | MCPクライアントの専権（ADR-0002） |
| 探索戦略の決定 | 高度な推論が必要 |
| エビデンスの統合評価 | 複雑な判断が必要 |
| ユーザーへの回答生成 | MCPクライアントが担当 |

### モデル選定

| モデル | サイズ | 用途 | 選定理由 |
|--------|--------|------|----------|
| Qwen2.5-3B-Instruct | 3B | NLI、抽出 | 日本語性能、サイズ効率 |
| (予備) Phi-3-mini | 3.8B | 英語特化時 | 英語性能が高い |

### プロンプト設計

NLI判定の例：

```
System: あなたはNLI（自然言語推論）の専門家です。
前提文と仮説文を比較し、関係を判定してください。

User:
前提: {premise}
仮説: {hypothesis}

以下の3つから1つを選んでください：
- SUPPORTS: 前提は仮説を支持する
- REFUTES: 前提は仮説に反する
- NEUTRAL: 前提からは仮説について判断できない

回答（1単語のみ）:
```

### 出力制御

```python
# 構造化出力を強制
response = await ollama.generate(
    model="qwen2.5:3b",
    prompt=prompt,
    format="json",  # JSON出力を強制
    options={
        "temperature": 0.1,  # 決定的な出力
        "num_predict": 50,   # 短い出力に制限
    }
)
```

## Consequences

### Positive
- **Zero OpEx達成**: 商用API不要
- **高速応答**: 3Bモデルは数百msで応答
- **品質担保**: タスクを限定することで精度維持
- **オフライン動作**: ネットワーク不要

### Negative
- **機能制限**: 複雑なタスクはMCPクライアント依存
- **言語制約**: 英語・日本語以外は精度低下の可能性
- **GPU必要**: 快適な動作にはGPUが望ましい

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| GPT-4 API | 高品質 | コスト、Zero OpEx違反 | 却下 |
| 7B+ モデル | より高精度 | GPU要件が厳しい | 将来検討 |
| ルールベース抽出 | 高速、確実 | 柔軟性不足 | 部分採用 |
| 外部NLIサービス | 高精度 | API依存 | 却下 |

## References
- `src/filter/ollama_provider.py` - Ollamaクライアント
- `src/filter/llm.py` - LLM抽出処理
- `src/filter/nli.py` - NLI判定実装
- ADR-0001: Local-First / Zero OpEx
- ADR-0002: Thinking-Working Separation
