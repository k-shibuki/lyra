# ADR-0017: Ranking Simplification and Evidence Graph Exploration Interface

## Date
2025-12-27

## Context

The current ranking system uses a 3-stage pipeline (BM25 → Embedding → Reranker) which:
- Adds complexity and latency
- Requires GPU resources for reranking
- Uses fixed top_k cutoff, potentially including low-quality results

Additionally, the `get_materials` tool returns all evidence data at once (300-400KB), causing:
- Context overflow in AI agents
- Difficulty exploring specific aspects of the Evidence Graph
- Lack of granularity for iterative exploration

## Decision

### 1. Remove Reranker Stage

- **Remove**: `Reranker` class, ML server `/rerank` endpoint, `JobKind.RERANK`
- **Replace with**: Dynamic cutoff using Kneedle algorithm
- **Benefits**: 
  - Reduced complexity (3 stages → 2 stages)
  - Lower latency (no reranker inference)
  - Adaptive cutoff based on score distribution
  - No GPU required for reranking

### 2. Deprecate `get_materials` Tool

- **Remove**: `get_materials` MCP tool and related code
- **Replace with**: 
  - `query_sql`: Read-only SQL execution for granular exploration
  - `vector_search`: Semantic similarity search over fragments/claims
  - `get_status` extension: Add `evidence_summary` field when status=completed
- **Benefits**:
  - AI agents can explore incrementally
  - No context overflow
  - Flexible querying with SQL
  - Semantic search for discovery

### 3. Embedding Persistence

- **Remove**: `cache_embed` table (expiring cache)
- **Replace with**: `embeddings` table (persistent storage)
- **Schema**:
  ```sql
  CREATE TABLE embeddings (
      id TEXT PRIMARY KEY,
      target_type TEXT NOT NULL,  -- 'fragment' | 'claim'
      target_id TEXT NOT NULL,
      model_id TEXT NOT NULL,
      embedding_blob BLOB NOT NULL,
      dimension INTEGER NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(target_type, target_id, model_id)
  );
  ```
- **Benefits**:
  - No recalculation of embeddings
  - Faster vector search
  - Better for production workloads

### 4. Analysis Views

- **Add**: SQL view templates (Jinja2) in `config/views/*.sql.j2`
- **Purpose**: Predefined queries for common analysis patterns
- **Examples**: `v_contradictions`, `v_hub_pages`, `v_evidence_timeline`
- **Benefits**: Guide AI agents in exploration patterns

## Implementation Details

### Kneedle Algorithm

```python
def kneedle_cutoff(
    ranked: list[dict[str, Any]],
    min_results: int = 3,
    max_results: int = 50,
    sensitivity: float = 1.0,
) -> list[dict[str, Any]]:
    """Detect knee point in score curve and cut off after it."""
    # Uses kneed library for knee detection
    # Falls back to min_results if library unavailable
```

### Security for `query_sql`

- Read-only SQLite connection (`mode=ro`)
- Pattern-based validation (forbidden keywords: ATTACH, INSERT, UPDATE, DELETE, etc.)
- Timeout protection (asyncio.wait_for)
- Output limit (max 200 rows)

### Configuration

```yaml
ranking:
  bm25_top_k: 150
  embedding_weight: 0.7
  bm25_weight: 0.3
  kneedle_cutoff:
    enabled: true
    min_results: 3
    max_results: 50
    sensitivity: 1.0
```

## Consequences

### Positive

- **Simpler architecture**: Fewer components to maintain
- **Better performance**: No reranker inference latency
- **Adaptive cutoff**: Quality-based rather than fixed count
- **Granular exploration**: AI agents can query specific aspects
- **No context overflow**: Incremental data retrieval

### Negative

- **Migration required**: Existing code using `get_materials` must migrate
- **No backward compatibility**: Clean break from old interface
- **DB migration**: `cache_embed` → `embeddings` (data loss acceptable in dev)

### Risks

- **SQL injection**: Mitigated by read-only connection + pattern validation
- **DoS via complex queries**: Mitigated by timeout + output limits
- **Kneedle library dependency**: Falls back gracefully if unavailable

## Alternatives Considered

### Keep Reranker, Add Tools

- **Rejected**: Adds complexity without solving context overflow

### Gradual Migration

- **Rejected**: User requested clean break, no backward compatibility

### Fixed Cutoff Instead of Kneedle

- **Rejected**: Less adaptive, may include low-quality results

## References

- ADR-0001: Local-First Zero-Opex Architecture
- ADR-0005: Evidence Graph Structure

