# regression-test

## Purpose

Run tests in two stages to detect regressions efficiently:

1. Run tests for files changed in this session (fast, scoped)
2. Run the full test suite (final gate)

**Both stages are required.** Stage 1 alone is not sufficient—always run Stage 2 as the final gate.

## When to use

- After quality checks pass (typically after `quality-check`)
- Before merging/pushing changes

## Inputs

- None required (but attach failing logs/output if rerunning after a failure)

## How to run (recommended)

Use `scripts/test.sh` (async + polling).

> **Note:** `test.sh check` has built-in polling. Do NOT combine it with `sleep` commands.

### Stage 1: session-scoped tests (recommended)

Run only the test files you touched in this session (based on git working tree changes: modified + untracked).

```bash
# Collect changed test files under tests/ (modified + untracked), then run them.
CHANGED_TESTS="$(
  (
    git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null || true
    git ls-files -m -o --exclude-standard 2>/dev/null || true
  ) | sort -u | grep -E '^tests/.*\.py$' || true
)"

if [[ -n "${CHANGED_TESTS}" ]]; then
  ./scripts/test.sh run ${CHANGED_TESTS}
  ./scripts/test.sh check
else
  echo "No changed test files under tests/. Skipping Stage 1."
fi
```

If you changed implementation code but didn’t touch tests, explicitly choose the smallest relevant pytest target(s) instead of running everything immediately:

```bash
# Examples (pick what matches your change)
./scripts/test.sh run "tests/test_xxx.py"
./scripts/test.sh run "tests/test_xxx.py" -k "test_specific_case"
./scripts/test.sh run "tests/unit/test_a.py" "tests/integration/test_b.py"
./scripts/test.sh check
```

### Stage 2: full suite (final gate)

Run the full test suite to catch regressions outside your local change surface:

```bash
./scripts/test.sh run tests/
# Output shows: ./scripts/test.sh check <run_id>
./scripts/test.sh check <run_id>
./scripts/test.sh kill <run_id>  # only if you need to abort
```

Polling example:

```bash
./scripts/test.sh run tests/
# Output: "Started. To check results: ./scripts/test.sh check 20251224_123456_12345"
./scripts/test.sh check 20251224_123456_12345
```

Completion logic:

- `check` returns `DONE` when pytest summary line exists AND pytest process has exited
- Each `run` generates a unique `run_id`; use it with `check`/`kill` to avoid result confusion

## Output (response format)

- **Summary**: passed / failed / skipped
- **Failures** (if any): list + first actionable traceback snippets

## Related rules

- `@.cursor/rules/code-execution.mdc`