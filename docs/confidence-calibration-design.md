# Confidence & Calibration Design

**Date:** 2025-12-27
**Status:** Proposal
**Related:** ADR-0011, `src/utils/calibration.py`, `src/filter/evidence_graph.py`

---

## 1. 用語定義

本プロジェクトでは「confidence」という用語が複数の文脈で使用されており、混乱を招いている。
以下に各用語を明確に定義する。

### 1.1 Confidence 用語マップ

| 用語 | 定義 | 生成元 | DB フィールド | 用途 |
|------|------|--------|---------------|------|
| **llm-confidence** | LLM が抽出時に自己報告する確信度 | Ollama (extract_claims) | `claims.claim_confidence` | 現状: 保存のみ、未使用 |
| **nli-confidence** | NLI モデルが証拠関係を判定した確信度 | DeBERTa-v3 (nli_judge) | `edges.nli_confidence` | ベイズ更新の入力 |
| **bayesian-confidence** | 全証拠を集約した主張の信頼度 | `calculate_claim_confidence()` | 計算値（非永続） | レポート、UI 表示 |

### 1.2 意味論的な違い

```
┌─────────────────────────────────────────────────────────────────────┐
│  llm-confidence                                                     │
│  ├── 問い: 「この抽出は正しいか？」                                  │
│  ├── 性質: 抽出品質の自己評価                                        │
│  ├── 校正可能性: 低（LoRA 非現実的、サンプル/コスト問題）            │
│  └── 現状: 保存されるが使われない                                    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  nli-confidence                                                     │
│  ├── 問い: 「Fragment は Claim を支持/反論するか？」                 │
│  ├── 性質: 証拠関係の判定確率                                        │
│  ├── 校正可能性: 高（Platt/Temperature scaling, LoRA 対応）          │
│  └── 現状: ベイズ更新で使用                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  bayesian-confidence                                                │
│  ├── 問い: 「この主張は真か？」                                      │
│  ├── 性質: Beta 分布の期待値                                         │
│  ├── 計算: alpha / (alpha + beta)                                   │
│  └── 現状: get_materials(), レポート生成で使用                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 現在のアーキテクチャ

### 2.1 データフロー

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LLM Extraction                              │
│  Ollama + extract_claims.j2                                         │
│  └── 出力: {"claim": "...", "confidence": 0.9}                      │
│                              │                                      │
│                              ▼                                      │
│            executor.py:723   claim.get("confidence", 0.5)           │
│                              │                                      │
│                              ▼                                      │
│            DB: claims.claim_confidence ─────────【llm-confidence】  │
│                              │                                      │
│                              │  ┌───────────────────────────────┐   │
│                              │  │ executor.py:928               │   │
│                              │  │ "We intentionally do NOT use  │   │
│                              │  │  LLM-extracted confidence"    │   │
│                              │  └───────────────────────────────┘   │
│                              ▼                                      │
│                         【未使用】                                   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         NLI Judgment                                │
│  DeBERTa-v3 (nli_judge)                                             │
│  └── 入力: (fragment_text, claim_text)                              │
│  └── 出力: {"label": "supports", "confidence": 0.85}                │
│                              │                                      │
│                              ▼                                      │
│            DB: edges.nli_confidence ────────────【nli-confidence】  │
│                              │                                      │
│                              ▼                                      │
│            evidence_graph.py:405-408                                │
│            if relation == "supports":                               │
│                alpha += nli_confidence                              │
│            elif relation == "refutes":                              │
│                beta += nli_confidence                               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      Bayesian Aggregation                           │
│  evidence_graph.py:calculate_claim_confidence()                     │
│                                                                     │
│  Prior: Beta(1, 1) ── 無情報事前分布                                │
│            │                                                        │
│            ▼                                                        │
│  Update: alpha += Σ(nli_confidence for supports)                    │
│          beta  += Σ(nli_confidence for refutes)                     │
│            │                                                        │
│            ▼                                                        │
│  Posterior: bayesian-confidence = alpha / (alpha + beta)            │
│             uncertainty = sqrt(variance)                            │
│             controversy = min(α-1, β-1) / total                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 現設計の問題点

| 問題 | 詳細 |
|------|------|
| **用語の衝突** | `confidence` が3つの異なる意味で使用 |
| **無駄な処理** | LLM に confidence を聞くが使わない |
| **誤解を招く DB** | `claim_confidence` が存在するが意味不明 |
| **calibration.py の曖昧さ** | NLI 用だが名前が汎用的 |

---

## 3. 提案: 設計の明確化

### 3.1 リネーム提案

| 現在 | 提案 | 理由 |
|------|------|------|
| `src/utils/calibration.py` | `src/utils/nli_calibration.py` | NLI 専用であることを明示 |
| `calibration_metrics` (MCP) | `nli_calibration_metrics` | 同上 |
| `calibration_rollback` (MCP) | `nli_calibration_rollback` | 同上 |

### 3.2 llm-confidence の扱い

#### Option A: 削除（シンプル）

```python
# extract_claims.j2 から confidence フィールドを削除
{"claim": "主張の内容", "type": "fact|opinion|prediction"}

