"""
Unit tests for external search guard in src.search.search_api._search_with_provider.

Goal:
- Prevent accidental external browser search during unit/integration tests.
- Allow explicitly enabled runs (E2E or opt-in env var).

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-GUARD-N-01 | pytest, no env opt-in | Equivalence – normal | Raises RuntimeError | Default safe |
| TC-GUARD-N-02 | pytest + LYRA_ALLOW_EXTERNAL_SEARCH=1 | Equivalence – normal | Does not raise at guard | Provider mocked to avoid network |
| TC-GUARD-N-03 | pytest + LYRA_TEST_LAYER=e2e | Equivalence – normal | Does not raise at guard | Provider mocked to avoid network |
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestExternalSearchGuard:
    @pytest.mark.asyncio
    async def test_guard_blocks_external_search_by_default(self) -> None:
        """
        TC-GUARD-N-01: Guard blocks by default during pytest.

        // Given: pytest context and no opt-in env vars
        // When:  _search_with_provider is called
        // Then:  RuntimeError is raised before any provider is created
        """
        from src.search.search_api import _search_with_provider

        with pytest.raises(RuntimeError) as exc_info:
            await _search_with_provider(query="q")

        assert "External search is disabled during pytest" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_guard_allows_with_opt_in_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        TC-GUARD-N-02: Guard allows when explicitly opted-in.

        // Given: LYRA_ALLOW_EXTERNAL_SEARCH=1
        // When:  _search_with_provider is called
        // Then:  Guard does not raise, and provider.search is invoked (mocked)
        """
        from src.search.search_api import _search_with_provider

        monkeypatch.setenv("LYRA_ALLOW_EXTERNAL_SEARCH", "1")
        monkeypatch.delenv("LYRA_TEST_LAYER", raising=False)

        mock_provider = MagicMock()
        mock_provider.search = AsyncMock()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"url": "https://example.com", "title": "t"}
        mock_response = MagicMock(ok=True, provider="mock", results=[mock_result], error=None)
        mock_provider.search.return_value = mock_response

        with patch("src.search.browser_search_provider.get_browser_search_provider", return_value=mock_provider):
            out = await _search_with_provider(query="q", engines=["mojeek"], limit=1)

        assert out == [{"url": "https://example.com", "title": "t"}]
        assert mock_provider.search.await_count == 1

    @pytest.mark.asyncio
    async def test_guard_allows_in_e2e_layer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        TC-GUARD-N-03: Guard allows when running in E2E layer.

        // Given: LYRA_TEST_LAYER=e2e
        // When:  _search_with_provider is called
        // Then:  Guard does not raise, and provider.search is invoked (mocked)
        """
        from src.search.search_api import _search_with_provider

        monkeypatch.setenv("LYRA_TEST_LAYER", "e2e")
        monkeypatch.delenv("LYRA_ALLOW_EXTERNAL_SEARCH", raising=False)

        mock_provider = MagicMock()
        mock_provider.search = AsyncMock()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"url": "https://example.com", "title": "t"}
        mock_response = MagicMock(ok=True, provider="mock", results=[mock_result], error=None)
        mock_provider.search.return_value = mock_response

        with patch("src.search.browser_search_provider.get_browser_search_provider", return_value=mock_provider):
            out = await _search_with_provider(query="q", engines=["mojeek"], limit=1)

        assert out == [{"url": "https://example.com", "title": "t"}]
        assert mock_provider.search.await_count == 1


