# Prompt Template Review and Improvement Proposals

**Date:** 2025-12-27
**Status:** Draft
**Related:** ADR-0005 (LLM Security), `config/prompts/*.j2`, `src/filter/llm_security.py`

---

## Executive Summary

This document reviews all 16 prompt templates in Lyra and the LLM output validation mechanisms. Key findings:

1. **Prompt Quality:** Varies from A (excellent) to D (needs major work)
2. **Language Inconsistency:** Mix of Japanese and English across templates
3. **Output Validation:** Robust for security (ADR-0005), but weak for format enforcement
4. **Retry Mechanism:** Fallback exists, but no structured retry with feedback

---

## Part 1: Prompt Template Inventory

### 1.1 Jinja2 Templates (`config/prompts/*.j2`)

| File | Purpose | Language | Rating | Priority |
|------|---------|----------|--------|----------|
| `extract_facts.j2` | Extract objective facts | JP | C | High |
| `extract_claims.j2` | Extract claims with context | JP | C | High |
| `summarize.j2` | Text summarization | JP | D | Critical |
| `translate.j2` | Translation | JP | D | Medium |
| `decompose.j2` | Atomic claim decomposition | JP | B | Low |
| `detect_citation.j2` | Citation vs navigation link | JP | B | Low |
| `relevance_evaluation.j2` | Citation relevance 0-10 | JP | A | - |

### 1.2 Python Inline Prompts

| Location | Variable | Purpose | Language | Rating |
|----------|----------|---------|----------|--------|
| `src/extractor/quality_analyzer.py:133` | `LLM_QUALITY_ASSESSMENT_PROMPT` | Content quality | EN | B |
| `src/extractor/quality_analyzer.py:156` | `LLM_QUALITY_ASSESSMENT_PROMPT_EN` | Content quality (EN) | EN | B |
| `src/report/chain_of_density.py:194` | `INITIAL_SUMMARY_PROMPT` | CoD initial summary | EN | B |
| `src/report/chain_of_density.py:220` | `DENSIFY_PROMPT` | CoD densification | EN/JP mixed | C |
| `src/filter/llm.py:345` | `EXTRACT_FACTS_INSTRUCTION` | Leakage detection | EN | - |
| `src/filter/llm.py:350` | `EXTRACT_CLAIMS_INSTRUCTION` | Leakage detection | EN | - |
| `src/filter/llm.py:354` | `SUMMARIZE_INSTRUCTION` | Leakage detection | EN | - |
| `src/filter/llm.py:356` | `TRANSLATE_INSTRUCTION` | Leakage detection | EN | - |
| `src/extractor/citation_detector.py:29` | `_DETECT_CITATION_INSTRUCTIONS` | YES/NO instruction | JP | - |

---

## Part 2: Individual Prompt Reviews

### 2.1 `extract_facts.j2` — Rating: C

**Current:**
```
あなたは情報抽出の専門家です。以下のテキストから客観的な事実を抽出してください。

テキスト:
{{ text }}

抽出した事実をJSON配列形式で出力してください。各事実は以下の形式で:
{"fact": "事実の内容", "confidence": 0.0-1.0の信頼度}

事実のみを出力し、意見や推測は含めないでください。
```

**Issues:**
- No definition of "fact" (verifiable statement? observation?)
- No criteria for confidence scoring
- No output count limit (token waste risk)
- No few-shot examples
- No evidence type classification

**Proposed Revision:**
```jinja2
You are an expert in information extraction for academic research.

## Task
Extract verifiable factual statements from the text below.

## Definition of "Fact"
- Empirically verifiable claims (not opinions or predictions)
- Contains specific entities (names, numbers, dates, locations)
- Can be traced to a primary source

## Input
{{ text }}

## Output Requirements
- Return 3-10 most important facts as JSON array
- Each fact: {"fact": "...", "confidence": 0.0-1.0, "evidence_type": "statistic|citation|observation"}
- Confidence criteria:
  - 1.0: Directly stated with explicit source
  - 0.7-0.9: Stated clearly without source
  - 0.5-0.6: Implied or paraphrased
  - 0.3-0.4: Inferred from context

## Example
[{"fact": "DPP-4 inhibitors reduced HbA1c by 0.5-1.0%", "confidence": 0.9, "evidence_type": "statistic"}]

Output JSON array only:
```

---

### 2.2 `extract_claims.j2` — Rating: C

**Current:**
```
あなたは情報分析の専門家です。以下のテキストから主張を抽出してください。

リサーチクエスチョン: {{ context }}

テキスト:
{{ text }}

抽出した主張をJSON配列形式で出力してください。各主張は以下の形式で:
{"claim": "主張の内容", "type": "fact|opinion|prediction", "confidence": 0.0-1.0}
```

**Issues:**
- Research question (`context`) usage unclear
- Claim type taxonomy too simple (fact/opinion/prediction)
- No relevance scoring to query
- No granularity specification

**Proposed Revision:**
```jinja2
You are a research analyst extracting claims relevant to a specific research question.

## Research Question
{{ context }}

## Source Text
{{ text }}

## Task
Extract claims that directly help answer the research question above.

## Claim Types
- factual: Verifiable statement about current/past state
- causal: Asserts cause-effect relationship (X causes Y)
- comparative: Compares entities/quantities (A > B)
- predictive: Future-oriented claim
- normative: Value judgment or recommendation

## Output
JSON array with 1-5 most relevant claims:
{
  "claim": "claim text",
  "type": "factual|causal|comparative|predictive|normative",
  "relevance_to_query": 0.0-1.0,
  "confidence": 0.0-1.0
}

Prioritize claims that:
1. Directly address the research question
2. Contain specific, verifiable information
3. Are supported by evidence in the text

Output JSON array only:
```

---

### 2.3 `summarize.j2` — Rating: D (Critical)

**Current:**
```
以下のテキストを要約してください。重要なポイントを簡潔にまとめてください。

テキスト:
{{ text }}

要約:
```

**Issues:**
- Extremely generic instructions
- No output length specification
- No structured output
- No purpose specification
- No entity preservation guidance

