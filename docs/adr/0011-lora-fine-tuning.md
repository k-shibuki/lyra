# ADR-0011: LoRA Fine-tuning Strategy

## Date
2025-12-20

## Context

The NLI models used in Lyra (DeBERTa-v3-xsmall/small) are general-purpose pre-trained models. The following challenges exist:

| Challenge | Details |
|-----------|---------|
| Domain Adaptation | Insufficient specialization for academic papers/technical documents |
| Misclassification | Errors like classifying supports as neutral |
| User-specific | Not optimized for each user's research domain |

Full fine-tuning has these problems:
- Requires tens of GB of GPU memory
- Training time of hours to days
- Entire model must be saved (several GB)

## Decision

**Adopt LoRA (Low-Rank Adaptation) for parameter-efficient fine-tuning.**

### LoRA Selection Reasons

| Aspect | LoRA | Full FT |
|--------|------|---------|
| Memory | Several GB | Tens of GB |
| Training Time | Minutes to hours | Hours to days |
| Adapter Size | Several MB | Several GB |
| Multiple Adapters | Possible | Difficult |

### Architecture

```
Base Model (DeBERTa-v3-xsmall/small)
    │
    ├── LoRA Adapter: General NLI improvement
    │
    ├── LoRA Adapter: Academic domain
    │
    └── LoRA Adapter: User-specific (learned from feedback)
```

### Feedback-driven Learning

Learn LoRA adapters from user feedback (see ADR-0012):

```python
# Collect feedback data
feedback_data = [
    {
        "premise": "Claim from Paper A...",
        "hypothesis": "User's hypothesis...",
        "correct_label": "supports",  # User correction
        "original_label": "neutral"   # Model misclassification
    },
    ...
]

# LoRA training (effective with tens to hundreds of samples)
adapter = train_lora(
    base_model="cross-encoder/nli-deberta-v3-small",
    data=feedback_data,
    rank=8,
    alpha=16
)
```

### Training Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| rank (r) | 8 | Balance between memory efficiency and performance |
| alpha | 16 | Recommended 2× of r |
| dropout | 0.1 | Higher regularization effective for small models (70-140M params) |
| target_modules | query, value | DeBERTa-v3 Attention layers |

### Adapter Management

```
~/.lyra/
  └── adapters/
      ├── base_nli_v1.safetensors      # Basic NLI improvement
      ├── academic_v1.safetensors       # Academic domain
      └── user_feedback_v3.safetensors  # Feedback learning
```

### MCP Tool Integration Decision

**Decision: MCP tooling rejected. Script-based operation adopted.**

#### Rejection Reasons

| Aspect | Problem |
|--------|---------|
| Processing Time | MCP timeout risk with tens of minutes to 1 hour |
| GPU Contention | Competes with ML Server during inference |
| Manual Verification | Shadow evaluation results should be human-reviewed before production |
| Iteration | Scripts more flexible for hyperparameter tuning |

#### Adopted Approach

```bash
# Run LoRA training via script (offline batch)
python scripts/train_lora.py --db data/lyra.db --output adapters/lora-v1

# After result verification, apply adapter to ML Server
curl -X POST http://localhost:8001/nli/adapter/load \
  -d '{"adapter_path": "adapters/lora-v1"}'
```

#### Relationship with calibration_metrics

- `calibration_metrics(get_stats)` / `(get_evaluations)`: State check/history reference (MCP tools)
- `evaluate` / `get_diagram_data`: Removed from MCP tools (ADR-0010). Batch evaluation/visualization done via scripts.

### Training Trigger Conditions

| Condition | Threshold | Reason |
|-----------|-----------|--------|
| Feedback Accumulation | 100+ samples | Statistical stability with ~33 samples per class for 3-class classification |
| Misclassification Rate | 10%+ | Indicates need for improvement |
| Domain Change | User-specified | New domain adaptation |

## Consequences

### Positive
- **Efficient**: Performance improvement with several MB adapters
- **Fast**: Training completes in minutes to hours
- **Reversible**: Can always rollback to original
- **Personalized**: Adapts to user's research domain

### Negative
- **Training Quality**: Depends on feedback quality
- **Complexity**: Adapter management overhead
- **Compatibility**: Depends on Ollama adapter support

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Full Fine-tuning | Best performance | Excessive resources | Rejected |
| Prompt Tuning | Lightweight | Limited effect | Rejected |
| Adapter Tuning | Similar to LoRA | Less efficient than LoRA | Rejected |
| QLoRA | Ultra-lightweight | Quality degradation risk | Future consideration |
| **MCP Tooling** | UI integration | Long processing, GPU contention, manual verification difficulty | **Rejected** |

## Implementation Status

**Note**: LoRA training functionality described in this ADR is planned for **Phase R (Future)**.
See `docs/T_LORA.md` for detailed task list.

### Current State (Implemented)
- `feedback(edge_correct)` accumulates NLI correction samples in `nli_corrections` table
- `calibration_metrics` tool enables probability calibration evaluation (Platt Scaling/Temperature Scaling)
- `calibration_rollback` tool enables parameter rollback

### Prerequisites (Phase 6)
To start LoRA training, the following are required:
- 100+ samples accumulated in `nli_corrections` table
- `feedback` tool in operational use

### Planned (Not Implemented)

| Task | Content | Status |
|------|---------|:------:|
| R.1.x | PEFT/LoRA library integration | Not started |
| R.2.x | Training script creation | Not started |
| R.3.x | Adapter version management | Not started |
| R.4.x | Testing and validation | Not started |

## References
- `docs/T_LORA.md` - LoRA fine-tuning detailed design
- `src/utils/calibration.py` - Probability calibration implementation
- `src/storage/schema.sql` - `nli_corrections`, `calibration_evaluations` tables
- `src/mcp/server.py` - `calibration_metrics`, `calibration_rollback` MCP tools
- ADR-0012: Feedback Tool Design
