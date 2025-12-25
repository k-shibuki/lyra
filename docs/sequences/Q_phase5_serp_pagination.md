# Phase 5: SERP Pagination Sequence

## Overview

This document describes the data flow for SERP pagination (Phase 5 of Async Architecture).

## Sequence Diagram

```mermaid
sequenceDiagram
    participant Caller
    participant search_serp as search_serp()
    participant _search_with_provider
    participant BrowserSearchProvider
    participant PaginationStrategy
    participant Parser
    participant TabPool

    Caller->>search_serp: search_serp(query, serp_max_pages=3)
    search_serp->>search_serp: _get_cache_key(query, engines, time_range, serp_max_pages)
    
    alt Cache hit
        search_serp-->>Caller: cached results
    end
    
    search_serp->>_search_with_provider: query, serp_max_pages
    _search_with_provider->>_search_with_provider: SearchOptions(serp_max_pages=3)
    _search_with_provider->>BrowserSearchProvider: search(query, options)
    
    BrowserSearchProvider->>BrowserSearchProvider: Select engine
    BrowserSearchProvider->>Parser: get_parser(engine)
    BrowserSearchProvider->>PaginationStrategy: PaginationStrategy(config)
    
    loop current_page <= max_page
        BrowserSearchProvider->>Parser: build_search_url(serp_page=current_page)
        Parser->>Parser: Calculate offset/page param
        Parser-->>BrowserSearchProvider: search_url
        
        BrowserSearchProvider->>TabPool: acquire()
        TabPool-->>BrowserSearchProvider: tab
        BrowserSearchProvider->>BrowserSearchProvider: tab.goto(search_url)
        BrowserSearchProvider->>Parser: parse(html)
        Parser-->>BrowserSearchProvider: parse_result
        BrowserSearchProvider->>TabPool: release(tab)
        
        BrowserSearchProvider->>BrowserSearchProvider: Merge results, dedupe by URL
        BrowserSearchProvider->>PaginationStrategy: calculate_novelty_rate()
        PaginationStrategy-->>BrowserSearchProvider: novelty_rate
        
        BrowserSearchProvider->>PaginationStrategy: should_fetch_next(context)
        
        alt Stop condition met
            PaginationStrategy-->>BrowserSearchProvider: False
            Note over BrowserSearchProvider: Break loop
        else Continue
            PaginationStrategy-->>BrowserSearchProvider: True
            BrowserSearchProvider->>BrowserSearchProvider: current_page++
        end
    end
    
    BrowserSearchProvider-->>_search_with_provider: SearchResponse(results)
    _search_with_provider-->>search_serp: results
    search_serp->>search_serp: Cache results
    search_serp-->>Caller: results
```

## Propagation Map

| Boundary | Parameter | Source | Transform | Sink |
|----------|-----------|--------|-----------|------|
| API | `serp_max_pages` | `search_serp()` arg | Passed as-is | `SearchOptions.serp_max_pages` |
| Options | `SearchOptions.serp_max_pages` | API | Validated (1-10) | `BrowserSearchProvider.search()` |
| Provider | `options.serp_max_pages` | Options | `max_page = serp_page + serp_max_pages - 1` | Pagination loop bound |
| Cache | `serp_max_pages` | API | Included in cache key | `_get_cache_key()` |
| Parser | `serp_page` | Loop counter | `offset = (page - 1) * results_per_page` | URL query param |
| URL | `offset` or `page` | Parser config | Depends on `pagination_type` | Search engine |
| Strategy | `novelty_rate` | Result merge | `new_urls / total_urls` | Stop condition |
| DB | `page_number` | Loop counter | Stored per item | `serp_items.page_number` |

## Stop Conditions

1. **max_pages reached**: `current_page > max_page`
2. **novelty_rate < 0.1**: Too many duplicate URLs
3. **harvest_rate < 0.05**: Too few relevant results (future)
4. **CAPTCHA/Error**: Return partial results if available

## Cache Key Format

```
query|engines|time_range|serp_max_pages={n}
```

Different `serp_max_pages` values produce different cache entries.