**Proposed Revision:**
```jinja2
You are a research summarizer for evidence synthesis.

## Input Text
{{ text }}

## Task
Create a structured summary preserving key evidence.

## Requirements
- Length: {{ max_words | default(100) }} words maximum
- Focus: Claims, findings, and their supporting evidence
- Preserve: Specific numbers, dates, source attributions
- Exclude: Background context, methodology details (unless critical)

## Output Format
{
  "summary": "Concise summary text",
  "key_claims": ["claim1", "claim2", ...],
  "key_statistics": ["stat1", "stat2", ...],
  "word_count": <number>
}

Output JSON only:
```

---

### 2.4 `translate.j2` — Rating: D

**Current:**
```
以下のテキストを{{ target_lang }}に翻訳してください。

テキスト:
{{ text }}

翻訳:
```

**Issues:**
- No handling for technical/medical terminology
- No guidance for proper nouns
- No precision requirements for numbers

**Proposed Revision:**
```jinja2
You are a professional translator specializing in academic and medical texts.

## Source Text
{{ text }}

## Target Language
{{ target_lang }}

## Translation Guidelines
- Preserve technical/medical terminology accurately
- Keep proper nouns (drug names, study names) in original form
  - Add translation in parentheses if helpful: "sitagliptin (シタグリプチン)"
- Maintain numerical precision (doses, percentages, p-values)
- Preserve citation markers [1], [2], etc.
- Do not add or remove information

## Output
Translated text only (no explanations or notes):
```

---

### 2.5 `decompose.j2` — Rating: B (Good)

**Strengths:**
- Detailed schema definition
- Few-shot example provided
- Clear constraints

**Minor Issues:**
- Hard-coded Japanese output
- `hints` field is vague

**Proposed Addition:**
```jinja2
{# Add to existing template #}

## Additional Guidance for hints
hints should specify concrete source types:
- Good: "PubMed RCTs", "FDA approval documents", "Cochrane reviews"
- Bad: "search online", "check news"

## Output Language
{{ output_lang | default("Japanese") }}
```

---

### 2.6 `detect_citation.j2` — Rating: B

**Strengths:**
- Clear YES/NO output
- Specific exclusion criteria

**Minor Issues:**
- Missing academic citation patterns

**Proposed Addition:**
```jinja2
{# Add to existing criteria #}

Academic citation indicators (high confidence):
- DOI links (doi.org/10.xxxx/...)
- PubMed links (pubmed.ncbi.nlm.nih.gov/...)
- arXiv links (arxiv.org/abs/...)
- Reference markers: [1], [2], (Smith et al., 2023)
- Academic phrases: "et al.", "Fig.", "Table", "Supplementary"
```

---

### 2.7 `relevance_evaluation.j2` — Rating: A (Excellent)

**Strengths:**
- Clear 0-10 scale with specific criteria
- Explicit exclusion of SUPPORTS/REFUTES judgment
- Well-defined "usefulness" evaluation axis

**No changes needed.** This is the reference template for quality.

---

### 2.8 `DENSIFY_PROMPT` — Rating: C

**Issue:** Mixed language (English body + Japanese footer)

**Current:**
```python
# ... English content ...
JSON出力のみを返してください:"""
```

**Fix:** Standardize to English:
```python
# ... English content ...
Return only JSON output:"""
```

---

## Part 3: Output Validation Analysis

### 3.1 Current Validation Mechanisms

| Layer | Mechanism | Location | Coverage |
|-------|-----------|----------|----------|
| **L2** | Input Sanitization | `llm_security.py:237-325` | All LLM inputs |
| **L3** | System Tag Protection | `llm_security.py:192-214` | System prompts |
| **L4** | Output Validation | `llm_security.py:515-607` | All LLM outputs |
| **L7** | Response Sanitization | `response_sanitizer.py` | MCP responses |

### 3.2 JSON Parsing Pattern

**Current approach (all locations):**
```python
# Pattern used across codebase
try:
    json_match = re.search(r"\[.*\]", response, re.DOTALL)  # or r"\{.*\}"
    if json_match:
        parsed = json.loads(json_match.group())
    else:
        parsed = []  # or {}
except json.JSONDecodeError:
    parsed = fallback_value
```

**Files using this pattern:**
- `src/filter/llm.py:474-482`
- `src/filter/claim_decomposition.py:241-295`
- `src/report/chain_of_density.py:663-674`
- `src/extractor/quality_analyzer.py:670-692`

### 3.3 Numeric Score Validation

**0-10 Score (relevance_evaluation):**
```python
# src/search/citation_filter.py:111-122
def _parse_llm_score_0_10(text: str) -> int | None:
    m = _INT_RE.search(text.strip())
    if not m:
        return None
    n = int(m.group(1))
    return max(0, min(10, n))  # Clamp to [0, 10]
```

**0.0-1.0 Score (quality, confidence):**
```python
# Clamp pattern used throughout
score = max(0.0, min(1.0, raw_score))
```

### 3.4 YES/NO Normalization

```python
# src/extractor/citation_detector.py:44-51
def _normalize_yes_no(text: str) -> str | None:
    cleaned = text.strip().upper()
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    if cleaned.startswith("YES"):
        return "YES"
    if cleaned.startswith("NO"):
        return "NO"
    return None
```

### 3.5 Fallback Mechanisms

| Component | Fallback Strategy | Location |
|-----------|------------------|----------|
| Claim Decomposition | Rule-based fallback | `claim_decomposition.py:182-199` |
| Chain-of-Density | Rule-based compression | `chain_of_density.py:538-544` |
| Quality Assessment | Return `None`, use rule-based | `quality_analyzer.py:687-692` |
| Citation Detection | Return `is_citation=False` | `citation_detector.py:161-176` |

---

## Part 4: Gaps and Improvement Proposals

### 4.1 Missing: Structured Retry with Feedback

**Current state:** On parse failure, immediately fall back to rule-based or default value.

**Problem:** LLM might produce correct answer with minor formatting issues.

**Proposed: Retry with correction prompt**

