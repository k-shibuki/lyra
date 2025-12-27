# ADR-0014: Browser SERP Resource Control

## Date
2025-12-25

## Status
Accepted (2025-12-25: TabPool + EngineRateLimiter implemented)

## Context

ADR-0010 specifies that `SearchQueueWorker` processes searches with 2 parallel workers. Browser SERP fetching has the following **local resource contention**:

| Resource | Constraint | Reason |
|----------|------------|--------|
| CDP Profile | 1 session at a time | Playwright persistent context cannot be shared |
| Fingerprint | Consistency required | Simultaneous access with different profiles risks bot detection |
| Tabs/Memory | Finite | More tabs = more memory pressure |

### Current Control

```python
# browser_search_provider.py:159
self._rate_limiter = asyncio.Semaphore(1)  # Global 1 parallel
```

**Problems:**
1. **Excessive Restriction**: Serializes even simultaneous requests to different engines (DuckDuckGo, Mojeek)
2. **Scalability Issues**: Becomes bottleneck when implementing pagination (multi-page fetch)
3. **Resource Inefficiency**: All engines processed sequentially in 1 tab

### Related ADRs

- **ADR-0013**: Global rate limits for academic APIs (Semantic Scholar, OpenAlex)
- **This ADR**: Browser SERP (local resource) contention control

Both share "resource contention control" as a theme, but resource characteristics and solutions differ, hence separate ADRs.

## Decision

**Introduce TabPool (tab management) to structurally eliminate browser operation contention (simultaneous operations on same Page).**

> **Important**: The current `BrowserSearchProvider` shares a single `page` and executes `goto()` etc.
> "Per-engine Semaphore" alone can still cause **simultaneous operations on the same Page**. First guarantee **correctness (eliminate contention)**.

### Design Principles

1. **Pages are not shared**: Browser operations for one search are confined to "borrowed tab (Page)"
2. **TabPool centralizes limit management**: Start with `max_tabs=1` and increase gradually
3. **Per-engine rate control**: QPS (min_interval) and concurrency controlled per engine
4. **Configuration responsibility separation**:
   - **Engine QPS/parallelism**: `config/engines.yaml` (Engine policy)
   - **URL templates/selectors**: `config/search_parsers.yaml` (Parser)

### Implementation

#### Phase 1: TabPool (max_tabs=1) for Correctness (Behavior unchanged)

```python
class BrowserSearchProvider:
    def __init__(self, ...):
        # BrowserContext is shared, but Page is not
        self._tab_pool = TabPool(max_tabs=1)  # Phase 1: keep behavior stable
        self._engine_locks: dict[str, asyncio.Semaphore] = {}  # per-engine concurrency cap (default 1)
    
    def _get_engine_lock(self, engine: str) -> asyncio.Semaphore:
        if engine not in self._engine_locks:
            self._engine_locks[engine] = asyncio.Semaphore(1)
        return self._engine_locks[engine]
    
    async def search(self, query: str, engine: str, ...) -> SearchResponse:
        # 1) Engine-level concurrency gate
        async with self._get_engine_lock(engine):
            # 2) Acquire a tab (Page) to avoid shared-page contention
            tab = await self._tab_pool.acquire(self._context)
            try:
                return await self._search_impl_on_page(tab, query, engine, ...)
            finally:
                self._tab_pool.release(tab)
```

**Effect:**
- **Correctness**: Eliminates simultaneous `goto()` etc. on same Page
- **Behavior Maintained**: `max_tabs=1` keeps parallelism same as current (safe introduction)
- **Future Extension**: Parallelization via `max_tabs>1` can be enabled via config gradually

#### Phase 2: TabPool Extension (max_tabs>1) for Increased Parallelism (Gradual, Measurement-based)

Considered when multi-pagination support is added:

```python
class TabPool:
    """Manage multiple browser tabs for parallel SERP fetching."""
    
    def __init__(self, max_tabs: int = 3):
        self._tabs: list[Page] = []
        self._available = asyncio.Semaphore(max_tabs)
    
    async def acquire(self) -> Page:
        """Acquire a tab from the pool."""
        await self._available.acquire()
        return self._get_or_create_tab()
    
    def release(self, tab: Page) -> None:
        """Release a tab back to the pool."""
        self._available.release()
```

**Note**: Increasing `max_tabs` in Phase 2 raises bot detection/memory/instability risks.
First complete Phase 1 (correctness guarantee), monitor CAPTCHA rate/success rate/latency, then gradually release.

### Configuration

Per-engine limits use `config/engines.yaml` (Engine policy):

```yaml
duckduckgo:
  # ... engine policy ...
  min_interval: 2.0
  concurrency: 1

mojeek:
  min_interval: 4.0
  concurrency: 1
```

## Consequences

### Positive

1. **Correctness Guarantee**: Structurally eliminates Page sharing contention
2. **Gradual Parallelization**: Parallelism adjustable just by raising `max_tabs`
3. **Pagination Ready**: Multi-page SERP fetch won't "fully block" other jobs
4. **Config-driven**: Per-engine QPS/parallelism centrally managed in `engines.yaml`

### Negative

1. **Complexity Increase**: Tab acquisition/release, ensure release on exception
2. **Memory Increase**: Tab/DOM holding increases with `max_tabs>1`
3. **Bot Detection Risk**: High parallelism may trigger detection

### Neutral

1. **No Academic API Changes**: Handled separately by ADR-0013
2. **No HTTP Fetch Changes**: Already protected by existing `RateLimiter`

## Alternatives Considered

### A. Maintain Global Semaphore (Status Quo)

**Rejection Reason:**
- Bottleneck when implementing pagination
- Parallel requests to different engines impossible

### B. Full Parallelism (No Locks)

