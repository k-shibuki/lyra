# Confidence & Calibration Design

**Date:** 2025-12-27
**Status:** Proposal (v2 - Updated for implementation/ADR alignment)
**Related:**
- ADR-0005: Evidence Graph Structure
- ADR-0011: LoRA Fine-tuning Strategy
- ADR-0012: Feedback Tool Design
- `src/filter/evidence_graph.py`
- `src/utils/calibration.py`

---

## 0. この文書の位置づけ（重要）

この文書は「confidence / calibration」に関する **現状分析（as-is）** と、プロダクトに対して有益な **改善提案（to-be）** をまとめる。

**更新方針（2025-12-27）**:
- 実装・スキーマ・ADRに対して断言している箇所は、一次情報（コード/ADR/DB schema）に合わせて修正する。
- ADRの方が望ましいが未実装の項目は、ADR側に「Open Issues / Gaps」として明記し、本書でも同様に扱う。
- 本書は設計議論の土台であり、今回のスコープは **ドキュメント修整のみ**（実装変更は行わない）。

## 1. 概念定義

### 1.1 コアエンティティ

Lyra のエビデンスグラフは以下の4つの主要エンティティで構成される。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Evidence Graph                                  │
│                                                                         │
│   ┌──────────┐          ┌──────────┐          ┌──────────┐             │
│   │   Page   │ ───────► │ Fragment │ ───────► │  Claim   │             │
│   │          │ contains │          │ supports │          │             │
│   │ (global) │          │ (global) │ refutes  │(task-scoped)           │
│   └──────────┘          └──────────┘ neutral  └──────────┘             │
│        │                      │                    ▲                    │
│        │                      │         Edge       │                    │
│        │                      └────────────────────┘                    │
│        │                           (global)                             │
│        │                                                                │
│   ┌──────────┐                                                          │
│   │  Domain  │  (参照情報のみ、Confidence 計算には使用しない)            │
│   └──────────┘                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 1.1.1 Page（ページ）

**定義**: クロールされた Web ページまたは学術論文
**スコープ**: グローバル（`url UNIQUE`、タスク間で再利用可能）
**DB テーブル**: `pages`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `id` | TEXT | 一意識別子 |
| `url` | TEXT | 正規化された URL（UNIQUE） |
| `domain` | TEXT | ドメイン名 |
| `page_type` | TEXT | article, knowledge, forum, academic, etc. |
| `paper_metadata` | TEXT (JSON) | 学術メタデータ `{year, doi, venue, citation_count, source_api}` |
| `title` | TEXT | ページタイトル |
| `fetched_at` | DATETIME | 取得日時 |

**学術メタデータ（paper_metadata JSON）**:
```json
{
  "year": 2023,
  "doi": "10.1234/example.2023",
  "venue": "Nature",
  "citation_count": 150,
  "source_api": "semantic_scholar",
  "paper_id": "abc123"
}
```

#### 1.1.2 Fragment（フラグメント）

**定義**: ページから抽出されたテキスト断片
**スコープ**: グローバル（`page_id` 経由で Page に紐づく）
**DB テーブル**: `fragments`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `id` | TEXT | 一意識別子 |
| `page_id` | TEXT | 親 Page への参照 |
| `fragment_type` | TEXT | paragraph, heading, list, table, quote, figure, code |
| `text_content` | TEXT | 抽出されたテキスト |
| `heading_hierarchy` | TEXT (JSON) | 見出し階層 `[{level, text}, ...]` |
| `position` | INTEGER | ページ内の順序 |
| `bm25_score` | REAL | BM25 スコア（ランキング時） |
| `embed_score` | REAL | 埋め込み類似度スコア |
| `rerank_score` | REAL | リランカースコア |

#### 1.1.3 Claim（主張）

**定義**: タスクに対して抽出または生成された検証対象の主張
**スコープ**: タスクスコープ（`task_id` で分離）
**DB テーブル**: `claims`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `id` | TEXT | 一意識別子 |
| `task_id` | TEXT | 所属タスク |
| `claim_text` | TEXT | 主張のテキスト |
| `claim_type` | TEXT | fact, opinion, prediction |
| `granularity` | TEXT | atomic, composite |
| `claim_confidence` | REAL | **llm-confidence**（LLM 自己報告。ベイズ更新の入力には使わないが、材料整形で並び替え/フォールバックに使われ得る） |
| `claim_adoption_status` | TEXT | adopted, pending, not_adopted |
| `supporting_count` | INTEGER | 支持エビデンス数 |
| `refuting_count` | INTEGER | 反論エビデンス数 |

#### 1.1.4 Edge（エッジ）

