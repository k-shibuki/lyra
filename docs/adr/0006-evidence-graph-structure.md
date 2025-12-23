# ADR-0006: Evidence Graph Structure

## Status
Accepted

## Date
2024-XX-XX（プロジェクト開始時）

## Context

学術調査において、情報の信頼性を評価するには以下が必要：

1. **出典の追跡**: 各主張がどのソースから来たか
2. **エビデンスの関係**: 支持/反論の関係性
3. **信頼度の計算**: 複数エビデンスからの総合評価
4. **監査可能性**: 主張→断片→ページの追跡

単純なリスト構造では、これらの関係性を表現できない。

また、「信頼できるドメインだから正しい」という仮定は誤り：
- 心理学研究の60%以上が再現不可能（再現性危機）
- 年間数千件の論文が撤回
- プレプリント（arXiv等）は査読なし
- ハゲタカジャーナルの存在

**ACADEMICドメインであっても、単独エビデンスでは確信できない。**

## Decision

**有向グラフ（Evidence Graph）を採用し、主張-断片-ページの関係を構造化する。**

### グラフ構造

```
         Claim (主張)
            │
    ┌───────┴───────┐
    │               │
[supports]      [refutes]
 conf: 0.92      conf: 0.78
    │               │
    ▼               ▼
Fragment (断片)  Fragment (断片)
    │               │
    ▼               ▼
  Page (ページ)    Page (ページ)
```

### ノードタイプ

| ノード | 内容 | 主要属性 |
|--------|------|---------|
| Claim | 検証対象の主張 | text, confidence, uncertainty, controversy |
| Fragment | 引用可能な断片 | text_content, context |
| Page | ソースページ | url, domain, domain_category, fetch_date |

### エッジタイプ

| エッジ | 意味 | 属性 |
|--------|------|------|
| SUPPORTS | 断片が主張を支持 | nli_confidence, source_domain_category |
| REFUTES | 断片が主張に反論 | nli_confidence, source_domain_category |
| NEUTRAL | 関連するが支持も反論もしない | nli_confidence |
| CITES | 学術引用関係 | citation_source (s2/openalex/extraction) |

### 信頼度計算：ベイズ更新

**ドメインカテゴリではなく、エビデンスの蓄積で信頼度を計算する。**

```
# Beta分布によるベイズ更新
事前分布: Beta(α=1, β=1)  # 無情報事前分布

SUPPORTSエッジごとに:
  α += nli_confidence * weight

REFUTESエッジごとに:
  β += nli_confidence * weight

# 期待値と不確実性
confidence = α / (α + β)
uncertainty = sqrt(α * β / ((α + β)² * (α + β + 1)))
controversy = min(α, β) / max(α, β)
```

**設計意図**:
- 単一エビデンス → 高uncertainty（確信できない）
- 複数独立エビデンスで裏付け → 低uncertainty（蓋然性向上）
- Nature論文でも単独なら高uncertainty
- 無名ブログでも5つの独立エビデンスなら低uncertainty

### ドメインカテゴリの位置づけ

| レベル | 説明 | 用途 |
|--------|------|------|
| PRIMARY | 標準化団体 | ランキング調整（参考） |
| GOVERNMENT | 政府機関 | ランキング調整（参考） |
| ACADEMIC | 学術機関 | ランキング調整（参考） |
| TRUSTED | 信頼メディア | ランキング調整（参考） |
| LOW | 検証済み | - |
| UNVERIFIED | 未知 | デフォルト |
| BLOCKED | ブロック | 取得停止 |

**重要**: ドメインカテゴリは**信頼性の保証ではない**。ランキングの参考情報であり、検証判定には使用しない。

### 対立関係の扱い

Lyraは対立を**事実として記録**し、**解釈はMCPクライアントに委ねる**：

| 責務 | Lyra | MCPクライアント |
|------|------|----------------|
| 対立の検出 | REFUTESエッジ作成 | - |
| ドメイン情報付与 | エッジに記録 | 参照して判断 |
| 「科学的論争か誤情報か」 | 判断しない | 判断する |

## Consequences

### Positive
- **関係性の明示化**: 支持/反論/引用関係が構造化
- **監査可能性**: 主張→断片→ページの完全追跡
- **ベイズ的不確実性**: 単一エビデンスへの過信を防止
- **論争の可視化**: controversy指標で対立を定量化

### Negative
- **複雑性**: グラフ操作のオーバーヘッド
- **ストレージ**: ノード・エッジの保存コスト
- **NLI依存**: 信頼度計算がNLIモデルの品質に依存

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| フラットリスト | シンプル | 関係性表現不可 | 却下 |
| 木構造 | 階層表現可能 | 複数親不可、引用関係表現困難 | 却下 |
| ドメイン信頼度ベース | 計算シンプル | 「ACADEMICだから正しい」の誤謬 | 却下 |
| 確定的スコア（0-1） | 理解しやすい | 不確実性を表現できない | 却下 |

## References
- `docs/archive/P_EVIDENCE_SYSTEM.md`（アーカイブ）- 決定3, 7, 13
- `src/filter/evidence_graph.py` - グラフ実装
- `src/storage/schema.sql` - DBスキーマ
- `README.md` "Evidence Graph" セクション
