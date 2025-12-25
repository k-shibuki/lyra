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

Use `make` commands (run `make help` for all options).

> **CRITICAL:** Always capture `run_id` from `make test` output and pass it to `make test-check RUN_ID=xxx`.
> Do NOT omit `RUN_ID` — state file fallback is unreliable and causes confusion.

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
  make test-scoped TARGET="${CHANGED_TESTS}"
  # Output shows: run_id: 20251225_123456_12345
  # Use that run_id:
  make test-check RUN_ID=<run_id_from_output>
else
  echo "No changed test files under tests/. Skipping Stage 1."
fi
```

If you changed implementation code but didn't touch tests, explicitly choose the smallest relevant pytest target(s) instead of running everything immediately:

```bash
# Examples (pick what matches your change)
make test-scoped TARGET="tests/test_xxx.py"
# Output shows: run_id: 20251225_123456_12345
make test-check RUN_ID=<run_id_from_output>
```

### Stage 2: full suite (final gate)

Run the full test suite to catch regressions outside your local change surface:

```bash
make test
# Output shows: run_id: 20251225_123456_12345
make test-check RUN_ID=<run_id_from_output>
make test-kill RUN_ID=<run_id>   # only if you need to abort
```

### run_id の取得方法

`make test` / `make test-scoped` の出力に以下が含まれます:

```
Artifacts:
  run_id:      20251225_123456_12345
  result_file: /tmp/lyra_test/result_20251225_123456_12345.txt
```

この `run_id` を `make test-check RUN_ID=xxx` に渡してください。

### Completion logic

- `test-check` returns `DONE` when pytest summary line exists AND pytest process has exited
- Each `run` generates a unique `run_id`; **always specify it** with `check`/`kill`

## Output (response format)

- **Summary**: passed / failed / skipped
- **Failures** (if any): list + first actionable traceback snippets

## Related rules

- `@.cursor/rules/code-execution.mdc`