**定義**: エンティティ間の関係（証拠関係、引用関係）
**スコープ**: グローバル（ただし `task_id` でスライス可能）
**DB テーブル**: `edges`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `id` | TEXT | 一意識別子 |
| `source_type` | TEXT | claim, fragment, page |
| `source_id` | TEXT | ソースノード ID |
| `target_type` | TEXT | claim, fragment, page |
| `target_id` | TEXT | ターゲットノード ID |
| `relation` | TEXT | **supports, refutes, neutral, cites** |
| `nli_label` | TEXT | NLI モデルの判定ラベル |
| `nli_confidence` | REAL | **nli-confidence**（ベイズ更新の入力） |
| `confidence` | REAL | 総合信頼度（レガシー） |
| `citation_source` | TEXT | 引用元 API (semantic_scholar, openalex, extraction) |
| `edge_human_corrected` | BOOLEAN | 人間による修正済みフラグ |

**関係タイプ（RelationType）**:

| 関係 | 方向 | 説明 |
|------|------|------|
| `supports` | Fragment → Claim | フラグメントが主張を支持 |
| `refutes` | Fragment → Claim | フラグメントが主張を反論 |
| `neutral` | Fragment → Claim | 関係不明 |
| `cites` | Page → Page | 引用関係 |

---

## 2. Confidence の3つの種類

本プロジェクトでは「confidence」という用語が**3つの異なる意味**で使用されている。

### 2.1 用語マップ

| 用語 | 定義 | 生成元 | DB フィールド | 用途 | 校正可能性 |
|------|------|--------|---------------|------|------------|
| **llm-confidence** | LLM が抽出時に自己報告する確信度（抽出の自己評価） | Ollama (extract_claims.j2) | `claims.claim_confidence` | 並び替え・低証拠時の暫定表示など（※真偽の根拠としては扱わない） | 低 |
| **nli-confidence** | NLI モデルによる証拠関係判定の確信度 | Transformers NLI (nli_judge) | `edges.nli_confidence` | ベイズ更新の入力（証拠の重み） | 中〜高（ただし校正適用は別途配線が必要） |
| **bayesian-confidence** | 全証拠を集約した主張の信頼度 | `calculate_claim_confidence()` | 計算値（非永続） | レポート、UI | 導出値（N/A） |

### 2.2 意味論的な違い

```
┌─────────────────────────────────────────────────────────────────────────┐
│  llm-confidence                                                          │
│  ├── 問い: 「この抽出は正しいか？」                                        │
│  ├── 性質: 抽出品質の自己評価                                              │
│  ├── 値域: 0.0 - 1.0（LLM の主観的判断）                                   │
│  ├── 校正可能性: 低                                                        │
│  │   └── 理由: LoRA ファインチューニング非現実的                            │
│  │   └── 理由: サンプル収集コスト高                                         │
│  │   └── 理由: LLM の自己評価は本質的に不安定                               │
│  └── 現状: ベイズ更新の入力には使わない（`SearchExecutor._persist_claim()` のコメントで明示）│
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  nli-confidence                                                          │
│  ├── 問い: 「Fragment は Claim を支持/反論するか？」                        │
│  ├── 性質: 証拠関係の判定確率（NLI モデルの softmax 出力）                  │
│  ├── 値域: 0.0 - 1.0（DeBERTa-v3 のモデル出力）                            │
│  ├── 校正可能性: 中〜高                                                    │
│  │   ├── Platt Scaling: P = 1 / (1 + exp(A*logit + B))                   │
│  │   ├── Temperature Scaling: P = sigmoid(logit / T)                     │
│  │   └── LoRA Fine-tuning: フィードバックサンプルから適応学習              │
│  └── 現状: ベイズ更新で使用。校正モジュールは存在するが、NLI推論経路への適用は未配線。│
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  bayesian-confidence                                                     │
│  ├── 問い: 「この主張は真か？」                                            │
│  ├── 性質: Beta 分布の期待値（ベイズ事後確率）                             │
│  ├── 値域: 0.0 - 1.0（事前分布 Beta(1,1) からの更新）                      │
│  ├── 計算: confidence = alpha / (alpha + beta)                           │
│  │   └── alpha += Σ(nli_confidence for supports)                        │
│  │   └── beta  += Σ(nli_confidence for refutes)                         │
│  └── 現状: get_materials(), レポート生成で使用                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. データフロー

### 3.1 検索からエビデンス蓄積まで

```
                              ┌─────────────────┐
                              │   User Query    │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │  Search Engines │  DuckDuckGo, Brave, Google
                              │    + Academic   │  Semantic Scholar, OpenAlex
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │   SERP Items    │  検索結果リスト
                              │    (serp_items) │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │   Page Fetch    │  HTTP/Browser クロール
                              │     (pages)     │  WARC 保存
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │   Extraction    │  テキスト抽出
                              │   (fragments)   │  見出し階層保持
                              └────────┬────────┘
                                       │
                     ┌─────────────────┼─────────────────┐
                     │                 │                 │
           ┌─────────▼─────────┐       │       ┌─────────▼─────────┐
           │   Multi-Stage     │       │       │  Claim Extraction │
           │     Ranking       │       │       │   (Ollama LLM)    │
           │ BM25 → Embed →    │       │       │                   │
           │ Reranker → Domain │       │       │ llm-confidence    │
           └─────────┬─────────┘       │       └─────────┬─────────┘
                     │                 │                 │
                     │                 │                 ▼
                     │                 │       ┌─────────────────────┐
                     │                 │       │      claims         │
                     │                 │       │  (task-scoped)      │
                     │                 │       └─────────┬───────────┘
                     │                 │                 │
                     └─────────────────┼─────────────────┘
                                       │
                              ┌────────▼────────┐
                              │   NLI Judgment  │  Transformers NLI (DeBERTa系)
                              │   (nli_judge)   │  Fragment ↔ Claim
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │      edges      │  nli_label
                              │  (evidence)     │  nli_confidence
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │ Bayesian Update │  calculate_claim_confidence()
                              │  Beta(α, β)     │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │ bayesian-       │  Reports
                              │ confidence      │  Materials
                              └─────────────────┘
