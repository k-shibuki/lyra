# ADR-0015: Adaptive Concurrency Control (Config-driven + Safe Auto-Backoff)

## Date
2025-12-25

## Context

Lyra processes multiple jobs in parallel via `SearchQueueWorker` (ADR-0010). External/shared resources within the search pipeline have different constraints, requiring attention when increasing worker count or internal fan-out.

**Foundation introduced by ADR-0013/0014 implementations:**

- **Academic APIs (Semantic Scholar / OpenAlex)**:
  - `AcademicSearchProvider` / citation graph use `asyncio.gather()` for parallel calls
  - **ADR-0013 introduced `AcademicAPIRateLimiter`**: Enforces global QPS limit before each request, preventing exceeding
- **Browser SERP (Playwright/CDP)**:
  - **ADR-0014 introduced `TabPool(max_tabs=1)`**: Structurally eliminates Page sharing contention
- **Worker Parallelism**:
  - Currently fixed at 2 workers. Above controls ensure external constraint compliance

**This ADR's Purpose**: Define policy to make parallelism **config-adjustable** and, where possible, **auto-optimize**.

## Decision

**Parallelism is "determined by config upper limits" as a principle, with auto-optimization limited to safe direction (primarily "decreasing").**

### 1) Config-driven Upper Bounds (Explicit Upper Limits)

- **Worker**:
  - `search_queue.num_workers` (e.g., settings.yaml)
- **Academic APIs**:
  - `academic_apis.apis.<provider>.rate_limit.max_parallel`
  - `academic_apis.apis.<provider>.rate_limit.min_interval_seconds`
- **Browser SERP**:
  - `browser.serp_max_tabs` (TabPool upper limit)
  - Per-engine QPS/parallelism in `config/engines.yaml` (engine policy)

### 2) Auto-control Strategy by Resource

Different risk characteristics per resource require different auto-control policies:

#### Academic API: Auto Increase/Decrease OK

`AcademicAPIRateLimiter` (ADR-0013) enforces global QPS limit before each request, so rate limits are reliably respected even with increased parallelism.

- **Decrease**: Immediately lower `effective_max_parallel` on 429
- **Increase**: Return by 1 step after stability period (e.g., 60 seconds) up to config limit
- **Risk**: Low (protected by rate limiting)

#### Browser SERP: Conservative (No Auto Increase)

Bot detection and CAPTCHAs cannot be prevented by rate limiting. Depends on engine-side heuristics, making prediction difficult.

- **Decrease**: Lower `effective_max_tabs` when CAPTCHA/403 rate increases
- **Increase**: **Manual only** (gradually raise via config changes)
- **Risk**: Medium to high (BAN risk from bot detection)

> Note: Recommend starting browser SERP with `max_tabs=1`, manually adjusting limits after observing CAPTCHA rate and success rate.

## Consequences

### Positive

1. **Scalability**: Upper limits can be gradually raised via config (Worker/API/SERP)
2. **Safety**: Auto won't run wild causing terms violations or CAPTCHA increases
3. **Operational Ease**: Upper limits switchable per environment (local/CI/production-equivalent)

### Negative

1. **Complexity Increase**: Effective concurrency state management required
2. **Observation Dependency**: Auto-control quality depends on metrics accuracy

## Implementation Notes

- Academic APIs use "**global control (Acquire) before each request**" not "retry" as mandatory (ADR-0013)
- Browser SERP introduces TabPool(max_tabs=1) first, eliminates Page contention, then increases parallelism (ADR-0014)
- Auto-backoff observation signals reuse existing metrics (`HTTP_ERROR_429_RATE`, `CAPTCHA_RATE`, etc.), adding API/SERP measurement points

## Related

- [ADR-0010: Async Search Queue Architecture](0010-async-search-queue.md)
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - Academic API
- [ADR-0014: Browser SERP Resource Control](0014-browser-serp-resource-control.md) - SERP
- `config/academic_apis.yaml`, `config/settings.yaml`, `config/engines.yaml`
