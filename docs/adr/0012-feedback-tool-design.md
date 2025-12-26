# ADR-0012: Feedback Tool Design

## Date
2025-12-23

## Context

Lyra supports academic research, but models make errors in the following situations:

| Error Type | Example |
|------------|---------|
| NLI Misclassification | Classifying supports as neutral |
| Extraction Omission | Missing important claims |
| Noise Inclusion | Judging irrelevant fragments as related |
| Citation Misidentification | Incorrectly inferring citation relationships |

A mechanism is needed to correct these errors and utilize them for model improvement.

## Decision

**Introduce a feedback tool with 3 levels and 6 action types to accept user corrections.**

### Feedback Tool Actions (3-Level Structure)

| Level | Action | Purpose | Target |
|-------|--------|---------|--------|
| Domain | `domain_block` | Block a domain | Domain pattern |
| Domain | `domain_unblock` | Unblock a domain | Domain pattern |
| Domain | `domain_clear_override` | Clear override | Domain pattern |
| Claim | `claim_reject` | Reject a claim | Claim ID |
| Claim | `claim_restore` | Restore a claim | Claim ID |
| Edge | `edge_correct` | Correct NLI edge | Edge ID |

### Tool Schema

```json
{
  "name": "feedback",
  "description": "Submit corrections and feedback on evidence",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": { "type": "string" },
      "action": {
        "type": "string",
        "enum": [
          "domain_block",
          "domain_unblock", 
          "domain_clear_override",
          "claim_reject",
          "claim_restore",
          "edge_correct"
        ]
      },
      "args": { "type": "object" }
    },
    "required": ["task_id", "action", "args"]
  }
}
```

### Action-specific Payloads

#### 1. domain_block

```json
{
  "action": "domain_block",
  "args": {
    "domain_pattern": "spam-site.com",
    "reason": "Low quality content, mostly advertisements"
  }
}
```

#### 2. domain_unblock

```json
{
  "action": "domain_unblock",
  "args": {
    "domain_pattern": "legitimate-site.com",
    "reason": "Previously blocked by mistake"
  }
}
```

#### 3. claim_reject

```json
{
  "action": "claim_reject",
  "args": {
    "claim_id": "claim_abc123",
    "reason": "Claim is too vague to verify"
  }
}
```

#### 4. edge_correct

```json
{
  "action": "edge_correct",
  "args": {
    "edge_id": "edge_xyz789",
    "correct_relation": "supports",
    "reason": "The conclusion section clearly supports the hypothesis"
  }
}
```

### Database Schema

Feedback data is stored across multiple tables:

```sql
-- NLI edge corrections (for edge_correct)
CREATE TABLE nli_corrections (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL,
    task_id TEXT,
    premise TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    predicted_confidence REAL NOT NULL,
    correct_label TEXT NOT NULL,
    reason TEXT,
    corrected_at TEXT NOT NULL
);

-- Domain override rules (for domain_block/unblock)
CREATE TABLE domain_override_rules (
    id TEXT PRIMARY KEY,
    domain_pattern TEXT NOT NULL,
    decision TEXT NOT NULL,  -- "block" | "unblock"
    reason TEXT NOT NULL,
    created_at DATETIME,
    is_active BOOLEAN DEFAULT 1
);

-- Domain override audit log
CREATE TABLE domain_override_events (
    id TEXT PRIMARY KEY,
    rule_id TEXT,
    action TEXT NOT NULL,
    domain_pattern TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at DATETIME
);
```

### Security Constraints

TLD-level blocking is prohibited:

```python
FORBIDDEN_PATTERNS = [
    "*",           # All domains
    "*.com",       # TLD level
    "*.co.jp",
    "*.org", 
    "*.net",
    "*.gov",
    "*.edu",
    "**",          # Recursive glob
]
```

### Immediate Graph Reflection

Feedback is immediately reflected in the graph:

```python
async def apply_feedback(action: str, args: dict):
    if action == "edge_correct":
        # Mark as human-reviewed, and optionally correct relation
        edge = await get_edge(args["edge_id"])
        previous_label = edge.nli_label or edge.relation
        edge.edge_human_corrected = True
        edge.edge_corrected_at = now()

        # If the label changes, update the edge relation/label
        if previous_label != args["correct_relation"]:
            edge.relation = args["correct_relation"]
            edge.nli_label = args["correct_relation"]
            edge.nli_confidence = 1.0
            edge.edge_correction_reason = args.get("reason")
        else:
            # Review only (no correction): keep existing model outputs
            edge.edge_correction_reason = args.get("reason")

        await save_edge(edge)
        
        # Persist correction samples only when the label actually changed
        # (predicted_label != correct_label). These samples are used for future LoRA training.
        if previous_label != args["correct_relation"]:
            await save_nli_correction(edge, args)
```

### Edge Review vs Correction (Important Operational Note)

`edge_correct` is used not only for "correction" but also to mark as "**human-reviewed**."

- **Reviewed (denominator)**: `edges.edge_human_corrected = 1` and `edges.edge_corrected_at` is set
- **Corrected (numerator)**: Above plus 1 record added to `nli_corrections` (`predicted_label != correct_label`)
- **Reviewed without correction (correct)**: Review mark on `edges` side, no `nli_corrections` increase

This separation enables "explicit recording of only errors" in operation, while allowing reviewed sets to be tracked from DB for case studies.

## Consequences

### Positive
- **Continuous Improvement**: Model quality improves from user feedback
- **Transparency**: Correction history is traceable (audit log tables)
- **Immediate Effect**: Immediately reflected in graph
- **3-Level Structure**: Clear responsibility separation for Domain/Claim/Edge
- **Security**: TLD-level blocking prohibition prevents misoperation

### Negative
- **User Burden**: Effort required for feedback input
- **Quality Risk**: Incorrect feedback may be mixed in
- **Complexity**: Managing 6 action types

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Simple good/bad buttons | Simple | Insufficient information | Rejected |
| Free text only | Flexible | Difficult to structure | Rejected |
| External annotation tool | Feature-rich | Integration cost, Zero OpEx | Rejected |

## References
- `src/mcp/feedback_handler.py` - Feedback action handler
- `src/mcp/server.py` - Feedback tool definition
- `src/storage/schema.sql` - nli_corrections, domain_override_rules tables
- ADR-0011: LoRA Fine-tuning Strategy
