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

### 4.4 Missing: Confidence Calibration

**Current state:** LLM self-reports confidence without calibration.

**Problem:** LLM confidence is often poorly calibrated.

**Proposed: Post-hoc calibration**

```python
def calibrate_confidence(raw_confidence: float, task: str) -> float:
    """Apply task-specific calibration curve."""
    # Based on empirical validation data
    calibration_curves = {
        "extract_facts": lambda x: x * 0.8,  # LLM overconfident
        "extract_claims": lambda x: x * 0.85,
        "relevance": lambda x: x,  # Well-calibrated
    }
    return calibration_curves.get(task, lambda x: x)(raw_confidence)
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

### Phase 4: Advanced Features (Long-term)

| Task | Description | Effort |
|------|-------------|--------|
| Confidence calibration | Empirical validation + calibration curves | 8h |
| A/B testing framework | Compare prompt variants | 8h |
| Prompt versioning system | Track prompt changes with metrics | 4h |

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