```python
# Proposed retry mechanism
async def parse_with_retry(
    response: str,
    expected_schema: dict,
    max_retries: int = 2,
) -> dict | None:
    """Parse LLM response with retry on format errors."""

    for attempt in range(max_retries + 1):
        try:
            # Attempt extraction
            json_match = re.search(r"[\[{].*[\]}]", response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                # Validate against schema
                if validate_schema(parsed, expected_schema):
                    return parsed

        except json.JSONDecodeError as e:
            if attempt < max_retries:
                # Retry with correction prompt
                response = await llm_call(
                    f"Your previous response had a JSON error: {e}\n"
                    f"Original response: {response[:500]}\n"
                    f"Please output valid JSON matching this schema: {expected_schema}"
                )
            else:
                return None

    return None
```

### 4.2 Missing: Schema Validation

**Current state:** JSON parsed but schema not validated.

**Problem:** Missing fields, wrong types silently accepted.

**Proposed: Add Pydantic models for LLM outputs**

```python
# src/filter/llm_schemas.py (new file)
from pydantic import BaseModel, Field, validator

class ExtractedFact(BaseModel):
    fact: str = Field(..., min_length=10)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_type: str = Field(default="observation")

    @validator("evidence_type")
    def validate_evidence_type(cls, v):
        allowed = {"statistic", "citation", "observation"}
        return v if v in allowed else "observation"

class ExtractedClaim(BaseModel):
    claim: str = Field(..., min_length=10)
    type: str = Field(default="factual")
    relevance_to_query: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
```

### 4.3 Missing: Output Format Enforcement

**Current state:** Prompts say "Output JSON only" but no enforcement.

**Problem:** LLM often adds preamble text before JSON.

**Proposed: Structured output modes**

```python
# For APIs that support it (e.g., OpenAI, Anthropic)
response = await client.messages.create(
    model="claude-3-5-sonnet-20241022",
    messages=[...],
    # Force JSON output
    response_format={"type": "json_object"}
)
```

### 4.4 ~~Missing: Confidence Calibration~~ → 既存実装あり

> **注意**: 信頼度キャリブレーションは `src/utils/calibration.py` に完全実装済み。

**既存実装:**
- Platt Scaling / Temperature Scaling
- Brier Score / ECE (Expected Calibration Error) 評価
- 自動劣化検知 + ロールバック
- 増分再キャリブレーション（サンプル蓄積トリガー）

**MCP ツール:**
- `calibration_metrics(get_stats)`: 現在のパラメータと履歴
- `calibration_metrics(get_evaluations)`: 評価履歴
- `calibration_rollback`: 以前のパラメータへロールバック

**参照:** ADR-0011 (LoRA Fine-tuning Strategy) §Relationship with calibration_metrics

```python
# 既存 API (src/utils/calibration.py)
from src.utils.calibration import get_calibrator

calibrator = get_calibrator()
calibrated_prob = calibrator.calibrate(raw_prob, source="llm_extract")
```

### 4.5 Recommendation: Standardize Prompt Structure

**Proposed template structure:**

```jinja2
{# SECTION 1: Role and Context #}
You are a {{ role }} for {{ purpose }}.

{# SECTION 2: Task Definition #}
## Task
{{ task_description }}

{# SECTION 3: Input #}
## Input
{{ input_variable }}

{# SECTION 4: Constraints (optional) #}
{% if constraints %}
## Constraints
{% for c in constraints %}
- {{ c }}
{% endfor %}
{% endif %}

{# SECTION 5: Output Specification #}
## Output Format
{{ output_schema }}

{# SECTION 6: Examples (optional) #}
{% if examples %}
## Example
{{ examples }}
{% endif %}

{# SECTION 7: Final Instruction #}
Output {{ output_format }} only:
```

---

## Part 5: Implementation Roadmap

### Phase 1: Critical Fixes (Immediate)

| Task | File | Effort |
|------|------|--------|
| Rewrite `summarize.j2` | `config/prompts/summarize.j2` | 1h |
| Rewrite `extract_claims.j2` | `config/prompts/extract_claims.j2` | 1h |
| Fix language mixing in `DENSIFY_PROMPT` | `src/report/chain_of_density.py` | 15m |

### Phase 2: Schema Validation (Short-term)

| Task | File | Effort |
|------|------|--------|
| Create Pydantic models for LLM outputs | `src/filter/llm_schemas.py` (new) | 2h |
| Integrate schema validation in `llm.py` | `src/filter/llm.py` | 2h |
| Add retry mechanism | `src/filter/llm.py` | 3h |

### Phase 3: Prompt Standardization (Medium-term)

| Task | File | Effort |
|------|------|--------|
| Convert all prompts to English | `config/prompts/*.j2` | 2h |
| Add output language parameter | All templates | 1h |
| Create prompt testing framework | `tests/prompts/` (new) | 4h |

### ~~Phase 4: Advanced Features~~ (削除 - 実装済み)

> **注意**: 以下の機能はすべて既存実装済みのため、Phase 4 は不要。

| 当初の提案 | 既存実装 | 参照 |
|------------|----------|------|
| Confidence calibration | ✅ Platt/Temperature scaling, Brier score, 自動ロールバック | `src/utils/calibration.py`, ADR-0011 |
| A/B testing framework | ✅ クエリA/Bテスト (表記/助詞/語順バリアント) | `src/search/ab_test.py`, ADR-0010 |
| Prompt versioning | ✅ git 管理で十分 (専用システム不要) | `config/prompts/*.j2` |

**MCP ツール (既存):**
- `calibration_metrics`: 統計取得、評価履歴
- `calibration_rollback`: パラメータロールバック

---

## Part 6: Phase 2 Detailed Technical Design

**Date Added:** 2025-12-27
**Status:** Proposal

This section provides a detailed technical design for Phase 2 (Schema Validation & Retry Mechanism), aligned with Lyra's existing architecture.

---

### 6.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM Output Pipeline                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  Prompt  │───▶│  LLM Call    │───▶│  Security Validation │  │
│  │ Template │    │  (Provider)  │    │  (validate_llm_output)│  │
│  └──────────┘    └──────────────┘    └──────────┬───────────┘  │
│                                                  │              │
│                                                  ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 NEW: Schema Validation Layer              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │  │
│  │  │ JSON Extract│─▶│ Pydantic    │─▶│ Retry w/Feedback│   │  │
│  │  │ (regex)     │  │ Validation  │  │ (max 2 retries) │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                  │              │
│                                                  ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Existing Fallback                      │  │
│  │              (Rule-based / Default Value)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 6.2 New File: `src/filter/llm_schemas.py`