**Rejection Reason:**
- Bot detection risk from consecutive requests to same engine
- Potential QPS limit violations

### C. Tab Pool Early Implementation

**Re-evaluation (This ADR's Conclusion):**
TabPool is introduced from Phase 1 not "for parallelization" but as "abstraction to avoid Page sharing contention."

## Implementation Status

**Status**: ✅ Phase 3 Implemented (2025-12-27)

### Phase 1: TabPool (max_tabs=1) + Correctness Guarantee

- `src/search/tab_pool.py`: `TabPool` + `EngineRateLimiter` implemented
- `src/search/browser_search_provider.py`: TabPool integration (max_tabs=1)
- `config/engines.yaml`: min_interval / concurrency settings added

### Phase 2: max_tabs=2 Extension (2025-12-25 Complete)

- `max_tabs=2` parallel operation tests implemented (`tests/test_tab_pool.py`)
- Config-driven concurrency support (`config/settings.yaml` configurable)
- Auto-backoff feature added (automatically reduces parallelism on CAPTCHA/403 detection)

### Phase 3: Dynamic Chrome Worker Pool (2025-12-27 Complete)

Each Worker gets **independent Chrome process, profile, and CDP port** for complete isolation.

**Design Principles:**

1. **num_workers Fully Linked**: Chrome count auto-determined from `settings.yaml`'s `num_workers`
2. **No Backward Compatibility**: Legacy single-Chrome design removed
3. **N-Scalable**: Auto-adapts when worker count increases
4. **Automatic Port Management**: Calculated as `chrome_base_port + worker_id`

**Architecture:**

```
Worker 0 ──▶ CDP:9222 ──▶ Chrome (Lyra-00) ──▶ user-data-dir/Lyra-00/
Worker 1 ──▶ CDP:9223 ──▶ Chrome (Lyra-01) ──▶ user-data-dir/Lyra-01/
Worker N ──▶ CDP:922N ──▶ Chrome (Lyra-0N) ──▶ user-data-dir/Lyra-0N/
```

**Changed Files:**

| Category | File | Changes |
|----------|------|---------|
| Config | `.env`, `.env.example` | `CHROME_PORT` → `CHROME_BASE_PORT`, `CHROME_PROFILE_PREFIX` |
| Config | `config/settings.yaml` | `chrome_port` → `chrome_base_port`, `chrome_profile_prefix` |
| Config | `src/utils/config.py` | `BrowserConfig` extended, helper functions added |
| Script | `scripts/chrome.sh` | Redesigned for pool management (start/stop/status) |
| Script | `scripts/lib/chrome/start.sh` | `start_chrome_worker_wsl/linux()` added |
| Script | `scripts/lib/chrome/pool.sh` | New: Pool management logic |
| Script | `scripts/mcp.sh` | Auto-starts Chrome Pool at startup |
| Python | `src/search/browser_search_provider.py` | Dynamic connection via `get_chrome_port(worker_id)` |
| Python | `src/crawler/fetcher.py` | Same as above |

**Config Helper Functions:**

```python
# src/utils/config.py
def get_chrome_port(worker_id: int) -> int:
    """Calculate CDP port from Worker ID"""
    return get_settings().browser.chrome_base_port + worker_id

def get_chrome_profile(worker_id: int) -> str:
    """Calculate profile name from Worker ID"""
    prefix = get_settings().browser.chrome_profile_prefix
    return f"{prefix}{worker_id:02d}"

def get_all_chrome_ports() -> list[int]:
    """Get CDP port list for all Workers"""
    base = get_settings().browser.chrome_base_port
    n = get_settings().concurrency.search_queue.num_workers
    return [base + i for i in range(n)]
```

**Makefile Commands:**

```bash
make chrome         # Show pool-wide status
make chrome-start   # Start Chrome for num_workers
make chrome-stop    # Stop all Chrome instances
make chrome-restart # Restart
```

**Shell Commands (for specific worker):**

```bash
./scripts/chrome.sh start-worker 0  # Start Chrome for Worker 0 only
./scripts/chrome.sh start-worker 1  # Start Chrome for Worker 1 only
```

### Phase 3.1: Auto-Start Race Condition Prevention (2025-12-27 Complete)

When multiple workers detect CDP unavailable simultaneously, they could all attempt to start Chrome, causing duplicate instances (e.g., 2 windows × 3 = 6 windows).

**Solution:**

1. **Global Lock**: `_chrome_start_lock` (asyncio.Lock) serializes auto-start attempts
2. **Re-check After Lock**: After acquiring lock, re-check CDP availability (another worker may have started it)
3. **Worker-Specific Start**: `chrome.sh start-worker N` starts only the specific worker's Chrome

**Implementation:**

```python
# src/search/browser_search_provider.py
_chrome_start_lock: asyncio.Lock | None = None

async def _auto_start_chrome(self) -> bool:
    lock = _get_chrome_start_lock()
    async with lock:
        # Re-check after lock (another worker may have started Chrome)
        if await _check_cdp_available(host, port):
            return True  # Already started
        
        # Start Chrome for this specific worker
        await subprocess_exec("chrome.sh", "start-worker", str(worker_id))
```

**Sequence Diagram:** See `docs/sequences/chrome_auto_start_lock.md`

**Benefits:**

1. **Complete Isolation**: Process, profile, cookies are independent
2. **Fingerprint Isolation**: Each Chrome has its own browser fingerprint
3. **Fault Isolation**: One Chrome blocked doesn't affect others
4. **Dynamic Scaling**: Auto-follows `num_workers` changes

## Related

- [ADR-0010: Async Search Queue Architecture](0010-async-search-queue.md) - Foundation for worker parallel execution
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - Academic API rate limits