```

### 3.2 モデル別の役割

| モデル | 種類 | 用途 | 出力 | Confidence への影響 |
|--------|------|------|------|---------------------|
| **BM25** | 語彙的 | 第1段ランキング | `bm25_score` | なし（ランキング用） |
| **BGE-M3** | Embedding | 第2段ランキング | `embed_score` | なし（ランキング用） |
| **BGE-Reranker-v2-m3** | Cross-Encoder | 第3段ランキング | `rerank_score` | なし（ランキング用） |
| **Ollama (Qwen2.5-3B)** | LLM | Claim 抽出 | `claim_confidence` | ベイズ更新の入力にはしない（ただし保持される） |
| **Transformers NLI (DeBERTa系)** | NLI classifier | 証拠判定 | `nli_confidence` | **ベイズ更新の入力** |

### 3.3 ランキングパイプライン詳細

```python
# 多段ランキング（`src/filter/ranking.py`）

# Stage 1: BM25 (keyword matching)
bm25_scores = bm25_ranker.get_scores(query)

# Stage 2: Embedding Similarity (semantic)
embed_scores = await embedding_ranker.get_scores(query, texts)

# Stage 3: Combined Score
combined_score = 0.3 * bm25_score + 0.7 * embed_score  # 重み付け

# Stage 4: Cross-Encoder Reranker
rerank_scores = await reranker.rerank(query, texts, top_k)

# Domain Category Weight (ranking adjustment only)
# Weights live in `src/utils/domain_policy.py` (CATEGORY_WEIGHTS)
final_score = rerank_score * category_weight
```

**重要**: Domain Category は**ランキング調整のみ**に使用。Confidence 計算には使用しない（ADR-0005）。

---

## 4. ベイズ更新アルゴリズム

### 4.1 数学的基礎

**Beta 分布によるベイズ更新**:

```
Prior:     Beta(1, 1)     ← 無情報事前分布
Posterior: Beta(α, β)     ← 証拠による更新

α = 1 + Σ(nli_confidence for SUPPORTS edges)
β = 1 + Σ(nli_confidence for REFUTES edges)

confidence  = α / (α + β)                           ← 期待値
variance    = (α × β) / ((α + β)² × (α + β + 1))   ← 分散
uncertainty = √variance                             ← 標準偏差
controversy = min(α-1, β-1) / (α + β - 2)           ← 対立度
```

### 4.2 実装（src/filter/evidence_graph.py:344-474）

```python
def calculate_claim_confidence(self, claim_id: str) -> dict[str, Any]:
    evidence = self.get_all_evidence(claim_id)

    # Prior: Beta(1, 1)
    alpha = 1.0
    beta = 1.0

    for relation, items in evidence.items():
        for e in items:
            nli_conf = e.get("nli_confidence")

            if relation == "supports" and nli_conf > 0:
                alpha += nli_conf     # 支持証拠 → α を増加
            elif relation == "refutes" and nli_conf > 0:
                beta += nli_conf      # 反論証拠 → β を増加
            # NEUTRAL: 更新なし（情報なし）

    confidence = alpha / (alpha + beta)
    variance = (alpha * beta) / ((alpha + beta)**2 * (alpha + beta + 1))
    uncertainty = math.sqrt(variance)

    total_evidence = alpha + beta - 2.0
    controversy = min(alpha - 1.0, beta - 1.0) / total_evidence if total_evidence > 0 else 0.0

    # NOTE:
    # - The real implementation includes rounding, evidence_count,
    #   and year/DOI/venue enrichment when available.
    # - This snippet is for conceptual correspondence only.
