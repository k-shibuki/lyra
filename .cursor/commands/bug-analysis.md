# bug-analysis

## Purpose

Investigate a bug systematically, identify root cause, implement a fix, and verify it.

## When to use

- A “normal” bug (not primarily a parser-selector issue, not primarily cross-module contract design)
- Exceptions, resource leaks, race conditions, incorrect edge-case handling

## Inputs (attach as `@...`)

- Error message / stack trace / logs (required; paste or attach files)
- Repro steps (minimal) (required)
- Relevant code (`@src/...`) and tests (`@tests/...`) (recommended)

## Investigation workflow

1. Confirm the symptom and reproduce (or explain why it is not reproducible).
2. Collect evidence: stack trace, logs, inputs, environment assumptions.
3. Form hypotheses and validate them against evidence.
4. Implement the smallest correct fix.
5. Verify: targeted tests + (if needed) regression tests.

## Common bug patterns (examples)

- **Async/concurrency**: missing `await`, race condition, deadlock → add awaits, serialize/lock, add timeouts
- **Type/data**: `None` access, type mismatch, empty data → guard Optional, validate inputs, handle empties
- **Resource management**: leaked file/connection, pool exhaustion → use context managers, `finally`, tune pooling
- **Error handling**: swallowed exceptions, over-broad except, missing retry → catch specific errors, log, retry safely

## Useful log commands (optional)

```bash
# Run from WSL venv (hybrid mode)
cat logs/app.log | tail -100
grep -r "ERROR\\|Exception" logs/
```

## Output (response format)

- **Symptom**: expected vs actual
- **Root cause**: what, where, why
- **Fix**: summary + files changed
- **Verification**: what you ran/checked and results
- **Next (manual)**: `NEXT_COMMAND: /quality-check`

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/refactoring.mdc`
