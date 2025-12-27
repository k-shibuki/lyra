"""Tests for Chrome auto-start lock and CDP availability check.

This module tests the race condition prevention mechanisms for Chrome auto-start.

Test Perspectives Table
=======================

| Case ID   | Input / Precondition              | Perspective          | Expected Result                        | Notes                |
|-----------|-----------------------------------|----------------------|----------------------------------------|----------------------|
| TC-N-01   | First call to get_lock           | Normal               | Returns Lock instance                  | Initial creation     |
| TC-N-02   | Multiple calls to get_lock       | Normal               | Same Lock instance (singleton)         | Singleton pattern    |
| TC-N-03   | CDP endpoint unavailable         | Boundary - NULL      | Returns False                          | Connection refused   |
| TC-N-04   | CDP endpoint available (mocked)  | Normal               | Returns True                           | HTTP 200 response    |
| TC-N-05   | CDP endpoint timeout             | Boundary - timeout   | Returns False                          | Timeout exceeded     |
| TC-N-06   | Lock prevents concurrent starts  | Normal               | Only one chrome.sh call at a time      | Race prevention      |
| TC-A-01   | Invalid host                     | Abnormal             | Returns False                          | Connection error     |
| TC-A-02   | Invalid port                     | Abnormal             | Returns False                          | Connection error     |
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.search.browser_search_provider import (
    _check_cdp_available,
    _get_chrome_start_lock,
)


class TestChromeStartLock:
    """Tests for Chrome start lock singleton."""

    def test_get_lock_returns_lock_instance(self) -> None:
        """Test that _get_chrome_start_lock returns a Lock instance.

        Given: No preconditions
        When: _get_chrome_start_lock() is called
        Then: Returns an asyncio.Lock instance
        """
        # When
        lock = _get_chrome_start_lock()

        # Then
        assert isinstance(lock, asyncio.Lock)

    def test_get_lock_returns_same_instance(self) -> None:
        """Test that _get_chrome_start_lock returns the same instance (singleton).

        Given: A lock has been created
        When: _get_chrome_start_lock() is called multiple times
        Then: Returns the same Lock instance each time
        """
        # When
        lock1 = _get_chrome_start_lock()
        lock2 = _get_chrome_start_lock()
        lock3 = _get_chrome_start_lock()

        # Then
        assert lock1 is lock2
        assert lock2 is lock3


class TestCdpAvailableCheck:
    """Tests for CDP endpoint availability check."""

    @pytest.mark.asyncio
    async def test_cdp_unavailable_connection_refused(self) -> None:
        """Test that _check_cdp_available returns False when connection refused.

        Given: No Chrome running on the port (connection refused)
        When: _check_cdp_available(host, port) is called
        Then: Returns False
        """
        # Given: Using a port that definitely has no server
        host = "localhost"
        port = 59999  # Unlikely to have anything listening

        # When
        result = await _check_cdp_available(host, port, timeout=1.0)

        # Then
        assert result is False

    @pytest.mark.asyncio
    async def test_cdp_unavailable_invalid_host(self) -> None:
        """Test that _check_cdp_available returns False for invalid host.

        Given: Invalid hostname
        When: _check_cdp_available(invalid_host, port) is called
        Then: Returns False
        """
        # Given
        host = "invalid.host.that.does.not.exist.local"
        port = 9222

        # When
        result = await _check_cdp_available(host, port, timeout=1.0)

        # Then
        assert result is False

    @pytest.mark.asyncio
    async def test_cdp_available_mocked(self) -> None:
        """Test that _check_cdp_available returns True when CDP responds.

        Given: CDP endpoint responds with HTTP 200
        When: _check_cdp_available(host, port) is called
        Then: Returns True
        """
        # Given: Mock aiohttp to return 200
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # When
            result = await _check_cdp_available("localhost", 9222)

            # Then
            assert result is True


class TestAutoStartLockBehavior:
    """Tests for lock behavior during auto-start."""

    @pytest.mark.asyncio
    async def test_lock_serializes_concurrent_calls(self) -> None:
        """Test that the lock serializes concurrent auto-start attempts.

        Given: Multiple concurrent calls trying to acquire the lock
        When: Tasks run concurrently
        Then: Lock is acquired one at a time (no concurrent execution inside lock)
        """
        # Given
        lock = _get_chrome_start_lock()
        execution_order: list[str] = []

        async def simulate_auto_start(worker_id: int) -> None:
            async with lock:
                execution_order.append(f"start_{worker_id}")
                await asyncio.sleep(0.01)  # Simulate some work
                execution_order.append(f"end_{worker_id}")

        # When: Run 3 workers concurrently
        await asyncio.gather(
            simulate_auto_start(0),
            simulate_auto_start(1),
            simulate_auto_start(2),
        )

        # Then: Each worker's start-end pair should be contiguous (not interleaved)
        # Pattern should be: start_X, end_X, start_Y, end_Y, start_Z, end_Z
        for i in range(0, len(execution_order), 2):
            start_event = execution_order[i]
            end_event = execution_order[i + 1]
            # Extract worker ID from event names
            start_worker = start_event.split("_")[1]
            end_worker = end_event.split("_")[1]
            assert (
                start_worker == end_worker
            ), f"Lock did not serialize execution: {execution_order}"