```

### 4.3 出力契約（src/filter/schemas.py:40-59）

```python
class ClaimConfidenceAssessment(BaseModel):
    ...
```

---

## 5. NLI 校正システム

### 5.1 アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        NLI Calibration Pipeline                          │
│                                                                         │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│   │ NLI Model   │────►│ Raw Prob    │────►│ Calibrator  │              │
│   │ (DeBERTa)   │     │ (0.0-1.0)   │     │             │              │
│   └─────────────┘     └─────────────┘     └──────┬──────┘              │
│                                                   │                     │
│                              ┌────────────────────┼────────────────────┐│
│                              │                    │                    ││
│                              ▼                    ▼                    ▼│
│                     ┌─────────────┐      ┌─────────────┐     ┌────────┐│
│                     │   Platt     │      │ Temperature │     │ LoRA   ││
│                     │  Scaling    │      │  Scaling    │     │(Future)││
│                     └─────────────┘      └─────────────┘     └────────┘│
│                              │                    │                     │
│                              └────────────────────┼────────────────────┘│
│                                                   │                     │
│                                                   ▼                     │
│                                          ┌─────────────┐               │
│                                          │ Calibrated  │               │
│                                          │ Probability │               │
│                                          └─────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 校正手法

#### 5.2.1 Platt Scaling（ロジスティック回帰）

```python
# src/utils/calibration.py:178-244

# 数式: P_calibrated = 1 / (1 + exp(A × logit + B))

class PlattScaling:
    @staticmethod
    def fit(logits, labels, max_iter=100, lr=0.01) -> tuple[float, float]:
        """勾配降下法でパラメータ A, B を最適化"""
        A, B = 0.0, 0.0
        for _ in range(max_iter):
            # ... 勾配計算 ...
            A -= lr * grad_A
            B -= lr * grad_B
        return A, B

    @staticmethod
    def transform(logit: float, A: float, B: float) -> float:
        z = A * logit + B
        return 1.0 / (1.0 + math.exp(-z))
```

**適用場面**: logit が利用可能な場合、精度が高い

#### 5.2.2 Temperature Scaling

```python
# src/utils/calibration.py:247-312

# 数式: P_calibrated = sigmoid(logit / T)

class TemperatureScaling:
    @staticmethod
    def fit(logits, labels, max_iter=50, lr=0.1) -> float:
        """負の対数尤度を最小化して温度パラメータ T を最適化"""
        T = 1.0
        for _ in range(max_iter):
            # ... NLL 勾配計算 ...
            T -= lr * grad_T
            T = max(0.1, min(10.0, T))  # 範囲制限
        return T

    @staticmethod
    def transform(logit: float, T: float) -> float:
        return 1.0 / (1.0 + math.exp(-logit / T))
```

**適用場面**: シンプルで効果的、デフォルト手法

### 5.3 評価指標

| 指標 | 定義 | 理想値 | 用途 |
|------|------|--------|------|
| **Brier Score** | mean((predicted - actual)²) | 0.0 | 全体的な校正品質 |
| **ECE** | Σ(\|B_m\| / n × \|accuracy(B_m) - confidence(B_m)\|) | 0.0 | ビン別の校正誤差 |

```python
# Brier Score（src/utils/calibration.py:320-342）
def brier_score(predictions, labels):
    return sum((p - l)**2 for p, l in zip(predictions, labels)) / len(predictions)

# ECE（src/utils/calibration.py:345-406）
def expected_calibration_error(predictions, labels, n_bins=10):
    # 10ビンに分割して各ビンの |accuracy - confidence| を計算
    ...
```

### 5.4 劣化検知とロールバック

```python
# src/utils/calibration.py:414-700

class CalibrationHistory:
    DEGRADATION_THRESHOLD = 0.05  # 5% Brier 悪化でロールバック
    DEFAULT_MAX_HISTORY = 10      # ソースごとに最大10バージョン保持

    def check_degradation(self, new_params, old_params):
        if new_params.brier_after > old_params.brier_after * 1.05:
            self.rollback(source, reason="degradation_detected")
