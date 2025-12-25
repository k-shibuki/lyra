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
# Lint check
make lint

# Lint with auto-fix
make lint-fix

# Format check
make format-check

# Format (auto-fix)
make format

# Type check
make typecheck

# Run all quality checks (lint + typecheck)
make quality
```

JSON Schema validation (if needed):

```bash
# Validate JSON Schema files against Draft 7 meta-schema
uv run check-jsonschema --schemafile http://json-schema.org/draft-07/schema# src/mcp/schemas/*.json
```

## Output (response format)

- **Issues found**: grouped by tool/code
- **Fixes applied**: summary + file list
- **Intentional exceptions**: list + reason

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/quality-check.mdc`
