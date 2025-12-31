"""Tests for materials.py scale resilience (10.4.5 Phase 2d).

Tests chunked IN clause processing and json_extract robustness.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|----------------------|-------------|-----------------|-------|
| TC-JSON-N-01 | paper_metadata = valid JSON | Normal | Extracts values | Happy path |
| TC-JSON-A-01 | paper_metadata = NULL | Negative | Returns NULL | NULL input |
| TC-JSON-A-02 | paper_metadata = "invalid" | Negative | Returns NULL | Malformed JSON |
| TC-CHUNK-INT-01 | Many page_ids | Normal | All results returned | Chunked query |
"""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from src.storage.database import Database


class TestJsonExtractRobustness:
    """Tests for json_extract handling in _collect_citation_network."""

    @pytest.mark.asyncio
    async def test_valid_json_extracts_values(self, test_database: "Database") -> None:
        """TC-JSON-N-01: Valid JSON paper_metadata extracts citation_count and year.

        // Given: A page with valid paper_metadata JSON
        // When: _collect_citation_network is called
        // Then: citation_count and year are extracted correctly
        """
        # Given: Create task, claim, fragment, edge, and page with valid metadata
        await test_database.insert("tasks", {"id": "task-1", "query": "test", "status": "active"})
        await test_database.insert(
            "claims",
            {"id": "claim-1", "task_id": "task-1", "claim_text": "Test claim"},
        )
        await test_database.insert(
            "pages",
            {
                "id": "page-1",
                "url": "https://example.com",
                "title": "Test Page",
                "domain": "example.com",
                "paper_metadata": '{"citation_count": 42, "year": 2023}',
            },
        )
        await test_database.insert(
            "fragments",
            {
                "id": "frag-1",
                "page_id": "page-1",
                "fragment_type": "paragraph",
                "text_content": "Fragment text",
            },
        )
        await test_database.insert(
            "edges",
            {
                "id": "edge-1",
                "source_type": "fragment",
                "source_id": "frag-1",
                "target_type": "claim",
                "target_id": "claim-1",
                "relation": "supports",
            },
        )

        # When
        from src.research.materials import _collect_citation_network

        with patch(
            "src.research.materials.get_database",
            return_value=test_database,
        ):
            result = await _collect_citation_network(test_database, "task-1")

        # Then
        assert len(result["source_pages"]) == 1
        page = result["source_pages"][0]
        assert page["citation_count"] == 42
        assert page["year"] == 2023

    @pytest.mark.asyncio
    async def test_null_paper_metadata_returns_null(self, test_database: "Database") -> None:
        """TC-JSON-A-01: NULL paper_metadata returns NULL for citation_count/year.

        // Given: A page with NULL paper_metadata
        // When: _collect_citation_network is called
        // Then: citation_count and year are NULL (no error)
        """
        # Given
        await test_database.insert("tasks", {"id": "task-1", "query": "test", "status": "active"})
        await test_database.insert(
            "claims",
            {"id": "claim-1", "task_id": "task-1", "claim_text": "Test claim"},
        )
        await test_database.insert(
            "pages",
            {
                "id": "page-1",
                "url": "https://example.com",
                "title": "Test Page",
                "domain": "example.com",
                "paper_metadata": None,  # NULL
            },
        )
        await test_database.insert(
            "fragments",
            {
                "id": "frag-1",
                "page_id": "page-1",
                "fragment_type": "paragraph",
                "text_content": "Fragment text",
            },
        )
        await test_database.insert(
            "edges",
            {
                "id": "edge-1",
                "source_type": "fragment",
                "source_id": "frag-1",
                "target_type": "claim",
                "target_id": "claim-1",
                "relation": "supports",
            },
        )

        # When
        from src.research.materials import _collect_citation_network

        result = await _collect_citation_network(test_database, "task-1")

        # Then
        assert len(result["source_pages"]) == 1
        page = result["source_pages"][0]
        assert page["citation_count"] is None
        assert page["year"] is None

    @pytest.mark.asyncio
    async def test_malformed_json_returns_null(self, test_database: "Database") -> None:
        """TC-JSON-A-02: Malformed paper_metadata returns NULL for citation_count/year.

        // Given: A page with invalid JSON in paper_metadata
        // When: _collect_citation_network is called
        // Then: citation_count and year are NULL (no error, graceful degradation)
        """
        # Given
        await test_database.insert("tasks", {"id": "task-1", "query": "test", "status": "active"})
        await test_database.insert(
            "claims",
            {"id": "claim-1", "task_id": "task-1", "claim_text": "Test claim"},
        )
        await test_database.insert(
            "pages",
            {
                "id": "page-1",
                "url": "https://example.com",
                "title": "Test Page",
                "domain": "example.com",
                "paper_metadata": "not valid json {{{",  # Malformed
            },
        )
        await test_database.insert(
            "fragments",
            {
                "id": "frag-1",
                "page_id": "page-1",
                "fragment_type": "paragraph",
                "text_content": "Fragment text",
            },
        )
        await test_database.insert(
            "edges",
            {
                "id": "edge-1",
                "source_type": "fragment",
                "source_id": "frag-1",
                "target_type": "claim",
                "target_id": "claim-1",
                "relation": "supports",
            },
        )

        # When
        from src.research.materials import _collect_citation_network

        result = await _collect_citation_network(test_database, "task-1")

        # Then
        assert len(result["source_pages"]) == 1
        page = result["source_pages"][0]
        assert page["citation_count"] is None
        assert page["year"] is None


