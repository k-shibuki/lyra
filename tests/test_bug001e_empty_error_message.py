"""
Tests for BUG-001e: Empty error messages on Ollama/ML server errors.

## Problem
`asyncio.TimeoutError` and some `aiohttp`/`httpx` exceptions have no `args`,
causing `str(e)` to return an empty string. This made error logs and responses
unhelpful for debugging.

## Fix
When `str(e)` is empty, use `{type(e).__name__}: (no message)` instead.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Exception with message | Equivalence – normal | str(e) used as-is | - |
| TC-N-02 | Empty string exception | Boundary – empty | TypeName: (no message) | BUG-001e fix |
| TC-N-03 | TimeoutError() no args | Boundary – no args | TimeoutError: (no message) | Real case |
| TC-A-01 | aiohttp.ClientError() | Boundary – empty base | ClientError: (no message) | - |
| TC-A-02 | httpx.RequestError("") | Boundary – empty str | RequestError: (no message) | - |
| TC-A-03 | ServerTimeoutError | Equivalence – timeout | Custom timeout message | Special case |
| TC-A-04 | Exception with cause | Boundary – nested | Outer type used | - |
"""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import httpx
import pytest

if TYPE_CHECKING:
    from src.filter.ollama_provider import OllamaProvider
    from src.ml_client import MLClient

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit


# ============================================================================
# OllamaProvider Empty Error Message Tests
# ============================================================================


