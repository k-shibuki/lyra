# Contributing to Lyra

Thank you for your interest in contributing to Lyra! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Style Guidelines](#style-guidelines)
- [Architecture](#architecture)
- [Reporting Issues](#reporting-issues)
- [Questions?](#questions)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct, version 3.0](https://www.contributor-covenant.org/version/3/0/code_of_conduct/). See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the full text.

We are committed to providing a welcoming and inclusive environment. Please be respectful and constructive in all interactions.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/lyra.git
   cd lyra
   ```
3. **Add upstream remote**:
   ```bash
   git remote add upstream https://github.com/k-shibuki/lyra.git
   ```

## Development Setup

See [README.md](../README.md#prerequisites) for:
- **Prerequisites** (Linux, Python 3.14+, Podman/Docker, Chrome, GPU)
- **Installation** (Quick Start)
- **Environment Variables** (`.env` configuration)

## Making Changes

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the [Style Guidelines](#style-guidelines)

3. **Write tests** for new functionality (see [Testing](#testing))

4. **Run quality checks**:
   ```bash
   make quality  # Runs lint, format-check, typecheck, jsonschema, shellcheck
   ```

5. **Commit with clear messages** following [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add new search source integration
   fix: resolve evidence graph cycle detection
   docs: update API documentation
   test: add edge case tests for NLI classifier
   ```

## Testing

Lyra uses `pytest` for testing with async execution designed for AI-driven development:

```bash
make test                           # Run unit + integration (default: -m "not e2e")
make test-all                       # Run ALL tests (no marker exclusions, includes e2e)
make test TARGET=tests/test_foo.py  # Run specific file
make test-check RUN_ID=xxx          # Poll for test results (use run_id from test output)
make test-e2e                       # Run E2E tests only
make test-e2e-internal              # E2E against local services (proxy/ml/ollama)
make test-e2e-external              # E2E against internet services (SERP/FETCH/Academic APIs)
make help                           # Show all available commands
```

**Async Workflow**: `make test` starts tests in the background and returns immediately (prints a `RUN_ID`). Use `make test-check RUN_ID=...` to poll for completion and view results.

### Output Mode (make commands)

- **Machine-readable**: `LYRA_OUTPUT_JSON=true make <target>` (stdout stays JSON)
- **Quiet**: `LYRA_QUIET=true make <target>` (suppress non-essential output)
- **Test verbosity**:
  - `LYRA_TEST_SHOW_TAIL_ON_SUCCESS=true make test-check RUN_ID=...`
  - `LYRA_TEST_JSON_DETAIL=full|minimal make test`

### Test Layers

Lyra follows a three-layer test strategy ([ADR-0009](../docs/adr/0009-test-layer-strategy.md)):

| Layer | Description | Markers |
|-------|-------------|---------|
| **L1** | Unit tests (isolated, fast) | Default |
| **L2** | Integration tests (DB, multi-component) | `@pytest.mark.integration` |
| **L3** | E2E tests (real environment) | `@pytest.mark.e2e` + (`internal` or `external`) |

Notes:
- `internal`: Local services only (proxy/ml/ollama). No internet SERP/API.
- `external`: Internet access (SERP/FETCH/Academic APIs). Use `rate_limited` / `manual` as needed.
- Lyra enforces this at collection time: E2E tests missing `internal`/`external` fail fast.

### Writing Tests

1. Create a **test perspectives table** before writing tests
2. Use **Given/When/Then** comments
3. Cover both **success and failure paths**
4. Target **branch coverage of 100%** where practical

## Submitting Changes

1. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a Pull Request** against the `main` branch

3. **Ensure CI passes** - All tests and lints must pass

4. **Request review** and address feedback

### Pull Request Guidelines

- Keep PRs focused on a single change
- Include tests for new functionality
- Update documentation as needed
- Reference related issues in the PR description

## Style Guidelines

### Python

- **Formatter**: `black` + `ruff` (configured in `pyproject.toml`)
- **Linter**: `ruff check`
- **Type checker**: `mypy`

Run all checks:
```bash
make lint          # Lint check
make format        # Auto-format
make typecheck     # Type check
make quality       # All checks (lint, format-check, typecheck, jsonschema, shellcheck)
make deadcode      # Dead code detection (manual, not CI - may have false positives)
```

See `make help` for full command reference.

### Code Comments

- Write comments in **English**
- Reference **ADRs** (Architecture Decision Records) when relevant
- Avoid referencing external documentation that may become stale

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## Architecture

Understanding Lyra's architecture helps you contribute effectively:

### Key Documents

- **[Architecture Overview](../docs/architecture.md)**: System design, data flow, and directory structure
- **[ADR Index](../docs/adr/index.md)**: Architecture Decision Records (by reading order, category, and evolution)

## Reporting Issues

When reporting bugs:

1. **Check existing issues** to avoid duplicates
2. **Use the issue template** if available
3. **Include**:
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, GPU, Python version)
   - Relevant logs (`make mcp-logs`)

## Questions?

- Open a [GitHub Discussion](https://github.com/k-shibuki/lyra/discussions) for questions
- Check the [ADR Index](../docs/adr/index.md) for design rationale
- Review [Architecture docs](../docs/architecture.md) for system understanding

---

Thank you for contributing to Lyra! 🎉

