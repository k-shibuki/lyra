# Lyra Architecture

## Overview

Lyra is an open-source server implementing the Model Context Protocol (MCP)—a standard interface for connecting AI assistants to external tools—that enables AI assistants to conduct desktop research with structured provenance, providing accurate and auditable evidence. The software exposes research capabilities—web search, content extraction, natural language inference, and evidence graph construction—as structured tools that MCP-compatible AI clients can invoke directly.

The architecture implements a three-layer collaboration model ([ADR-0002](adr/0002-three-layer-collaboration-model.md)):
- **Thinking Layer (Human)**: Primary source reading, final judgment, domain expertise
- **Reasoning Layer (MCP Client)**: Research planning, query design, synthesis
- **Working Layer (Lyra)**: Source discovery, extraction, NLI, persistence

Lyra uses a hybrid architecture where the MCP server runs on the host (WSL2/Linux) while inference services run in network-isolated containers. Search queries are processed asynchronously via a job queue ([ADR-0010](adr/0010-async-search-queue.md)), and each task defines a central hypothesis to verify ([ADR-0017](adr/0017-task-hypothesis-first.md)).

## System Architecture

See [figures/figure1-architecture.mmd](figures/figure1-architecture.mmd) for the Mermaid source.

```mermaid
flowchart TB
    subgraph Host["WSL2/Linux Host"]
        MCP["MCP Client<br/>(Claude, etc.)"]
        Server["MCP Server<br/>+ Evidence Graph"]
        Chrome["Chrome"]
    end
    subgraph Containers["Containers (Podman)"]
        subgraph lyra-internal["lyra-internal (isolated)"]
            Ollama["ollama<br/>qwen2.5:3b"]
            ML["ml<br/>BGE-M3, NLI"]
        end
        Proxy["proxy"]
        subgraph lyra-net["lyra-net"]
            Tor["tor"]
        end
    end
    Internet((Internet))
    Academic["Academic APIs<br/>(S2, OpenAlex)"]
    MCP <-->|stdio| Server
    Server --> Chrome
    Server --> Academic
    Chrome --> Internet
    Academic --> Internet
    Server <-->|HTTP| Proxy
    Proxy <--> Ollama
    Proxy <--> ML
    Proxy <--> Tor
    Tor <-->|SOCKS| Internet
```

## Components

### Host Components

| Component | Description |
|-----------|-------------|
| **MCP Server** | Main application server (Python). Handles MCP protocol, search orchestration, evidence graph management. Runs directly on host for optimal I/O. |
| **Evidence Graph** | SQLite database storing claims, evidence, and relationships. Located at `data/lyra.db`. |
| **Chrome** | Browser automation for web scraping. Runs on host (Windows Chrome for WSL2). |

### Container Services

| Service | Container | Network | Description |
|---------|-----------|---------|-------------|
| `proxy` | `proxy` | lyra-net, lyra-internal | HTTP bridge between host MCP server and internal services |
| `ollama` | `ollama` | lyra-internal | Local LLM runtime (qwen2.5:3b). GPU-accelerated when available, network-isolated. |
| `ml` | `ml` | lyra-internal | Embedding (bge-m3) and NLI inference. GPU-accelerated when available, network-isolated. |
| `tor` | `tor` | lyra-net | SOCKS proxy for anonymous web access |

### GPU Auto-Detection

Lyra automatically detects GPU availability at startup:
- **GPU detected** (`nvidia-smi` available): GPU overlay files are applied, enabling CUDA acceleration
- **No GPU**: Runs in CPU mode with a warning logged; fully functional but slower (20-100x)

The compose scripts (`scripts/lib/compose.sh`) handle this automatically via overlay files (`podman-compose.gpu.yml` / `docker-compose.gpu.yml`).

### Networks

| Network | Type | Purpose |
|---------|------|---------|
| `lyra-net` | Bridge | External-capable. Used by proxy and tor. |
| `lyra-internal` | Internal | Isolated (no internet). Ollama and ML only communicate with proxy. Prevents data exfiltration. |

## Data Flow

Per [ADR-0015](adr/0015-unified-search-sources.md), all queries execute both Browser SERP and Academic APIs in parallel, with identifier extraction enabling cross-source enrichment.