Pydantic models for LLM outputs, aligned with existing type conventions.

```python
"""
Pydantic schemas for LLM output validation.

These schemas define the expected structure of LLM outputs for various tasks.
They integrate with the existing type system:
- ClaimType, ClaimPolarity, ClaimGranularity from claim_decomposition.py
- EvidenceItem, ClaimConfidenceAssessment from schemas.py
- RelationType from evidence_graph.py
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Enums (reuse from existing modules where possible)
# =============================================================================

class EvidenceType(str, Enum):
    """Type of evidence supporting a fact."""
    STATISTIC = "statistic"      # Numerical data, percentages, p-values
    CITATION = "citation"        # Reference to another source
    OBSERVATION = "observation"  # Direct observation or statement
    EXPERIMENT = "experiment"    # Experimental result
    EXPERT = "expert"            # Expert opinion/statement


class ClaimTypeExtended(str, Enum):
    """Extended claim type taxonomy (superset of ClaimType)."""
    FACTUAL = "factual"
    CAUSAL = "causal"
    COMPARATIVE = "comparative"
    PREDICTIVE = "predictive"
    NORMATIVE = "normative"
    DEFINITIONAL = "definitional"
    TEMPORAL = "temporal"
    QUANTITATIVE = "quantitative"


# =============================================================================
# Extract Facts Output Schema
# =============================================================================

class ExtractedFact(BaseModel):
    """Single fact extracted from text.

    Corresponds to extract_facts.j2 output.
    """
    fact: str = Field(..., min_length=10, description="Factual statement")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score"
    )
    evidence_type: EvidenceType = Field(
        default=EvidenceType.OBSERVATION,
        description="Type of evidence"
    )

    @field_validator("evidence_type", mode="before")
    @classmethod
    def normalize_evidence_type(cls, v: Any) -> EvidenceType:
        if isinstance(v, str):
            v = v.lower().strip()
            try:
                return EvidenceType(v)
            except ValueError:
                return EvidenceType.OBSERVATION
        return v


class ExtractFactsResponse(BaseModel):
    """Response from extract_facts task."""
    facts: list[ExtractedFact] = Field(
        default_factory=list,
        max_length=20,  # Prevent token waste
        description="Extracted facts"
    )

    @model_validator(mode="after")
    def deduplicate_facts(self) -> "ExtractFactsResponse":
        """Remove near-duplicate facts."""
        seen = set()
        unique = []
        for fact in self.facts:
            # Simple dedup by first 50 chars
            key = fact.fact[:50].lower()
            if key not in seen:
                seen.add(key)
                unique.append(fact)
        self.facts = unique
        return self


# =============================================================================
# Extract Claims Output Schema
# =============================================================================

class ExtractedClaim(BaseModel):
    """Single claim extracted from text.

    Corresponds to extract_claims.j2 output.
    Direct field names - no aliases needed (DB rebuilt).
    """
    claim_text: str = Field(..., min_length=10, description="Claim text")
    claim_type: ClaimTypeExtended = Field(
        default=ClaimTypeExtended.FACTUAL,
        description="Claim type"
    )
    claim_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score"
    )
    relevance_to_query: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relevance to research question"
    )

    @field_validator("claim_type", mode="before")
    @classmethod
    def normalize_claim_type(cls, v: Any) -> ClaimTypeExtended:
        if isinstance(v, str):
            v = v.lower().strip()
            # Map legacy types
            legacy_map = {
                "fact": "factual",
                "opinion": "normative",
                "prediction": "predictive",
            }
            v = legacy_map.get(v, v)
            try:
                return ClaimTypeExtended(v)
            except ValueError:
                return ClaimTypeExtended.FACTUAL
        return v


class ExtractClaimsResponse(BaseModel):
    """Response from extract_claims task."""
    claims: list[ExtractedClaim] = Field(
        default_factory=list,
        max_length=10,  # Limit per extract_claims.j2 proposal
        description="Extracted claims"
    )


# =============================================================================
# Summarize Output Schema
# =============================================================================

class SummaryResponse(BaseModel):
    """Structured summary response.

    Corresponds to proposed summarize.j2 output.
    """
    summary: str = Field(..., min_length=20, description="Summary text")
    key_claims: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key claims extracted"
    )
    key_statistics: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key statistics extracted"
    )
    word_count: int = Field(default=0, ge=0, description="Word count")

    @model_validator(mode="after")
    def compute_word_count(self) -> "SummaryResponse":
        if self.word_count == 0:
            self.word_count = len(self.summary.split())
        return self


# =============================================================================
# Quality Assessment Output Schema
# =============================================================================

class QualityAssessmentResponse(BaseModel):
    """LLM quality assessment response.

    Corresponds to LLM_QUALITY_ASSESSMENT_PROMPT output.
    """
    quality_score: float = Field(..., ge=0.0, le=1.0)
    is_ai_generated: bool = Field(default=False)
    is_spam: bool = Field(default=False)
    is_aggregator: bool = Field(default=False)
    reason: str = Field(default="", max_length=500)

    @field_validator("quality_score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> float:
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        return 0.5  # Default on parse error


# =============================================================================
# Relevance Score Output Schema
# =============================================================================

class RelevanceScoreResponse(BaseModel):
    """Relevance evaluation response (0-10 scale).

    Corresponds to relevance_evaluation.j2 output.
    """
    score: int = Field(..., ge=0, le=10)

    @field_validator("score", mode="before")
    @classmethod
    def parse_and_clamp(cls, v: Any) -> int:
        if isinstance(v, str):
            # Extract first integer from string
            import re
            match = re.search(r"\d+", v)
            if match:
                v = int(match.group())
            else:
                return 5  # Default
        if isinstance(v, (int, float)):
            return max(0, min(10, int(v)))
        return 5

    @property
    def normalized(self) -> float:
        """Return normalized 0.0-1.0 score."""
        return self.score / 10.0


# =============================================================================
# Chain-of-Density Output Schema
# =============================================================================

class DensityClaim(BaseModel):
    """Claim with source indices for CoD."""
    text: str = Field(..., min_length=5)
    source_indices: list[int] = Field(default_factory=list)


class DensitySummaryResponse(BaseModel):
    """Chain-of-Density summary response.

    Corresponds to INITIAL_SUMMARY_PROMPT / DENSIFY_PROMPT output.
    """
    summary: str = Field(..., min_length=20)
    entities: list[str] = Field(default_factory=list, max_length=50)
    claims: list[DensityClaim] = Field(default_factory=list)


# =============================================================================
# Citation Detection Output Schema
# =============================================================================

class CitationDetectionResponse(BaseModel):
    """Citation detection response.

    Corresponds to detect_citation.j2 output.
    """
    is_citation: bool = Field(...)

    @field_validator("is_citation", mode="before")
    @classmethod
    def parse_yes_no(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v = v.strip().upper()
            # Remove non-alpha characters
            import re
            v = re.sub(r"[^A-Z]", "", v)
            return v.startswith("YES")
        return False


# =============================================================================
# Decomposition Output Schema
# =============================================================================

class DecomposedClaim(BaseModel):
    """Atomic claim from decomposition.

    Corresponds to decompose.j2 output.
    Aligned with AtomicClaim dataclass.
    """
    text: str = Field(..., min_length=10)
    polarity: Literal["positive", "negative", "neutral"] = Field(
        default="neutral"
    )
    granularity: Literal["atomic", "composite", "meta"] = Field(
        default="atomic"
    )
    type: str = Field(default="factual")
    keywords: list[str] = Field(default_factory=list, max_length=10)
    hints: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

    @field_validator("polarity", mode="before")
    @classmethod
    def normalize_polarity(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("positive", "negative", "neutral"):
                return v
        return "neutral"

    @field_validator("granularity", mode="before")
    @classmethod
    def normalize_granularity(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("atomic", "composite", "meta"):
                return v
        return "atomic"


class DecomposeResponse(BaseModel):
    """Response from decompose task."""
    claims: list[DecomposedClaim] = Field(
        default_factory=list,
        max_length=20,
        description="Decomposed atomic claims"
    )


# =============================================================================
# Schema Registry
# =============================================================================

TASK_SCHEMAS: dict[str, type[BaseModel]] = {
    "extract_facts": ExtractFactsResponse,
    "extract_claims": ExtractClaimsResponse,
    "summarize": SummaryResponse,
    "quality_assessment": QualityAssessmentResponse,
    "relevance_evaluation": RelevanceScoreResponse,
    "chain_of_density": DensitySummaryResponse,
    "detect_citation": CitationDetectionResponse,
    "decompose": DecomposeResponse,
}


def get_schema_for_task(task: str) -> type[BaseModel] | None:
    """Get Pydantic schema for a given task."""
    return TASK_SCHEMAS.get(task)
```

