# Evidence Graph探索インターフェースの課題と提案

## 概要

本文書は、S_FULL_E2E.md ケーススタディ実行中に発見された `get_materials` ツールの課題と、AIエージェントがEvidence Graphを効果的に探索するためのインターフェース改善提案をまとめる。

---

## 1. 計測結果

### 1.1 task_9c48928b のデータサイズ

| テーブル | 件数 | テキストサイズ |
|----------|------|----------------|
| claims | 333件 | 38 KB |
| fragments | 67件 | 127 KB |
| edges | 333件 | (関係データのみ) |
| **合計テキスト** | - | **162 KB** |

### 1.2 JSONエクスポートサイズ

| ファイル | サイズ | 備考 |
|----------|--------|------|
| claims.json | 23 KB | 100件にLIMIT |
| edges.json | 49 KB | 333件 |
| fragments.json | 145 KB | 67件 |
| **合計** | **217 KB** | メタデータ含む |

### 1.3 get_materials 出力推定

`get_materials(include_graph=true, include_citations=true)` の出力は、上記JSONに加えて以下を含む：
- evidence_graph構造（nodes/edges配列）
- citations network
- summary統計

**推定サイズ: 300-400 KB**

---

## 2. 現状の課題

### 2.1 コンテキストオーバーフロー

**症状**: `get_materials` を1回呼び出すだけで、AIエージェントのコンテキストウィンドウを圧迫し、後続の処理ができなくなる。

**原因**: 
- 全データを一度に返却する設計
- 333件のclaims × 関連fragmentsの全テキストが含まれる
- エージェント会話には他の文脈も存在する

### 2.2 探索不可能

**症状**: AIが「このEvidence Graphから何がわかるか」を判断できない。

**原因**:
- データが構造化されていても、量が多すぎて全体を把握できない
- 重要なclaims、矛盾するエビデンス、主要トピックが埋もれる

### 2.3 代替手段の限界

| 代替手段 | 問題 |
|----------|------|
| sqlite3直接クエリ | AIエージェントには使えない（プロダクトとしてNG） |
| D3.js可視化 | 人間向け、AIの探索には役立たない |
| 手動でclaims抽出 | スケールしない、自動化できない |

---

## 3. Lyraの目的との整合性

**Lyraの目的**: AIに信頼できる情報を与える

**必要なもの**: AIがEvidence Graphを**自律的に探索できる**インターフェース

現状の `get_materials` は「全データダンプ」であり、AIの探索を支援する設計になっていない。

---

## 4. 提案: Evidence Graph探索ツール群

### 4.1 設計思想

1. **小さなツール群**: 各ツールは10-20件程度のデータを返す
2. **AIが戦略を立てる**: ツールを組み合わせて自律探索
3. **構造を活かす**: supports/refutes関係、ドメインカテゴリを活用
4. **透明性**: AIがどのエビデンスを見て結論を出したか追跡可能

### 4.2 提案ツール一覧

#### (1) get_evidence_summary

**目的**: 全体像の把握（軽量）

**入力**: `task_id`

**出力**:
```json
{
  "task_id": "task_9c48928b",
  "query": "DPP-4阻害薬の有効性と安全性...",
  "statistics": {
    "total_claims": 333,
    "total_fragments": 67,
    "supports_edges": 41,
    "refutes_edges": 11,
    "neutral_edges": 281
  },
  "top_topics": ["有効性", "心血管安全性", "低血糖リスク", "他剤比較"],
  "contradiction_highlights": [
    {"topic": "心不全リスク", "claim_count": 3}
  ],
  "primary_source_ratio": 0.45
}
```

**推定サイズ**: 1-2 KB

---

#### (2) list_claim_topics

**目的**: トピック一覧の取得

**入力**: `task_id`

**出力**:
```json
{
  "topics": [
    {"name": "HbA1c効果", "claim_count": 45, "has_contradiction": false},
    {"name": "心血管安全性", "claim_count": 28, "has_contradiction": true},
    {"name": "低血糖リスク", "claim_count": 12, "has_contradiction": false},
    ...
  ]
}
```

**推定サイズ**: 1-3 KB

