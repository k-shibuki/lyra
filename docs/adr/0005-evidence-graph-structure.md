# ADR-0005: Evidence Graph Structure

## Date
2025-11-15

## Context

学術調査では、複数のソースから収集したエビデンスを統合し、仮説の信頼度を評価する必要がある。

従来のアプローチ：

| アプローチ | 問題点 |
|------------|--------|
| フラットなリスト | エビデンス間の関係が不明 |
| 単純なスコアリング | 矛盾するエビデンスの扱いが困難 |
| 手動評価のみ | スケールしない |

必要な機能：
- 仮説とエビデンスの関係を表現
- 支持・反証の両方を追跡
- エビデンス間の引用関係を表現
- 信頼度の自動計算

## Decision

**Claimをルートとしたエビデンスグラフ構造を採用し、ベイズ的な信頼度計算を行う。**

### グラフ構造

```
         Claim（主張・仮説）
              │
    ┌─────────┼─────────┐
    │         │         │
Fragment  Fragment  Fragment
(SUPPORTS) (REFUTES) (NEUTRAL)
    │
    └── Page ── Domain
```

### ノードタイプ

| ノード | 説明 | 主要属性 |
|--------|------|----------|
| Claim | ユーザーの主張・仮説 | text, confidence |
| Fragment | ページから抽出した断片 | text_content, extraction_method |
| Page | クロールしたWebページ | url, title, crawled_at |
| Domain | ドメイン（参考情報） | domain_name |

### エッジタイプ

| エッジ | From | To | 説明 |
|--------|------|-----|------|
| SUPPORTS | Fragment | Claim | 断片が主張を支持 |
| REFUTES | Fragment | Claim | 断片が主張に反証 |
| NEUTRAL | Fragment | Claim | 関係不明確 |
| EXTRACTED_FROM | Fragment | Page | 抽出元 |
| CITES | Fragment | Fragment | 引用関係 |

### 信頼度計算（ベイズ的アプローチ）

```python
def calculate_confidence(claim: Claim) -> float:
    """
    Claimの信頼度を計算

    P(H|E) ∝ P(E|H) × P(H)
    - P(H): 事前確率（デフォルト0.5）
    - P(E|H): 尤度（エビデンスの質と量に依存）
    """
    supports = get_edges(claim, "SUPPORTS")
    refutes = get_edges(claim, "REFUTES")

    support_weight = sum(
        edge.source.reliability_score * edge.nli_confidence
        for edge in supports
    )
    refute_weight = sum(
        edge.source.reliability_score * edge.nli_confidence
        for edge in refutes
    )

    # ロジスティック関数で0-1に正規化
    log_odds = support_weight - refute_weight
    confidence = 1 / (1 + exp(-log_odds))

    return confidence
```

### Domainカテゴリ（参考情報のみ）

**重要**: ドメインカテゴリは参考情報であり、信頼度計算には**使用しない**。

理由：
- 同じドメインでも記事の質は様々
- ドメインベースの重み付けは偏見を生む
- Fragment単位の評価が本質

```python
# ドメインカテゴリ（参考表示用）
DOMAIN_CATEGORIES = {
    "academic": ["arxiv.org", "nature.com", ...],
    "news": ["reuters.com", "nytimes.com", ...],
    "government": [".gov", ".go.jp", ...],
}

# 信頼度計算ではドメインを参照しない
def calculate_reliability(fragment: Fragment) -> float:
    # ❌ domain_weight = DOMAIN_WEIGHTS[fragment.page.domain.category]
    # ✓ Fragment自体の特徴のみ使用
    return compute_from_fragment_features(fragment)
```

## Consequences

### Positive
- **透明性**: なぜその信頼度かを追跡可能
- **矛盾の可視化**: 支持・反証が並列表示
- **拡張性**: 新しいエッジタイプを追加可能
- **引用追跡**: 学術論文間の引用関係を表現

### Negative
- **計算コスト**: グラフ走査が必要
- **複雑性**: 単純なリストより理解が難しい
- **メンテナンス**: グラフの整合性維持が必要

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| フラットリスト | シンプル | 関係性が表現不可 | 却下 |
| Knowledge Graph (RDF) | 標準化 | 過剰に複雑 | 却下 |
| ベクトルDB only | 類似検索が高速 | 関係性が弱い | 補助的採用 |
| スコアのみ | 軽量 | 根拠が不透明 | 却下 |

## References
- `docs/P_EVIDENCE_SYSTEM.md`（アーカイブ）
- `src/storage/schema.sql` - グラフスキーマ
- `src/graph/confidence.py` - 信頼度計算
