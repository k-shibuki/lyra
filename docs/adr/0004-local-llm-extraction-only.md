# ADR-0004: Local LLM for Extraction Only

## Date
2025-11-08

## Context

Lyra needs to extract and structure information from web pages. Specific tasks:

| Task | Input | Output |
|------|-------|--------|
| Claim Extraction | Page text + Hypothesis | List of related claims |
| NLI Judgment | Premise text + Hypothesis | SUPPORTS / REFUTES / NEUTRAL |
| Entity Extraction | Text | Names, organizations, dates, etc. |
| Summarization | Long text | Short summary |

LLMs are effective for these tasks, but ADR-0001 (Zero OpEx) constraints prohibit commercial APIs (GPT-4, Claude API).

Additionally, as specified in ADR-0002, **strategic decisions (query design, exploration strategy) are handled by the MCP client**. Having local LLMs handle these would degrade quality.

## Decision

**Use local LLM (Qwen2.5-3B) only for "mechanical extraction and classification tasks."**

### Permitted Tasks

| Task | Model Usage |
|------|-------------|
| NLI Judgment | 3-class classification (SUPPORTS/REFUTES/NEUTRAL) |
| Claim Extraction | Structured output (JSON) |
| Summary Generation | Compression task |

### Prohibited Tasks

| Task | Reason |
|------|--------|
| Search Query Design | MCP client's exclusive domain (ADR-0002) |
| Exploration Strategy Decisions | Requires advanced reasoning |
| Evidence Synthesis Evaluation | Requires complex judgment |
| User Response Generation | MCP client's responsibility |

### Model Selection

| Model | Size | Purpose | Selection Reason |
|-------|------|---------|------------------|
| Qwen2.5-3B-Instruct | 3B | Claim extraction, summarization | Japanese performance, size efficiency |
| DeBERTa-v3-* (Transformers) | 70-140M | NLI stance classification | Robust NLI specialization (supports/refutes/neutral) |
| (Backup) Phi-3-mini | 3.8B | English-focused extraction/summarization | High English performance |

**Implementation note (2025-12-27)**:
- In the current codebase, NLI is implemented via a Transformers sequence-classification model
  (local or via the ML server) rather than via the Ollama LLM. See `src/filter/nli.py` and `src/ml_server/nli.py`.
  Ollama/Qwen is used for structured claim extraction (`config/prompts/extract_claims.j2`) and summarization.

### Prompt Design

NLI judgment example:

```
System: You are an NLI (Natural Language Inference) expert.
Compare the premise and hypothesis, and determine their relationship.

User:
Premise: {premise}
Hypothesis: {hypothesis}

Choose one of the following three options:
- SUPPORTS: Premise supports the hypothesis
- REFUTES: Premise contradicts the hypothesis
- NEUTRAL: Cannot determine from premise

Answer (single word only):
```

### Output Control

```python
# Force structured output
response = await ollama.generate(
    model="qwen2.5:3b",
    prompt=prompt,
    format="json",  # Force JSON output
    options={
        "temperature": 0.1,  # Deterministic output
        "num_predict": 50,   # Limit to short output
    }
)
```

## Consequences

### Positive
- **Zero OpEx Achieved**: No commercial API required
- **Fast Response**: 3B model responds in hundreds of milliseconds
- **Quality Assurance**: Accuracy maintained by limiting tasks
- **Offline Operation**: No network required

### Negative
- **Feature Limitation**: Complex tasks depend on MCP client
- **Language Constraints**: Accuracy may decrease for non-English/Japanese
- **GPU Needed**: GPU desirable for comfortable operation

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| GPT-4 API | High quality | Cost, Zero OpEx violation | Rejected |
| 7B+ Models | Higher accuracy | Stricter GPU requirements | Future consideration |
| Rule-based Extraction | Fast, reliable | Insufficient flexibility | Partial adoption |
| External NLI Service | High accuracy | API dependency | Rejected |

## References
- `src/filter/ollama_provider.py` - Ollama client
- `src/filter/llm.py` - LLM extraction processing
- `src/filter/nli.py` - NLI judgment implementation
- ADR-0001: Local-First / Zero OpEx
- ADR-0002: Thinking-Working Separation
