# Lyra

[![CI](https://github.com/shibukik/lyra/actions/workflows/ci.yml/badge.svg)](https://github.com/shibukik/lyra/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)

**MCP server that enables AI assistants to conduct research with traceable, high-quality evidence.**

Lyra is an open-source MCP (Model Context Protocol) server that provides AI assistants with structured, verifiable evidence for desktop research. By building an Evidence Graph with full source traceability, Lyra solves the fundamental problem of AI-assisted research: knowing where information comes from and how reliable it is.

## Statement of Need

When AI assistants conduct web research, they face critical evidence quality problems:

| Problem | Impact |
|---------|--------|
| **Untraceable sources** | AI returns information without clear provenance |
| **Contradictory evidence** | Conflicting claims are mixed without structure |
| **No confidence metrics** | Impossible to assess reliability objectively |

**Lyra solves these by providing:**

- **Evidence Graph**: Every claim links to source fragments and URLs with NLI stance detection
- **Bayesian Confidence**: Automatic reliability scoring from accumulated evidence
- **Incremental Exploration**: SQL and vector search for granular evidence access
- **Local-First**: All ML processing on your machine (zero data exfiltration, zero operational cost)

For detailed architecture, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Key Concepts

### Three-Layer Collaboration

Lyra implements a clear separation of responsibilities ([ADR-0002](docs/adr/0002-thinking-working-separation.md)):

| Layer | Role |
|-------|------|
| **Human** | Primary source reading, final judgment, domain expertise |
| **AI Client** | Research planning, query design, synthesis |
| **Lyra** | Source discovery, extraction, NLI, persistence |

**Key principle**: Lyra is a *navigation tool*. It discovers and organizes sources; detailed analysis is the researcher's role.

### Evidence Graph

Claims connect to evidence through a structured graph ([ADR-0005](docs/adr/0005-evidence-graph-structure.md)):

```
Claim (hypothesis) ← Fragment (SUPPORTS/REFUTES/NEUTRAL) ← Page ← URL
```

Each edge carries calibrated NLI confidence, and claims accumulate Bayesian confidence from evidence.

## Features

- 🔍 **Multi-source Search**: Academic APIs (Semantic Scholar, OpenAlex) + web engines
- 🧠 **Evidence Extraction**: LLM claim extraction with NLI stance detection
- 📊 **Evidence Graph**: SQLite-backed with Bayesian confidence
- 🔒 **Network Isolation**: ML containers have no internet access ([ADR-0006](docs/adr/0006-eight-layer-security-model.md))
- 🔄 **Human-in-the-Loop**: CAPTCHA handling and feedback-driven improvement ([ADR-0007](docs/adr/0007-human-in-the-loop-auth.md))

## Prerequisites

- **WSL2/Linux** with NVIDIA GPU (8GB+ VRAM)
- **Python 3.13+** (managed via `uv`)
- **Podman** or **Docker** with GPU support
- **Chrome** (for browser automation)

```bash
# WSL2/Linux
sudo apt install -y curl git podman podman-compose
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

**Note**: CPU-only operation is not supported.

## Quick Start

```bash
git clone https://github.com/shibukik/lyra.git && cd lyra
make doctor   # Check environment
make up       # Start (auto-build first time)
```

### MCP Client Configuration

```bash
# Cursor
mkdir -p .cursor && cp config/mcp-config.example.json .cursor/mcp.json
```

For other clients, copy `config/mcp-config.example.json` to your client's config location.

## Usage Example

```python
# 1. Create task
task = create_task(query="Efficacy of DPP-4 inhibitors for diabetes?")

# 2. Queue searches (async execution)
queue_searches(task_id=task.task_id, queries=[
    "DPP-4 inhibitors efficacy meta-analysis",
    "DPP-4 inhibitors cardiovascular safety",
    "DPP-4 inhibitors limitations"  # Include refutation queries
])

# 3. Monitor progress
get_status(task_id=task.task_id, wait=30)

# 4. Explore evidence
vector_search(query="cardiovascular", target="claims", task_id=task.task_id)
query_view(view_name="v_contradictions", task_id=task.task_id)

# 5. Provide feedback
feedback(action="edge_correct", edge_id="...", correct_relation="supports")
```

## MCP Tools

| Category | Tools |
|----------|-------|
| Task Management | `create_task`, `get_status`, `stop_task` |
| Search | `queue_searches` |
| Evidence Exploration | `query_sql`, `vector_search`, `query_view`, `list_views` |
| Authentication | `get_auth_queue`, `resolve_auth` |
| Feedback | `feedback` |
| Calibration | `calibration_metrics`, `calibration_rollback` |

## Commands

```bash
make up       # Start services
make down     # Stop services
make doctor   # Check environment
make test     # Run tests
make help     # Show all commands
```

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md) - System design and data flow
- [MCP Tools Reference](docs/MCP_REFERENCE.md) - Tool descriptions and schemas
- [ADR Index](docs/adr/) - 17 architecture decision records
- [Contributing Guide](.github/CONTRIBUTING.md)
- [Code of Conduct](.github/CODE_OF_CONDUCT.md) - Contributor Covenant 3.0

Key ADRs:
- [ADR-0002: Thinking-Working Separation](docs/adr/0002-thinking-working-separation.md)
- [ADR-0005: Evidence Graph Structure](docs/adr/0005-evidence-graph-structure.md)
- [ADR-0010: Async Search Queue](docs/adr/0010-async-search-queue.md)

## Limitations

- **Platform**: WSL2/Linux + NVIDIA GPU required
- **Scope**: Navigation tool; primary source analysis is researcher's role
- **Content**: Academic papers via abstracts; web content limited to initial portions
- **NLI**: General-purpose model; domain adaptation via LoRA ([ADR-0011](docs/adr/0011-lora-fine-tuning.md))

## Citation

If you use Lyra in your research, please cite using [CITATION.cff](CITATION.cff).

## License

MIT License - see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Katsuya Shibuki