---

### 6.3 New File: `src/filter/llm_output_parser.py`

Unified parsing with retry mechanism.

```python
"""
LLM output parser with schema validation and retry mechanism.

Integrates with:
- llm_security.py for security validation
- llm_schemas.py for schema validation
- provider.py for LLM calls
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import structlog

from pydantic import BaseModel, ValidationError

from .llm_schemas import TASK_SCHEMAS, get_schema_for_task
from .llm_security import validate_llm_output
from .provider import LLMOptions, LLMResponse, default_provider

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class ParseStatus(str, Enum):
    """Status of parse attempt."""
    SUCCESS = "success"
    JSON_ERROR = "json_error"
    SCHEMA_ERROR = "schema_error"
    EMPTY_RESPONSE = "empty_response"
    RETRY_EXHAUSTED = "retry_exhausted"


@dataclass
class ParseResult:
    """Result of LLM output parsing."""
    status: ParseStatus
    data: BaseModel | None = None
    raw_response: str = ""
    errors: list[str] = field(default_factory=list)
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.status == ParseStatus.SUCCESS and self.data is not None


# =============================================================================
# JSON Extraction
# =============================================================================

def extract_json(text: str, expect_array: bool = False) -> dict | list | None:
    """Extract JSON from LLM response text.

    Handles common LLM output patterns:
    - Pure JSON
    - JSON wrapped in markdown code blocks
    - JSON preceded by explanatory text

    Args:
        text: Raw LLM response
        expect_array: If True, extract JSON array; otherwise JSON object

    Returns:
        Parsed JSON or None if extraction fails
    """
    if not text or not text.strip():
        return None

    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Pattern for JSON in markdown code blocks
    code_block_pattern = r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern for raw JSON (array or object)
    if expect_array:
        pattern = r"\[.*\]"
    else:
        pattern = r"\{.*\}"

    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# =============================================================================
# Schema Validation
# =============================================================================

def validate_with_schema(
    data: dict | list,
    schema: type[T],
    task: str,
) -> tuple[T | None, list[str]]:
    """Validate parsed data against Pydantic schema.

    Args:
        data: Parsed JSON data
        schema: Pydantic model class
        task: Task name for error context

    Returns:
        Tuple of (validated model or None, list of error messages)
    """
    errors = []

    try:
        # Handle list vs single object
        if isinstance(data, list):
            # Wrap in container if schema expects it
            if hasattr(schema, "__fields__"):
                # Find the list field name
                for field_name, field_info in schema.model_fields.items():
                    if "list" in str(field_info.annotation).lower():
                        data = {field_name: data}
                        break

        validated = schema.model_validate(data)
        return validated, []

    except ValidationError as e:
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            msg = f"{loc}: {error['msg']}"
            errors.append(msg)
        return None, errors


# =============================================================================
# Retry Mechanism
# =============================================================================

CORRECTION_PROMPT_TEMPLATE = """Your previous response had format issues.

## Errors
{errors}

## Original Response (truncated)
{original_response}

## Required Format
Output must be valid JSON matching this structure:
{schema_example}

## Instructions
1. Fix the format errors listed above
2. Output ONLY valid JSON, no explanations
3. Ensure all required fields are present

Output JSON only:"""


async def retry_with_feedback(
    original_response: str,
    errors: list[str],
    schema: type[BaseModel],
    task: str,
    model: str | None = None,
) -> LLMResponse:
    """Retry LLM call with error feedback.

    Args:
        original_response: The original malformed response
        errors: List of validation errors
        schema: Expected schema
        task: Task name
        model: Optional model override

    Returns:
        New LLM response
    """
    # Generate schema example
    schema_example = schema.model_json_schema()

    # Truncate original response
    truncated = original_response[:500]
    if len(original_response) > 500:
        truncated += "..."

    prompt = CORRECTION_PROMPT_TEMPLATE.format(
        errors="\n".join(f"- {e}" for e in errors[:5]),  # Limit errors
        original_response=truncated,
        schema_example=json.dumps(schema_example, indent=2),
    )

    options = LLMOptions(model=model, temperature=0.1, max_tokens=2000)
    return await default_provider.generate(prompt, options)


# =============================================================================
# Main Parser
# =============================================================================

@dataclass
class ParserConfig:
    """Configuration for LLM output parser."""
    max_retries: int = 2
    enable_security_validation: bool = True
    enable_schema_validation: bool = True
    enable_retry: bool = True
    model: str | None = None


async def parse_llm_output(
    response: str | LLMResponse,
    task: str,
    config: ParserConfig | None = None,
    system_prompt: str | None = None,
) -> ParseResult:
    """Parse and validate LLM output.

    Args:
        response: Raw LLM response text or LLMResponse object
        task: Task name (must match TASK_SCHEMAS key)
        config: Parser configuration
        system_prompt: System prompt for leakage detection

    Returns:
        ParseResult with validated data or error information
    """
    config = config or ParserConfig()

    # Extract text from LLMResponse if needed
    if isinstance(response, LLMResponse):
        if not response.ok:
            return ParseResult(
                status=ParseStatus.EMPTY_RESPONSE,
                errors=[response.error_message or "LLM call failed"],
            )
        raw_text = response.text
    else:
        raw_text = response

    if not raw_text or not raw_text.strip():
        return ParseResult(
            status=ParseStatus.EMPTY_RESPONSE,
            errors=["Empty response from LLM"],
        )

    # Get schema for task
    schema = get_schema_for_task(task)
    if schema is None and config.enable_schema_validation:
        logger.warning(f"No schema defined for task: {task}")
        config.enable_schema_validation = False

    # Security validation (ADR-0005 L4)
    if config.enable_security_validation:
        validation_result = validate_llm_output(
            raw_text,
            system_prompt=system_prompt,
            mask_leakage=True,
        )
        raw_text = validation_result.validated_text

    # Determine if we expect array or object
    expect_array = task in ("extract_facts", "extract_claims", "decompose")

    # Parse loop with retry
    attempts = 0
    errors: list[str] = []

    while attempts <= config.max_retries:
        attempts += 1

        # Step 1: Extract JSON
        parsed = extract_json(raw_text, expect_array=expect_array)

        if parsed is None:
            errors.append(f"Attempt {attempts}: Failed to extract JSON from response")
            if attempts <= config.max_retries and config.enable_retry:
                # Retry with feedback
                retry_response = await retry_with_feedback(
                    raw_text,
                    ["Could not find valid JSON in response"],
                    schema or BaseModel,
                    task,
                    config.model,
                )
                if retry_response.ok:
                    raw_text = retry_response.text
                    continue

            return ParseResult(
                status=ParseStatus.JSON_ERROR,
                raw_response=raw_text,
                errors=errors,
                attempts=attempts,
            )

        # Step 2: Schema validation (if enabled)
        if config.enable_schema_validation and schema:
            validated, validation_errors = validate_with_schema(parsed, schema, task)

            if validated is None:
                errors.extend(f"Attempt {attempts}: {e}" for e in validation_errors)

                if attempts <= config.max_retries and config.enable_retry:
                    # Retry with validation errors
                    retry_response = await retry_with_feedback(
                        raw_text,
                        validation_errors,
                        schema,
                        task,
                        config.model,
                    )
                    if retry_response.ok:
                        raw_text = retry_response.text
                        continue

                return ParseResult(
                    status=ParseStatus.SCHEMA_ERROR,
                    raw_response=raw_text,
                    errors=errors,
                    attempts=attempts,
                )

            # Success with schema validation
            return ParseResult(
                status=ParseStatus.SUCCESS,
                data=validated,
                raw_response=raw_text,
                attempts=attempts,
            )

        # Success without schema validation (return raw parsed data)
        # Wrap in a generic model for consistency
        return ParseResult(
            status=ParseStatus.SUCCESS,
            data=None,  # No schema, so no model
            raw_response=raw_text,
            attempts=attempts,
        )

    # Exhausted retries
    return ParseResult(
        status=ParseStatus.RETRY_EXHAUSTED,
        raw_response=raw_text,
        errors=errors,
        attempts=attempts,
    )


# =============================================================================
# Convenience Functions
# =============================================================================

async def extract_facts(
    text: str,
    model: str | None = None,
) -> ParseResult:
    """Extract facts from text with validation."""
    from .llm import render_prompt

    prompt = render_prompt("extract_facts", text=text[:4000])
    options = LLMOptions(model=model, temperature=0.1)
    response = await default_provider.generate(prompt, options)

    return await parse_llm_output(
        response,
        task="extract_facts",
        config=ParserConfig(model=model),
    )


async def extract_claims(
    text: str,
    context: str = "",
    model: str | None = None,
) -> ParseResult:
    """Extract claims from text with validation."""
    from .llm import render_prompt

    prompt = render_prompt(
        "extract_claims",
        text=text[:4000],
        context=context or "General research",
    )
    options = LLMOptions(model=model, temperature=0.1)
    response = await default_provider.generate(prompt, options)

    return await parse_llm_output(
        response,
        task="extract_claims",
        config=ParserConfig(model=model),
    )
```