class TestChunkedCitationQueries:
    """Tests for chunked IN clause processing in citation network."""

    @pytest.mark.asyncio
    async def test_empty_page_ids_no_error(self, test_database: "Database") -> None:
        """Empty page_ids list doesn't cause errors.

        // Given: A task with no linked pages
        // When: _collect_citation_network is called
        // Then: Returns empty citations and hub_pages (no error)
        """
        # Given
        await test_database.insert("tasks", {"id": "task-1", "query": "test", "status": "active"})

        # When
        from src.research.materials import _collect_citation_network

        result = await _collect_citation_network(test_database, "task-1")

        # Then
        assert result["source_pages"] == []
        assert result["citations"] == []
        assert result["hub_pages"] == []

    @pytest.mark.asyncio
    async def test_hub_pages_aggregation_across_chunks(self) -> None:
        """Hub pages are correctly aggregated across chunks.

        // Given: page_ids that would span multiple chunks
        // When: _collect_citation_network processes them
        // Then: cited_by_count is summed correctly across chunks
        """
        # Given: Simulate scenario where same page is cited from different chunks
        # We'll use mocks to verify the aggregation logic

        mock_db = AsyncMock()

        # First query returns source pages (600 pages -> 2 chunks)
        source_pages_result = [
            {
                "id": f"page-{i}",
                "title": f"Page {i}",
                "url": f"https://example.com/{i}",
                "domain": "example.com",
                "citation_count": None,
                "year": None,
            }
            for i in range(600)
        ]

        # Hub query results: same target page cited from different source chunks
        hub_chunk1 = [{"page_id": "hub-1", "title": "Hub Page", "cited_by_count": 3}]
        hub_chunk2 = [{"page_id": "hub-1", "title": "Hub Page", "cited_by_count": 2}]

        # Track hub query calls separately
        hub_call_count = [0]

        async def mock_fetch_all(query: str, params: tuple = ()) -> list:
            if "SELECT DISTINCT p.id" in query:
                return source_pages_result
            elif "e.id as edge_id" in query:
                return []  # No citations for simplicity
            elif "COUNT(*) as cited_by_count" in query:
                hub_call_count[0] += 1
                # Return different hub results for each chunk
                if hub_call_count[0] == 1:
                    return hub_chunk1
                else:
                    return hub_chunk2
            return []

        mock_db.fetch_all = mock_fetch_all

        # When
        from src.research.materials import _collect_citation_network

        result = await _collect_citation_network(mock_db, "task-1")

        # Then: hub-1 should have aggregated count of 5 (3 + 2)
        assert len(result["hub_pages"]) == 1
        assert result["hub_pages"][0]["page_id"] == "hub-1"
        assert result["hub_pages"][0]["cited_by_count"] == 5

    def test_chunked_utility_integration(self) -> None:
        """Verify chunked utility works as expected for query building.

        // Given: A large list of page_ids
        // When: Iterating with chunked()
        // Then: Each chunk can be used to build valid IN clause
        """
        from src.utils.db_helpers import chunked

        # Given
        page_ids = [f"page-{i}" for i in range(600)]

        # When
        chunks = list(chunked(page_ids))

        # Then
        assert len(chunks) == 2
        assert len(chunks[0]) == 500
        assert len(chunks[1]) == 100

        # Verify each chunk can build valid placeholders
        for chunk in chunks:
            placeholders = ",".join(["?"] * len(chunk))
            assert placeholders.count("?") == len(chunk)
