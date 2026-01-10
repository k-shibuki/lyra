"""
Tests for guard against sending OpenAlex Work IDs to Semantic Scholar.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---|---|---|---|---|
| TC-API-02-N-01 | paper_id="openalex:W123" | Equivalence – normal | get_paper returns None, no HTTP session used | Avoid 404 noise |
| TC-API-02-N-02 | paper_id="https://openalex.org/W123" | Equivalence – normal | get_paper returns None, no HTTP session used | URL form |
| TC-API-02-N-03 | paper_id="openalex:W123" | Equivalence – normal | get_references returns [], no HTTP session used | - |
| TC-API-02-N-04 | paper_id="openalex:W123" | Equivalence – normal | get_citations returns [], no HTTP session used | - |
| TC-API-02-B-01 | paper_id="openalex:" | Boundary – empty | Treated as OpenAlex-like and skipped | Prefix-only still must not call S2 |
"""

from unittest.mock import AsyncMock

import pytest

from src.search.apis.semantic_scholar import SemanticScholarClient


@pytest.mark.asyncio
async def test_api_02_get_paper_skips_openalex_work_id() -> None:
    # Given: SemanticScholarClient with _get_session mocked
    client = SemanticScholarClient()
    with pytest.MonkeyPatch.context() as mp:
        mock_get_session = AsyncMock()
        mp.setattr(client, "_get_session", mock_get_session, raising=True)

        # When: get_paper is called with OpenAlex Work ID
        result = await client.get_paper("openalex:W123")

        # Then: It is skipped and no HTTP session is used
        assert result is None
        mock_get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_02_get_paper_skips_openalex_url() -> None:
    # Given: SemanticScholarClient with _get_session mocked
    client = SemanticScholarClient()
    with pytest.MonkeyPatch.context() as mp:
        mock_get_session = AsyncMock()
        mp.setattr(client, "_get_session", mock_get_session, raising=True)

        # When: get_paper is called with OpenAlex URL
        result = await client.get_paper("https://openalex.org/W123")

        # Then: It is skipped and no HTTP session is used
        assert result is None
        mock_get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_02_get_references_skips_openalex_work_id() -> None:
    # Given: SemanticScholarClient with _get_session mocked
    client = SemanticScholarClient()
    with pytest.MonkeyPatch.context() as mp:
        mock_get_session = AsyncMock()
        mp.setattr(client, "_get_session", mock_get_session, raising=True)

        # When: get_references is called with OpenAlex Work ID
        result = await client.get_references("openalex:W123")

        # Then: It is skipped and no HTTP session is used
        assert result == []
        mock_get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_02_get_citations_skips_openalex_work_id() -> None:
    # Given: SemanticScholarClient with _get_session mocked
    client = SemanticScholarClient()
    with pytest.MonkeyPatch.context() as mp:
        mock_get_session = AsyncMock()
        mp.setattr(client, "_get_session", mock_get_session, raising=True)

        # When: get_citations is called with OpenAlex Work ID
        result = await client.get_citations("openalex:W123")

        # Then: It is skipped and no HTTP session is used
        assert result == []
        mock_get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_02_get_paper_skips_openalex_prefix_only() -> None:
    # Given: SemanticScholarClient with _get_session mocked
    client = SemanticScholarClient()
    with pytest.MonkeyPatch.context() as mp:
        mock_get_session = AsyncMock()
        mp.setattr(client, "_get_session", mock_get_session, raising=True)

        # When: get_paper is called with OpenAlex prefix only (edge case)
        result = await client.get_paper("openalex:")

        # Then: It is still treated as OpenAlex-like and skipped
        assert result is None
        mock_get_session.assert_not_awaited()
