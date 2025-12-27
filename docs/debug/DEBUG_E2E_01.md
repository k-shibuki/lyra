# E2E Debug Report (2025-12-27/28)

## Summary

✅ **Resolved** — Fixed critical bugs in Academic API clients AND metrics calculation logic.

## Symptoms

- **Expected**: E2E scenario completes with searches returning papers, references, and citations
- **Actual**: 
  - 330 errors/warnings in logs (36 ERROR, 294 WARNING)
  - 429 Rate Limit errors not retried
  - Pydantic validation failures on null author names
  - NoneType errors during paper parsing

## Error Analysis

| Category | Count | Event | Cause |
|----------|-------|-------|-------|
| API Rate Limit | 11 | Semantic Scholar search failed | 429 Too Many Requests (not retried) |
| HTTP 404 | 112 | Non-retryable exception | Paper/reference does not exist |
| HTTP 429 | 20 | Non-retryable exception | Rate limit exceeded |
| References fetch | 51 | Failed to get references | S2 API failures |
| Citations fetch | 42 | Failed to get citations | S2 API failures |
| Paper fetch | 39 | Failed to get paper | OpenAlex/S2 failures |
| OpenAlex validation | 2 | OpenAlex search failed | Pydantic: `Author.name` is None |
| Browser crashed | 8 | Browser search error | User closed browser (not a bug) |

## Hypotheses and Results

### Phase 1: API Client Issues (Dec 27)

| ID | Hypothesis | Result |
|----|------------|--------|
| A | `Author.name` required field cannot handle `display_name: null` | ✅ Adopted |
| B | `get_paper`/`get_references`/`get_citations` missing Rate Limiter | ✅ Adopted |
| C | `report_429()` not called | ⚪ Not verified (improved by fix B) |
| D | `api_retry.py` not catching `httpx.HTTPStatusError` | ✅ Adopted (root cause) |
| E | `min_interval_seconds: 3.0` insufficient | ⚪ Improved by fix B |
| G | `_parse_paper` cannot handle None values | ✅ Adopted |

### Phase 2: Metrics Calculation Issues (Dec 28)

| ID | Hypothesis | Result |
|----|------------|--------|
| H | Academic API papers not updating `ExplorationState` metrics | ✅ Adopted (root cause) |
| I | `SearchPipeline.execute()` not registering search in `ExplorationState` | ✅ Adopted |
| J | `_process_citation_graph` not calling `state.record_page_fetch()` | ✅ Adopted |
| K | `_process_citation_graph` not calling `state.record_fragment()` | ✅ Adopted |

## Fixes Applied

### Phase 1: API Client Fixes (Dec 27)

1. **`src/utils/api_retry.py`**: Added `httpx.HTTPStatusError` exception handler alongside custom `HTTPStatusError`
2. **`src/search/apis/semantic_scholar.py`**: 
   - Added Rate Limiter to `get_paper`, `get_references`, `get_citations`
   - Fixed `_parse_paper` to use `or {}` / `or 0` / `or False` patterns for null values
   - Added ValueError check for `paperId: None` entries (skip malformed references)
3. **`src/search/apis/openalex.py`**: 
   - Added Rate Limiter to `get_paper`, `get_references`, `get_citations`
   - Added fallback for author name: `display_name or raw_author_name or ""`
4. **`tests/test_utils_api_retry.py`**: Added TC-R-07 and TC-R-08 for `httpx.HTTPStatusError`

### Phase 2: Metrics Calculation Fixes (Dec 28)

5. **`src/research/pipeline.py`**: 
   - Added `state.register_search()` and `state.start_search()` in `execute()` to register pipeline-generated search IDs
   - Added `state.record_page_fetch()` calls in `_process_citation_graph` for academic papers
   - Added `state.record_fragment()` calls in `_process_citation_graph` for academic papers
   - Added same metrics tracking for citation papers in citation graph processing
6. **`scripts/debug_metrics_test.py`**: Created comprehensive metrics debugging script

## Verification

### Phase 1: API Client Verification

```bash
timeout 120 uv run python scripts/debug_e2e_test.py
```

**Result**:
```
[2] Testing Semantic Scholar get_references directly...
  References: 53 papers    ← Success
  Citations: 18 papers     ← Success
=== Debug Test Complete ===
```

**Confirmed behaviors**:
- Rate Limiter correctly acquires/releases
- `paperId: None` entries are skipped
- Null values (`externalIds`, `citationCount`, etc.) handled correctly

### Phase 2: Metrics Calculation Verification

```bash
timeout 120 uv run python scripts/debug_metrics_test.py
```

**Result** (from instrumentation logs):
```json
{"message": "Page fetch recorded", "data": {"is_primary_source": true, "pages_fetched": 56, "has_primary_source": true}}
{"message": "Fragment added - metrics updated", "data": {"harvest_rate": 1.0, "useful_fragments": 56}}
```

**Confirmed behaviors**:
- Academic papers correctly update `SearchState.pages_fetched`
- Academic papers correctly update `SearchState.useful_fragments`
- `harvest_rate` correctly calculated (1.0 = fragments/pages)
- `is_primary_source: true` for all academic papers
- `has_primary_source: true` set in search state
- `independent_sources` tracked per unique domain (18 domains)

## Remaining Issues

1. [x] Verify metrics calculation logic - ✅ Resolved
2. [ ] Full E2E scenario re-run test (awaiting MCP server restart to apply fixes)
3. [ ] Remove debug instrumentation after final verification
