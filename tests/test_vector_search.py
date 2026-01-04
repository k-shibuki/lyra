"""
Tests for vector_search MCP tool.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-VS-N-01 | Valid query, target=claims | Equivalence – normal | Returns results with similarity scores | - |
| TC-VS-N-02 | Valid query, target=fragments | Equivalence – normal | Returns results with similarity scores | - |
| TC-VS-N-03 | Query with task_id filter | Equivalence – normal | Returns only task-scoped results | - |
| TC-VS-N-04 | top_k parameter | Equivalence – normal | Respects top_k limit | - |
| TC-VS-N-05 | min_similarity parameter | Equivalence – normal | Filters by similarity threshold | - |
| TC-VS-A-01 | Missing query parameter | Boundary – missing | Raises InvalidParamsError | - |
| TC-VS-A-02 | Empty query string | Boundary – empty | Raises InvalidParamsError | - |
| TC-VS-A-03 | Invalid target (not fragments/claims) | Boundary – invalid enum | Raises InvalidParamsError | - |
| TC-VS-A-04 | top_k > 50 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-VS-A-05 | top_k < 1 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-VS-A-06 | min_similarity > 1.0 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-VS-A-07 | min_similarity < 0.0 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-VS-A-08 | Zero embeddings in DB | Boundary – no data | Returns ok=False with error | - |
"""

import pytest

from src.storage.database import Database

pytestmark = pytest.mark.unit

from unittest.mock import patch

from src.mcp.errors import InvalidParamsError
from src.mcp.tools import vector


@pytest.mark.asyncio
async def test_vector_search_valid_query_claims(test_database: Database) -> None:
    """
    TC-VS-N-01: Valid query with target=claims returns results.

    // Given: Valid query and target=claims with embeddings in DB
    // When: Executing vector_search
    // Then: Returns results with similarity scores
    """
    from unittest.mock import AsyncMock

    # Setup: Insert claim and embedding
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
        ("task_vs_01", "test", "completed"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        ("claim_1", "task_vs_01", "Test claim text", 0.8),
    )
    # Insert a dummy embedding
    import struct

    dummy_embedding = struct.pack("<3f", 0.5, 0.5, 0.5)
    await db.execute(
        "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
        ("claim:claim_1:test_model", "claim", "claim_1", "BAAI/bge-m3", dummy_embedding, 3),
    )

    # Mock ML client to return matching embedding
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
        mock_get_ml.return_value = mock_client

        result = await vector.handle_vector_search({"query": "test query", "target": "claims"})

        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "claim_1"
        assert "total_searched" in result
        assert result["total_searched"] == 1


@pytest.mark.asyncio
async def test_vector_search_valid_query_fragments(test_database: Database) -> None:
    """
    TC-VS-N-02: Valid query with target=fragments returns results.

    // Given: Valid query and target=fragments with embeddings in DB
    // When: Executing vector_search
    // Then: Returns results with similarity scores
    """
    from unittest.mock import AsyncMock

    # Setup: Insert page, fragment, and embedding
    db = test_database
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        ("page_vs_02", "https://example.com", "example.com"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content, is_relevant) VALUES (?, ?, ?, ?, ?)",
        ("frag_1", "page_vs_02", "paragraph", "Test fragment text", 1),
    )
    # Insert a dummy embedding
    import struct

    dummy_embedding = struct.pack("<3f", 0.5, 0.5, 0.5)
    await db.execute(
        "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
        ("fragment:frag_1:test_model", "fragment", "frag_1", "BAAI/bge-m3", dummy_embedding, 3),
    )

    # Mock ML client to return matching embedding
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
        mock_get_ml.return_value = mock_client

        result = await vector.handle_vector_search({"query": "test query", "target": "fragments"})

        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "frag_1"


@pytest.mark.asyncio
async def test_vector_search_with_task_id(test_database: Database) -> None:
    """
    TC-VS-N-03: Query with task_id filter returns only task-scoped results.

    // Given: Query with task_id parameter
    // When: Executing vector_search
    // Then: Returns only results from specified task
    """
    from unittest.mock import AsyncMock

    # Setup: Insert task, claim, and embedding
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
        ("task_123", "test", "completed"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        ("claim_task_123", "task_123", "Task-scoped claim", 0.8),
    )
    import struct

    dummy_embedding = struct.pack("<3f", 0.5, 0.5, 0.5)
    await db.execute(
        "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "claim:claim_task_123:test_model",
            "claim",
            "claim_task_123",
            "BAAI/bge-m3",
            dummy_embedding,
            3,
        ),
    )

    # Mock ML client
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
        mock_get_ml.return_value = mock_client

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "task_id": "task_123"}
        )

        assert result["ok"] is True
        assert result["total_searched"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "claim_task_123"


@pytest.mark.asyncio
async def test_vector_search_top_k(test_database: Database) -> None:
    """
    TC-VS-N-04: top_k parameter respects limit.

    // Given: Query with top_k=2 and multiple embeddings
    // When: Executing vector_search
    // Then: Returns at most top_k results
    """
    from unittest.mock import AsyncMock

    # Setup: Insert multiple claims with embeddings
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
        ("task_topk", "test", "completed"),
    )

    import struct

    for i in range(5):
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
            (f"claim_topk_{i}", "task_topk", f"Claim {i}", 0.8),
        )
        # Vary embeddings slightly so they have different similarities
        emb = struct.pack("<3f", 0.5 + i * 0.01, 0.5, 0.5)
        await db.execute(
            "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
            (f"claim:claim_topk_{i}:test_model", "claim", f"claim_topk_{i}", "BAAI/bge-m3", emb, 3),
        )

    # Mock ML client
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
        mock_get_ml.return_value = mock_client

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "top_k": 2}
        )

        assert result["ok"] is True
        assert result["total_searched"] == 5
        assert len(result["results"]) <= 2  # Respects top_k


