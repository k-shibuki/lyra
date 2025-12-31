"""Tests for citation network in get_materials.

Tests the include_citations option and _collect_citation_network function
per Sb_CITATION_NETWORK Phase 3.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-CN-N-01 | include_citations=true, task with citations | Normal | citation_network in response | Core wiring |
| TC-CN-N-02 | source_pages populated | Normal | Correct pages returned | Wiring |
| TC-CN-N-03 | citations populated | Normal | Citation edges returned | Wiring |
| TC-CN-N-04 | hub_pages calculated | Normal | Sorted by count | Effect |
| TC-CN-N-05 | include_citations=false | Normal | citation_network is null | Default |
| TC-CN-N-06 | include_graph=true AND include_citations=true | Normal | Both populated | Independent |
| TC-CN-B-01 | Task with no claims | Boundary | Empty citation_network | Edge case |
| TC-CN-B-02 | Claims but no citations | Boundary | Empty citations/hub_pages | No cites |
| TC-CN-B-03 | hub_pages limit 10 | Boundary | At most 10 results | Limit |
| TC-CN-A-01 | Invalid task_id | Negative | Error response | Error handling |
"""

from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from src.storage.database import Database


class TestCitationNetworkBasic:
    """Tests for basic citation network functionality."""

    @pytest.mark.asyncio
    async def test_include_citations_returns_citation_network(
        self, test_database: "Database"
    ) -> None:
        """TC-CN-N-01: include_citations=true returns citation_network.

        // Given: Task with claims, fragments, pages, and cites edges
        // When: get_materials_action with include_citations=true
        // Then: citation_network is in response
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-2', 'https://cited.com', 'cited.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-frag-claim', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-cites', 'page', 'page-1', 'page', 'page-2', 'cites')
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: citation_network is in response
        assert result["ok"] is True
        assert "citation_network" in result
        assert result["citation_network"] is not None

    @pytest.mark.asyncio
    async def test_source_pages_populated(self, test_database: "Database") -> None:
        """TC-CN-N-02: source_pages contains correct pages.

        // Given: Task with claim linked to fragment with page
        // When: get_materials_action with include_citations=true
        // Then: source_pages contains the page
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, title, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', 'Source Page', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: source_pages contains the page
        citation_network = result["citation_network"]
        assert len(citation_network["source_pages"]) == 1
        assert citation_network["source_pages"][0]["id"] == "page-1"
        assert citation_network["source_pages"][0]["title"] == "Source Page"
        assert citation_network["source_pages"][0]["url"] == "https://source.com"

    @pytest.mark.asyncio
    async def test_citations_populated(self, test_database: "Database") -> None:
        """TC-CN-N-03: citations contains citation edges.

        // Given: Task with source page that has cites edges
        // When: get_materials_action with include_citations=true
        // Then: citations contains the edges
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, title, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', 'Source', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, title, fetched_at)
            VALUES ('page-2', 'https://cited.com', 'cited.com', 'Cited Paper', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-frag-claim', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, citation_source)
            VALUES ('edge-cites', 'page', 'page-1', 'page', 'page-2', 'cites', 'semantic_scholar')
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: citations contains the edge
        citation_network = result["citation_network"]
        assert len(citation_network["citations"]) == 1
        assert citation_network["citations"][0]["edge_id"] == "edge-cites"
        assert citation_network["citations"][0]["citing_page_id"] == "page-1"
        assert citation_network["citations"][0]["cited_page_id"] == "page-2"
        assert citation_network["citations"][0]["cited_title"] == "Cited Paper"
        assert citation_network["citations"][0]["citation_source"] == "semantic_scholar"

    @pytest.mark.asyncio
    async def test_hub_pages_sorted_by_count(self, test_database: "Database") -> None:
        """TC-CN-N-04: hub_pages sorted by cited_by_count descending.

        // Given: Multiple pages with different citation counts
        // When: get_materials_action with include_citations=true
        // Then: hub_pages sorted by cited_by_count DESC
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data with multiple citations to different pages
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        # Source pages
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-src1', 'https://src1.com', 'src1.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-src2', 'https://src2.com', 'src2.com', datetime('now'))
            """
        )
        # Cited pages
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, title, fetched_at)
            VALUES ('page-hub-high', 'https://hub-high.com', 'hub-high.com', 'High Hub', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, title, fetched_at)
            VALUES ('page-hub-low', 'https://hub-low.com', 'hub-low.com', 'Low Hub', datetime('now'))
            """
        )
        # Fragments
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-src1', 'paragraph', 'Frag 1', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-2', 'page-src2', 'paragraph', 'Frag 2', datetime('now'))
            """
        )
        # Fragment -> claim edges
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-fc1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-fc2', 'fragment', 'frag-2', 'claim', 'claim-1', 'supports')
            """
        )
        # Cites edges: page-hub-high is cited by both sources, page-hub-low by one
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-c1', 'page', 'page-src1', 'page', 'page-hub-high', 'cites')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-c2', 'page', 'page-src2', 'page', 'page-hub-high', 'cites')
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-c3', 'page', 'page-src1', 'page', 'page-hub-low', 'cites')
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: hub_pages sorted by cited_by_count DESC
        citation_network = result["citation_network"]
        hub_pages = citation_network["hub_pages"]
        assert len(hub_pages) == 2
        assert hub_pages[0]["page_id"] == "page-hub-high"
        assert hub_pages[0]["cited_by_count"] == 2
        assert hub_pages[1]["page_id"] == "page-hub-low"
        assert hub_pages[1]["cited_by_count"] == 1

    @pytest.mark.asyncio
    async def test_include_citations_false_returns_null(self, test_database: "Database") -> None:
        """TC-CN-N-05: include_citations=false returns no citation_network.

        // Given: Task with citation data
        // When: get_materials_action with include_citations=false (default)
        // Then: citation_network is not in response
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create minimal task
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # When: Call get_materials_action without include_citations (default=false)
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(task_id="test-task")

        # Then: citation_network is not in response
        assert "citation_network" not in result

    @pytest.mark.asyncio
    async def test_include_graph_and_citations_both_work(self, test_database: "Database") -> None:
        """TC-CN-N-06: include_graph and include_citations work independently.

        // Given: Task with data
        // When: get_materials_action with both include_graph=true and include_citations=true
        // Then: Both evidence_graph and citation_network are in response
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Call get_materials_action with both options
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_graph=True,
                include_citations=True,
            )

        # Then: Both are in response
        assert "evidence_graph" in result
        assert result["evidence_graph"] is not None
        assert "citation_network" in result
        assert result["citation_network"] is not None


