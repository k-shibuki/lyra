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

LLMs are effective for these tasks, but ADR-0001 (Zero OpEx) constraints prohibit commercial APIs.

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
| DeBERTa-v3-small | ~140M | NLI stance classification | Robust NLI specialization (supports/refutes/neutral) |

**Implementation note (2025-12-27)**:
- In the current codebase, NLI is implemented via a Transformers sequence-classification model
  (local or via the ML server) rather than via the Ollama LLM. See `src/filter/nli.py` and `src/ml_server/nli.py`.
  Ollama/Qwen is used for structured claim extraction (`config/prompts/extract_claims.j2`) and summarization.

### Prompt Design

**Critical guidelines for 3B models **:

| Guideline | Reason |
|-----------|--------|
| Keep prompts under 300 characters | 3B models struggle with long prompts (>500 chars often produce empty output) |
| Use `<placeholder>` format for values | Concrete values like `0.8` get copied verbatim |
| Specify quantity limits explicitly | "Extract 1-5 claims" prevents under/over-extraction |
| Prioritize instructions for quality | "Prioritize claims with numbers, dates, proper nouns" |
| Disable security tags by default | Session tags add ~400 chars; enable only for 7B+ models |
| Use JSON Schema via `format` param | Ollama's schema enforcement is more reliable than prompt instructions |

**Example prompt (extract_claims.j2)**:

```jinja2
Extract 1-5 verifiable claims from the text. Prioritize claims with numbers, dates, or proper nouns.

Research context: {{ context }}

Text: {{ text }}

Output JSON array. Each item: {"claim": "<claim text>", "type": "<fact|opinion|prediction>", "relevance_to_query": <0.0-1.0>, "confidence": <0.0-1.0>}
```

**Anti-pattern** (causes value copying):
```
Return JSON array: [{"claim": "...", "type": "fact", "relevance_to_query": 0.8, "confidence": 0.9}]
```

### NLI Judgment (DeBERTa)

NLI uses a fine-tuned Transformer model, not LLM prompts:

| Aspect | Description |
|--------|-------------|
| Model | `cross-encoder/nli-deberta-v3-small` (sequence classification) |
| Input format | `{premise} [SEP] {nli_hypothesis}` |
| Output | ENTAILMENT / CONTRADICTION / NEUTRAL + softmax score |
| Label mapping | ENTAILMENT→supports, CONTRADICTION→refutes, others→neutral |
| Calibration | Platt Scaling applied to raw confidence (see ADR-0012) |

This approach provides faster inference (~10ms/pair) and more consistent results than LLM-based NLI.

### Output Control

| Setting | Value | Purpose |
|---------|-------|---------|
| format | json | Force structured JSON output |
| temperature | 0.1-0.3 | Near-deterministic output for extraction tasks |
| num_predict | Limited | Constrain output length for focused responses |

The Ollama provider supports JSON Schema enforcement via the `format` parameter for more reliable structured output than prompt-only instructions.

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
| Commercial APIs | High quality | Cost, Zero OpEx violation | Rejected |
| 7B+ Models | Higher accuracy | Stricter GPU requirements | Future consideration |
| Rule-based Extraction | Fast, reliable | Insufficient flexibility | Partial adoption |
| External NLI Service | High accuracy | API dependency | Rejected |

## Related

- [ADR-0001: Local-First / Zero OpEx](0001-local-first-zero-opex.md) - Zero OpEx constraints for LLM selection
- [ADR-0002: Three-Layer Collaboration Model](0002-three-layer-collaboration-model.md) - Defines extraction as Working layer task
- `src/filter/ollama_provider.py` - Ollama client
- `src/filter/llm.py` - LLM extraction processing
- `src/filter/nli.py` - NLI judgment implementation
