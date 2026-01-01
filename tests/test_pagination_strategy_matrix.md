# Test Matrix: PaginationStrategy

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Fixed strategy, page < serp_max_pages | Equivalence – normal | should_fetch_next = True | - |
| TC-N-02 | Auto strategy, novelty_rate > min | Equivalence – normal | should_fetch_next = True | - |
| TC-N-03 | Auto strategy, harvest_rate > min | Equivalence – normal | should_fetch_next = True | - |
| TC-N-04 | Auto strategy, both rates > min | Equivalence – normal | should_fetch_next = True | - |
| TC-N-05 | Exhaustive strategy, page < serp_max_pages | Equivalence – normal | should_fetch_next = True | - |
| TC-N-06 | Novelty rate: all URLs new | Equivalence – normal | calculate_novelty_rate = 1.0 | - |
| TC-N-07 | Novelty rate: partial URLs seen | Equivalence – normal | calculate_novelty_rate = correct ratio | - |
| TC-B-01 | current_page = serp_max_pages | Boundary – max | should_fetch_next = False | - |
| TC-B-02 | current_page = serp_max_pages + 1 | Boundary – max+1 | should_fetch_next = False | - |
| TC-B-03 | current_page = 1 | Boundary – min | should_fetch_next = True (if < max) | - |
| TC-B-04 | novelty_rate = min_novelty_rate | Boundary – threshold | should_fetch_next = False | - |
| TC-B-05 | novelty_rate = min_novelty_rate - 0.001 | Boundary – threshold-1 | should_fetch_next = False | - |
| TC-B-06 | novelty_rate = min_novelty_rate + 0.001 | Boundary – threshold+1 | should_fetch_next = True | - |
| TC-B-07 | harvest_rate = min_harvest_rate | Boundary – threshold | should_fetch_next = False | - |
| TC-B-08 | harvest_rate = min_harvest_rate - 0.001 | Boundary – threshold-1 | should_fetch_next = False | - |
| TC-B-09 | harvest_rate = min_harvest_rate + 0.001 | Boundary – threshold+1 | should_fetch_next = True | - |
| TC-B-10 | new_urls = [] | Boundary – empty | calculate_novelty_rate = 0.0 | - |
| TC-B-11 | seen_urls = set() | Boundary – empty | calculate_novelty_rate = 1.0 | - |
| TC-B-12 | novelty_rate = 0.0 | Boundary – zero | should_fetch_next = False | - |
| TC-B-13 | novelty_rate = 1.0 | Boundary – max | should_fetch_next = True | - |
| TC-A-01 | novelty_rate = None | Boundary – NULL | should_fetch_next = True (no rate info) | - |
| TC-A-02 | harvest_rate = None | Boundary – NULL | should_fetch_next = True (no rate info) | - |
| TC-A-03 | Both rates = None | Boundary – NULL | should_fetch_next = True | - |
| TC-A-04 | Auto strategy, novelty_rate < min, harvest_rate OK | Equivalence – one condition fails | should_fetch_next = False | - |
| TC-A-05 | Auto strategy, novelty_rate OK, harvest_rate < min | Equivalence – one condition fails | should_fetch_next = False | - |
| TC-A-06 | Exhaustive strategy, page = serp_max_pages | Boundary – max | should_fetch_next = False | - |
| TC-A-07 | Fixed strategy, page = serp_max_pages | Boundary – max | should_fetch_next = False | - |

## Wiring/Effect Test Cases (Pagination)

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-W-01 | serp_page=2, DuckDuckGo | Wiring – URL param | URL contains offset for page 2 (s=30) | - |
| TC-W-02 | serp_page=2, Mojeek | Wiring – URL param | URL contains offset for page 2 (s=10) | - |
| TC-W-03 | serp_page=3, Startpage | Wiring – URL param | URL contains page=3 param | - |
| TC-W-04 | serp_max_pages=5 | Wiring – config | PaginationConfig.serp_max_pages=5 | - |
| TC-E-01 | serp_page=1 vs serp_page=2 | Effect – different URLs | URLs differ by offset/page | - |
| TC-E-02 | serp_max_pages in cache key | Effect – different cache | Different cache keys for different serp_max_pages | - |
| TC-E-03 | SearchOptions propagation | Effect – options passed | serp_page/serp_max_pages reach provider | - |

## Implementation Notes

- Wiring tests: Verify parameter is included in generated URL/config
- Effect tests: Verify changing parameter value changes output
- All wiring/effect tests added to:
  - `test_search_parsers.py` (URL building for DuckDuckGo, Mojeek)
  - `test_pagination_strategy.py` (PaginationConfig, cache key)
  - `test_search_provider.py` (SearchOptions validation)

## Test Summary

| File | Test Count | Coverage |
|------|------------|----------|
| `test_pagination_strategy.py` | 20 tests | PaginationStrategy + wiring/effect |
| `test_search_parsers.py::TestDuckDuckGoParser` | 12 tests | Including serp_page wiring/effect |
| `test_search_parsers.py::TestMojeekParser` | 6 tests | Including serp_page wiring/effect |
| `test_search_provider.py::TestSearchOptions` | 10 tests | Including serp_max_pages validation |

