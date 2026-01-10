# ADR-0008: Academic Data Source Strategy

## Date
2025-11-28 (Updated: 2026-01-10)

## Context

Academic information retrieval faces these challenges:

| Challenge | Details |
|-----------|---------|
| API Limitations | Many academic DBs are paid or rate-limited |
| Coverage | Single source provides insufficient comprehensiveness |
| Reliability | Need to distinguish preprints from peer-reviewed |
| Zero OpEx | ADR-0001 prohibits paid APIs |

Comparison of major academic data sources:

| Source | Papers | API | Citation Data | Cost |
|--------|--------|-----|---------------|------|
| Semantic Scholar | 200M+ | Free (limited) | Yes | Free |
| OpenAlex | 250M+ | Free (unlimited) | Yes | Free |
| Google Scholar | Largest | None (scraping required) | Yes | Free (ToS risk) |
| Crossref | 140M+ | Free | Limited | Free |
| PubMed | 36M+ | Free | No | Free |
| Scopus/WoS | Large | Paid | Yes | Paid |

## Decision

**Adopt a 2-tier strategy with Semantic Scholar (S2) as primary and OpenAlex as secondary.**

### Data Source Hierarchy

Two entry points converge on a shared API layer:

```mermaid
flowchart LR
    subgraph ENTRY["Entry Points"]
        direction TB
        DQ["Direct Query<br/>(keyword search)"]
        SERP["SERP URL<br/>(pubmed/pmc/arxiv/doi.org/<br/>openalex.org/semanticscholar.org)"]
    end

    subgraph RESOLVE["ID Resolution"]
        direction TB
        EX["IdentifierExtractor"]
        IR["IDResolver"]
        EX -->|"PMID/PMCID/arXiv"| IR
    end

    subgraph API["Academic API Layer"]
        direction TB
        S2{"Semantic Scholar"}
        OA{"OpenAlex"}
        S2 -->|"Rate Limit<br/>/ Not Found"| OA
    end

    OUT["Paper Metadata<br/>+ Citations"]

    DQ --> S2
    SERP --> EX
    EX -->|"DOI (direct)"| S2
    EX -->|"openalex:W..."| OA
    EX -->|"s2:paperId"| S2
    IR -->|DOI| S2

    S2 -->|Success| OUT
    OA --> OUT
```

| Entry Point | Use Case | Processing |
|-------------|----------|------------|
| Direct Query | Academic search, citation graph | Direct to S2/OpenAlex |
| SERP URL | Metadata complement for browser results | Extract ID → Resolve → API |
| OpenAlex/S2 URL | Provider-native URLs from SERP | Direct to respective API (no DOI conversion) |

### Semantic Scholar (S2) Selection Reasons

| Aspect | Details |
|--------|---------|
| Citation Graph | High-quality citation/reference relationships |
| Abstract | Abstracts available for nearly all papers |
| TL;DR | AI-generated summaries included |
| API Quality | RESTful, well-documented |
| Free Tier | Rate-limited (see `config/academic_apis.yaml` for current limits) |

### Abstract-Only Strategy

Lyra retrieves abstracts rather than full text for academic papers. This is an intentional design choice:

| Reason | Details |
|--------|---------|
| Context Window Efficiency | Full papers (5-20K words) would overwhelm LLM context; abstracts provide dense signal |
| Attention Control | LLMs struggle to locate relevant passages in long documents |
| Navigation vs Reading | Researchers naturally read important papers in full; Lyra's role is discovery |
| API Availability | Abstracts are consistently available via S2/OpenAlex; full text requires publisher access |

This aligns with ADR-0002's three-layer model: Lyra discovers, AI synthesizes, humans evaluate primary sources.

### OpenAlex Complementary Reasons

| Aspect | Details |
|--------|---------|
| Coverage | Broader than S2 (250M+ works) |
| Rate Limit | Effectively unlimited (polite pool) |
| Institution Info | Rich author affiliation data |
| Open | Completely open data |

### Provider-Native URL Handling

SERP results may include URLs directly from OpenAlex (`openalex.org/W...`) or Semantic Scholar (`semanticscholar.org/paper/.../`). These are routed directly to their respective APIs without DOI conversion:

| URL Pattern | Extracted ID | Target API | DOI Conversion |
|-------------|--------------|------------|----------------|
| `openalex.org/W2741809807` | `openalex:W2741809807` | OpenAlex | Not needed |
| `semanticscholar.org/paper/.../abc123...` | `s2:abc123...` (40-hex) | Semantic Scholar | Not needed |
| `doi.org/10.xxx/...` | DOI | S2 (primary) | Already DOI |
| `pubmed.ncbi.nlm.nih.gov/123` | PMID | S2 via IDResolver | Required |
| `pmc.ncbi.nlm.nih.gov/articles/PMC123456` | PMCID | S2 via IDResolver | Required (NCBI idconv API) |

**Note on PMCID**: PMC (PubMed Central) IDs are resolved via NCBI's idconv API, which returns both PMID and DOI when available. The DOI is used directly for academic API queries when present.

