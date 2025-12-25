# Phase 4: Search Resource Control - Sequence Diagram

> **Related ADRs**: 
> - ADR-0013: Worker Resource Contention Control (Academic APIs)
> - ADR-0014: Browser SERP Resource Control (TabPool)
> - ADR-0015: Adaptive Concurrency Control (Auto-Backoff)

## Overview

Phase 4 implements resource control for parallel search execution:
1. **AcademicAPIRateLimiter**: Global QPS/concurrency limits for academic APIs
2. **TabPool**: Browser tab management to prevent Page sharing
3. **EngineRateLimiter**: Per-engine QPS/concurrency limits for browser SERP
4. **Auto-Backoff**: Automatic concurrency reduction on errors (429, CAPTCHA, 403)

## Propagation Map

### Concurrency Settings Flow

| Boundary | Parameter | Source | Sink |
|----------|-----------|--------|------|
| Config → Worker | `concurrency.search_queue.num_workers` | `config/settings.yaml` | `SearchQueueWorkerManager.start()` |
| Config → TabPool | `concurrency.browser_serp.max_tabs` | `config/settings.yaml` | `TabPool.__init__()` |
| Config → Backoff | `concurrency.backoff.academic_api.*` | `config/settings.yaml` | `AcademicAPIRateLimiter.report_429()` |
| Config → Backoff | `concurrency.backoff.browser_serp.*` | `config/settings.yaml` | `TabPool.report_captcha()` |

### Academic API Rate Limit Flow

| Boundary | Parameter | Source | Sink |
|----------|-----------|--------|------|
| Config → Limiter | `rate_limit.min_interval_seconds` | `config/academic_apis.yaml` | `AcademicAPIRateLimiter.acquire()` |
| Config → Limiter | `rate_limit.max_parallel` | `config/academic_apis.yaml` | `AcademicAPIRateLimiter.acquire()` |
| Limiter → Client | acquire/release | `BaseAcademicClient.search()` | `SemanticScholarClient._search_impl()` |

### Browser SERP Resource Flow

| Boundary | Parameter | Source | Sink |
|----------|-----------|--------|------|
| Config → Engine | `min_interval`, `concurrency` | `config/engines.yaml` | `EngineRateLimiter._get_engine_config()` |
| Pool → Provider | `TabPool.acquire()` | `BrowserSearchProvider.search()` | Playwright `Page` operations |

## Sequence Diagrams

### 1. Academic API Search with Rate Limiting

```mermaid
sequenceDiagram
    participant W as SearchQueueWorker
    participant P as SearchPipeline
    participant AP as AcademicSearchProvider
    participant RL as AcademicAPIRateLimiter
    participant S2 as SemanticScholarClient

    W->>P: search_action(query)
    P->>AP: search(query)
    AP->>AP: _get_client("semantic_scholar")
    AP->>S2: search(query, limit)
    
    Note over S2,RL: Rate limiting in BaseAcademicClient.search()
    S2->>RL: acquire("semantic_scholar")
    
    alt Backoff Active
        RL-->>RL: Wait for effective_max_parallel slot
    end
    
    RL->>RL: Enforce min_interval (QPS)
    RL-->>S2: Slot acquired
    
    S2->>S2: _search_impl(query, limit)
    S2-->>RL: release("semantic_scholar")
    S2-->>AP: AcademicSearchResult
    AP-->>P: SearchResponse
    P-->>W: result dict
```

### 2. Browser SERP Search with TabPool

```mermaid
sequenceDiagram
    participant W as SearchQueueWorker
    participant P as SearchPipeline
    participant BP as BrowserSearchProvider
    participant TP as TabPool
    participant ER as EngineRateLimiter
    participant PW as Playwright Page

    W->>P: search_action(query)
    P->>BP: search(query, options)
    BP->>BP: _ensure_browser()
    
    Note over BP,ER: ADR-0014: Acquire engine rate limit first
    BP->>ER: acquire("duckduckgo")
    ER->>ER: Enforce min_interval + concurrency
    ER-->>BP: Engine slot acquired
    
    Note over BP,TP: ADR-0014: Then acquire tab from pool
    BP->>TP: acquire(context)
    
    alt effective_max_tabs reached
        TP-->>TP: Wait for tab slot
    end
    
    TP-->>BP: Page (tab) acquired
    
    Note over BP,PW: Operations on borrowed tab
    BP->>PW: goto(search_url)
    BP->>PW: wait_for_load_state()
    BP->>PW: content()
    
    BP->>TP: release(tab)
    BP->>ER: release("duckduckgo")
    
    alt CAPTCHA Detected
        BP->>TP: report_captcha()
        Note over TP: Reduce effective_max_tabs (ADR-0015)
    end
    
    BP-->>P: SearchResponse
    P-->>W: result dict
```

