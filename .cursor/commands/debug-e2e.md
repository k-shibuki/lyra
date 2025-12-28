# debug-e2e

## Purpose

Debug E2E scenarios systematically—identify root causes, implement fixes, and verify them.

## When to use

- Executing or troubleshooting `docs/S_FULL_E2E.md` or similar E2E scenarios
- Failures spanning multiple components (MCP → Worker → DB → Browser)
- State-related bugs (unexpected DB records, queue inconsistencies)

## Inputs (attach as `@...`)

- Error message / stack trace / logs (required; paste or attach files)
- Repro steps or scenario reference (required)
- Relevant code (`@src/...`) and tests (`@tests/...`) (recommended)
- ADRs (`@docs/adr/`) for architectural context (recommended)

## Policy (rules)

Follow the debug policy here:

- `@.cursor/rules/debug-e2e.mdc`

This command focuses on concrete procedures and Lyra-specific troubleshooting.

---

## Investigation workflow

1. **Confirm symptom**: Reproduce (or explain why not reproducible). State expected vs actual.
2. **Define expected state**: Before diving in, articulate the correct DB/queue/cache state.
3. **Collect evidence**: Stack trace, logs, DB queries, environment checks.
4. **Triage errors**: Classify each error as Normal/Problem (see Error Triage below).
5. **Form hypotheses**: List candidate causes with hypothesis IDs (A, B, C, ...).
6. **Instrument & validate**: Add logs/assertions to prove or disprove each hypothesis.
7. **Pattern analysis**: Group validated findings into patterns (see Pattern Analysis below).
8. **Prioritize**: Assign P1/P2/P3—don't fix everything (see Priority Management below).
9. **Implement minimal fix**: Change the smallest amount of code that corrects the issue.
10. **Verify**: Run targeted tests + regression tests.

---

## Error Triage (Normal vs Problem)

**Critical step**: Not all errors are bugs. Before investigating, classify each error.

| Classification | Meaning | Action |
|----------------|---------|--------|
| **Normal** | Expected behavior, not a bug | Document in Known Acceptable Errors, skip |
| **Problem** | Unexpected, needs investigation | Form hypothesis, investigate |
| **Unknown** | Need more context to classify | Gather more logs, then reclassify |

### Known Acceptable Errors

These are **not bugs**—skip investigation:

| Error | Why it's normal | Source |
|-------|-----------------|--------|
| Academic API 404 | Paper doesn't exist or was deleted | DEBUG_E2E_02 |
| Profile drift (auto-repaired) | Browser fingerprint naturally changes | DEBUG_E2E_02 |
| Pipeline timeout (180s) | ADR-0002 safe stop working correctly | ADR-0002 |
| User closed browser | External action, not a bug | DEBUG_E2E_01 |
| OpenAlex 404 on `s2:xxx` IDs | S2 ID format not recognized | DEBUG_E2E_02 |

**Update this table** when you discover new "normal" errors.

---

## Hypothesis Management

### The value of rejection

**Rejecting a hypothesis is as valuable as confirming one.** It narrows the search space.

```markdown
| ID | Hypothesis | Result |
|----|------------|--------|
| H-A | Rate Limiter not shared between workers | ❌ Rejected - Singleton confirmed |
| H-B | OpenAlex ID conversion missing | ⏳ Pending - P3 |
| H-C | NoneType defense missing | ✅ Adopted - Fixed |
```

### Don't skip rejection

```
Formed → Instrumented → Validated → Adopted / ❌ Rejected
                                          ↓
                               (if Rejected) → Next hypothesis
```

**Bad**: Jump to fix without validation.
**Good**: Prove/disprove before changing code.

---

## Pattern Analysis

After triaging errors and validating hypotheses, group findings:

```markdown
### Pattern Analysis

**1. Academic API 404 Errors (124 total)**
- Classification: Normal
- Action: None (add to Known Acceptable Errors)

**2. Semantic Scholar Rate Limiting (2)**
- Classification: Problem
- Action: P2 - Increase backoff

**3. Profile Drift (2)**
- Classification: Normal (auto-repaired)
- Action: None
```

