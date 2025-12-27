# ADR-0008: Academic Data Source Strategy

## Date
2025-11-28

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

```
[1] Semantic Scholar API
    ↓ On rate limit or not found
[2] OpenAlex API
    ↓ If not found
[3] DOI/URL direct access
```

### Semantic Scholar (S2) Selection Reasons

| Aspect | Details |
|--------|---------|
| Citation Graph | High-quality citation/reference relationships |
| Abstract | Abstracts available for nearly all papers |
| TL;DR | AI-generated summaries included |
| API Quality | RESTful, well-documented |
| Free Tier | 5,000 requests/5 minutes |

### OpenAlex Complementary Reasons

| Aspect | Details |
|--------|---------|
| Coverage | Broader than S2 (250M+ works) |
| Rate Limit | Effectively unlimited (polite pool) |
| Institution Info | Rich author affiliation data |
| Open | Completely open data |

### Citation Graph Construction

```python
# Get citations from S2
paper = s2_client.get_paper(paper_id)
references = paper.references      # Papers this paper cites
citations = paper.citations        # Papers citing this paper

# Integrate into Evidence Graph (see ADR-0005)
for ref in references:
    graph.add_edge(
        from_node=paper.fragment_id,
        to_node=ref.fragment_id,
        edge_type="CITES",
        citation_source="s2"
    )
```

### Fallback Strategy

```python
async def get_paper_metadata(identifier: str) -> PaperMetadata:
    # 1. Try S2
    try:
        return await s2_client.get_paper(identifier)
    except RateLimitError:
        await asyncio.sleep(backoff)
        # 2. Fallback to OpenAlex
        return await openalex_client.get_work(identifier)
    except NotFoundError:
        # 3. Direct DOI resolution
        if is_doi(identifier):
            return await resolve_doi_metadata(identifier)
        raise
```

### Preprint Handling

| Source | Review Status | Confidence Impact |
|--------|--------------|-------------------|
| arXiv | Unreviewed | Reflected in uncertainty (higher) |
| bioRxiv/medRxiv | Unreviewed | Reflected in uncertainty (higher) |
| Published Journal | Peer-reviewed | Normal |

```python
# Record review status in metadata
if paper.venue in ["arXiv", "bioRxiv", "medRxiv"]:
    paper.peer_reviewed = False
    paper.preprint = True
```

**Implementation note (2025-12-27)**:
- The current implementation stores academic metadata in `pages.paper_metadata` and may surface `year/doi/venue`
  into evidence materials, but it does **not** yet explicitly model `peer_reviewed/preprint` nor adjust
  Bayesian uncertainty based on venue class.
- Treating preprints as higher-uncertainty sources remains a desirable behavior, but it should be implemented
  carefully to avoid re-introducing coarse domain/venue bias (see ADR-0005).

### API Client Configuration

```python
# Semantic Scholar
S2_CONFIG = {
    "base_url": "https://api.semanticscholar.org/graph/v1",
    "rate_limit": 5000,  # per 5 minutes
    "rate_window": 300,
    "timeout": 30,
    "retry_count": 3
}

# OpenAlex
OPENALEX_CONFIG = {
    "base_url": "https://api.openalex.org",
    "polite_pool_email": "lyra@example.com",  # Required
    "timeout": 30,
    "retry_count": 3
}
```

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

## References
- `src/search/apis/semantic_scholar.py` - Semantic Scholar API client
- `src/search/apis/openalex.py` - OpenAlex API client
- `src/search/academic_provider.py` - Academic API integration provider
- `config/academic_apis.yaml` - API configuration
- ADR-0005: Evidence Graph Structure
