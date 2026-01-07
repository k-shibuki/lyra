# debug-e2e

E2E scenario debugging. Policy: `@.cursor/rules/debug-e2e.mdc`

## Inputs

| Required | `@logs/lyra_*.log`, error/stacktrace, repro steps |
|----------|---------------------------------------------------|
| Optional | `@src/...`, `@tests/...`, `@docs/adr/` |

---

## Workflow

| Step | Action |
|------|--------|
| 1. Symptom | Reproduce, state expected vs actual |
| 2. Expected state | Define correct DB/queue/cache state |
| 3. Evidence | Collect logs, DB queries, env checks |
| 4. Triage | Classify each error as Normal/Problem |
| 5. Hypotheses | List with IDs (A, B, C...) |
| 6. Validate | Instrument, record Adopted/Rejected |
| 7. Pattern | Aggregate ERROR/WARNING from logs |
| 8. Prioritize | Assign P1/P2/P3/Won't Fix |
| 9. Fix | Minimal change |
| 10. Verify | Run tests, regression check |

---

## Triage

| Classification | Action |
|----------------|--------|
| **Normal** | Skip if known in `docs/debug/` |
| **Problem** | Form hypothesis, investigate |
| **Unknown** | Gather more logs, reclassify |

---

## Hypothesis

```
Formed → Instrumented → Validated → ✅ Adopted / ❌ Rejected
                                              ↓
                                   (Rejected) → Next
```

Rejection narrows search space. Don't fix without validation.

---

## Pattern Analysis

Aggregate ERROR/WARNING from `logs/lyra_*.log` and `.cursor/debug.log`:

| Category | Action |
|----------|--------|
| **Normal operation** | Document in report, skip |
| **Edge case** | Add defensive code |
| **Design flaw** | Create ADR |
| **Implementation bug** | Fix immediately |

---

## Priority

| P1 | E2E blocking, data corruption |
|----|-------------------------------|
| P2 | Performance degradation |
| P3 | Optimization |
| Won't Fix | Normal behavior |

---

## Common bug patterns

| Pattern | Symptoms | Fix |
|---------|----------|-----|
| Async | Missing `await`, race, deadlock | awaits, lock, timeout |
| Type/data | `None` access, empty data | Optional guard, validate |
| Resource | Leaked connection, pool exhaustion | context manager, `finally` |
| Error handling | Swallowed exception | Catch specific, log, retry |
| State | Orphan records, invalid transition | Validate before op |

---

## Environment

```bash
make doctor          # Health check
make chrome-start    # CDP connection
make up              # Containers
make mcp             # MCP Server
```

## Logs

```bash
make mcp-logs                        # Recent 100 lines
make mcp-logs-f                      # Follow
make mcp-logs-grep PATTERN="error"   # Search
```

---

## Job Scheduler Semantics

### Restart behavior (fail_all policy)

- On MCP server startup, **all `queued`/`running` jobs are reset to `failed`** with `error_message='server_restart_reset'`.
- Jobs do NOT auto-resume after restart. This is intentional to prevent "zombie" jobs.
- To continue work after restart: re-submit targets via `queue_targets` or `queue_reference_candidates`.

### stop_task behavior

- **Default scope changed to `all_jobs`**: All job kinds are cancelled by default (not just `target_queue`).
- Use `scope="target_queue_only"` if you want `verify_nli`/`citation_graph` to complete.
- DB is the sole source of truth; in-memory queues are not used.

### Resuming work

Tasks are always resumable. To continue after `stop_task` or restart:

1. Call `queue_targets` or `queue_reference_candidates` with the same `task_id`
2. Same queries/URLs/DOIs are allowed (no duplicate blocking for previously failed/cancelled)
3. Check `get_status(task_id=...)` for current state

---

## Phase-specific debugging

| Phase | Goal | Check |
|-------|------|-------|
| A. Environment | MCP/Chrome/DB running | `make doctor`, `make chrome-diagnose` |
| B. Queue | Task → Jobs → Worker | `jobs` table, `make logs-f` |
| C. Fetch | SERP → fetch → extract | `intervention_queue`, `fragments` table |
| D. NLI | Fragment-Claim judgment | `make status`, `claims`/`edges` table |
| E. Materials | `get_materials` returns graph | `claims` with task_id filter |

---

## State validation

Schema: `src/storage/schema.sql`

```sql
-- Orphaned intervention_queue
SELECT * FROM intervention_queue iq LEFT JOIN tasks t ON iq.task_id = t.id WHERE t.id IS NULL;

-- Stuck jobs
SELECT * FROM jobs WHERE status = 'pending' AND created_at < datetime('now', '-1 hour');

-- Orphan fragments/edges
SELECT f.* FROM fragments f LEFT JOIN pages p ON f.page_id = p.id WHERE p.id IS NULL;
SELECT e.* FROM edges e LEFT JOIN fragments f ON e.fragment_id = f.id WHERE f.id IS NULL;
```

---

## E2E checklist

1. `make doctor` → `make chrome-start` → `make up` → `make mcp`
2. `create_task` → `queue_searches` → `get_status(wait=30)`
3. If auth needed: `get_auth_queue` → `resolve_auth`
4. `get_materials(include_graph=true)` → validate graph
5. `stop_task` → remove instrumentation

---

## Commands

```bash
fuser data/lyra.db                              # DB lock check
timeout 10 sqlite3 data/lyra.db "SELECT ..."    # Direct query
make test TARGET=tests/test_xxx.py              # Run specific test
```

---

## Output format

Symptom → Expected state → Root cause → Fix → Verification

---

## Report template

`docs/debug/DEBUG_E2E_NN.md` — See existing reports for structure.

---

## References

| Path | Purpose |
|------|---------|
| `docs/S_FULL_E2E.md` | E2E protocol |
| `docs/adr/` | Architecture decisions |
| `docs/debug/` | Past sessions, known acceptable errors |
| `src/storage/schema.sql` | Table structure |

---

## Isolated debugging

When MCP Server holds DB lock, use `src/storage/isolation.py:isolated_database_path()`.

Run debug scripts: `timeout 120 uv run python scripts/debug_*.py`

| Isolated script | API client, rate limiter, parse errors |
|-----------------|----------------------------------------|
| MCP tools | DB state, full E2E flow |

---

## Instrumentation

Log file: `.cursor/debug.log` (NDJSON)

```bash
cat .cursor/debug.log | jq -s 'map(select(.hypothesisId == "A"))'
> .cursor/debug.log  # Clear before run
```

Add instrumentation with region markers for easy cleanup:

```python
# #region agent log
import json, time
with open(".cursor/debug.log", "a") as f:
    f.write(json.dumps({
        "hypothesisId": "A",
        "location": "src/module.py:func_name",
        "message": "description",
        "data": {"key": "value"},
        "timestamp": time.time() * 1000
    }) + "\n")
# #endregion
```

After debugging, search and remove all `#region agent log` blocks.

---

## Related

`@.cursor/rules/debug-e2e.mdc`
