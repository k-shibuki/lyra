# test-create

## Purpose

Design and implement tests for the implemented change.

## When to use

- After implementing a task (typically after `implement`)
- Any time coverage is missing for a change you introduced

## Inputs (attach as `@...`)

- `@docs/adr/` or `@docs/P_EVIDENCE_SYSTEM.md` (recommended)
- Relevant source files (`@src/...`) and existing tests (`@tests/...`) (recommended)

## Constraints

- Do **not** reference archived documents (`@docs/archive/`) in code comments.
- Use Given/When/Then comments for readability.
- Include **at least as many negative tests as positive tests**.
- Unit tests must **not** depend on external resources (network, remote services, model downloads).
  - Mock integration points (e.g., `nli_judge`, LLM/HTTP clients, browser/fetchers) so tests are deterministic and non-hanging.
- **DB isolation is handled by pytest fixtures** (`test_database` in `tests/conftest.py`). Do not use `isolated_database_path` inside pytest tests.

## Steps

1. Produce a test matrix (equivalence partitions + boundary cases) in Markdown.
2. Implement tests based on that matrix.
3. For any new parameter/field, add at least one **wiring/effect** test so the suite fails if the parameter is validated but not propagated/used:
   - Wiring: assert downstream call args / generated request / generated query includes the new parameter.
   - Effect: change the parameter value and assert behavior/output changes per requirements.
4. Add Given/When/Then comments.
5. Ensure exceptions include both type and message assertions when meaningful.

## Test matrix template

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Valid input A        | Equivalence – normal                 | Processing succeeds | - |
| TC-A-01 | NULL                 | Boundary – NULL                      | Validation error | - |

## Running tests (recommended)

Use `make` commands (run `make help` for all options).

> **CRITICAL:** Always capture `run_id` from `make test` output and pass it to `make test-check RUN_ID=xxx`.

```bash
make test
# Output shows: run_id: 20251225_123456_12345
make test-check RUN_ID=<run_id_from_output>
```

For specific test files:

```bash
make test-scoped TARGET="tests/test_xxx.py"
# Output shows: run_id: 20251225_123456_12345
make test-check RUN_ID=<run_id_from_output>
```

## Output (response format)

- **Test matrix**: table (updated if scope changes)
- **New/updated test files**: list of paths
- **Notes**: gaps, flakiness risks, runtime concerns

## Related rules

- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/code-execution.mdc`
