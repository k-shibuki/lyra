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

Ruff lint:

```bash
# Run from WSL venv (hybrid mode)
ruff check src/ tests/
ruff check --fix src/ tests/  # if applicable
```

Ruff format:

```bash
ruff format --check src/ tests/
ruff format src/ tests/  # auto-fix
```

Mypy:

```bash
mypy src/ tests/ --config-file pyproject.toml
```

Note: `--config-file pyproject.toml` applies `[tool.mypy]` settings (e.g., `warn_return_any = true`).

## Output (response format)

- **Issues found**: grouped by tool/code
- **Fixes applied**: summary + file list
- **Intentional exceptions**: list + reason

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/quality-check.mdc`