```

**保存先**:
- `data/calibration_params.json`: 現在のパラメータ
- `data/calibration_history.json`: バージョン履歴
- `data/calibration_samples.json`: 保留中サンプル
- `data/calibration_rollback_log.json`: ロールバック記録

### 5.5 再校正トリガー

| 条件 | 閾値 | 実装 |
|------|------|------|
| サンプル蓄積 | 10件以上 | `RECALIBRATION_THRESHOLD = 10`（※サンプル蓄積の“自動配線”は別途必要） |
| 劣化検知 | Brier 5%悪化 | 自動ロールバック |

**重要（現状の事実）**:
- 校正モジュール（`src/utils/calibration.py`）は存在するが、NLI推論→`edges.nli_confidence` への適用は未配線。
- MCPの `calibration_metrics` は **get_stats / get_evaluations** に限定される（評価/学習の実行はMCP経由では行わない設計）。
- `calibration_evaluations` テーブルは存在するが、現状コードでは主に参照（SELECT）用途で、評価結果の永続化（INSERT）は未整備の可能性が高い。

---

## 6. 関連 ADR の要約

### 6.1 ADR-0005: Evidence Graph Structure

| 項目 | 決定事項 |
|------|----------|
| **グラフ構造** | Claim をルートとする有向グラフ |
| **Confidence 計算** | ベイズ更新（Beta 分布） |
| **Domain Category** | **参照情報のみ**、Confidence 計算には使用しない |
| **スコープ分離** | Claims は task-scoped、Pages/Fragments は global |
| **ステータス** | ✅ 実装済み（ただし “明示的provenance edge” 等はOpen Issue） |

### 6.2 ADR-0011: LoRA Fine-tuning Strategy

| 項目 | 決定事項 |
|------|----------|
| **手法** | LoRA（Low-Rank Adaptation） |
| **対象モデル** | DeBERTa-v3 (NLI) |
| **MCP ツール化** | ❌ 却下（GPU 競合、長時間処理） |
| **運用方式** | スクリプトベース（オフラインバッチ） |
| **訓練トリガー** | 100+サンプル蓄積、10%+誤分類率 |
| **ステータス** | 📝 計画中（Phase R） |

### 6.3 ADR-0012: Feedback Tool Design

| 項目 | 決定事項 |
|------|----------|
| **構造** | 3レベル × 6アクション |
| **Domain** | `domain_block`, `domain_unblock`, `domain_clear_override` |
| **Claim** | `claim_reject`, `claim_restore` |
| **Edge** | `edge_correct` → **NLI 訓練データ蓄積** |
| **セキュリティ** | TLD レベルブロック禁止 |
| **ステータス** | ✅ 実装済み |

---

## 7. 決定事項 vs 未決定事項

### 7.1 ✅ 決定済み・実装済み

| 項目 | 詳細 | 参照 |
|------|------|------|
| Evidence Graph 構造 | NetworkX + SQLite | ADR-0005 |
| ベイズ Confidence 計算 | Beta 分布更新 | evidence_graph.py:344-474 |
| NLI モデル | Transformers sequence classifier（DeBERTa系） | ADR-0004 |
| 校正モジュール | Platt/Temperature Scaling | calibration.py（※適用配線は別） |
| フィードバックツール | 3レベル6アクション | ADR-0012 |
| nli_corrections テーブル | LoRA 訓練データ蓄積 | schema.sql |
| Domain Category 非使用 | Confidence 計算に影響しない | ADR-0005 |

### 7.2 ⚠️ 未決定・議論中

| 項目 | オプション | 推奨 | 参照 |
|------|-----------|------|------|
| **llm-confidence の扱い** | A: 削除, B: フィルタ, C: 弱い事前分布, D: 抽出品質スコアとしてのみ活用 | （結論は §8.4-8.5） | §8 |
| **prior_strength 値** | 0.3, 0.5, 1.0 | 0.5 | §8 |
| **MCP ツールリネーム** | calibration → nli_calibration | 未定 | §9 |

### 7.3 ❌ 未実装・将来計画

| 項目 | フェーズ | 前提条件 |
|------|----------|----------|
| LoRA 訓練スクリプト | Phase R | PEFT ライブラリ統合 |
| アダプタバージョン管理 | Phase R | 訓練スクリプト完成 |
| シャドウ評価 | Phase R | 100+サンプル蓄積 |

---

## 8. llm-confidence の扱い（提案）

### 8.1 現状の問題

```
┌─────────────────────────────────────────────────────────────────────────┐
│  問題                                                                    │
│  ├── LLM が出す confidence が「抽出品質」なのか「真偽」なのかが曖昧       │
│  ├── claim_confidence は保持されるが、真偽推定（bayesian-confidence）の入力には使わない │
│  ├── 用語の混乱を招く                                                    │
│  └── 処理リソースの無駄                                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 オプション比較

#### Option A: 削除（シンプル）

```python
# extract_claims.j2 から confidence フィールドを削除
{"claim": "主張の内容", "type": "fact|opinion|prediction"}

# claims.claim_confidence は deprecated
```

