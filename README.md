# Lyra

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)

**AI-powered academic research assistant with full transparency and zero operational cost.**

Lyra is an open-source MCP (Model Context Protocol) server that enables AI assistants to conduct desktop research with complete local data sovereignty. It separates "thinking" (strategic reasoning by cloud AI) from "working" (mechanical execution by Lyra), keeping research data entirely on your machine while leveraging frontier AI reasoning capabilities.

## Statement of Need

AI-assisted web research faces a fundamental tension: powerful reasoning models (GPT-4, Claude) are cloud-based, but transmitting research queries and collected evidence to external servers is unacceptable for sensitive domains.

**Existing approaches force a choice:**

| Approach | Limitation |
|----------|------------|
| Cloud AI with web access | Queries and findings leave the machine |
| Local-only tools | Sacrifice frontier reasoning capability |
| Browser automation scripts | Require custom coding, no evidence tracking |

**Lyra resolves this by:**

- **Evidence Graph**: Traceable claim-evidence relationships with NLI verification
- **Local-first**: All ML processing on your machine (zero data exfiltration)
- **Zero OpEx**: No recurring costs beyond hardware
- **Full Transparency**: Every claim links back to its source fragments and URLs

This architecture specifically benefits healthcare researchers, legal/compliance teams, independent researchers, and security-conscious organizations.

## Features

- 🔍 **Multi-source Search**: Academic APIs (Semantic Scholar, OpenAlex) + web search engines
- 🧠 **Evidence Extraction**: LLM-based claim extraction with NLI stance detection
- 📊 **Evidence Graph**: SQLite-backed graph of claims, evidence, and sources with Bayesian confidence
- 🔒 **Network Isolation**: ML containers have no internet access (security by design)
- 🌐 **MCP Protocol**: Integrates with Cursor, Claude Desktop, Zed, and other MCP clients
- 🔄 **Human-in-the-Loop**: Graceful CAPTCHA handling and feedback-driven improvement

## Prerequisites

- **WSL2/Linux** with NVIDIA GPU (8GB+ VRAM)
- **Python 3.13+** (managed via `uv`)
- **Podman** or **Docker** with GPU support
- **Chrome** (for browser automation)

```bash
# WSL2/Linux
sudo apt install -y curl git podman podman-compose  # or docker.io docker-compose-plugin
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

## Quick Start

```bash
git clone https://github.com/shibukik/lyra.git && cd lyra
make doctor   # Check environment
make up       # Start (auto-build first time)
```

## MCP Client Configuration

### Cursor

```bash
mkdir -p .cursor
cp config/mcp-config.example.json .cursor/mcp.json
```

### Other MCP Clients

Copy `config/mcp-config.example.json` to your MCP client's configuration location.

## Usage Example

```python
# In your MCP client (e.g., Cursor AI):

# 1. Create a research task
create_task(query="What is the efficacy of DPP-4 inhibitors as add-on therapy for insulin-treated diabetes?")
# → Returns task_id

# 2. Queue search queries (designed by AI assistant)
queue_searches(task_id, queries=[
    "DPP-4 inhibitors efficacy meta-analysis HbA1c",
    "DPP-4 inhibitors safety cardiovascular outcomes",
    "sitagliptin add-on therapy insulin RCT"
])

# 3. Monitor progress with long-polling
get_status(task_id, wait=30)
# → Returns search progress, metrics, evidence counts

# 4. Explore evidence graph
vector_search(query="cardiovascular safety", target="claims", task_id=task_id)
query_view(view_name="v_contradictions", task_id=task_id)

# 5. Provide feedback to improve NLI accuracy
feedback(action="edge_correct", edge_id="...", correct_relation="supports")
```

## Commands

```bash
make up                  # Start (auto: uv, .env, build if needed)
make down                # Stop containers
make logs SERVICE=ollama # Specific service logs
make shell               # Enter proxy container
make mcp                 # Start MCP manually (debug)
make doctor              # Check environment
make help                # Show all commands
```

**Services**: `proxy`, `ollama`, `ml`, `tor`

## Testing

```bash
make test      # Run all tests
make test-cov  # With coverage report
make lint      # Lint check
make type      # Type check
make check     # All quality checks
```

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Architecture Decisions (ADR)](docs/adr/) - 17 design decision records
- [Evidence Graph Structure](docs/adr/0005-evidence-graph-structure.md)
- [Security Model](docs/adr/0006-eight-layer-security-model.md)

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines on how to contribute to Lyra.

## Citation

If you use Lyra in your research, please cite:

```bibtex
@software{lyra2025,
  author = {Shibuki, Katsuya},
  title = {Lyra: A Local-First MCP Toolkit for AI-Collaborative Desktop Research},
  year = {2025},
  url = {https://github.com/shibukik/lyra}
}
```

See [CITATION.cff](CITATION.cff) for machine-readable citation information.

## Limitations

- **Platform Dependency**: WSL2/Linux with NVIDIA GPU required
- **Designed for Navigation**: Lyra discovers and organizes sources; primary source analysis is part of researcher's tool-assisted workflow
- **Content Scope**: Academic papers processed via abstracts only; web content limited to initial portions
- **Chrome Dependency**: Browser automation requires Chrome installation
- **Selector Maintenance**: Web scrapers may require updates when sites change
- **NLI Accuracy**: General-purpose model may require domain adaptation for specialized fields

## Troubleshooting

```bash
make doctor           # Diagnose issues
make logs SERVICE=ml  # Check ML server logs
make mcp-logs         # Check MCP server logs
```

## License

MIT License - see [LICENSE](LICENSE) for details.

Copyright (c) 2025 Katsuya Shibuki
