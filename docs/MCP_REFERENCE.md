# MCP Tools Reference

Lyra exposes 13 tools via MCP (Model Context Protocol).

**Schema locations:**
- Input schemas: `src/mcp/server.py` (`TOOLS` array)
- Output schemas: `src/mcp/schemas/*.json`

## Typical Workflow

```
create_task → queue_searches → get_status(wait=30) → vector_search/query_view → stop_task
```

## Tools

### Task Management

| Tool | Description |
|------|-------------|
| `create_task` | Create research task with query and optional config (budget, priority_domains) |
| `get_status` | Get task progress; supports long-polling via `wait` parameter |
| `stop_task` | Stop task (graceful/immediate/full modes) |

### Search

| Tool | Description |
|------|-------------|
| `queue_searches` | Queue multiple queries for parallel background execution |

### Evidence Exploration

| Tool | Description |
|------|-------------|
| `query_sql` | Execute read-only SQL against Evidence Graph |
| `vector_search` | Semantic similarity search over fragments/claims |
| `query_view` | Execute predefined SQL view template |
| `list_views` | List available view templates |

### Authentication

| Tool | Description |
|------|-------------|
| `get_auth_queue` | Get pending CAPTCHA/auth items |
| `resolve_auth` | Mark auth items as solved/skipped; triggers retry |

### Feedback

| Tool | Description |
|------|-------------|
| `feedback` | Human corrections: `edge_correct`, `claim_reject/restore`, `domain_block/unblock` |

### Calibration

| Tool | Description |
|------|-------------|
| `calibration_metrics` | View NLI calibration stats (admin) |
| `calibration_rollback` | Rollback calibration to previous version (admin) |

## Related Documentation

- [Architecture Overview](ARCHITECTURE.md)
- [ADR-0002: Thinking-Working Separation](adr/0002-thinking-working-separation.md)
- [ADR-0010: Async Search Queue](adr/0010-async-search-queue.md)
- [ADR-0012: Feedback Tool Design](adr/0012-feedback-tool-design.md)