| Pros | Cons |
|------|------|
| シンプル | 将来の拡張性を失う |
| 誤解なし | 既存データの活用不可 |

#### Option B: フィルタ用（品質ゲート）

```python
# 低 confidence 抽出は破棄
if claim.get("confidence", 0.5) < 0.3:
    continue  # 抽出品質が低い
```

| Pros | Cons |
|------|------|
| 抽出品質向上 | LLM confidence の校正が困難 |
| 明確な閾値 | 閾値決定の根拠が弱い |

#### Option C: 弱い事前分布（条件付き）

```python
# evidence_graph.py:calculate_claim_confidence()

def calculate_claim_confidence(
    self,
    claim_id: str,
    use_llm_prior: bool = True,
) -> dict[str, Any]:
    evidence = self.get_all_evidence(claim_id)

    # NEW: llm-confidence を弱い事前分布として使用
    if use_llm_prior:
        llm_conf = self._get_claim_llm_confidence(claim_id)
        prior_strength = 0.5  # 弱いウェイト
        alpha = 1.0 + llm_conf * prior_strength
        beta = 1.0 + (1 - llm_conf) * prior_strength
    else:
        alpha = 1.0  # 元の無情報事前分布
        beta = 1.0

    # ... rest unchanged ...
```

| Pros | Cons |
|------|------|
| 既存データを活用 | 複雑さ増加 |
| NLI 証拠がない場合のヒント | 校正なしでも影響は軽微 |
| NLI 証拠が増えれば wash out | |
| 後方互換性あり | |

### 8.3 影響分析（Option C）

| 状況 | 現在 | Option C 後 | 変化 |
|------|------|-------------|------|
| NLI 証拠なし、llm-conf=0.9 | 0.50 | ~0.55 | +0.05 |
| NLI 証拠なし、llm-conf=0.3 | 0.50 | ~0.45 | -0.05 |
| NLI 証拠1件（supports, 0.8） | ~0.64 | ~0.65 | +0.01 |
| NLI 証拠3件（supports） | ~0.80 | ~0.80 | ≈0 |

**結論**: prior_strength=0.5 では、NLI 証拠が 1-2 件で prior の影響は消える。

### 8.4 Option D（追加）: “抽出品質”としてのみ使う（推奨）

**要点**: `llm-confidence` は「主張の真偽」ではなく「抽出の自己評価」として解釈し、真偽推定（bayesian-confidence）の事前分布には混ぜない。
用途を限定して、意味論の混線と“証拠ゼロ時の見かけの確信”を避ける。

- **用途例**:
  - 低 `llm-confidence` の claim を「要再確認」「優先度低」として材料整形・UIで扱う
  - （将来）低 `llm-confidence` を再抽出/人手レビューの優先度に使う
  - `edges.nli_confidence`（証拠の重み）や bayesian-confidence には混ぜない

| Pros | Cons |
|------|------|
| 真偽推定の意味論を壊しにくい（学術的にも説明しやすい） | “証拠ゼロ時のヒント”にはならない |
| 校正データ無しでも運用できる | 抽出品質の評価設計は別途必要 |

### 8.5 学術的ベスト（結論）

このプロダクト（証拠グラフ + NLIで支持/反証を集約）における学術的ベストは原則として:

- **Best**: **Option D**（`llm-confidence` は抽出品質スコアとしてのみ活用し、真偽推定に混ぜない）
- **条件付きで許容**: Option C（弱い事前分布）
  - 条件: 「証拠ゼロ/少数時の表示」をどう扱うかがプロダクト上重要で、かつ prior が誤誘導しないことを
    事後評価（ホールドアウト、時間分割、レビュー付きデータ）で確認できる場合

---

## 9. 学術的ベストプラクティスとの比較

### 9.1 Confidence Calibration（確信度校正）

| 手法 | 概要 | Lyra での状況 |
|------|------|---------------|
| **Platt Scaling** | ロジスティック回帰による校正 | ✅ モジュール実装済み（適用配線は別途） |
| **Temperature Scaling** | 単一パラメータスケーリング | ✅ モジュール実装済み（適用配線は別途） |
| **Isotonic Regression** | 非パラメトリック校正 | ❌ 未実装 |
| **Histogram Binning** | ビン別校正 | ❌ 未実装 |
| **Beta Calibration** | Beta 分布ベース | ❌ 未実装 |

**注意**: “学術的ベスト”はタスク・制約依存であり、本プロダクトでは
「教師データの取り方（バイアス）」「3-class NLIの扱い」「運用コスト」が支配的になる。
本節は“参考比較”として読む。

