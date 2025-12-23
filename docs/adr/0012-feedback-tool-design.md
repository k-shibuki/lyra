# ADR-0012: Feedback Tool Design

## Status
Accepted

## Date
2025-12-23

## Context

Lyraは学術調査を支援するが、以下の状況でモデルが誤判定を行う：

| 誤判定タイプ | 例 |
|-------------|-----|
| NLI誤判定 | SUPPORTSをNEUTRALと誤分類 |
| 抽出漏れ | 重要な主張を見落とす |
| ノイズ混入 | 無関係な断片を関連と判定 |
| 引用誤認 | 引用関係の誤った推定 |

これらの誤りを訂正し、モデル改善に活用する仕組みが必要。

## Decision

**feedbackツールを新設し、6種類のアクションでユーザー訂正を受け付ける。**

### feedbackツールのアクション

| # | アクション | 目的 | 対象 |
|---|------------|------|------|
| 1 | `correct_nli` | NLI判定の訂正 | Fragment-Claim関係 |
| 2 | `flag_irrelevant` | 無関係断片のフラグ | Fragment |
| 3 | `flag_missing` | 見落とし断片の報告 | Page内の未抽出テキスト |
| 4 | `correct_citation` | 引用関係の訂正 | Fragment-Fragment関係 |
| 5 | `rate_usefulness` | 有用性評価 | Fragment/Page |
| 6 | `add_note` | 自由コメント | 任意ノード |

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
          "correct_nli",
          "flag_irrelevant",
          "flag_missing",
          "correct_citation",
          "rate_usefulness",
          "add_note"
        ]
      },
      "target_id": { "type": "string" },
      "payload": { "type": "object" }
    },
    "required": ["task_id", "action", "target_id", "payload"]
  }
}
```

### アクション別ペイロード

#### 1. correct_nli

```json
{
  "action": "correct_nli",
  "target_id": "edge_abc123",
  "payload": {
    "correct_relation": "SUPPORTS",
    "original_relation": "NEUTRAL",
    "confidence": 0.95,
    "reason": "論文の結論セクションで明確に支持している"
  }
}
```

#### 2. flag_irrelevant

```json
{
  "action": "flag_irrelevant",
  "target_id": "frag_xyz789",
  "payload": {
    "reason": "広告テキストが混入している"
  }
}
```

#### 3. flag_missing

```json
{
  "action": "flag_missing",
  "target_id": "page_def456",
  "payload": {
    "missing_text": "Figure 3 shows a 40% improvement...",
    "location_hint": "Results section, paragraph 2"
  }
}
```

#### 4. correct_citation

```json
{
  "action": "correct_citation",
  "target_id": "frag_source",
  "payload": {
    "cited_fragment_id": "frag_target",
    "relation": "CITES",
    "correction_type": "add"  // or "remove"
  }
}
```

#### 5. rate_usefulness

```json
{
  "action": "rate_usefulness",
  "target_id": "frag_abc123",
  "payload": {
    "rating": 5,  // 1-5
    "aspect": "relevance"  // relevance, clarity, credibility
  }
}
```

#### 6. add_note

```json
{
  "action": "add_note",
  "target_id": "claim_main",
  "payload": {
    "note": "この主張は2023年以降の研究で覆されている可能性あり"
  }
}
```

### データベーススキーマ

```sql
CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload JSON NOT NULL,
    created_at TEXT NOT NULL,
    applied_to_training INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX idx_feedback_task ON feedback(task_id);
CREATE INDEX idx_feedback_action ON feedback(action);
CREATE INDEX idx_feedback_training ON feedback(applied_to_training);
```

### LoRA学習への統合

フィードバックデータはADR-0010のLoRA学習に使用される：

```python
# correct_nliフィードバックから学習データ生成
def feedback_to_training_sample(feedback: Feedback) -> TrainingSample:
    edge = get_edge(feedback.target_id)
    return TrainingSample(
        premise=edge.fragment.text_content,
        hypothesis=edge.claim.text,
        label=feedback.payload["correct_relation"],
        weight=feedback.payload.get("confidence", 0.9)
    )

# 定期的にLoRA学習をトリガー
if count_unused_feedback() >= 50:
    trigger_lora_training()
```

### グラフへの即時反映

フィードバックはグラフにも即時反映：

```python
async def apply_feedback(feedback: Feedback):
    if feedback.action == "correct_nli":
        # エッジの関係を更新
        edge = await get_edge(feedback.target_id)
        edge.relation = feedback.payload["correct_relation"]
        edge.human_corrected = True
        await save_edge(edge)

        # Claimの信頼度を再計算
        await recalculate_claim_confidence(edge.claim_id)
```

## Consequences

### Positive
- **継続的改善**: ユーザーフィードバックでモデル品質向上
- **透明性**: 訂正履歴が追跡可能
- **即時効果**: グラフに即時反映
- **多様な訂正**: 6種類のアクションで包括的

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
- `docs/P_EVIDENCE_SYSTEM.md` 決定17（アーカイブ）
- `src/mcp/tools/feedback.py` - feedbackツール実装
- `src/storage/schema.sql` - feedbackテーブル
- ADR-0010: LoRA Fine-tuning Strategy