---

### 6.4 Integration Points

#### 6.4.1 Replace `src/filter/llm.py` parsing

```python
# Delete lines 474-482 (legacy regex parsing)
# Replace with:

from .llm_output_parser import parse_llm_output, ParserConfig

async def _process_extraction(
    response_text: str,
    task: str,
    passage_id: str,
    source_url: str,
) -> dict:
    """Process extraction with schema validation.

    On parse failure after retries: logs error, returns empty result, continues processing.
    """
    result = await parse_llm_output(response_text, task=task)

    if result.ok:
        if task == "extract_facts":
            extracted = [f.model_dump() for f in result.data.facts]
        elif task == "extract_claims":
            extracted = [c.model_dump() for c in result.data.claims]
        else:
            extracted = result.data.model_dump()
        return {
            "id": passage_id,
            "source_url": source_url,
            "extracted": extracted,
        }
    else:
        # Log error and continue with empty result
        logger.warning(
            "LLM parse failed after retries",
            task=task,
            passage_id=passage_id,
            attempts=result.attempts,
            errors=result.errors,
        )
        return {
            "id": passage_id,
            "source_url": source_url,
            "extracted": [],
            "parse_errors": result.errors,
        }
```

#### 6.4.2 Replace `src/filter/claim_decomposition.py`