class TestOllamaProviderEmptyErrorMessage:
    """Tests for OllamaProvider error message handling (BUG-001e)."""

    @pytest.fixture
    def ollama_provider(self) -> OllamaProvider:
        """Create an OllamaProvider for testing."""
        from src.filter.ollama_provider import OllamaProvider

        return OllamaProvider(
            host="http://localhost:11434",
            model="test-model:3b",
        )

    @pytest.mark.asyncio
    async def test_generate_normal_error_message(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-N-01: Exception with normal message should use str(e) as-is.

        // Given: aiohttp raises ClientError with a message
        // When: generate() catches the exception
        // Then: The error message is used as-is
        """
        # Given
        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = aiohttp.ClientError("Connection refused")
        mock_session.post = MagicMock(return_value=mock_cm)

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        # Then
        assert response.ok is False
        assert response.error == "Connection refused"
        assert "Connection refused" in response.error

    @pytest.mark.asyncio
    async def test_generate_empty_client_error(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-A-01: aiohttp.ClientError() with no args should use type name.

        // Given: aiohttp raises ClientError with no message (str(e) == "")
        // When: generate() catches the exception
        // Then: Error message is "ClientError: (no message)"
        """
        # Given
        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = aiohttp.ClientError()  # No message
        mock_session.post = MagicMock(return_value=mock_cm)

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        # Then
        assert response.ok is False
        assert response.error is not None
        assert response.error != ""  # BUG-001e: should NOT be empty
        assert "ClientError" in response.error
        assert "(no message)" in response.error

    @pytest.mark.asyncio
    async def test_generate_timeout_error_no_args(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-N-03: TimeoutError() with no args should use type name.

        // Given: asyncio.wait_for raises TimeoutError() (no args)
        // When: generate() catches the exception
        // Then: Error message is "TimeoutError: (no message)"
        """
        # Given
        mock_session = MagicMock()
        mock_cm = AsyncMock()
        # TimeoutError raised by asyncio.wait_for has no args
        mock_cm.__aenter__.side_effect = TimeoutError()
        mock_session.post = MagicMock(return_value=mock_cm)

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        # Then
        assert response.ok is False
        assert response.error is not None
        assert response.error != ""  # BUG-001e: should NOT be empty
        assert "TimeoutError" in response.error
        assert "(no message)" in response.error

    @pytest.mark.asyncio
    async def test_generate_server_timeout_has_custom_message(
        self, ollama_provider: OllamaProvider
    ) -> None:
        """
        TC-A-03: ServerTimeoutError should use custom timeout message.

        // Given: aiohttp raises ServerTimeoutError
        // When: generate() catches the exception
        // Then: Error message mentions timeout with duration
        """
        # Given
        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = aiohttp.ServerTimeoutError("Timeout")
        mock_session.post = MagicMock(return_value=mock_cm)

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        # Then
        assert response.ok is False
        assert response.error is not None
        # ServerTimeoutError has special handling with custom message
        assert "timeout" in response.error.lower()

    @pytest.mark.asyncio
    async def test_chat_empty_client_error(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-A-01 (chat): aiohttp.ClientError() in chat should use type name.

        // Given: aiohttp raises ClientError with no message in chat()
        // When: chat() catches the exception
        // Then: Error message is "ClientError: (no message)"
        """
        # Given
        from src.filter.provider import ChatMessage

        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = aiohttp.ClientError()
        mock_session.post = MagicMock(return_value=mock_cm)

        messages = [ChatMessage(role="user", content="Hello")]

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.chat(messages)

        # Then
        assert response.ok is False
        assert response.error is not None
        assert response.error != ""
        assert "ClientError" in response.error
        assert "(no message)" in response.error

    @pytest.mark.asyncio
    async def test_chat_timeout_error_no_args(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-N-03 (chat): TimeoutError() in chat should use type name.

        // Given: TimeoutError() raised in chat()
        // When: chat() catches the exception
        // Then: Error message is "TimeoutError: (no message)"
        """
        # Given
        from src.filter.provider import ChatMessage

        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = TimeoutError()
        mock_session.post = MagicMock(return_value=mock_cm)

        messages = [ChatMessage(role="user", content="Hello")]

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.chat(messages)

        # Then
        assert response.ok is False
        assert response.error is not None
        assert response.error != ""
        assert "TimeoutError" in response.error
        assert "(no message)" in response.error

    @pytest.mark.asyncio
    async def test_embed_timeout_error_no_args(self, ollama_provider: OllamaProvider) -> None:
        """
        TC-N-03 (embed): TimeoutError() in embed should use type name.

        // Given: TimeoutError() raised in embed()
        // When: embed() catches the exception
        // Then: Error message is "TimeoutError: (no message)"
        """
        # Given
        mock_session = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = TimeoutError()
        mock_session.post = MagicMock(return_value=mock_cm)

        # When
        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.embed(["test text"])

        # Then
        assert response.ok is False
        assert response.error is not None
        assert response.error != ""
        assert "TimeoutError" in response.error
        assert "(no message)" in response.error


# ============================================================================
# MLClient Empty Error Message Tests
# ============================================================================


class TestMLClientEmptyErrorMessage:
    """Tests for MLClient error message handling (BUG-001e)."""

    @pytest.fixture
    def ml_client(self) -> MLClient:
        """Create an MLClient for testing."""
        from src.ml_client import MLClient

        client = MLClient()
        client._base_url = "http://localhost:8080/ml"
        return client

    @pytest.mark.asyncio
    async def test_request_normal_error_message(self, ml_client: MLClient) -> None:
        """
        TC-N-01: httpx.RequestError with message should use str(e) as-is.

        // Given: httpx raises RequestError with a message
        // When: _request_with_retry catches the exception
        // Then: The error message is logged as-is
        """
        # Given
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        # When/Then
        with patch.object(ml_client, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(httpx.ConnectError) as exc_info:
                await ml_client._request_with_retry("GET", "/health")

            # Verify the original exception message is preserved
            assert "Connection refused" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_empty_error_message_logged(self, ml_client: MLClient) -> None:
        """
        TC-A-02: httpx.RequestError("") should log type name.

        // Given: httpx raises RequestError with empty message
        // When: _request_with_retry catches and logs the exception
        // Then: Log message includes type name, not empty string
        """
        # Given
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("")

        # When
        with patch.object(ml_client, "_get_client", AsyncMock(return_value=mock_client)):
            with patch("src.ml_client.logger") as mock_logger:
                with pytest.raises(httpx.RequestError):
                    await ml_client._request_with_retry("GET", "/health")

                # Then: Logger should have been called with non-empty error
                warning_calls = mock_logger.warning.call_args_list
                assert len(warning_calls) > 0

                # Check that error field is not empty
                for call in warning_calls:
                    if "error" in call.kwargs:
                        error_msg = call.kwargs["error"]
                        assert error_msg != ""  # BUG-001e fix
                        assert "RequestError" in error_msg
                        assert "(no message)" in error_msg

    @pytest.mark.asyncio
    async def test_request_connect_error_empty(self, ml_client: MLClient) -> None:
        """
        TC-A-02 (ConnectError): httpx.ConnectError("") should log type name.

        // Given: httpx raises ConnectError with empty message
        // When: _request_with_retry catches and logs the exception
        // Then: Log message includes "ConnectError: (no message)"
        """
        # Given
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("")

        # When
        with patch.object(ml_client, "_get_client", AsyncMock(return_value=mock_client)):
            with patch("src.ml_client.logger") as mock_logger:
                with pytest.raises(httpx.ConnectError):
                    await ml_client._request_with_retry("POST", "/embed", json={"texts": ["test"]})

                # Then
                warning_calls = mock_logger.warning.call_args_list
                assert len(warning_calls) > 0

                for call in warning_calls:
                    if "error" in call.kwargs:
                        error_msg = call.kwargs["error"]
                        assert error_msg != ""
                        assert "ConnectError" in error_msg
                        assert "(no message)" in error_msg


# ============================================================================
# Direct Exception Behavior Tests
# ============================================================================


class TestExceptionStringBehavior:
    """Tests to document exception str() behavior that causes BUG-001e."""

    def test_timeout_error_no_args_is_empty(self) -> None:
        """
        Document: TimeoutError() with no args produces empty str().

        This is the root cause of BUG-001e.
        """
        exc = TimeoutError()
        assert str(exc) == ""
        assert exc.args == ()

    def test_timeout_error_with_message_not_empty(self) -> None:
        """
        Document: TimeoutError("message") produces non-empty str().
        """
        exc = TimeoutError("Timeout after 30s")
        assert str(exc) == "Timeout after 30s"
        assert exc.args == ("Timeout after 30s",)

    def test_aiohttp_client_error_no_args_is_empty(self) -> None:
        """
        Document: aiohttp.ClientError() with no args produces empty str().
        """
        exc = aiohttp.ClientError()
        assert str(exc) == ""
        assert exc.args == ()

    def test_httpx_request_error_empty_string_is_empty(self) -> None:
        """
        Document: httpx.RequestError("") produces empty str().
        """
        exc = httpx.RequestError("")
        assert str(exc) == ""
        assert exc.args == ("",)

    def test_cancelled_error_no_args_is_empty(self) -> None:
        """
        Document: asyncio.CancelledError() produces empty str().

        This is often the __cause__ of TimeoutError.
        """
        exc = asyncio.CancelledError()
        assert str(exc) == ""
        assert exc.args == ()


# ============================================================================
# Error Message Fallback Pattern Tests
# ============================================================================


class TestErrorMessageFallbackPattern:
    """Tests for the error message fallback pattern used in BUG-001e fix."""

    def test_fallback_pattern_with_message(self) -> None:
        """
        Fallback pattern should return original message when present.
        """
        exc = ValueError("Original error")
        error_msg = str(exc) or f"{type(exc).__name__}: (no message)"
        assert error_msg == "Original error"

    def test_fallback_pattern_without_message(self) -> None:
        """
        Fallback pattern should return type name when message is empty.
        """
        exc = TimeoutError()
        error_msg = str(exc) or f"{type(exc).__name__}: (no message)"
        assert error_msg == "TimeoutError: (no message)"

    def test_fallback_pattern_preserves_exception_type(self) -> None:
        """
        Fallback pattern should preserve the specific exception type name.
        """
        exceptions = [
            (aiohttp.ClientError(), "ClientError"),
            (aiohttp.ServerTimeoutError(""), "ServerTimeoutError"),
            (httpx.ConnectError(""), "ConnectError"),
            (httpx.TimeoutException(""), "TimeoutException"),
            (asyncio.CancelledError(), "CancelledError"),
        ]

        for exc, expected_type in exceptions:
            error_msg = str(exc) or f"{type(exc).__name__}: (no message)"
            if str(exc) == "":
                assert expected_type in error_msg
                assert "(no message)" in error_msg