| Category | Description | Action |
|----------|-------------|--------|
| **Normal operation** | Expected errors | Document, skip |
| **Edge case** | Rare but valid | Add defensive code |
| **Design flaw** | Architectural issue | Create ADR |
| **Implementation bug** | Code doesn't match design | Fix now |

---

## Priority Management

**Don't fix everything.** Assign priorities:

| Priority | Criteria | Timeline |
|----------|----------|----------|
| **P1** | Blocks E2E, data corruption | Fix now |
| **P2** | Degrades performance, warnings | This session |
| **P3** | Optimization opportunity | Backlog |
| **Won't Fix** | Normal behavior, acceptable | Document only |

### Decision tree

```
Blocks E2E? → Yes: P1
           → No: Data inconsistency? → Yes: P1
                                    → No: UX degradation? → Yes: P2
                                                         → No: Known acceptable? → Yes: Won't Fix
                                                                                → No: P3
```

### Remaining Issues format

```markdown
| Priority | Issue | Description | Action |
|----------|-------|-------------|--------|
| P2 | S2 Rate Limiting | 2 failed after 6 retries | Increase backoff |
| P3 | API 404 Caching | 124 warnings | Cache invalid IDs |
| Won't Fix | OpenAlex S2 ID | 404 on s2:xxx | Known limitation |
```

---

## Common bug patterns

| Pattern | Symptoms | Typical Fix |
|---------|----------|-------------|
| **Async/concurrency** | Missing `await`, race condition, deadlock | Add awaits, serialize/lock, add timeouts |
| **Type/data** | `None` access, type mismatch, empty data | Guard Optional, validate inputs, handle empties |
| **Resource management** | Leaked file/connection, pool exhaustion | Use context managers, `finally`, tune pooling |
| **Error handling** | Swallowed exceptions, over-broad except | Catch specific errors, log, retry safely |
| **State inconsistency** | Orphan records, invalid status transitions | Validate state before operations, add constraints |

---

## Environment setup (run first)

```bash
# Full health check
make doctor

# Chrome CDP connection
make chrome-start
make chrome-diagnose

# Container status
make dev-up
make dev-status

# MCP Server
make mcp
```

## Log access

MCP Server logs are written to `logs/lyra_YYYYMMDD.log`:

```bash
# Show recent logs (tail -100)
make mcp-logs

# Follow logs in real-time (tail -f)
make mcp-logs-f

# Search logs by pattern
make mcp-logs-grep PATTERN="ALL_FETCHES_FAILED"
make mcp-logs-grep PATTERN="error"

# Direct file access (for advanced filtering)
tail -f logs/lyra_$(date +%Y%m%d).log | jq -r 'select(.level == "WARNING")'
```

---

## Phase-specific debugging (Lyra E2E)

### Phase A: Environment & Connection

**Goal**: MCP Server running, Chrome CDP connected, DB initialized.

| Symptom | Hypothesis | Check |
|---------|------------|-------|
| MCP Server startup failure | Port conflict, missing dependency | `make mcp` logs, `lsof -i :PORT` |
| Chrome CDP connection failure | WSL2 network issue, Chrome not running | `make chrome-diagnose` |
| DB initialization error | Migration failure | `src/storage/schema.sql`, migration logs |

### Phase B: Task Creation & Search Queue

**Goal**: `create_task` → `queue_searches` → Worker processing works.

| Symptom | Hypothesis | Check |
|---------|------------|-------|
| Jobs not queued | `queue_searches` not inserting | Query `jobs` table |
| Worker not processing | Worker not started, lock contention | `make dev-logs-f`, query `jobs.status` |
| Search API errors | Rate limiter, API key issues | `adapters` table, API response logs |

### Phase C: Page Fetch & Extract

**Goal**: SERP results → page fetch → text extraction works.

| Symptom | Hypothesis | Check |
|---------|------------|-------|
| No pages fetched | TabPool exhausted, CAPTCHA block | `intervention_queue` table, browser logs |
| Extraction fails | LLM error, parse failure | Extractor logs, `fragments` table |

### Phase D: NLI & Evidence Graph

**Goal**: Fragment-Claim NLI judgment, graph construction works.