### 3. Auto-Backoff on 429 Error

```mermaid
sequenceDiagram
    participant C as AcademicClient
    participant RL as AcademicAPIRateLimiter
    participant API as External API

    C->>RL: acquire("semantic_scholar")
    RL-->>C: Slot acquired
    
    C->>API: HTTP Request
    API-->>C: 429 Too Many Requests
    
    C->>RL: report_429("semantic_scholar")
    
    Note over RL: Backoff triggered (ADR-0015)
    RL->>RL: effective_max_parallel -= decrease_step
    RL->>RL: backoff_active = True
    RL->>RL: last_429_time = now()
    
    C->>RL: release("semantic_scholar")
    
    Note over RL: Recovery check on next acquire()
    C->>RL: acquire("semantic_scholar")
    
    alt time_since_429 >= recovery_stable_seconds
        RL->>RL: effective_max_parallel += 1
        Note over RL: Gradual recovery
    end
```

### 4. Parallel Workers with Resource Control

```mermaid
sequenceDiagram
    participant M as SearchQueueWorkerManager
    participant W0 as Worker-0
    participant W1 as Worker-1
    participant TP as TabPool (max_tabs=2)
    participant RL as AcademicAPIRateLimiter

    M->>W0: start()
    M->>W1: start()
    
    par Worker-0 job
        W0->>TP: acquire(context)
        TP-->>W0: Tab-1
        W0->>W0: Execute search on Tab-1
    and Worker-1 job
        W1->>TP: acquire(context)
        TP-->>W1: Tab-2
        W1->>W1: Execute search on Tab-2
    end
    
    Note over TP: Both tabs in use (max_tabs=2)
    
    par Release
        W0->>TP: release(Tab-1)
    and
        W1->>TP: release(Tab-2)
    end
```

## Integration Points

### Config-Driven Concurrency (ADR-0015)

```yaml
# config/settings.yaml
concurrency:
  search_queue:
    num_workers: 2        # Loaded by SearchQueueWorkerManager
  browser_serp:
    max_tabs: 2           # Loaded by get_tab_pool()
  backoff:
    academic_api:
      recovery_stable_seconds: 60
      decrease_step: 1
    browser_serp:
      decrease_step: 1
```

### Code Integration Points

| Component | File | Integration |
|-----------|------|-------------|
| Worker Manager | `src/scheduler/search_worker.py` | Reads `num_workers` from config |
| TabPool | `src/search/tab_pool.py` | Reads `max_tabs` from config |
| Academic Rate Limiter | `src/search/apis/rate_limiter.py` | Reads from `config/academic_apis.yaml` |
| Engine Rate Limiter | `src/search/tab_pool.py` | Reads from `config/engines.yaml` |
| Browser Provider | `src/search/browser_search_provider.py` | Uses TabPool + EngineRateLimiter |
| Academic Provider | `src/search/academic_provider.py` | Uses AcademicAPIRateLimiter (via base class) |

## Verification Checklist

- [x] Config loaded correctly (`get_settings().concurrency`)
- [x] Worker count matches config
- [x] TabPool max_tabs matches config
- [x] Academic API rate limiting enforced
- [x] Browser SERP uses TabPool (not shared page)
- [x] Auto-backoff triggers on 429/CAPTCHA/403
- [x] Recovery works after stable period

## Related Files

- `tests/test_tab_pool.py` - TabPool unit tests
- `tests/test_concurrency_config.py` - Concurrency config tests
- `tests/test_concurrency_wiring.py` - Concurrency wiring tests
- `docs/adr/0013-worker-resource-contention.md`
- `docs/adr/0014-browser-serp-resource-control.md`
- `docs/adr/0015-adaptive-concurrency-control.md`