@pytest.mark.asyncio
async def test_vector_search_min_similarity(test_database: Database) -> None:
    """
    TC-VS-N-05: min_similarity parameter filters results.

    // Given: Query with embeddings and min_similarity threshold
    // When: Executing vector_search
    // Then: Only returns results with similarity >= threshold
    """
    from unittest.mock import AsyncMock

    # Setup: Insert claim with embedding
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
        ("task_minsim", "test", "completed"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence) VALUES (?, ?, ?, ?)",
        ("claim_minsim", "task_minsim", "High similarity claim", 0.8),
    )
    import struct

    # Embedding that should have very high similarity with query (identical)
    dummy_embedding = struct.pack("<3f", 0.5, 0.5, 0.5)
    await db.execute(
        "INSERT INTO embeddings (id, target_type, target_id, model_id, embedding_blob, dimension) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "claim:claim_minsim:test_model",
            "claim",
            "claim_minsim",
            "BAAI/bge-m3",
            dummy_embedding,
            3,
        ),
    )

    # Mock ML client with identical query embedding
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]
        mock_get_ml.return_value = mock_client

        result = await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": 0.9}
        )

        assert result["ok"] is True
        # With identical embeddings, cosine similarity = 1.0, so it should pass the threshold
        assert len(result["results"]) >= 1


@pytest.mark.asyncio
async def test_vector_search_missing_query() -> None:
    """
    TC-VS-A-01: Missing query parameter raises InvalidParamsError.

    // Given: No query parameter
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"target": "claims"})

    assert "query is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_empty_query() -> None:
    """
    TC-VS-A-02: Empty query string raises InvalidParamsError.

    // Given: Empty query string
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "", "target": "claims"})

    assert "query is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_invalid_target() -> None:
    """
    TC-VS-A-03: Invalid target raises InvalidParamsError.

    // Given: target not in ['fragments', 'claims']
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "invalid"})

    assert "target must be 'fragments' or 'claims'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_top_k_too_high() -> None:
    """
    TC-VS-A-04: top_k > 50 raises InvalidParamsError.

    // Given: top_k=51
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "claims", "top_k": 51})

    assert "top_k must be between 1 and 50" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_top_k_too_low() -> None:
    """
    TC-VS-A-05: top_k < 1 raises InvalidParamsError.

    // Given: top_k=0
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search({"query": "test", "target": "claims", "top_k": 0})

    assert "top_k must be between 1 and 50" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_min_similarity_too_high() -> None:
    """
    TC-VS-A-06: min_similarity > 1.0 raises InvalidParamsError.

    // Given: min_similarity=1.1
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": 1.1}
        )

    assert "min_similarity must be between 0.0 and 1.0" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_min_similarity_too_low() -> None:
    """
    TC-VS-A-07: min_similarity < 0.0 raises InvalidParamsError.

    // Given: min_similarity=-0.1
    // When: Calling handle_vector_search
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await vector.handle_vector_search(
            {"query": "test", "target": "claims", "min_similarity": -0.1}
        )

    assert "min_similarity must be between 0.0 and 1.0" in str(exc_info.value)


@pytest.mark.asyncio
async def test_vector_search_zero_embeddings(test_database: Database) -> None:
    """
    TC-VS-A-08: Zero embeddings returns ok=False with descriptive error.

    // Given: No embeddings in database for target
    // When: Calling handle_vector_search
    // Then: Returns ok=False with error message about no embeddings
    """
    from unittest.mock import AsyncMock

    # Mock ML client to avoid actual embedding call
    with patch("src.storage.vector_store.get_ml_client") as mock_get_ml:
        mock_client = AsyncMock()
        mock_client.embed.return_value = [[0.5, 0.5, 0.5]]  # Dummy embedding
        mock_get_ml.return_value = mock_client

        # No embeddings in test_database (clean DB)
        result = await vector.handle_vector_search(
            {
                "query": "test query",
                "target": "claims",
                "task_id": "nonexistent_task",
            }
        )

        assert result["ok"] is False
        assert "error" in result
        assert "no embeddings found" in result["error"].lower()
        assert result["total_searched"] == 0
