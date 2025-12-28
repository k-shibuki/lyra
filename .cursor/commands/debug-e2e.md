# debug-e2e

E2Eシナリオのデバッグ手順。Policy: `@.cursor/rules/debug-e2e.mdc`

## Inputs

| Required | `@logs/lyra_*.log`, エラー/スタックトレース, 再現手順 |
|----------|-------------------------------------------------------|
| Optional | `@src/...`, `@tests/...`, `@docs/adr/` |

---

## Workflow

| Step | Action |
|------|--------|
| 1. Symptom | 再現確認、expected vs actual を明記 |
| 2. Expected state | 正常時の DB/queue/cache 状態を定義 |
| 3. Evidence | ログ収集、DBクエリ、環境確認 |
| 4. Triage | 各エラーを Normal/Problem に分類 |
| 5. Hypotheses | 仮説をID付きで列挙 (A, B, C...) |
| 6. Validate | 計装で仮説を検証、Adopted/Rejected を記録 |
| 7. Pattern | ログのERROR/WARNINGを集計・分類 |
| 8. Prioritize | P1/P2/P3/Won't Fix を割り当て |
| 9. Fix | 最小限の修正 |
| 10. Verify | テスト実行、回帰確認 |

---

## Triage

| Classification | Action |
|----------------|--------|
| **Normal** | `docs/debug/` で既知なら skip |
| **Problem** | 仮説を立て調査 |
| **Unknown** | 追加ログ収集後に再分類 |

---

## Hypothesis

```
Formed → Instrumented → Validated → ✅ Adopted / ❌ Rejected
                                              ↓
                                   (Rejected) → Next
```

**棄却も成果**。検証なしに修正しない。

---

## Pattern Analysis

`logs/lyra_*.log` と `.cursor/debug.log` の ERROR/WARNING を集計し分類:

| Category | Action |
|----------|--------|
| **Normal operation** | debug report に記録、skip |
| **Edge case** | 防御コード追加 |
| **Design flaw** | ADR 作成 |
| **Implementation bug** | 即時修正 |

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
make dev-up          # Containers
make mcp             # MCP Server
```

## Logs

```bash
make mcp-logs                        # Recent 100 lines
make mcp-logs-f                      # Follow
make mcp-logs-grep PATTERN="error"   # Search
```

---

## Phase-specific debugging

| Phase | Goal | Check |
|-------|------|-------|
| A. Environment | MCP/Chrome/DB running | `make doctor`, `make chrome-diagnose` |
| B. Queue | Task → Jobs queued → Worker processing | `jobs` table, `make dev-logs-f` |
| C. Fetch | SERP → page fetch → extraction | `intervention_queue`, `fragments` table |
| D. NLI | Fragment-Claim judgment, graph | `make dev-status`, `claims`/`edges` table |
| E. Materials | `get_materials` returns graph | `claims` with task_id filter |

---

## State validation queries

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

1. `make doctor` → `make chrome-start` → `make dev-up` → `make mcp`
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

| `docs/S_FULL_E2E.md` | E2E protocol |
|----------------------|--------------|
| `docs/adr/` | Architecture decisions |
| `docs/debug/` | Past sessions, known acceptable errors |
| `src/storage/schema.sql` | Table structure |

---

## Isolated debugging

MCP Server が DB lock を持つ場合、`isolated_database_path()` を使用:

```bash
timeout 120 uv run python scripts/debug_e2e_test.py
```

```python
from src.storage.isolation import isolated_database_path
async with isolated_database_path() as db_path:
    # temp DB を使用、data/lyra.db に影響なし
```

| Isolated script | API client, rate limiter, parse errors |
|-----------------|----------------------------------------|
| MCP tools | DB state, full E2E flow |

---

## Instrumentation

`.cursor/debug.log` (NDJSON):

```bash
cat .cursor/debug.log | jq -s 'map(select(.hypothesisId == "A"))'
> .cursor/debug.log  # Clear
```

```python
# #region agent log
import json
with open(".cursor/debug.log", "a") as f:
    f.write(json.dumps({"hypothesisId": "A", "location": "...", "data": {...}}) + "\n")
# #endregion
```

完了後、`#region agent log` ブロックを削除。

---

## Related

`@.cursor/rules/debug-e2e.mdc` | `@.cursor/rules/code-execution.mdc`