**技術的実現策**:
```python
# 複数手法のアンサンブル
calibrated_probs = [
    platt_scaling.transform(logit),
    temperature_scaling.transform(logit),
    isotonic_regression.transform(prob),
]
final_prob = np.mean(calibrated_probs)  # or weighted average
```

### 9.2 Evidence Aggregation（証拠集約）

| 手法 | 概要 | Lyra での状況 |
|------|------|---------------|
| **Bayesian Updating** | Beta 分布による更新 | ✅ 採用 |
| **Dempster-Shafer** | 証拠理論 | ❌ 未採用 |
| **Subjective Logic** | 不確実性モデリング | ❌ 未採用 |
| **Weighted Voting** | 重み付け投票 | ❌ 未採用 |

**補足**: Subjective Logic 等は魅力的だが、現状のデータ構造（supports/refutes/neutral + 重み）では
Beta更新が説明容易で、実装・運用の整合も取りやすい。

**技術的実現策**:
```python
# Subjective Logic の導入（将来）
class SubjectiveOpinion:
    belief: float      # 信念
    disbelief: float   # 不信
    uncertainty: float # 不確実性
    base_rate: float   # 基準率

    def fuse(self, other: "SubjectiveOpinion") -> "SubjectiveOpinion":
        # Cumulative fusion operator
        ...
```

### 9.3 Source Reliability（ソース信頼性）

| 手法 | 概要 | Lyra での状況 |
|------|------|---------------|
| **Domain-based** | ドメイン別重み | ❌ Confidence 計算に非使用（ADR-0005） |
| **Citation-based** | 被引用数 | 📝 メタデータとして保持 |
| **Temporal Decay** | 時間減衰 | ❌ 未実装 |
| **Cross-validation** | 相互検証 | ❌ 未実装 |

**注意**: Domain-based weightingはADR-0005で原則不採用。導入するなら、
“ドメイン”ではなく“研究デザイン/査読/被引用/再現性”等の、より説明可能な特徴量に寄せる必要がある。

**技術的実現策**:
```python
# 時間減衰の導入（将来）
def apply_temporal_decay(confidence: float, publication_year: int) -> float:
    current_year = 2025
    age = current_year - publication_year
    decay_factor = 0.95 ** age  # 5% annual decay
    return confidence * decay_factor
```

---

## 10. 課題と技術的解決策

### 10.1 現在の課題

| 課題 | 詳細 | 優先度 |
|------|------|--------|
| **用語の混乱** | 3種類の confidence が混在 | 高 |
| **llm-confidence の意味論** | 抽出品質/真偽が混線しやすい | 中 |
| **校正ファイル名** | `calibration.py` が NLI 専用に見えない | 中 |
| **LoRA 未実装** | フィードバックが活用されていない | 低（将来） |
| **校正の配線不足** | NLI推論→edgesへの校正適用、評価結果の永続化が未整備 | 高 |

### 10.2 技術的解決策

#### 課題1: 用語の混乱

**解決策**: ドキュメント整備 + コード内コメント統一

```python
# Before
confidence = ...  # 何の confidence?

# After
nli_confidence = ...      # NLI モデルの出力
bayesian_confidence = ... # ベイズ更新後の信頼度
```

#### 課題2: llm-confidence の意味論（抽出品質 vs 真偽）

**解決策**: Option D を基本とし、`llm-confidence` は「抽出品質の自己評価」としてのみ利用する（真偽推定の入力にはしない）。
Option C（弱い事前分布）は、証拠ゼロ時のUX要件と評価計画が揃った場合に限り検討する。

#### 課題3: 校正ファイル名

**解決策**: リネーム

| 現在 | 提案 |
|------|------|
| `src/utils/calibration.py` | `src/utils/nli_calibration.py` |
| `calibration_metrics` (MCP) | `nli_calibration_metrics` |
| `calibration_rollback` (MCP) | `nli_calibration_rollback` |

#### 課題4: LoRA 未実装

**解決策**: Phase R での実装計画

```bash
# 訓練スクリプト（将来）
python scripts/train_lora.py \
    --db data/lyra.db \
    --min-samples 100 \
    --output adapters/nli-lora-v1

# アダプタ適用
curl -X POST http://localhost:8001/nli/adapter/load \
    -d '{"adapter_path": "adapters/nli-lora-v1"}'
```

---

## 11. 実装ロードマップ

### Phase 1: 用語明確化（ドキュメント）

| タスク | ファイル | ステータス |
|--------|----------|:----------:|
| 本設計文書の確定 | `docs/confidence-calibration-design.md` | ✅ |
| ADR-0011 への参照追加 | `docs/adr/0011-lora-fine-tuning.md` | 📝 |

### Phase 2: リネーム（コード）