| Symptom | Hypothesis | Check |
|---------|------------|-------|
| NLI not running | Model not loaded, container down | `make dev-status`, model logs |
| Graph empty | No claims, no edges created | `claims`, `edges` tables |

### Phase E: Materials & Report

**Goal**: `get_materials` returns correct evidence graph.

| Symptom | Hypothesis | Check |
|---------|------------|-------|
| Empty materials | No claims for task_id | `claims` table with task filter |
| Graph serialization error | Invalid edge references | `edges` foreign key integrity |

---

## State validation queries

### intervention_queue

```sql
-- Orphaned auth items (task doesn't exist)
SELECT iq.* FROM intervention_queue iq
LEFT JOIN tasks t ON iq.task_id = t.id
WHERE t.id IS NULL AND iq.status = 'pending';

-- Expired but still pending
SELECT * FROM intervention_queue
WHERE status = 'pending' AND expires_at < datetime('now');

-- After stop_task: should be cancelled
SELECT * FROM intervention_queue
WHERE task_id = ? AND status NOT IN ('cancelled', 'resolved', 'skipped');
```

### jobs

```sql
-- Stuck jobs (pending for too long)
SELECT * FROM jobs
WHERE status = 'pending' AND created_at < datetime('now', '-1 hour');

-- Jobs without matching task
SELECT j.* FROM jobs j
LEFT JOIN tasks t ON j.task_id = t.id
WHERE t.id IS NULL;
```

### fragments / edges

```sql
-- Fragments without page
SELECT f.* FROM fragments f
LEFT JOIN pages p ON f.page_id = p.id
WHERE p.id IS NULL;

-- Edges with invalid fragment reference
SELECT e.* FROM edges e
LEFT JOIN fragments f ON e.fragment_id = f.id
WHERE f.id IS NULL;
```

---

## S_FULL_E2E execution checklist

### Preparation

- [ ] `make doctor` passed
- [ ] `make chrome-start` succeeded
- [ ] `make dev-up` containers running
- [ ] `make mcp` server started

### Task execution

- [ ] `create_task` returns task_id
- [ ] `queue_searches` queues jobs
- [ ] `get_status(wait=30)` shows progress
- [ ] If `pending_auth_count > 0`: `get_auth_queue` → `resolve_auth`
- [ ] Repeat `get_status` until searches complete

### Materials retrieval

- [ ] `get_materials(include_graph=true)` returns data
- [ ] Evidence graph structure is valid
- [ ] Sample 30 NLI judgments for expert review

### Cleanup

- [ ] `stop_task` stops the task
- [ ] Remove debug instrumentation (after verification)

---

## Useful commands

```bash
# Check DB lock holders
fuser data/lyra.db

# Kill zombie test processes
make test-kill-all

# Query DB directly
timeout 10 sqlite3 data/lyra.db "SELECT * FROM tasks LIMIT 5;"

# MCP Server logs
make mcp-logs                      # Recent 100 lines
make mcp-logs-f                    # Follow (real-time)
make mcp-logs-grep PATTERN="error" # Search by pattern

# Container logs
make dev-logs-f

# Run specific tests
make test TARGET=tests/test_specific.py
make test-check RUN_ID=<run_id>
```

---

## Output (response format)

- **Symptom**: expected vs actual
- **Expected state**: what DB/queue should look like
- **Root cause**: what, where, why
- **Fix**: summary + files changed
- **Verification**: what was run/checked and results

---

## Debug report template

Create a report in `docs/debug/DEBUG_E2E_NN.md` for significant debugging sessions:

```markdown
# E2E Debug Report (YYYY-MM-DD)

## Summary
One-line result: ✅ Resolved / ❌ Ongoing / ⚠️ Partial

## Symptoms
- Expected: ...
- Actual: ...

## Error Analysis
| Category | Count | Classification | Cause |
|----------|-------|----------------|-------|
| Academic API 404 | 124 | Normal | Paper doesn't exist |
| Rate Limiting | 2 | Problem | Too many requests |

## Hypotheses and Results
| ID | Hypothesis | Result |
|----|------------|--------|
| H-A | Rate Limiter not shared | ❌ Rejected - Singleton confirmed |
| H-B | NoneType defense missing | ✅ Adopted - Fixed |

## Pattern Analysis
**1. Academic API 404 Errors (124 total)**
- Classification: Normal
- Action: None (documented in Known Acceptable Errors)

**2. Rate Limiting (2)**
- Classification: Problem
- Action: P2 - Increase backoff

## Fixes Applied
1. `src/xxx.py`: change summary
2. `src/yyy.py`: change summary

## Verification
```bash
timeout 60 uv run python scripts/debug_xxx.py
```
Result: ✅ PASS

## Remaining Issues
| Priority | Issue | Description | Action |
|----------|-------|-------------|--------|
| P2 | S2 Rate Limiting | 2 failed | Increase backoff |
| P3 | API 404 Caching | 124 warnings | Cache invalid IDs |
| Won't Fix | OpenAlex S2 ID | 404 on s2:xxx | Known limitation |
```

---

## Reference documents

| Document | Path | Purpose |
|----------|------|---------|
| E2E scenario | `docs/S_FULL_E2E.md` | Experiment protocol |
| ADRs | `docs/adr/` | Architecture decisions |
| Schema | `src/storage/schema.sql` | Table structure |
| MCP tools | `src/mcp/server.py` | Tool definitions |
| Debug reports | `docs/debug/` | Past debugging sessions |

### Learning from past debug sessions

Before starting a new debug session, **check `docs/debug/` for similar issues**:

```bash
# List past debug reports
ls -la docs/debug/

# Search for similar symptoms
grep -r "rate limit" docs/debug/
grep -r "NoneType" docs/debug/
```

Past reports contain:
- **Known Acceptable Errors**: Don't reinvestigate
- **Proven fixes**: Patterns that worked before
- **Rejected hypotheses**: Don't repeat failed investigations

---

## Isolated debugging (when MCP Server holds DB lock)

When the MCP Server is running, it holds a WAL write lock on `data/lyra.db`. 
Direct DB writes from test scripts will hang. Use **isolated DB + debug scripts** instead.

### Debug script pattern

```bash
# Run with timeout (required to prevent hangs)
timeout 120 uv run python scripts/debug_e2e_test.py
```

The script uses `isolated_database_path()` context manager to create a temporary DB:

```python
from src.storage.isolation import isolated_database_path

async def main():
    async with isolated_database_path() as db_path:
        # Your test code here - uses temp DB, not data/lyra.db
        client = SomeAPIClient()
        result = await client.search("test query")
```

**Key benefits**:
- No DB lock conflicts with MCP Server
- Clean state for each run
- Auto-cleanup after test

### When to use isolated debugging

| Scenario | Use isolated script | Use MCP tools |
|----------|---------------------|---------------|
| API client bugs | ✅ | ❌ |
| Rate limiter issues | ✅ | ❌ |
| Parse/validation errors | ✅ | ❌ |
| DB state issues | ❌ | ✅ |
| Full E2E flow | ❌ | ✅ |

### Instrumentation logs

Debug logs are written to `.cursor/debug.log` in NDJSON format:

```bash
# View all logs as JSON array
cat .cursor/debug.log | jq -s '.'

# Filter by hypothesis ID
cat .cursor/debug.log | jq -s 'map(select(.hypothesisId == "A"))'

# Count by location
cat .cursor/debug.log | jq -s 'group_by(.location) | map({loc: .[0].location, count: length})'

# Clear logs before new run
> .cursor/debug.log
```

### Adding instrumentation

Use `#region agent log` markers for easy cleanup:

```python
# #region agent log
import json
with open("/home/statuser/lyra/.cursor/debug.log", "a") as f:
    f.write(json.dumps({
        "location": "src/module.py:func",
        "message": "description",
        "data": {"key": "value"},
        "timestamp": __import__("time").time() * 1000,
        "hypothesisId": "A"
    }) + "\n")
# #endregion
```

After debugging, search and remove all `#region agent log` blocks.

---

## Related rules

- `@.cursor/rules/debug-e2e.mdc`
- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/integration-design.mdc` (for cross-module contract issues)