# claims.claim_confidence は deprecated 扱い
```

**Pros:** シンプル、誤解なし
**Cons:** 将来の拡張性を失う

#### Option B: フィルタ用（品質ゲート）

```python
# 低 confidence 抽出は破棄
if claim.get("confidence", 0.5) < 0.3:
    continue  # 抽出品質が低い
```

**Pros:** 抽出品質の向上
**Cons:** LLM confidence の校正が必要（困難）

#### Option C: 弱い事前分布（推奨）

```python
# evidence_graph.py:calculate_claim_confidence()

# 現在: 無情報事前分布
alpha = 1.0
beta = 1.0

# 提案: llm-confidence を弱い事前分布として使用
llm_conf = self._get_llm_confidence(claim_id)  # 0.0-1.0
prior_strength = 0.5  # 弱いウェイト（NLI より弱く）
alpha = 1.0 + llm_conf * prior_strength
beta = 1.0 + (1 - llm_conf) * prior_strength
```

**Pros:**
- 既存データを活用
- NLI 証拠がない場合のヒント
- NLI 証拠が増えれば prior は wash out される

**Cons:**
- 複雑さが増す
- llm-confidence の校正がなくても影響は軽微だが、校正があればベター

---

## 4. calibration.py の現状と役割

### 4.1 現在の実装（NLI 専用）

```python
# src/utils/calibration.py (1700+ lines)

# 対象モデル
source: str = ""  # e.g., "nli_judge", "llm_extract"

# 手法
- Platt Scaling (logistic regression)
- Temperature Scaling

# 評価指標
- Brier Score
- ECE (Expected Calibration Error)

# 機能
- 自動劣化検知 + ロールバック
- パラメータ履歴管理
- MCP ツール統合
```

### 4.2 リネーム後の構成

```
src/utils/
├── nli_calibration.py      # 現 calibration.py をリネーム
│   ├── Calibrator
│   ├── PlattScaling
│   ├── TemperatureScaling
│   └── nli_calibration_metrics_action()
│
└── (将来) llm_confidence_prior.py  # Option C 実装時
    └── get_llm_confidence_prior()
```

### 4.3 MCP ツールのリネーム

```python
# src/mcp/server.py

# 現在
Tool(name="calibration_metrics", ...)
Tool(name="calibration_rollback", ...)