| タスク | 変更前 | 変更後 | ステータス |
|--------|--------|--------|:----------:|
| ファイルリネーム | `calibration.py` | `nli_calibration.py` | 📝 |
| MCP ツールリネーム | `calibration_metrics` | `nli_calibration_metrics` | 📝 |
| MCP ツールリネーム | `calibration_rollback` | `nli_calibration_rollback` | 📝 |
| import 更新 | 全参照箇所 | - | 📝 |

### Phase 3: Option C 実装

| タスク | ファイル | ステータス |
|--------|----------|:----------:|
| `_get_claim_llm_confidence()` | `evidence_graph.py` | 📝 |
| `calculate_claim_confidence()` 修正 | `evidence_graph.py` | 📝 |
| ユニットテスト追加 | `tests/filter/test_evidence_graph.py` | 📝 |

### Phase R: LoRA 実装（将来）

| タスク | 内容 | ステータス |
|--------|------|:----------:|
| R.1.x | PEFT/LoRA ライブラリ統合 | ❌ |
| R.2.x | 訓練スクリプト作成 | ❌ |
| R.3.x | アダプタバージョン管理 | ❌ |
| R.4.x | テストと検証 | ❌ |

---

## 12. 閾値一覧

| 閾値 | 値 | 場所 | 用途 |
|------|-----|------|------|
| 高 Confidence | ≥ 0.7 | report/generator.py | レポート内分類 |
| 反論検出 | > 0.7 | filter/nli.py | 矛盾検出 |
| OCR 行信頼度 | > 0.5 | extractor/content.py | OCRの低信頼行を除外 |
| 校正劣化 | 0.05 | utils/calibration.py | ロールバックトリガー |
| 再校正 | ≥ 10 samples | utils/calibration.py | 再校正トリガー |
| LoRA 訓練 | ≥ 100 samples | ADR-0011 | 訓練開始条件 |

---

## Appendix A: コード参照

| 概念 | ファイル | 備考 |
|------|----------|------|
| NodeType, RelationType / EvidenceGraph | `src/filter/evidence_graph.py` | Graph構造・DBロード・Beta更新 |
| calculate_claim_confidence() | `src/filter/evidence_graph.py` | Beta更新（supports/refutesのnli_confidenceを加算） |
| add_claim_evidence() | `src/filter/evidence_graph.py` | edges永続化（nli_confidence/label含む） |
| ClaimConfidenceAssessment | `src/filter/schemas.py` | get_materialsとの境界契約 |
| Calibrator / Platt / Temperature | `src/utils/calibration.py` | 校正モジュール（ただし適用配線は別） |
| NLI judge | `src/filter/nli.py` | local/remote NLI（Transformers） |
| Ranking | `src/filter/ranking.py` | DomainCategory重みはrankingのみ |
| DB schema | `src/storage/schema.sql` | pages/fragments/claims/edges/nli_corrections 等 |
| llm-confidence 生成 | `config/prompts/extract_claims.j2` | JSON出力に confidence を含む |
| llm-confidence をベイズ入力にしない | `src/research/executor.py` | NLIをedgesに保存し、LLM confidence は入力にしない旨をコメントで明示 |

## Appendix B: 関連 ADR 一覧

| ADR | タイトル | Confidence 関連度 |
|-----|----------|:----------------:|
| 0004 | Local LLM for Extraction Only | ✅ NLI 分類 |
| 0005 | Evidence Graph Structure | ✅ **基盤** |
| 0008 | Academic Data Source Strategy | ✅ 証拠収集 |
| 0011 | LoRA Fine-tuning Strategy | ✅ **NLI 校正** |
| 0012 | Feedback Tool Design | ✅ **訓練データ収集** |

## Appendix C: 用語集

| 用語 | 定義 |
|------|------|
| **llm-confidence** | LLM が抽出時に自己報告する確信度（抽出品質の自己評価）。真偽推定の入力には使わない。 |
| **nli-confidence** | NLI モデルが証拠関係（supports/refutes/neutral）を判定したスコア。ベイズ更新の入力（証拠の重み）。 |
| **bayesian-confidence** | 全証拠を集約した主張の最終的な信頼度。 |
| **Platt Scaling** | ロジスティック回帰による確率校正手法。 |
| **Temperature Scaling** | 単一温度パラメータによる確率校正手法。 |
| **Brier Score** | 確率予測の精度指標。0 が理想。 |
| **ECE** | Expected Calibration Error。校正誤差の指標。 |
| **LoRA** | Low-Rank Adaptation。パラメータ効率的なファインチューニング手法。 |
| **Beta 分布** | 確率の確率分布。ベイズ更新で使用。 |
| **Evidence Graph** | 主張と証拠の関係を表す有向グラフ。 |
