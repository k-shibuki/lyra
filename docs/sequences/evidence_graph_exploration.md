## Evidence Graph Exploration (query_sql + vector_search) — Integration Sequence

```mermaid
sequenceDiagram
    autonumber
    participant Client as MCP Client (Cursor/Claude)
    participant MCP as Lyra MCP Server (stdio)
    participant DB as SQLite (Evidence Graph DB)
    participant Worker as Search Workers
    participant ML as lyra-ml (Embedding/NLI)

    Client->>MCP: create_task(query, config)
    MCP->>DB: INSERT tasks / initialize state
    MCP-->>Client: {task_id, ...}

    Client->>MCP: queue_searches(task_id, queries[])
    MCP->>DB: INSERT jobs (queued)
    MCP->>Worker: enqueue jobs
    MCP-->>Client: {queued_count, ...}

    loop long polling
        Client->>MCP: get_status(task_id, wait=30)
        MCP->>DB: SELECT task/jobs/metrics
        MCP-->>Client: {status, metrics, evidence_summary?}
    end

    Note over Client,MCP: Evidence Graph Exploration (incremental)
    Client->>MCP: vector_search(query, target=claims|fragments, task_id?)
    MCP->>ML: embed(query)
    MCP->>DB: SELECT embeddings + join targets
    MCP-->>Client: {results[], total_searched}

    Client->>MCP: query_sql(sql, options)
    MCP->>DB: read-only SQL (guards: authorizer/progress/timeout)
    MCP-->>Client: {rows[], columns[], truncated, schema?}

    opt human feedback
        Client->>MCP: feedback(edge_correct/claim_reject/...)
        MCP->>DB: persist feedback/corrections
        MCP-->>Client: {ok}
    end

    Client->>MCP: stop_task(task_id)
    MCP->>Worker: cancel/finish jobs
    MCP->>DB: update task status
    MCP-->>Client: {ok, status=completed}
```

## Data contracts (shared boundaries)

- **`query_sql`**
  - Request: `{sql: str, options?: {limit, timeout_ms, max_vm_steps, include_schema}}`
  - Response: `{ok: bool, rows: object[], row_count: int, columns: str[], truncated: bool, elapsed_ms: int, schema?: {...}, error?: str}`
- **`vector_search`**
  - Request: `{query: str, target: "claims"|"fragments", task_id?: str, top_k?: int, min_similarity?: float}`
  - Response: `{ok: bool, results: [{id, similarity, text_preview?}], total_searched: int, error?: str}`

## Propagation map (checkpoints)

- **`query_sql.options.timeout_ms`**
  - Accept: `src/mcp/tools/sql.py` (`handle_query_sql`)
  - Effect: `asyncio.wait_for` timeout + SQLite progress handler deadline
  - Observable: timeout returns `ok=False` with timeout/interrupted error
- **`query_sql.options.max_vm_steps`**
  - Accept: `src/mcp/tools/sql.py`
  - Effect: SQLite progress handler interrupts when budget exceeded
  - Observable: `ok=False` with interrupted error
- **`vector_search.target/task_id`**
  - Accept: `src/mcp/tools/vector.py`
  - Forward: `src/storage/vector_store.vector_search`
  - Effect: SQL WHERE/CTE scopes target rows
  - Observable: `total_searched` and returned IDs change with task_id/target