**実装案**: claimsをLLMでクラスタリング、またはキーワード抽出

---

#### (3) get_claims_by_topic

**目的**: 特定トピックのclaims取得

**入力**: `task_id`, `topic`, `limit=20`

**出力**:
```json
{
  "topic": "HbA1c効果",
  "claims": [
    {
      "id": "c_xxx",
      "text": "DPP-4i + insulin でHbA1c -0.52%低下 (WMD, 95% CI -0.61 to -0.43)",
      "evidence_count": 3,
      "supports": 2,
      "refutes": 0
    },
    ...
  ]
}
```

**推定サイズ**: 5-10 KB

---

#### (4) get_claim_evidence

**目的**: 特定claimの根拠詳細

**入力**: `claim_id`

**出力**:
```json
{
  "claim_id": "c_xxx",
  "claim_text": "DPP-4i + insulin でHbA1c -0.52%低下...",
  "evidence": {
    "supports": [
      {
        "fragment_id": "f_aaa",
        "text": "This updated systematic review...",
        "source": {
          "url": "https://doi.org/...",
          "domain": "doi.org",
          "domain_category": "PRIMARY",
          "title": "DPP-4 inhibitors meta-analysis"
        },
        "confidence": 0.92
      }
    ],
    "refutes": [],
    "neutral": [...]
  }
}
```

**推定サイズ**: 3-8 KB

---

#### (5) find_contradictions

**目的**: 矛盾するエビデンスの発見

**入力**: `task_id`

**出力**:
```json
{
  "contradictions": [
    {
      "topic": "心不全リスク",
      "claims": [
        {"id": "c_111", "text": "DPP-4阻害薬は心不全リスクを増加させない", "supports": 2},
        {"id": "c_222", "text": "saxagliptinは心不全入院リスクを増加させる可能性", "supports": 1}
      ],
      "note": "薬剤間の差異の可能性"
    }
  ]
}
```

**推定サイズ**: 2-5 KB

---

### 4.3 AIの探索フロー例

```
1. get_evidence_summary("task_9c48928b")
   → 全体像把握: 333 claims, 主要トピック確認, 矛盾ハイライト

2. AIが判断: "研究質問に関連するトピックは有効性と安全性"

3. get_claims_by_topic("task_9c48928b", "HbA1c効果")
   → 主要なclaims一覧を取得

4. get_claim_evidence("c_xxx")
   → 最重要claimの根拠を詳細確認

5. find_contradictions("task_9c48928b")
   → 矛盾するエビデンスを確認

6. AIが結論を構成
```

---

## 5. 実装の優先順位

| 優先度 | ツール | 理由 |
|--------|--------|------|
| P0 | get_evidence_summary | 全体像把握は必須 |
| P0 | get_claims_by_topic | トピックベース探索の基盤 |
| P1 | get_claim_evidence | 根拠確認に必要 |
| P1 | find_contradictions | 信頼性評価に必要 |
| P2 | list_claim_topics | トピック自動抽出（LLM依存） |

---

## 6. 既存ツールとの関係

### 6.1 get_materials の扱い

**選択肢**:
1. **廃止**: 新ツール群に完全移行
2. **軽量化**: `format="summary"` オプション追加で get_evidence_summary 相当を返す
3. **維持**: バッチ処理・非AI用途向けに残す

**推奨**: 選択肢2（後方互換性を維持しつつ改善）

### 6.2 feedback ツールとの連携

`find_contradictions` で発見した矛盾は、`feedback(action=edge_correct)` で人間がレビュー・修正できる。

---

## 7. 次のアクション

1. [ ] ADR作成: Evidence Graph探索ツール設計
2. [ ] get_evidence_summary 実装
3. [ ] get_claims_by_topic 実装（トピック分類ロジック含む）
4. [ ] S_FULL_E2E.md 再実行で検証

---

## 参考

- 関連タスク: task_9c48928b（DPP-4阻害薬の有効性と安全性）
- 関連ADR: ADR-0005 Evidence Graph Structure
- 関連ファイル: `case_study/lyra/evidence_graph.html`（D3.js可視化）