**Minimal-Calls Strategy**: When complementing SERP results with academic API data:

1. **Primary call**: Route to the API matching the extracted ID type (OpenAlex ID → OpenAlex, S2 ID → S2, DOI → S2)
2. **Secondary call**: Only if primary returns `None` or missing abstract, **and** a DOI is available, query the other API using DOI
3. **Index merge**: SERP entries with provider-native IDs are merged into DOI-based canonical entries when API returns a DOI

This minimizes API calls while maximizing metadata extraction. See `src/research/pipeline.py:_complement_serp_result()` for implementation.

### Citation Graph Construction

Citation relationships from S2 API are integrated into the Evidence Graph (see ADR-0005).

```mermaid
flowchart LR
    P[Paper] -->|references| R1[Referenced Paper 1]
    P -->|references| R2[Referenced Paper 2]
    C1[Citing Paper 1] -->|cites| P
    C2[Citing Paper 2] -->|cites| P
```

Edges are stored in the `edges` table with type `CITES`, enabling citation relationship tracking.

### Fallback Strategy

Fallback behavior executes in the following order:

| Order | Condition | Action |
|-------|-----------|--------|
| 1 | Provider-native ID (OpenAlex/S2) | Route directly to matching API |
| 2 | S2 success | Return result |
| 3 | S2 rate limited | Backoff, then try OpenAlex |
| 4 | S2 not found | Try OpenAlex |
| 5 | Both not found + DOI available | Resolve via DOI URL |
| 6 | All failed | Return error |

**Note**: For SERP complementation, secondary API calls are only made when:
- Primary API returns `None` or paper lacks abstract, **and**
- A DOI is available (either from identifier or from primary API response)

See `src/search/academic_provider.py` for parallel search and merge logic.

### Preprint Handling

| Source | Review Status |
|--------|--------------|
| arXiv | Unreviewed |
| bioRxiv/medRxiv | Unreviewed |
| Published Journal | Peer-reviewed |

When a paper's `venue` is a preprint server (arXiv, bioRxiv, medRxiv, etc.), the metadata includes review status for display purposes. However, per ADR-0005's principle, **confidence calculation does not use venue-based weighting** to avoid bias.

### API Client Configuration

API settings are managed in `config/academic_apis.yaml`. Key configuration items:

| API | Key Settings | Rate Limit (anonymous) | Rate Limit (with key/email) |
|-----|--------------|------------------------|----------------------------|
| Semantic Scholar | base_url, rate_limit, timeout, priority | 0.33 req/s (shared pool) | 0.9 req/s (dedicated) |
| OpenAlex | base_url, rate_limit, polite_pool User-Agent, priority | 6 req/s | 8 req/s (polite pool) |
| NCBI | base_url, rate_limit, timeout, priority | 2 req/s | 8 req/s (with API key) |

Rate limits and retry policies follow ADR-0013 (Worker Resource Contention Control).

Configure API keys/emails in `.env` (see `.env.example` for details):
- `LYRA_ACADEMIC_APIS__APIS__SEMANTIC_SCHOLAR__API_KEY`
- `LYRA_ACADEMIC_APIS__APIS__OPENALEX__EMAIL`
- `LYRA_ACADEMIC_APIS__APIS__NCBI__API_KEY`

## Consequences

### Positive
- **Zero OpEx Maintained**: Both APIs are free
- **High Coverage**: 2 tiers cover most academic papers
- **Citation Graph**: Strengthened evidence relationships
- **Redundancy**: Operation continues if one fails

### Negative
- **API Dependency**: Affected by external service changes
- **Rate Limits**: Waiting required for bulk retrieval
- **Data Quality**: Auto-extracted data contains errors

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Google Scholar Scraping | Maximum coverage | ToS violation risk, unstable | Rejected |
| Crossref Only | Stable | Insufficient citation data | Rejected |
| Scopus/WoS | High quality | Paid (Zero OpEx violation) | Rejected |
| PubMed Only | Strong in medicine | Limited coverage | Rejected |

## Related

- [ADR-0005: Evidence Graph Structure](0005-evidence-graph-structure.md) - CITES edges for citation relationships, normalized bibliographic tables
- `src/search/apis/semantic_scholar.py` - Semantic Scholar API client
- `src/search/apis/openalex.py` - OpenAlex API client
- `src/search/academic_provider.py` - Academic API integration provider
- `src/search/identifier_extractor.py` - DOI/PMID/PMCID/arXiv/OpenAlex/S2 extractor from URLs
- `src/search/id_resolver.py` - PMID/PMCID/arXiv to DOI resolver (NCBI idconv API for PMCID)
- `src/search/canonical_index.py` - SERP/API entry deduplication and merge logic
- `src/research/pipeline.py` - Search pipeline (Flow 1 implementation, `_complement_serp_result()`)
- `src/storage/works.py` - Normalized bibliographic metadata persistence
- `config/academic_apis.yaml` - API configuration
