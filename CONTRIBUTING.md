# Contributing to Lyra

Thank you for your interest in contributing to Lyra!

## Before You Start

1. **Read the documentation**:
   - [README.md](README.md) — Project overview, architecture, and setup
   - [docs/adr/](docs/adr/) — Architecture Decision Records explaining design rationale

2. **Understand the design principles**:
   - Local-first: All data stays on the user's machine
   - Thinking-working separation: MCP client reasons, Lyra executes
   - Evidence graph: Every claim links to source fragments with provenance

## Development Workflow

### 1. Create a Branch

Always work on a feature branch:

```bash
git checkout -b <type>/<short-description>
```

Branch naming examples:
- `feat/add-new-search-engine`
- `fix/nli-timeout-handling`
- `docs/update-adr-format`

### 2. Make Your Changes

- Follow existing code style and patterns
- Add tests for new functionality
- Update documentation if needed

### 3. Commit with Conventional Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>
```

**Types**:
- `feat` — New feature
- `fix` — Bug fix
- `docs` — Documentation only
- `refactor` — Code change that neither fixes a bug nor adds a feature
- `test` — Adding or updating tests
- `chore` — Maintenance tasks

**Scope** (optional): Component or area affected (e.g., `paper`, `mcp`, `search`, `nli`)

**Examples**:
```
feat(search): add Brave API integration
fix(nli): handle timeout on large documents
docs(adr): add ADR-0017 for caching strategy
refactor(crawler): simplify tab pool management
```

### 4. Submit a Pull Request

- Provide a clear description of your changes
- Reference any related issues
- Ensure tests pass

## Reporting Issues

When reporting bugs, please include:
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, GPU)

## Questions?

Open an issue for discussion before starting major changes.
