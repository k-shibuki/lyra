# quality-check

## Purpose

Run linting, formatting checks, and type checks.

## When to use

- Before running the full test suite (typically before `regression-test`)
- Before merging/pushing

## Policy (rules)

Follow the quality policy here:

- `@.cursor/rules/quality-check.mdc`

## Commands

Use `make` commands (run `make help` for all options):

```bash
# Lint check (Python files only; JSON is excluded via pyproject.toml)
make lint

# Lint with auto-fix
make lint-fix

# Format check
make format-check

# Format (auto-fix)
make format

# Type check
make typecheck

# JSON Schema validation
make jsonschema

# Shell script check
make shellcheck

# Run all quality checks (lint + typecheck + jsonschema + shellcheck)
make quality
```

## Output (response format)

- **Issues found**: grouped by tool/code
- **Fixes applied**: summary + file list
- **Intentional exceptions**: list + reason

## Related rules

- `@.cursor/rules/quality-check.mdc`
