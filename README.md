# Lyra

[![CI](https://github.com/k-shibuki/lyra/actions/workflows/ci.yml/badge.svg)](https://github.com/k-shibuki/lyra/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)

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

For detailed architecture, see [docs/architecture.md](docs/architecture.md).

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

- **Linux** (WSL2 or Native Ubuntu Desktop 24.04 LTS)
- **Python 3.14+** (managed via `uv`)
- **Podman** or **Docker**
- **Browser for automation (CDP)**:
  - **WSL2**: Windows **Google Chrome** (required; fixed path)
  - **Native Linux**: **Google Chrome** (recommended) or **Chromium** (supported)
- **NVIDIA GPU** (recommended, optional - CPU fallback available)

### WSL2 Setup

```bash
sudo apt install -y curl git make podman podman-compose shellcheck

# GPU support (recommended) - requires NVIDIA repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

Browser automation on WSL2 uses **Windows Google Chrome** via CDP.
Install Chrome on Windows and keep the default path:
`C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe`

### Native Linux (Ubuntu) Setup

```bash
# Core dependencies (make is required for build commands)
sudo apt install -y curl git make podman podman-compose libcurl4-openssl-dev shellcheck

# Rust toolchain (required for building sudachipy - Japanese NLP tokenizer)
# Note: apt's rustc is too old; use rustup for latest version
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env

# Browser automation
# Option A: Google Chrome (recommended; official repo)
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable
#
# Option B: Chromium (supported; easier but less stable)
# sudo snap install chromium

# Desktop notifications (optional)
sudo apt install -y libnotify-bin

# Window activation for CAPTCHA handling (optional)
sudo apt install -y xdotool

# GPU support (optional but recommended for performance) - requires NVIDIA repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

Note: `source $HOME/.cargo/env` is only for enabling `rustc/cargo` in your current shell (it is not related to Lyra's `.env`).

**Note**: Python 3.14 is automatically managed by `uv` - no system installation required.

**GPU Auto-Detection**: Lyra automatically detects GPU availability at startup. If `nvidia-smi` is not found, it runs in CPU mode (slower inference, but fully functional).

**CPU-only Mode**: To explicitly disable GPU and run in CPU mode (even when GPU is available), set `LYRA_DISABLE_GPU=1` in your `.env` file. This is useful for testing or when you want to avoid nvidia-container-toolkit setup.

## Quick Start

```bash
git clone https://github.com/k-shibuki/lyra.git && cd lyra
make doctor   # Check environment
make setup    # Install Python deps (uv will auto-manage Python 3.14+)
make up       # Start (auto-build first time)
```

Note: `.env` is created automatically from `.env.example` on the first run of `make doctor` / `make setup` / `make up`.
Edit `.env` if you need to customize settings.

### MCP Client Configuration

```bash
# Cursor
mkdir -p .cursor && cp config/mcp-config.example.json .cursor/mcp.json
```

**Important**: Edit `.cursor/mcp.json` and update the path to match your installation:

```json
{
  "mcpServers": {
    "lyra": {
      "command": "/full/path/to/lyra/scripts/mcp.sh",
      "args": []
    }
  }
}
```

Replace `/full/path/to/lyra` with your actual Lyra installation path (e.g., `/home/username/Projects/lyra`).

For other clients, copy `config/mcp-config.example.json` to your client's config location and adjust the path accordingly.

## Usage Example

```python
# 1. Create task
task = create_task(hypothesis="DPP-4 inhibitors improve HbA1c in type 2 diabetes")

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

- [Architecture Overview](docs/architecture.md) - System design and data flow
- [MCP Tools Reference](docs/mcp_reference.md) - Tool descriptions and schemas
- [ADR Index](docs/adr/) - 17 architecture decision records
- [Contributing Guide](.github/CONTRIBUTING.md)
- [Code of Conduct](.github/CODE_OF_CONDUCT.md) - Contributor Covenant 3.0

Key ADRs:
- [ADR-0002: Thinking-Working Separation](docs/adr/0002-thinking-working-separation.md)
- [ADR-0005: Evidence Graph Structure](docs/adr/0005-evidence-graph-structure.md)
- [ADR-0010: Async Search Queue](docs/adr/0010-async-search-queue.md)

## Limitations

- **Platform**: Linux (WSL2 or Native Ubuntu Desktop 24.04 LTS); NVIDIA GPU recommended for performance
- **Scope**: Navigation tool; primary source analysis is researcher's role
- **Content**: Academic papers via abstracts; web content limited to initial portions
- **NLI**: General-purpose model; domain adaptation via LoRA ([ADR-0011](docs/adr/0011-lora-fine-tuning.md))
- **CPU Mode**: Functional but significantly slower inference (20-100x compared to GPU)

## Citation

If you use Lyra in your research, please cite using [CITATION.cff](CITATION.cff).

## License

MIT License - see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Katsuya Shibuki
