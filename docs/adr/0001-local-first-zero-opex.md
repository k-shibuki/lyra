# ADR-0001: Local-First Architecture / Zero OpEx

## Date
2025-11-01 (Updated: 2026-01-04)

## Context

Research support tools are used over extended periods. Dependence on commercial cloud APIs introduces the following risks:

| Risk | Details |
|------|---------|
| Cost Escalation | Pay-per-use billing (potentially hundreds to thousands of dollars monthly) |
| Service Discontinuation | API provider policy changes can render tools unusable |
| Rate Limiting | Throttling when processing large volumes of academic papers |
| Privacy | Research data transmitted to external servers |
| Offline Unavailability | Complete functionality loss during network outages |

However, local execution also presents challenges:

| Challenge | Mitigation |
|-----------|------------|
| Compute Resources | Sufficient performance with ~3B parameter models |
| Setup Complexity | Simplified installation via Ollama + uv |
| Model Quality | Quality ensured by specializing in extraction tasks |

## Decision

**All processing is completed locally, reducing operational expenditure (OpEx) to zero.**

Specifically:
1. **LLM Processing**: Local models (Qwen2.5-3B, etc.) via Ollama
2. **Vector Search**: Local embedding models + SQLite FTS
3. **Web Crawling**: Playwright (local execution)
4. **Data Storage**: SQLite (local file)
5. **ML Inference**: ml container for embedding/NLI (reranker removed per ADR-0017)

### GPU Requirements

**NVIDIA GPU + CUDA environment is recommended but optional.**

| Component | GPU Requirement | Reason |
|-----------|-----------------|--------|
| Ollama (LLM) | Recommended | Practical inference speed (20-100x faster) |
| ml (Embedding/NLI) | Recommended | Batch processing performance |

**CPU Fallback**: Lyra automatically detects GPU availability at startup via `nvidia-smi`. When no GPU is detected, it runs in CPU mode with a warning logged. CPU mode is fully functional but significantly slower (suitable for testing or low-volume use).

**GPU Auto-Detection**: The compose scripts (`scripts/lib/compose.sh`) automatically apply GPU overlay files (`podman-compose.gpu.yml` / `docker-compose.gpu.yml`) when `nvidia-smi` is available. No manual configuration required.

### Exceptions (Permitted External Communication)
- Academic APIs (Semantic Scholar, OpenAlex): Free with relaxed rate limits
- Target website access: Required for crawling
- Ollama model downloads: Initial setup only

### Prohibited External Dependencies
- OpenAI API / Anthropic API (paid)
- Google Cloud / AWS / Azure (incurs charges)
- Paid CAPTCHA solving services
- SaaS vector databases (Pinecone, etc.)

## Consequences

### Positive
- **Zero OpEx**: No ongoing costs beyond electricity
- **Complete Data Sovereignty**: Research data never leaves the local machine
- **Offline Operation**: Past data available during network outages
- **Long-term Stability**: Unaffected by external service discontinuation

### Negative
- **GPU Recommended**: NVIDIA GPU + CUDA for practical speed (CPU fallback available but 20-100x slower)
- **Model Quality Constraints**: GPT-4/Claude-level reasoning not achievable
- **Storage Consumption**: Model files require tens of GB

### Design Implications
- LLM specializes in "extraction"; "reasoning" is delegated to MCP clients (see ADR-0002)
- Authentication-required sites use Human-in-the-Loop approach (see ADR-0007)

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| OpenAI API | High quality, easy | Monthly cost, external data transmission | Rejected |
| Hybrid (Local+API) | Flexible | Incurs cost, increases complexity | Rejected |
| Self-hosted Cloud | Scalable | Infrastructure operation costs | Rejected |
| CPU-Only Default | Runs without GPU | 20-100x slower | Rejected (GPU recommended, CPU fallback supported) |

## References
- Ollama: https://ollama.ai
- Qwen2.5: https://huggingface.co/Qwen
