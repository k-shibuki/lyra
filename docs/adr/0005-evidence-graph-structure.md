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

### Data Ownership & Scope（グローバル / タスク固有の境界）

本ADRで扱う「Evidence Graph」は、永続化されたデータがすべて `task_id` 列を持つわけではない。
Lyraでは、**タスク固有（task-scoped）**と**グローバル（global / reuseable）**が混在し、**task_idで“切り出す”**ことでタスク単位の材料を構成する。

#### スコープの基本原則

- **Task-scoped（タスク固有）**
  - `claims` は `task_id` を持ち、タスクの成果物（主張ノード）である。
  - タスクの Evidence Graph は、原則として **この task の claims を起点**に切り出される。
- **Global / Reusable（タスク横断で再利用され得る）**
  - `pages` は `url UNIQUE` で `task_id` を持たず、同一URLはタスク横断で共有され得る（キャッシュ/再利用の設計）。
  - `fragments` も `task_id` を持たず `page_id → pages.id` にぶら下がるため、タスク固有の所有権が弱い。
  - `edges` も `task_id` を持たず、**claimを起点にフィルタ**してタスクの部分グラフを構成する。

#### 実装上のスコーピング（重要）

- Evidence Graph のロードは `task_id` を指定すると **claims(task_id=...) に接続する edges** のみを読み込む。
  - これにより、`edges/pages/fragments` がグローバルに存在しても、タスクの材料は `task_id` で切り出せる。

#### 同一リソースの再発見（異なるクエリ・コンテキスト）

同じ論文（DOI/URL）が**異なるクエリやコンテキストから再発見**された場合の振る舞い：

| レイヤー | 振る舞い | 理由 |
|----------|----------|------|
| `pages` | 2回目以降は既存 `page_id` を返す（挿入しない） | URLでUNIQUE、グローバルリソースとして1回だけ保存 |
| `fragments` | 2回目以降は既存 `fragment_id` を返す | `page_id` に紐づくグローバルリソース |
| `claims` | **新規作成** | タスク固有。異なるクエリ/コンテキストは異なるClaim |
| `edges` | **新規作成**（Fragment → 新Claim） | 同じFragmentが複数のClaimを支持/反証できる |

実装上のワークフロー：

1. **リソース発見時**: `resource_index` で DOI/URL をチェック
2. **既存の場合**: 既存 `page_id` と `fragment_id` を取得して返す
3. **呼び出し元**: 取得した `fragment_id` を使って新しい `claims` と `edges` を作成

これにより：
- **ストレージ効率**: 同じ論文データは1回だけ保存
- **コンテキスト保持**: 各クエリ固有のClaimとして評価可能
- **引用追跡**: 同じFragmentから複数Claimへのedgeで表現

### Cleanup Policy（soft / hard）

本ADRのスコープ設計により、停止/削除時のクリーンアップは次の2段階に分けるのが安全である。

#### Soft cleanup（安全・デフォルト）

目的: **他タスクへ影響し得るデータ（pages/fragments等）を触らず**、該当タスクの材料を論理的に不可視化する。

- **Task-scopedを対象**に削除/無効化する（例: `tasks`, `claims`, `queries`, `serp_items`, `task_metrics`, `decisions`, `jobs`, `event_log`, `intervention_queue` など）。
- Evidence Graph観点では、少なくとも次を対象にする:
  - **claims**: `claims.task_id = ?`
  - **edges**: source/target がこの task の claim を参照するもの
    - `edges` は FK で守られていないため、claims削除後に「claim参照edge」が残るとDBが汚れる。
    - ただし claim ID はタスク固有であるため、該当 edges の削除は他タスクへ波及しにくい。

Soft cleanup後の状態:
- `pages/fragments/edges(非claim参照)` はDB上に残り得るが、`task_id` を起点とする材料収集では辿れない（論理的不可視化）。

#### Hard cleanup（慎重）

目的: ストレージ回収のために、**共有され得るデータ**も「安全条件を満たす場合に限り」削除する。

Hard cleanupは **必ず task_id から辿れる集合を計算し、かつ“他タスクから参照されていない”ことを確認**してから削除する。

推奨: hard cleanup は次の仕様とする。

- **hard(orphans_only)**
  - Soft cleanupを実施後に、追加で以下の “孤児（orphan）” を削除する。
    - **orphan edges**: source_id/target_id が存在しない（または削除済み）ノードを参照する edges
    - **orphan fragments**: どの edges にも参照されない fragments
    - **orphan pages**: どの fragments にも参照されず、かつ edges でも参照されない pages
  - `pages` にはファイルパス列（html/warc/screenshot等）があるため、ページ削除時に対応するファイル削除も行う（best-effort）。

Note:
- “中途半端な状態をゼロにする（強い原子性）”は、非同期I/O＋増分永続化の特性上、現実的でない。

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
- `src/storage/schema.sql` - グラフスキーマ（edges, claims, fragmentsテーブル）
- `src/filter/evidence_graph.py` - エビデンスグラフ実装（NetworkX + SQLite）