```python
# Delete _parse_llm_response() method (lines 241-295)
# Replace with:

from .llm_output_parser import parse_llm_output

async def _parse_llm_response(self, response: str, source_question: str) -> list[AtomicClaim]:
    """Parse LLM response with schema validation.

    On parse failure after retries: logs error, returns empty list, continues processing.
    """
    result = await parse_llm_output(response, task="decompose")

    if not result.ok:
        logger.warning(
            "Decomposition parse failed after retries",
            source_question=source_question[:100],
            attempts=result.attempts,
            errors=result.errors,
        )
        return []  # Return empty list, continue processing

    return [
        AtomicClaim(
            claim_id=f"claim_{uuid.uuid4().hex[:8]}",
            text=item.text,
            expected_polarity=ClaimPolarity(item.polarity),
            granularity=ClaimGranularity(item.granularity),
            claim_type=ClaimType(item.type),
            source_question=source_question,
            confidence=item.confidence,
            keywords=item.keywords,
            verification_hints=item.hints,
        )
        for item in result.data.claims
    ]
```

#### 6.4.3 Replace `src/search/citation_filter.py`

```python
# Delete _parse_llm_score_0_10() function (lines 111-122)
# Replace with:

from src.filter.llm_output_parser import parse_llm_output

async def _evaluate_relevance(response_text: str, source_url: str = "") -> float:
    """Evaluate relevance with schema validation.

    On parse failure after retries: logs error, returns default score (0.5), continues processing.
    """
    result = await parse_llm_output(response_text, task="relevance_evaluation")

    if not result.ok:
        logger.warning(
            "Relevance parse failed after retries",
            source_url=source_url,
            attempts=result.attempts,
            errors=result.errors,
        )
        return 0.5  # Return neutral score, continue processing

    return result.data.normalized  # 0.0-1.0
```

---

### 6.5 Database Alignment (Direct Mapping)

No aliases needed - field names match DB columns directly:

| Pydantic Field | DB Column | Type |
|----------------|-----------|------|
| `claim_text` | `claim_text` | TEXT |
| `claim_type` | `claim_type` | TEXT (enum string) |
| `claim_confidence` | `claim_confidence` | REAL |
| `relevance_to_query` | `relevance_to_query` | REAL (NEW) |
| `expected_polarity` | `expected_polarity` | TEXT |
| `granularity` | `granularity` | TEXT |

**New columns to add:**
- `claims.relevance_to_query REAL DEFAULT 0.5`
- `claims.evidence_type TEXT` (for facts extraction)

---

### 6.6 Testing Strategy

#### Unit Tests (`tests/filter/test_llm_schemas.py`)

```python
import pytest
from pydantic import ValidationError

from src.filter.llm_schemas import (
    ExtractedFact,
    ExtractedClaim,
    ExtractFactsResponse,
    RelevanceScoreResponse,
)


class TestExtractedFact:
    def test_valid_fact(self):
        fact = ExtractedFact(
            fact="DPP-4 inhibitors reduce HbA1c by 0.5-1.0%",
            confidence=0.9,
            evidence_type="statistic",
        )
        assert fact.confidence == 0.9
        assert fact.evidence_type.value == "statistic"

    def test_confidence_clamping(self):
        # Should not allow out-of-range
        with pytest.raises(ValidationError):
            ExtractedFact(fact="test fact here", confidence=1.5)

    def test_evidence_type_normalization(self):
        fact = ExtractedFact(
            fact="test fact here",
            confidence=0.5,
            evidence_type="STATISTIC",  # Uppercase
        )
        assert fact.evidence_type.value == "statistic"

    def test_unknown_evidence_type_defaults(self):
        fact = ExtractedFact(
            fact="test fact here",
            confidence=0.5,
            evidence_type="unknown_type",
        )
        assert fact.evidence_type.value == "observation"


class TestRelevanceScoreResponse:
    def test_parse_integer(self):
        score = RelevanceScoreResponse(score=7)
        assert score.score == 7
        assert score.normalized == 0.7

    def test_parse_string(self):
        score = RelevanceScoreResponse(score="8")
        assert score.score == 8

    def test_parse_with_text(self):
        score = RelevanceScoreResponse(score="Score: 9 out of 10")
        assert score.score == 9

    def test_clamp_high(self):
        score = RelevanceScoreResponse(score=15)
        assert score.score == 10

    def test_clamp_low(self):
        score = RelevanceScoreResponse(score=-5)
        assert score.score == 0
```

#### Integration Tests (`tests/filter/test_llm_output_parser.py`)

