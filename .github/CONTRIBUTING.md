# Contributing to Lyra

Thank you for your interest in contributing to Lyra! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Contributing to Lyra](#contributing-to-lyra)
  - [Table of Contents](#table-of-contents)
  - [Code of Conduct](#code-of-conduct)
  - [Getting Started](#getting-started)
  - [Development Setup](#development-setup)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Environment Variables](#environment-variables)
  - [Making Changes](#making-changes)
  - [Testing](#testing)
    - [Test Categories](#test-categories)
    - [Writing Tests](#writing-tests)
  - [Submitting Changes](#submitting-changes)
    - [Pull Request Guidelines](#pull-request-guidelines)
  - [Style Guidelines](#style-guidelines)
    - [Python](#python)
    - [Code Comments](#code-comments)
    - [Commit Messages](#commit-messages)
  - [Architecture](#architecture)
    - [Key Documents](#key-documents)
    - [Key Concepts](#key-concepts)
    - [Directory Structure](#directory-structure)
  - [Reporting Issues](#reporting-issues)
  - [Questions?](#questions)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct, version 3.0](https://www.contributor-covenant.org/version/3/0/code_of_conduct/). See [CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md) for the full text.

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
   git remote add upstream https://github.com/shibukik/lyra.git
   ```

## Development Setup

### Prerequisites

- **WSL2/Linux** with NVIDIA GPU (8GB+ VRAM)
- **Python 3.13+** (managed via `uv`)
- **Podman** or **Docker** with GPU support
- **Chrome** (for browser automation)

### Installation

```bash
# Install dependencies
make setup-full

# Check environment
make doctor

# Start containers (proxy, ollama, ml, tor)
make up

# Download ML models
make setup-ml-models
```

### Environment Variables

Copy the example configuration:
```bash
cp .env.example .env
```

## Making Changes

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the [Style Guidelines](#style-guidelines)

3. **Write tests** for new functionality (see [Testing](#testing))

4. **Run quality checks**:
   ```bash
   make check  # Runs lint, format check, and type check
   ```

5. **Commit with clear messages** following [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add new search source integration
   fix: resolve evidence graph cycle detection
   docs: update API documentation
   test: add edge case tests for NLI classifier
   ```

## Testing

Lyra uses `pytest` for testing with extensive coverage:

```bash
# Run all tests
make test

# Run tests with coverage report
make test-cov

# Run specific test file
uv run pytest tests/path/to/test_file.py -v

# Run tests matching a pattern
uv run pytest -k "test_evidence_graph" -v
```

### Test Categories

- **Unit tests**: `tests/unit/` - Isolated component tests
- **Integration tests**: `tests/integration/` - Multi-component tests
- **E2E tests**: `tests/e2e/` - Full workflow tests

### Writing Tests

Follow the test conventions in `../.cursor/rules/test-conventions.mdc`:

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

- **Formatter**: `ruff format` (configured in `pyproject.toml`)
- **Linter**: `ruff check`
- **Type checker**: `pyright`

Run all checks:
```bash
make lint    # Lint check
make format  # Auto-format
make type    # Type check
make check   # All of the above
```

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

- **[Architecture Overview](../docs/ARCHITECTURE.md)**: System design and components
- **[ADRs](../docs/adr/)**: 17 Architecture Decision Records documenting design rationale

### Key Concepts

1. **Thinking-Working Separation** (ADR-0002): Cloud AI handles reasoning; Lyra handles mechanical execution locally

2. **Evidence Graph** (ADR-0005): Claim-Fragment-Page structure with Bayesian confidence calculation

3. **Local-First** (ADR-0001): All ML inference runs locally; zero operational cost

4. **MCP Integration** (ADR-0003): Exposes tools via Model Context Protocol

### Directory Structure

```
lyra/
├── src/                  # Source code
│   ├── mcp/              # MCP server and tools
│   ├── filter/           # Evidence graph, NLI
│   ├── search/           # Search APIs and browser
│   ├── storage/          # Database layer
│   └── ml_server/        # ML inference server
├── tests/                # Test suite
├── containers/           # Docker/Podman configs
├── docs/                 # Documentation
│   ├── adr/              # Architecture Decision Records
│   └── design/           # Design documents
└── scripts/              # Shell scripts
```

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

- Open a [GitHub Discussion](https://github.com/shibukik/lyra/discussions) for questions
- Check the [ADRs](../docs/adr/) for design rationale
- Review [Architecture docs](../docs/ARCHITECTURE.md) for system understanding

---

Thank you for contributing to Lyra! 🎉

