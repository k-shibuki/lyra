# ADR-0012: Feedback Tool Design

## Date
2025-12-23

## Context

Lyraは学術調査を支援するが、以下の状況でモデルが誤判定を行う：

| 誤判定タイプ | 例 |
|-------------|-----|
| NLI誤判定 | supportsをneutralと誤分類 |
| 抽出漏れ | 重要な主張を見落とす |
| ノイズ混入 | 無関係な断片を関連と判定 |
| 引用誤認 | 引用関係の誤った推定 |

これらの誤りを訂正し、モデル改善に活用する仕組みが必要。

## Decision

**feedbackツールを新設し、3レベル・6種類のアクションでユーザー訂正を受け付ける。**

### feedbackツールのアクション（3レベル構成）

| レベル | アクション | 目的 | 対象 |
|--------|------------|------|------|
| Domain | `domain_block` | ドメインをブロック | ドメインパターン |
| Domain | `domain_unblock` | ドメインブロック解除 | ドメインパターン |
| Domain | `domain_clear_override` | オーバーライドをクリア | ドメインパターン |
| Claim | `claim_reject` | クレームを却下 | Claim ID |
| Claim | `claim_restore` | クレームを復元 | Claim ID |
| Edge | `edge_correct` | NLIエッジを訂正 | Edge ID |

### ツールスキーマ

```json
{
  "name": "feedback",
  "description": "Submit corrections and feedback on evidence",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": { "type": "string" },
      "action": {
        "type": "string",
        "enum": [
          "domain_block",
          "domain_unblock", 
          "domain_clear_override",
          "claim_reject",
          "claim_restore",
          "edge_correct"
        ]
      },
      "args": { "type": "object" }
    },
    "required": ["task_id", "action", "args"]
  }
}
```

### アクション別ペイロード

#### 1. domain_block

```json
{
  "action": "domain_block",
  "args": {
    "domain_pattern": "spam-site.com",
    "reason": "Low quality content, mostly advertisements"
  }
}
```

#### 2. domain_unblock

```json
{
  "action": "domain_unblock",
  "args": {
    "domain_pattern": "legitimate-site.com",
    "reason": "Previously blocked by mistake"
  }
}
```

#### 3. claim_reject

```json
{
  "action": "claim_reject",
  "args": {
    "claim_id": "claim_abc123",
    "reason": "Claim is too vague to verify"
  }
}
```

#### 4. edge_correct

```json
{
  "action": "edge_correct",
  "args": {
    "edge_id": "edge_xyz789",
    "correct_relation": "supports",
    "reason": "The conclusion section clearly supports the hypothesis"
  }
}
```

### データベーススキーマ

フィードバックデータは複数のテーブルに分散して保存される：

```sql
-- NLIエッジ訂正（edge_correct用）
CREATE TABLE nli_corrections (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL,
    task_id TEXT,
    premise TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    predicted_confidence REAL NOT NULL,
    correct_label TEXT NOT NULL,
    reason TEXT,
    corrected_at TEXT NOT NULL
);

-- ドメインオーバーライドルール（domain_block/unblock用）
CREATE TABLE domain_override_rules (
    id TEXT PRIMARY KEY,
    domain_pattern TEXT NOT NULL,
    decision TEXT NOT NULL,  -- "block" | "unblock"
    reason TEXT NOT NULL,
    created_at DATETIME,
    is_active BOOLEAN DEFAULT 1
);

-- ドメインオーバーライド監査ログ
CREATE TABLE domain_override_events (
    id TEXT PRIMARY KEY,
    rule_id TEXT,
    action TEXT NOT NULL,
    domain_pattern TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at DATETIME
);
```

### セキュリティ制約

TLDレベルのブロックは禁止される：

```python
FORBIDDEN_PATTERNS = [
    "*",           # 全ドメイン
    "*.com",       # TLDレベル
    "*.co.jp",
    "*.org", 
    "*.net",
    "*.gov",
    "*.edu",
    "**",          # 再帰glob
]
```

### グラフへの即時反映

フィードバックはグラフにも即時反映：

```python
async def apply_feedback(action: str, args: dict):
    if action == "edge_correct":
        # Mark as human-reviewed, and optionally correct relation
        edge = await get_edge(args["edge_id"])
        previous_label = edge.nli_label or edge.relation
        edge.edge_human_corrected = True
        edge.edge_corrected_at = now()

        # If the label changes, update the edge relation/label
        if previous_label != args["correct_relation"]:
            edge.relation = args["correct_relation"]
            edge.nli_label = args["correct_relation"]
            edge.nli_confidence = 1.0
            edge.edge_correction_reason = args.get("reason")
        else:
            # Review only (no correction): keep existing model outputs
            edge.edge_correction_reason = args.get("reason")

        await save_edge(edge)
        
        # Persist correction samples only when the label actually changed
        # (predicted_label != correct_label). These samples are used for future LoRA training.
        if previous_label != args["correct_relation"]:
            await save_nli_correction(edge, args)
```

### Edge review vs correction (運用上の重要事項)

`edge_correct` は「訂正」だけでなく「**人手レビュー済み**」の印を付けるためにも使う。

- **レビュー済み（分母）**: `edges.edge_human_corrected = 1` かつ `edges.edge_corrected_at` がセットされる
- **訂正あり（分子）**: 上記に加えて `nli_corrections` に1レコードが追加される（`predicted_label != correct_label`）
- **レビュー済みで訂正なし（正しい）**: `edges` 側はレビュー印あり、`nli_corrections` は増えない

この分離により、運用では「誤りだけを明示的に記録」しつつ、ケーススタディ等でレビュー済み集合をDBから追跡できる。

## Consequences

### Positive
- **継続的改善**: ユーザーフィードバックでモデル品質向上
- **透明性**: 訂正履歴が追跡可能（監査ログテーブル）
- **即時効果**: グラフに即時反映
- **3レベル構成**: Domain/Claim/Edgeで明確な責任分離
- **セキュリティ**: TLDレベルブロック禁止で誤操作防止

### Negative
- **ユーザー負担**: フィードバック入力の手間
- **品質リスク**: 誤ったフィードバックの混入
- **複雑性**: 6種類のアクション管理

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 単純なgood/badボタン | シンプル | 情報量不足 | 却下 |
| 自由テキストのみ | 柔軟 | 構造化困難 | 却下 |
| 外部アノテーションツール | 高機能 | 統合コスト、Zero OpEx | 却下 |

## References
- `src/mcp/feedback_handler.py` - feedbackアクションハンドラー
- `src/mcp/server.py` - feedbackツール定義
- `src/storage/schema.sql` - nli_corrections, domain_override_rules テーブル
- ADR-0011: LoRA Fine-tuning Strategy
