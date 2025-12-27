"""
Tests for page_number propagation to serp_items table.

Validates that page_number is correctly stored in the database when SERP results
are inserted via search_serp().

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-W-01 | search_serp() with page_number=1 | Wiring | serp_items.page_number=1 | Default |
| TC-W-02 | search_serp() with page_number=3 | Wiring | serp_items.page_number=3 | Custom |
| TC-W-03 | Result dict missing page_number | Wiring | serp_items.page_number=1 | Fallback |
| TC-E-01 | Different page_number values | Effect | Different DB values | Effect |
| TC-B-01 | page_number=1 (minimum) | Boundary | Valid insert | Min |
| TC-B-02 | page_number=10 (max expected) | Boundary | Valid insert | Max |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests (mocked DB)
pytestmark = pytest.mark.unit


class TestSearchApiPageNumberWiring:
    """Wiring tests for page_number propagation to serp_items table."""

    @pytest.mark.asyncio
    async def test_page_number_included_in_insert(self) -> None:
        """TC-W-01: Wiring test - page_number is included in serp_items INSERT.

        // Given: Search result with page_number=2
        // When: search_serp() stores results
        // Then: INSERT includes page_number=2
        """
        from src.search.search_api import search_serp

        # Given: Mock database and search provider
        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)  # No cache
        mock_db.insert = AsyncMock(return_value="query_123")
        mock_db.execute = AsyncMock()

        # Mock search results with page_number=2
        mock_results = [
            {
                "title": "Test Result",
                "url": "https://example.com",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
                "source_tag": "unknown",
                "page_number": 2,
                "date": None,
            }
        ]

        with (
            patch("src.search.search_api.get_database", AsyncMock(return_value=mock_db)),
            patch(
                "src.search.search_api._search_with_provider",
                AsyncMock(return_value=mock_results),
            ),
            patch(
                "src.search.search_api.parse_query_operators", return_value=MagicMock(operators=[])
            ),
        ):
            # When: search_serp() is called
            await search_serp(
                query="test query",
                task_id="task_123",
                use_cache=False,
            )

            # Then: INSERT includes page_number=2
            # Find the serp_items INSERT call
            serp_insert_calls = [
                call for call in mock_db.insert.call_args_list if call[0][0] == "serp_items"
            ]
            assert len(serp_insert_calls) == 1

            insert_data = serp_insert_calls[0][0][1]
            assert "page_number" in insert_data
            assert insert_data["page_number"] == 2

    @pytest.mark.asyncio
    async def test_page_number_defaults_to_one_when_missing(self) -> None:
        """TC-W-03: Wiring test - page_number defaults to 1 when missing from result.

        // Given: Search result without page_number field
        // When: search_serp() stores results
        // Then: INSERT includes page_number=1 (default)
        """
        from src.search.search_api import search_serp

        # Given: Mock database and search provider
        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)  # No cache
        mock_db.insert = AsyncMock(return_value="query_123")
        mock_db.execute = AsyncMock()

        # Mock search results WITHOUT page_number (backward compatibility)
        mock_results = [
            {
                "title": "Test Result",
                "url": "https://example.com",
                "snippet": "Test snippet",
                "engine": "duckduckgo",
                "rank": 1,
                "source_tag": "unknown",
                "date": None,
                # Note: no page_number key
            }
        ]

        with (
            patch("src.search.search_api.get_database", AsyncMock(return_value=mock_db)),
            patch(
                "src.search.search_api._search_with_provider",
                AsyncMock(return_value=mock_results),
            ),
            patch(
                "src.search.search_api.parse_query_operators", return_value=MagicMock(operators=[])
            ),
        ):
            # When: search_serp() is called
            await search_serp(
                query="test query",
                task_id="task_123",
                use_cache=False,
            )

            # Then: INSERT includes page_number=1 (default)
            serp_insert_calls = [
                call for call in mock_db.insert.call_args_list if call[0][0] == "serp_items"
            ]
            assert len(serp_insert_calls) == 1

            insert_data = serp_insert_calls[0][0][1]
            assert "page_number" in insert_data
            assert insert_data["page_number"] == 1

    @pytest.mark.asyncio
    async def test_page_number_boundary_minimum(self) -> None:
        """TC-B-01: Boundary test - page_number=1 (minimum value).

        // Given: Search result with page_number=1
        // When: search_serp() stores results
        // Then: INSERT includes page_number=1
        """
        from src.search.search_api import search_serp

        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_db.insert = AsyncMock(return_value="query_123")
        mock_db.execute = AsyncMock()

        mock_results = [
            {
                "title": "Test",
                "url": "https://example.com",
                "snippet": "Test",
                "engine": "duckduckgo",
                "rank": 1,
                "source_tag": "unknown",
                "page_number": 1,
                "date": None,
            }
        ]

        with (
            patch("src.search.search_api.get_database", AsyncMock(return_value=mock_db)),
            patch(
                "src.search.search_api._search_with_provider",
                AsyncMock(return_value=mock_results),
            ),
            patch(
                "src.search.search_api.parse_query_operators", return_value=MagicMock(operators=[])
            ),
        ):
            await search_serp(query="test", task_id="task_123", use_cache=False)

            serp_insert_calls = [
                call for call in mock_db.insert.call_args_list if call[0][0] == "serp_items"
            ]
            assert serp_insert_calls[0][0][1]["page_number"] == 1

    @pytest.mark.asyncio
    async def test_page_number_boundary_maximum(self) -> None:
        """TC-B-02: Boundary test - page_number=10 (maximum expected value).

        // Given: Search result with page_number=10
        // When: search_serp() stores results
        // Then: INSERT includes page_number=10
        """
        from src.search.search_api import search_serp

        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_db.insert = AsyncMock(return_value="query_123")
        mock_db.execute = AsyncMock()

        mock_results = [
            {
                "title": "Test",
                "url": "https://example.com",
                "snippet": "Test",
                "engine": "duckduckgo",
                "rank": 1,
                "source_tag": "unknown",
                "page_number": 10,
                "date": None,
            }
        ]

        with (
            patch("src.search.search_api.get_database", AsyncMock(return_value=mock_db)),
            patch(
                "src.search.search_api._search_with_provider",
                AsyncMock(return_value=mock_results),
            ),
            patch(
                "src.search.search_api.parse_query_operators", return_value=MagicMock(operators=[])
            ),
        ):
            await search_serp(query="test", task_id="task_123", use_cache=False)

            serp_insert_calls = [
                call for call in mock_db.insert.call_args_list if call[0][0] == "serp_items"
            ]
            assert serp_insert_calls[0][0][1]["page_number"] == 10


class TestSearchApiPageNumberEffect:
    """Effect tests for page_number propagation."""

    @pytest.mark.asyncio
    async def test_different_page_numbers_stored_correctly(self) -> None:
        """TC-E-01: Effect test - different page_number values are stored correctly.

        // Given: Search results with page_number=1 and page_number=2
        // When: search_serp() stores results
        // Then: Each result has correct page_number in INSERT
        """
        from src.search.search_api import search_serp

        mock_db = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_db.insert = AsyncMock(return_value="query_123")
        mock_db.execute = AsyncMock()

        # Results from different SERP pages
        mock_results = [
            {
                "title": "Result from page 1",
                "url": "https://example.com/1",
                "snippet": "First page result",
                "engine": "duckduckgo",
                "rank": 1,
                "source_tag": "unknown",
                "page_number": 1,
                "date": None,
            },
            {
                "title": "Result from page 2",
                "url": "https://example.com/2",
                "snippet": "Second page result",
                "engine": "duckduckgo",
                "rank": 2,
                "source_tag": "unknown",
                "page_number": 2,
                "date": None,
            },
        ]

        with (
            patch("src.search.search_api.get_database", AsyncMock(return_value=mock_db)),
            patch(
                "src.search.search_api._search_with_provider",
                AsyncMock(return_value=mock_results),
            ),
            patch(
                "src.search.search_api.parse_query_operators", return_value=MagicMock(operators=[])
            ),
        ):
            await search_serp(query="test", task_id="task_123", use_cache=False)

            # Then: Each result has correct page_number
            serp_insert_calls = [
                call for call in mock_db.insert.call_args_list if call[0][0] == "serp_items"
            ]
            assert len(serp_insert_calls) == 2

            # First result should have page_number=1
            assert serp_insert_calls[0][0][1]["page_number"] == 1
            # Second result should have page_number=2
            assert serp_insert_calls[1][0][1]["page_number"] == 2
