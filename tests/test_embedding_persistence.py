"""
Tests for embedding persistence.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-EP-N-01 | Persist fragment embedding | Equivalence – normal | Saved to embeddings table | - |
| TC-EP-N-02 | Persist claim embedding | Equivalence – normal | Saved to embeddings table | - |
| TC-EP-N-03 | Duplicate embedding (same target+model) | Equivalence – normal | Replaces existing (INSERT OR REPLACE) | - |
| TC-EP-N-04 | Different model_id | Equivalence – normal | Creates separate entry | - |
| TC-EP-N-05 | Retrieve persisted embedding | Equivalence – normal | Returns correct embedding | - |
| TC-EP-A-01 | Invalid target_type | Boundary – invalid | Raises error or ignored | - |
| TC-EP-A-02 | Empty embedding list | Boundary – empty | Handles gracefully | - |
| TC-EP-A-03 | Embedding dimension mismatch | Abnormal – dimension error | Handles gracefully | - |
"""

import pytest

from src.storage.database import Database

pytestmark = pytest.mark.unit

from src.storage import vector_store


@pytest.mark.asyncio
async def test_persist_fragment_embedding(test_database: Database) -> None:
    """
    TC-EP-N-01: Persist fragment embedding saves to database.

    // Given: Fragment ID and embedding vector
    // When: Calling persist_embedding
    // Then: Saved to embeddings table
    """
    db = test_database
    # Create test fragment
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        ("page_1", "https://example.org/page_1", "example.org"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        ("frag_1", "page_1", "paragraph", "Test fragment"),
    )

    embedding = [0.1] * 768
    await vector_store.persist_embedding("fragment", "frag_1", embedding)

    # Verify saved
    row = await db.fetch_one(
        "SELECT * FROM embeddings WHERE target_type = 'fragment' AND target_id = 'frag_1'"
    )
    assert row is not None
    assert row["dimension"] == 768
    assert row["model_id"] == "BAAI/bge-m3"


@pytest.mark.asyncio
async def test_persist_claim_embedding(test_database: Database) -> None:
    """
    TC-EP-N-02: Persist claim embedding saves to database.

    // Given: Claim ID and embedding vector
    // When: Calling persist_embedding
    // Then: Saved to embeddings table
    """
    db = test_database
    # Create test task and claim
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_1", "test query", "completed"),
    )
    await db.execute(
        "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
        ("claim_1", "task_1", "Test claim"),
    )

    embedding = [0.2] * 768
    await vector_store.persist_embedding("claim", "claim_1", embedding)

    # Verify saved
    row = await db.fetch_one(
        "SELECT * FROM embeddings WHERE target_type = 'claim' AND target_id = 'claim_1'"
    )
    assert row is not None
    assert row["dimension"] == 768


@pytest.mark.asyncio
async def test_persist_duplicate_replaces(test_database: Database) -> None:
    """
    TC-EP-N-03: Duplicate embedding replaces existing entry.

    // Given: Embedding already exists for target+model
    // When: Calling persist_embedding again
    // Then: Replaces existing entry (INSERT OR REPLACE)
    """
    db = test_database
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        ("page_1", "https://example.org/page_1", "example.org"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        ("frag_1", "page_1", "paragraph", "Test"),
    )

    embedding1 = [0.1] * 768
    await vector_store.persist_embedding("fragment", "frag_1", embedding1)

    embedding2 = [0.2] * 768
    await vector_store.persist_embedding("fragment", "frag_1", embedding2)

    # Should have only one entry
    rows = await db.fetch_all(
        "SELECT * FROM embeddings WHERE target_type = 'fragment' AND target_id = 'frag_1'"
    )
    assert len(rows) == 1
    # Verify it's the new embedding
    deserialized = vector_store.deserialize_embedding(rows[0]["embedding_blob"])
    assert deserialized[0] == pytest.approx(0.2, rel=1e-6)


@pytest.mark.asyncio
async def test_persist_different_model(test_database: Database) -> None:
    """
    TC-EP-N-04: Different model_id creates separate entry.

    // Given: Same target with different model_id
    // When: Calling persist_embedding
    // Then: Creates separate entry
    """
    db = test_database
    await db.execute(
        "INSERT INTO pages (id, url, domain) VALUES (?, ?, ?)",
        ("page_1", "https://example.org/page_1", "example.org"),
    )
    await db.execute(
        "INSERT INTO fragments (id, page_id, fragment_type, text_content) VALUES (?, ?, ?, ?)",
        ("frag_1", "page_1", "paragraph", "Test"),
    )

    embedding = [0.1] * 768
    await vector_store.persist_embedding("fragment", "frag_1", embedding, model_id="model1")
    await vector_store.persist_embedding("fragment", "frag_1", embedding, model_id="model2")

    # Should have two entries
    rows = await db.fetch_all(
        "SELECT * FROM embeddings WHERE target_type = 'fragment' AND target_id = 'frag_1'"
    )
    assert len(rows) == 2
    model_ids = {row["model_id"] for row in rows}
    assert "model1" in model_ids
    assert "model2" in model_ids
