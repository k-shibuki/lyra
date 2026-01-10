# debug

General-purpose debugging command. Policy: `@.cursor/rules/debug.mdc`

## Debug Method Priority

1. **Python scripts** (`debug/scripts/`) - Isolated, reproducible, no user interaction
2. **MCP tools** - When DB state inspection needed during MCP session
3. **User operations** - Only when unavoidable (MCP restart, browser auth)

## Inputs

| Required | `@logs/lyra_*.log`, error/stacktrace, repro steps |
|----------|---------------------------------------------------|
| Optional | `@src/...`, `@tests/...`, `@docs/adr/` |

---

## Task Prefix Convention

**Multiple AI agents may debug concurrently.** Use consistent prefixes:

| Artifact | Pattern | Example |
|----------|---------|---------|
| Docs | `debug/docs/<TASK>_report.md` | `debug/docs/BUDGET_report.md` |
| Logs | `debug/scripts/<TASK>_debug.log` | `debug/scripts/BUDGET_debug.log` |
| Hypothesis IDs | `<TASK>-H1`, `<TASK>-H2`, ... | `BUDGET-H1`, `NLI-H2` |

Common prefixes: `BUDGET`, `NLI`, `SERP`, `API`, `FETCH`, `EXTRACT`, `QUEUE`

---

## Workflow

| Step | Action |
|------|--------|
| 1. Symptom | Reproduce, state expected vs actual |
| 2. Hypotheses | List with IDs (`<TASK>-H1`, ...) |
| 3. Instrument | Add logs to verify hypotheses |
| 4. Validate | Adopted / Rejected with evidence |
| 5. Fix | Minimal change |
| 6. Verify | Run tests |

---

## Make Commands

### Environment

```bash
make doctor              # Health check (dependencies, config)
make up                  # Start containers (proxy/ollama/ml/tor)
make down                # Stop containers
make status              # Container status
```

### MCP Server

```bash
make mcp                 # Start MCP server
make mcp-status          # Check status
make mcp-restart         # Restart (code reload)
make mcp-stop            # Stop server
```

### Chrome (Browser Pool)

```bash
make chrome              # Pool status
make chrome-start        # Start pool
make chrome-stop         # Stop pool
make chrome-diagnose     # Connection issues
```

### Logs

```bash
# MCP Server (logs/lyra_YYYYMMDD.log)
make mcp-logs                        # Last 100 lines
make mcp-logs-f                      # Follow
make mcp-logs-grep PATTERN="error"   # Search

# Containers
make logs SERVICE=proxy              # Specific service
make logs-f SERVICE=ollama           # Follow
```

### Testing

```bash
make test                            # All tests
make test TARGET=tests/test_xxx.py   # Specific file
make test-unit                       # Unit only
make test-integration                # Integration only
```

### Database

```bash
make db-reset                        # Reset DB (destructive!)
fuser data/lyra.db                   # Check lock
```

### Debug Scripts (Preferred)

```bash
timeout 120 uv run python debug/scripts/<TASK>_debug.py
```

Python scripts are **preferred over MCP tools** for debugging:
- No user interaction required
- Isolated from MCP server state
- Reproducible execution

---

## DB Inspection via MCP

Use `query_sql` tool for read-only queries (no lock issues):

```sql
-- Task status
SELECT id, hypothesis, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 5;

-- Job queue
SELECT kind, state, COUNT(*) FROM jobs WHERE task_id = '...' GROUP BY kind, state;

-- Stuck jobs (older than 1 hour)
SELECT * FROM jobs WHERE state = 'queued' AND created_at < datetime('now', '-1 hour');

-- Recent pages
SELECT id, url, title, fetched_at FROM pages ORDER BY fetched_at DESC LIMIT 10;

-- Claims for task
SELECT id, claim_text, claim_type FROM claims WHERE task_id = '...' LIMIT 20;
```

---

## Phase-specific Debugging

| Phase | Goal | Check |
|-------|------|-------|
| A. Environment | Services running | `make doctor`, `make chrome-diagnose` |
| B. Queue | Task → Jobs → Worker | `jobs` table, `make mcp-logs-f` |
| C. Fetch | SERP → fetch → extract | `intervention_queue`, `fragments` |
| D. NLI | Fragment-Claim edges | `claims`, `edges` tables |

---

## Job Scheduler Behavior

### On MCP restart

- All `queued`/`running` jobs → `failed` (error: `server_restart_reset`)
- **Jobs do NOT auto-resume** (prevents zombies)
- To continue: re-submit via `queue_targets`

### stop_task

- Default: cancels **all** job kinds
- `scope="target_queue_only"`: let `verify_nli`/`citation_graph` complete

---

## Instrumentation

### Philosophy

**No limit on log count.** Add enough to track propagation and debug in one run.

### Log location

`debug/scripts/<TASK>_debug.log` (NDJSON) — **NOT** `.cursor/debug.log`

### Clear & Query

```bash
echo "" > debug/scripts/<TASK>_debug.log              # Clear
cat debug/scripts/<TASK>_debug.log | jq .             # View
tail -f debug/scripts/<TASK>_debug.log | jq .         # Follow
```

### Template

```python
# #region agent log
import json, time
with open("debug/scripts/<TASK>_debug.log", "a") as f:
    f.write(json.dumps({
        "hypothesisId": "<TASK>-H1",
        "location": "src/module.py:func",
        "message": "desc",
        "data": {"key": "value"},
        "timestamp": time.time() * 1000
    }) + "\n")
# #endregion
```

### Propagation Tracking Pattern

```
[Entry] → [Transform1] → [Transform2] → [Exit]
  H1-L1      H1-L2          H1-L3        H1-L4
```

Log at **each boundary** to find exact divergence point.

### Cleanup

```bash
grep -rn "# #region agent log" src/
```

---

## References

| Path | Purpose |
|------|---------|
| `docs/adr/` | Architecture decisions |
| `debug/docs/` | Past debug reports |
| `src/storage/schema.sql` | DB schema |

---

## Related

- `@.cursor/rules/debug.mdc` (policy)
- `@.cursor/commands/integration-design.md` (for preventing integration issues during new feature development)