class TestCitationNetworkBoundary:
    """Tests for boundary cases in citation network."""

    @pytest.mark.asyncio
    async def test_no_claims_empty_citation_network(self, test_database: "Database") -> None:
        """TC-CN-B-01: Task with no claims returns empty citation_network.

        // Given: Task with no claims
        // When: get_materials_action with include_citations=true
        // Then: citation_network has empty arrays
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Task with no claims
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: citation_network has empty arrays
        citation_network = result["citation_network"]
        assert citation_network["source_pages"] == []
        assert citation_network["citations"] == []
        assert citation_network["hub_pages"] == []

    @pytest.mark.asyncio
    async def test_claims_no_citations_empty_arrays(self, test_database: "Database") -> None:
        """TC-CN-B-02: Claims but no citations returns empty citations/hub_pages.

        // Given: Task with claims but no cites edges
        // When: get_materials_action with include_citations=true
        // Then: source_pages populated, citations/hub_pages empty
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Task with claim but no cites edges
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-1', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-1', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-1', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: source_pages populated, citations/hub_pages empty
        citation_network = result["citation_network"]
        assert len(citation_network["source_pages"]) == 1
        assert citation_network["citations"] == []
        assert citation_network["hub_pages"] == []

    @pytest.mark.asyncio
    async def test_hub_pages_limit_10(self, test_database: "Database") -> None:
        """TC-CN-B-03: hub_pages limited to 10 results.

        // Given: More than 10 cited pages
        // When: get_materials_action with include_citations=true
        // Then: hub_pages has at most 10 entries
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: Create test data with 15 cited pages
        await test_database.execute(
            """
            INSERT INTO tasks (id, query, status, created_at)
            VALUES ('test-task', 'Test question', 'pending', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, llm_claim_confidence)
            VALUES ('claim-1', 'test-task', 'Test claim', 0.9)
            """
        )
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, fetched_at)
            VALUES ('page-src', 'https://source.com', 'source.com', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, created_at)
            VALUES ('frag-1', 'page-src', 'paragraph', 'Fragment text', datetime('now'))
            """
        )
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES ('edge-fc', 'fragment', 'frag-1', 'claim', 'claim-1', 'supports')
            """
        )

        # Create 15 cited pages with cites edges
        for i in range(15):
            await test_database.execute(
                f"""
                INSERT INTO pages (id, url, domain, title, fetched_at)
                VALUES ('page-cited-{i}', 'https://cited{i}.com', 'cited{i}.com', 'Cited {i}', datetime('now'))
                """
            )
            await test_database.execute(
                f"""
                INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
                VALUES ('edge-c{i}', 'page', 'page-src', 'page', 'page-cited-{i}', 'cites')
                """
            )

        # When: Call get_materials_action with include_citations=true
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="test-task",
                include_citations=True,
            )

        # Then: hub_pages has at most 10 entries
        citation_network = result["citation_network"]
        assert len(citation_network["hub_pages"]) == 10


class TestCitationNetworkNegative:
    """Tests for negative cases in citation network."""

    @pytest.mark.asyncio
    async def test_invalid_task_returns_error(self, test_database: "Database") -> None:
        """TC-CN-A-01: Invalid task_id returns error response.

        // Given: Non-existent task_id
        // When: get_materials_action with include_citations=true
        // Then: Returns error response (ok=false)
        """
        from unittest.mock import patch

        from src.research import materials

        # Given: No task exists

        # When: Call get_materials_action with non-existent task
        with patch.object(materials, "get_database", return_value=test_database):
            result = await materials.get_materials_action(
                task_id="non-existent-task",
                include_citations=True,
            )

        # Then: Returns error response
        assert result["ok"] is False
        assert "error" in result
        assert "citation_network" not in result
