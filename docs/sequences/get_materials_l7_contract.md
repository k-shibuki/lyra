## get_materials: MCP (call_tool) → L7 Sanitization → Client contract

```mermaid
sequenceDiagram
  autonumber
  participant Client as Cursor AI (client)
  participant MCP as src/mcp/server.py call_tool()
  participant Dispatch as _dispatch_tool()
  participant Handler as _handle_get_materials()
  participant Materials as src/research/materials.py get_materials_action()
  participant DB as SQLite (src/storage)
  participant L7 as src/mcp/response_sanitizer.py sanitize_response()
  participant Schema as src/mcp/schemas/get_materials.json (allowlist)

  Client->>MCP: call_tool("get_materials", {task_id, options})
  MCP->>Dispatch: _dispatch_tool("get_materials", args)
  Dispatch->>Handler: _handle_get_materials(args)
  Handler->>DB: SELECT id FROM tasks WHERE id=?
  Handler->>Materials: get_materials_action(task_id, include_graph, format)
  Materials->>DB: SELECT claims/fragments/edges...
  Materials-->>Handler: result (raw dict, contains Bayesian fields)
  Handler-->>Dispatch: result
  Dispatch-->>MCP: result
  MCP->>L7: sanitize_response(result, "get_materials")
  L7->>Schema: load + apply allowlist (strip_unknown_fields)
  L7-->>MCP: sanitized_result
  MCP-->>Client: JSON text content (sanitized_result)
```

### Propagation map（フィールド: `uncertainty/controversy/evidence/evidence_years`）

- **Source (origin)**: `src/filter/evidence_graph.py:EvidenceGraph.calculate_claim_confidence()`
- **Assembly (pack into claims)**: `src/research/materials.py:_collect_claims()`
  - `claims[i].uncertainty`
  - `claims[i].controversy`
  - `claims[i].evidence`
  - `claims[i].evidence_years`
- **MCP handler boundary**: `src/mcp/server.py:_handle_get_materials()` → returns raw dict
- **L7 allowlist boundary (must allow!)**: `src/mcp/response_sanitizer.py:_strip_unknown_fields()` with schema `src/mcp/schemas/get_materials.json`
- **Client sink**: Cursor AI receives JSON (post-L7) and uses fields for ranking/temporal judgments

### Verification (tests)

- `tests/test_mcp_integration.py`
  - `TestGetMaterialsIntegration::test_get_materials_call_tool_preserves_bayesian_fields`
  - `TestGetMaterialsIntegration::test_get_materials_l7_strips_unknown_claim_fields_but_keeps_allowed`