# 提案
Tool(name="nli_calibration_metrics", ...)
Tool(name="nli_calibration_rollback", ...)
```

**注意:** MCP ツール名の変更はクライアント（Claude）への影響あり。
ADR-0012 (Feedback Tool Design) との整合性を確認する必要あり。

---

## 5. Option C 実装詳細

### 5.1 DB 変更なし

`claims.claim_confidence` は既に存在。追加フィールド不要。

### 5.2 コード変更

#### 5.2.1 `evidence_graph.py` 修正

```python
def calculate_claim_confidence(
    self,
    claim_id: str,
    use_llm_prior: bool = True,  # 新パラメータ
) -> dict[str, Any]:
    """Calculate overall confidence for a claim using Bayesian updating.

    Args:
        claim_id: Claim object ID.
        use_llm_prior: If True, use llm-confidence as weak prior.

    Returns:
        Confidence assessment dict.
    """
    import math

    evidence = self.get_all_evidence(claim_id)

    # === NEW: Get llm-confidence as weak prior ===
    if use_llm_prior:
        llm_conf = self._get_claim_llm_confidence(claim_id)
        prior_strength = 0.5  # Weak weight
        alpha = 1.0 + llm_conf * prior_strength
        beta = 1.0 + (1 - llm_conf) * prior_strength
    else:
        # Original: Uninformative prior Beta(1, 1)
        alpha = 1.0
        beta = 1.0

    # ... rest unchanged ...
```

#### 5.2.2 llm-confidence 取得ヘルパー

```python
def _get_claim_llm_confidence(self, claim_id: str) -> float:
    """Get llm-confidence for a claim from DB.

    Returns:
        llm-confidence (0.0-1.0), defaults to 0.5 if not found.
    """
    # claim_id is object ID, need to query claims table
    # For now, return 0.5 (neutral) as placeholder
    # TODO: Implement DB query
    return 0.5
```

### 5.3 影響分析

| 状況 | 現在 | Option C 後 |
|------|------|-------------|
| NLI 証拠なし、llm-conf=0.9 | 0.50 | ~0.55 (weak boost) |
| NLI 証拠なし、llm-conf=0.3 | 0.50 | ~0.45 (weak penalty) |
| NLI 証拠あり (supports x3) | ~0.80 | ~0.80 (prior washed out) |

prior_strength=0.5 では、NLI 証拠が 1-2 件で prior の影響は消える。

---

## 6. 実装ロードマップ

### Phase 1: 用語明確化（ドキュメント）

| タスク | ファイル |
|--------|----------|
| この設計文書の確定 | `docs/confidence-calibration-design.md` |
| ADR-0011 への参照追加 | `docs/adr/0011-lora-fine-tuning.md` |

### Phase 2: リネーム（コード）

| タスク | 現在 | 変更後 |
|--------|------|--------|
| ファイルリネーム | `calibration.py` | `nli_calibration.py` |
| MCP ツールリネーム | `calibration_metrics` | `nli_calibration_metrics` |
| MCP ツールリネーム | `calibration_rollback` | `nli_calibration_rollback` |
| import 更新 | 全参照箇所 | - |

### Phase 3: Option C 実装（機能追加）

| タスク | ファイル |
|--------|----------|
| `_get_claim_llm_confidence()` 実装 | `evidence_graph.py` |
| `calculate_claim_confidence()` 修正 | `evidence_graph.py` |
| ユニットテスト追加 | `tests/filter/test_evidence_graph.py` |

### Phase 4: プロンプト整理

| タスク | ファイル |
|--------|----------|
| confidence フィールドの意図を明確化 | `extract_claims.j2` |
| または削除検討 | - |

---

## 7. 決定事項（TBD）

- [ ] Option C を採用するか
- [ ] prior_strength の値（0.3? 0.5? 1.0?）
- [ ] MCP ツールリネームのタイミング
- [ ] llm-confidence を将来削除するか維持するか

---

## Appendix: 関連コード参照

| 概念 | ファイル | 行 |
|------|----------|-----|
| llm-confidence 生成 | `config/prompts/extract_claims.j2` | 9 |
| llm-confidence 保存 | `src/research/executor.py` | 723, 910-919 |
| nli-confidence 生成 | `src/filter/nli.py` | 192 |
| nli-confidence 保存 | `src/filter/evidence_graph.py` | add_claim_evidence() |
| bayesian-confidence 計算 | `src/filter/evidence_graph.py` | 344-459 |
| calibration 実装 | `src/utils/calibration.py` | 全体 |