```mermaid
flowchart TB
    Query["User Query"]
    MCP["MCP Client<br/>(Cursor)"]
    Server["MCP Server<br/>(Host)"]
    Queue["Search Queue"]
    
    subgraph Parallel["Parallel Search (ADR-0015)"]
        Chrome["Chrome<br/>(Browser SERP)"]
        Academic["Academic APIs<br/>(S2, OpenAlex)"]
    end
    
    Internet((Internet))
    
    IDExtract["ID Extractor<br/>(DOI/PMID/arXiv)"]
    IDResolve["ID Resolver<br/>(PMID→DOI, arXiv→DOI)"]
    Dedup["CanonicalPaperIndex<br/>(Deduplication)"]
    
    subgraph WebFetch["Web Fetch"]
        Fetch["HTTP Fetch<br/>(SERP-only entries)"]
        Tor["Tor Proxy<br/>(Anonymous)"]
    end
    Abstract["Abstract Persistence<br/>(Academic papers)"]
    
    Extract["Content Extraction<br/>(trafilatura)"]
    Ollama["Ollama<br/>(Claim Extraction)"]
    ML["ML<br/>(Embed/NLI)"]
    Graph["Evidence Graph<br/>(SQLite)"]
    
    CitationJob["Citation Graph Job<br/>(Deferred)"]
    
    Query --> MCP --> Server --> Queue
    Queue --> Chrome & Academic
    Chrome --> Internet
    Academic --> Internet
    
    Chrome --> IDExtract
    IDExtract -->|"PMID/arXiv"| IDResolve
    IDResolve -->|"DOI lookup"| Academic
    
    IDExtract --> Dedup
    Academic --> Dedup
    
    Dedup -->|"No abstract"| Fetch
    Dedup -->|"Has abstract"| Abstract
    
    Fetch --> Internet
    Fetch -.->|"optional"| Tor
    Tor --> Internet
    Internet --> Extract
    Extract --> Ollama
    
    Abstract --> Ollama
    Ollama --> ML
    ML --> Graph
    
    Abstract --> CitationJob
    CitationJob --> Academic
```

**Key flows:**
1. **Parallel search**: Browser SERP and Academic APIs run simultaneously
2. **ID extraction**: SERP URLs are parsed for DOI/PMID/arXiv identifiers
3. **ID resolution**: Non-DOI identifiers are resolved to DOI via Semantic Scholar
4. **Academic API complement**: SERP entries with identifiers are enriched with academic metadata
5. **Deduplication**: `CanonicalPaperIndex` merges results from both sources
6. **Web Fetch First**: Entries without abstracts are fetched before citation graph processing
7. **Citation Graph**: Academic papers trigger deferred `CITATION_GRAPH` jobs

## Security Model

See [ADR-0006: 8-Layer Security Model](adr/0006-eight-layer-security-model.md) for details.

Key points:
- **Network Isolation**: Ollama/ML containers have no internet access
- **GPU Isolation**: When GPU is available, shared via CDI/runtime with no direct host access
- **Data Isolation**: Evidence graph is local-only
- **Prompt Injection Defense**: Isolated inference prevents exfiltration

## Directory Structure

```
lyra/
├── containers/           # Container definitions
│   ├── Dockerfile        # proxy container (custom)
│   ├── Dockerfile.ml     # ml container (custom)
│   ├── podman-compose.yml        # Base compose (CPU mode)
│   ├── podman-compose.gpu.yml    # GPU overlay (auto-applied when GPU detected)
│   ├── docker-compose.yml        # Base compose (CPU mode)
│   └── docker-compose.gpu.yml    # GPU overlay (auto-applied when GPU detected)
│   # Note: ollama uses ollama/ollama:latest, tor uses dperson/torproxy:latest
│   # (official images, no custom Dockerfile needed)
├── scripts/              # Shell scripts for operations
├── src/                  # Python source code
├── config/               # Configuration files
├── data/                 # SQLite database, cache
├── models/               # ML models (ollama, huggingface)
└── logs/                 # Application logs
```

## Related

- [ADR Index](adr/index.md) - Full list of Architecture Decision Records with multiple views