```python
import pytest
from src.filter.llm_output_parser import (
    extract_json,
    parse_llm_output,
    ParserConfig,
    ParseStatus,
)


class TestExtractJson:
    def test_pure_json(self):
        result = extract_json('[{"fact": "test", "confidence": 0.9}]')
        assert result == [{"fact": "test", "confidence": 0.9}]

    def test_markdown_code_block(self):
        text = """Here are the facts:
```json
[{"fact": "test", "confidence": 0.9}]
```
"""
        result = extract_json(text, expect_array=True)
        assert result == [{"fact": "test", "confidence": 0.9}]

    def test_with_preamble(self):
        text = """Based on my analysis, here are the extracted facts:
[{"fact": "test", "confidence": 0.9}]
I hope this helps!"""
        result = extract_json(text, expect_array=True)
        assert result == [{"fact": "test", "confidence": 0.9}]


@pytest.mark.asyncio
class TestParseWithRetry:
    async def test_success_first_attempt(self):
        response = '[{"fact": "DPP-4 inhibitors reduce HbA1c", "confidence": 0.9}]'
        result = await parse_llm_output(
            response,
            task="extract_facts",
            config=ParserConfig(enable_retry=False),
        )
        assert result.ok
        assert result.attempts == 1
        assert len(result.data.facts) == 1

    async def test_schema_validation_error(self):
        # Missing required field
        response = '[{"fact": "short"}]'  # Too short, missing confidence
        result = await parse_llm_output(
            response,
            task="extract_facts",
            config=ParserConfig(enable_retry=False),
        )
        assert result.status == ParseStatus.SCHEMA_ERROR
        assert "confidence" in str(result.errors).lower() or "min_length" in str(result.errors).lower()
```

---

### 6.7 Implementation Plan (No Backward Compatibility)

> **Premise:** DB is rebuilt from scratch. No migration needed. Legacy code can be deleted immediately.

#### Single-Phase Implementation

| Step | Task | Files | Delete |
|------|------|-------|--------|
| 1 | Create Pydantic schemas | `src/filter/llm_schemas.py` (new) | - |
| 2 | Create unified parser | `src/filter/llm_output_parser.py` (new) | - |
| 3 | Replace LLM parsing in llm.py | `src/filter/llm.py` | Legacy regex parsing |
| 4 | Replace claim decomposition parsing | `src/filter/claim_decomposition.py` | `_parse_llm_response()` |
| 5 | Replace citation filter parsing | `src/search/citation_filter.py` | `_parse_llm_score_0_10()` |
| 6 | Update DB schema | `src/storage/schema.sql` | - |
| 7 | Add tests | `tests/filter/test_llm_*.py` | - |

#### Simplified Schema (No Aliases)

Since DB is rebuilt, field names can match directly:

```python
class ExtractedClaim(BaseModel):
    """Direct field names matching new DB schema."""
    claim_text: str = Field(..., min_length=10)
    claim_type: ClaimTypeExtended = Field(default=ClaimTypeExtended.FACTUAL)
    claim_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance_to_query: float = Field(default=0.5, ge=0.0, le=1.0)
    # No aliases needed - direct mapping
```

#### DB Schema Changes (`schema.sql`)

```sql
-- claims table: add new columns
ALTER TABLE claims ADD COLUMN relevance_to_query REAL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN evidence_type TEXT;  -- for facts

-- Or simply recreate:
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'factual',  -- Extended enum
    claim_confidence REAL DEFAULT 0.5,
    relevance_to_query REAL DEFAULT 0.5,  -- NEW
    granularity TEXT DEFAULT 'atomic',
    expected_polarity TEXT DEFAULT 'neutral',
    -- ... rest unchanged
);
```

#### Code Deletion List

Remove these legacy patterns:

| File | Lines | Pattern |
|------|-------|---------|
| `llm.py` | 474-482 | `json_match = re.search(r"\[.*\]"...)` |
| `claim_decomposition.py` | 241-295 | `_parse_llm_response()` method |
| `citation_filter.py` | 111-122 | `_parse_llm_score_0_10()` function |
| `quality_analyzer.py` | 670-692 | Inline JSON parsing |
| `chain_of_density.py` | 663-674 | `_parse_llm_response()` |

---

### 6.8 Metrics & Monitoring

```python
# Metrics logged automatically by ParseResult
@dataclass
class ParseMetrics:
    task: str
    status: ParseStatus
    attempts: int
    duration_ms: float
    error_types: list[str]  # JSON_ERROR, SCHEMA_ERROR, etc.

# Aggregate in task_metrics table
llm_parse_metrics = {
    "success_rate": success / total,
    "retry_rate": retried / total,
    "avg_attempts": sum(attempts) / total,
    "error_breakdown": {
        "json_error": json_errors / total,
        "schema_error": schema_errors / total,
    },
}
```

---

## Appendix A: Validation Function Reference

### `validate_llm_output()` — Main Entry Point

**Location:** `src/filter/llm_security.py:515-607`

```python
def validate_llm_output(
    text: str,
    expected_max_length: int | None = None,
    warn_on_suspicious: bool = True,
    system_prompt: str | None = None,
    mask_leakage: bool = True,
) -> OutputValidationResult:
```

**Checks performed:**
1. URL detection (`http://`, `https://`, `ftp://`)
2. IP address detection (IPv4, IPv6)
3. Prompt leakage detection (n-gram matching)
4. Output truncation (10x expected max)
5. Fragment masking (`[REDACTED]`)

### `sanitize_input()` — Input Preprocessing

**Location:** `src/filter/llm_security.py:237-325`

**7-step process:**
1. Unicode NFKC normalization
2. HTML entity decoding
3. Zero-width character removal
4. Control character removal
5. LYRA tag pattern removal
6. Dangerous pattern detection
7. Length limiting

---

## Appendix B: Prompt Quality Checklist

Use this checklist when writing or reviewing prompts:

- [ ] **Role defined:** Clear persona/expertise specified
- [ ] **Task explicit:** One-sentence task description
- [ ] **Input labeled:** Input data clearly delimited
- [ ] **Output schema:** Exact format specified (JSON, plain text)
- [ ] **Constraints listed:** Length limits, count limits, exclusions
- [ ] **Examples provided:** At least one few-shot example for complex tasks
- [ ] **Language consistent:** Single language throughout
- [ ] **Final instruction:** "Output X only:" to reduce preamble
- [ ] **Confidence criteria:** If requesting confidence, define scale
- [ ] **Validation possible:** Output can be programmatically validated
