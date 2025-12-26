# ADR-0016: Unified Search Sources

## Date
2025-12-26

## Status
Accepted

## Context

The previous search pipeline classified queries as "academic" or "general" (`is_academic` flag) and routed differently:

```
Academic query detection ─┬─→ Academic API priority (S2/OpenAlex) → Use Abstract or browser fallback
                         └─→ Browser SERP priority → Academic API supplement only on identifier detection
```

### Problems

| Problem | Details |
|---------|---------|
| Detection Instability | Keyword-based detection ("paper", "doi:", site:arxiv.org, etc.) produces false positives/negatives |
| Reduced Coverage | Academic queries skip SERP, general queries skip academic API, limiting coverage |
| Code Complexity | Branching logic scattered across `_is_academic_query()`, `_expand_academic_query()`, etc. |
| Maintenance Burden | Detection condition adjustments difficult, test case combinatorial explosion |

### Insights from Measured Data

- General queries often return SERP results containing DOI/arXiv IDs
- Academic queries often have useful sources like Wikipedia/blogs in SERP
- Many papers have sufficient Abstracts, allowing Evidence without fetching

## Decision

**For all queries, always execute both Browser SERP and academic APIs (Semantic Scholar + OpenAlex) in parallel, merging and deduplicating results.**

### Unified Search Flow

```
┌─────────────────────────────────────────────────────────────┐
│ SearchPipeline._execute_unified_search()                    │
│                                                             │
│   ┌─────────────────┐     ┌─────────────────┐              │
│   │ search_serp()   │     │ AcademicSearch- │              │
│   │ (Browser SERP)  │     │ Provider.search │              │
│   └────────┬────────┘     └────────┬────────┘              │
│            │                       │                        │
│            └───────────┬───────────┘                        │
│                        ▼                                    │
│            ┌─────────────────────┐                          │
│            │ CanonicalPaperIndex │  Deduplication (DOI/title)│
│            └──────────┬──────────┘                          │
│                       ▼                                     │
│            ┌─────────────────────┐                          │
│            │ Abstract-only or    │  Per ADR-0008            │
│            │ Browser fetch       │                          │
│            └──────────┬──────────┘                          │
│                       ▼                                     │
│            ┌─────────────────────┐                          │
│            │ Citation graph      │  Only for papers with    │
│            │ (get_citation_graph)│  Abstract                │
│            └─────────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

### Deduplication Strategy

Uses `CanonicalPaperIndex` (introduced in ADR-0008):

1. **DOI Match**: Same DOI is merged (API metadata takes priority)
2. **Title Similarity**: Normalized titles with 90%+ similarity are merge candidates
3. **Source Attribution Preserved**: Track with `source: "both" | "api_only" | "serp_only"`

### Deleted Code

- `SearchPipeline._is_academic_query()` - Query detection logic
- `SearchPipeline._expand_academic_query()` - Academic query expansion
- Conditional branching in `_execute_normal_search()`

### Changed Methods

| Method | Change |
|--------|--------|
| `_execute_normal_search()` | Always calls `_execute_unified_search()` |
| `_execute_unified_search()` | Renamed from old `_execute_complementary_search()` |
| `_execute_browser_search()` | Simplified to fetch/extract only (no SERP call) |

## Consequences

### Positive

1. **Improved Coverage**: Both sources searched for all queries increases coverage
2. **Simplified Code**: No detection logic needed, improved maintainability
3. **Easier Testing**: No branching conditions, simplified test cases
4. **Consistent Behavior**: Same path regardless of query content

### Negative

1. **Increased API Consumption**: Academic API called even for general queries, more rate consumption
2. **Latency Increase**: Parallel execution still bound by slower source

### Mitigation

- **Rate Limits**: Protected by ADR-0013's global rate limiter
- **Timeouts**: Appropriate timeouts set for academic APIs
- **Fault Tolerance**: One source failure doesn't affect the other (`try/except` isolation)

## Alternatives Considered

### A. Improve Detection Logic

**Rejection Reason**: 
- Keyword/pattern matching limitations
- ML model introduction violates Zero OpEx (ADR-0001)
- "Search both" is more reliable than "is it academic?"

### B. User Selection

**Rejection Reason**:
- Increased UX burden (Cursor AI agent assumes automatic decisions)
- Forgetting to select reduces coverage

### C. Staged Fallback (SERP→API or API→SERP)

**Rejection Reason**:
- Ordering introduces delay
- Parallel is simpler and faster

## Implementation Status

**Status**: ✅ Implemented (2025-12-26)

- `src/research/pipeline.py`: Unified search flow implementation complete
- `tests/test_research.py`: `TestUnifiedDualSourceSearch` test class added
- Debug instrumentation (agent log) removed

## Related

- [ADR-0008: Academic Data Source Strategy](0008-academic-data-source-strategy.md) - Academic API selection and CanonicalPaperIndex
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - Academic API rate limits
- [ADR-0014: Browser SERP Resource Control](0014-browser-serp-resource-control.md) - Browser SERP resource control
