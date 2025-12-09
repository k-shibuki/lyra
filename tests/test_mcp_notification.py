"""Tests for notify_user and wait_for_user MCP tools.

Tests notification functionality per §3.2.1.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-N-01 | event=auth_required | Equivalence – normal | Notification sent | Auth event |
| TC-N-02 | event=task_progress | Equivalence – normal | Notification sent | Progress event |
| TC-N-03 | event=task_complete | Equivalence – normal | Notification sent | Complete event |
| TC-N-04 | event=error | Equivalence – normal | Notification sent | Error event |
| TC-N-05 | event=info | Equivalence – normal | Notification sent | Info event |
| TC-N-06 | wait_for_user prompt | Equivalence – normal | Notification sent | Wait trigger |
| TC-N-07 | wait_for_user with timeout | Equivalence – normal | Custom timeout in response | Custom timeout |
| TC-N-08 | wait_for_user default timeout | Equivalence – normal | Default 300s timeout | Default value |
| TC-A-01 | Missing event | Equivalence – error | InvalidParamsError | Required param |
| TC-A-02 | Invalid event type | Equivalence – error | InvalidParamsError | Invalid enum |
| TC-A-03 | Missing payload | Equivalence – error | InvalidParamsError | Required param |
| TC-A-04 | Missing prompt for wait | Equivalence – error | InvalidParamsError | Required param |
| TC-B-01 | timeout_seconds=0 | Boundary – zero | Accepts 0 (immediate) | Zero timeout |
| TC-B-02 | timeout_seconds=1 | Boundary – min | Accepts 1 second | Minimal timeout |
| TC-B-03 | Empty prompt | Boundary – empty | InvalidParamsError | Empty string |
| TC-B-04 | Empty payload dict | Boundary – empty | Accepts empty payload | Minimal payload |
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


class TestNotifyUserExecution:
    """Tests for notify_user execution."""

    @pytest.mark.asyncio
    async def test_auth_required_notification(self) -> None:
        """
        TC-N-01: Auth required notification.
        
        // Given: event=auth_required with URL
        // When: Calling notify_user
        // Then: Sends notification with auth message
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_notify_user({
                "event": "auth_required",
                "payload": {
                    "url": "https://example.com/protected",
                    "domain": "example.com",
                },
            })
        
        assert result["ok"] is True
        assert result["event"] == "auth_required"
        assert result["notified"] is True
        
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["event"] == "auth_required"

    @pytest.mark.asyncio
    async def test_task_progress_notification(self) -> None:
        """
        TC-N-02: Task progress notification.
        
        // Given: event=task_progress with message
        // When: Calling notify_user
        // Then: Sends progress notification
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_notify_user({
                "event": "task_progress",
                "payload": {
                    "message": "50% complete",
                    "task_id": "task_abc",
                    "progress_percent": 50,
                },
            })
        
        assert result["ok"] is True
        assert result["event"] == "task_progress"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_complete_notification(self) -> None:
        """
        TC-N-03: Task complete notification.
        
        // Given: event=task_complete
        // When: Calling notify_user
        // Then: Sends completion notification
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_notify_user({
                "event": "task_complete",
                "payload": {
                    "message": "Research task completed",
                    "task_id": "task_abc",
                },
            })
        
        assert result["ok"] is True
        assert result["event"] == "task_complete"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_notification(self) -> None:
        """
        TC-N-04: Error notification.
        
        // Given: event=error with message
        // When: Calling notify_user
        // Then: Sends error notification
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_notify_user({
                "event": "error",
                "payload": {
                    "message": "An error occurred",
                },
            })
        
        assert result["ok"] is True
        assert result["event"] == "error"
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["event"] == "error"

    @pytest.mark.asyncio
    async def test_info_notification(self) -> None:
        """
        TC-N-05: Info notification.
        
        // Given: event=info with message
        // When: Calling notify_user
        // Then: Sends info notification
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_notify_user({
                "event": "info",
                "payload": {
                    "message": "Information message",
                },
            })
        
        assert result["ok"] is True
        assert result["event"] == "info"
        mock_send.assert_called_once()


class TestNotifyUserValidation:
    """Tests for notify_user parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_event_raises_error(self) -> None:
        """
        TC-A-01: Missing event parameter.
        
        // Given: No event provided
        // When: Calling notify_user
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_notify_user
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_notify_user({
                "payload": {"message": "test"},
            })
        
        assert exc_info.value.details.get("param_name") == "event"

    @pytest.mark.asyncio
    async def test_invalid_event_type_raises_error(self) -> None:
        """
        TC-A-02: Invalid event type.
        
        // Given: event=invalid_event
        // When: Calling notify_user
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_notify_user
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_notify_user({
                "event": "invalid_event",
                "payload": {"message": "test"},
            })
        
        assert "event" in str(exc_info.value.details.get("param_name"))

    @pytest.mark.asyncio
    async def test_missing_payload_raises_error(self) -> None:
        """
        TC-A-03: Missing payload parameter.
        
        // Given: No payload provided
        // When: Calling notify_user
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_notify_user
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_notify_user({
                "event": "info",
            })
        
        assert exc_info.value.details.get("param_name") == "payload"

    @pytest.mark.asyncio
    async def test_empty_payload_accepted(self) -> None:
        """
        TC-B-04: Empty payload dict is accepted.
        
        // Given: payload={}
        // When: Calling notify_user
        // Then: Accepts empty payload
        """
        from src.mcp.server import _handle_notify_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ):
            result = await _handle_notify_user({
                "event": "info",
                "payload": {},
            })
        
        assert result["ok"] is True


class TestWaitForUserValidation:
    """Tests for wait_for_user parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_prompt_raises_error(self) -> None:
        """
        TC-A-04: Missing prompt parameter.
        
        // Given: No prompt provided
        // When: Calling wait_for_user
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_wait_for_user
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_wait_for_user({})
        
        assert exc_info.value.details.get("param_name") == "prompt"

    @pytest.mark.asyncio
    async def test_empty_prompt_raises_error(self) -> None:
        """
        TC-B-03: Empty prompt string.
        
        // Given: prompt=""
        // When: Calling wait_for_user
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_wait_for_user
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_wait_for_user({
                "prompt": "",
            })
        
        assert exc_info.value.details.get("param_name") == "prompt"


class TestWaitForUserBoundaryValues:
    """Tests for wait_for_user boundary values."""

    @pytest.mark.asyncio
    async def test_timeout_zero(self) -> None:
        """
        TC-B-01: timeout_seconds=0 (immediate).
        
        // Given: timeout_seconds=0
        // When: Calling wait_for_user
        // Then: Accepts 0 timeout
        """
        from src.mcp.server import _handle_wait_for_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ):
            result = await _handle_wait_for_user({
                "prompt": "Test prompt",
                "timeout_seconds": 0,
            })
        
        assert result["ok"] is True
        assert result["timeout_seconds"] == 0

    @pytest.mark.asyncio
    async def test_timeout_one_second(self) -> None:
        """
        TC-B-02: timeout_seconds=1 (minimal).
        
        // Given: timeout_seconds=1
        // When: Calling wait_for_user
        // Then: Accepts 1 second timeout
        """
        from src.mcp.server import _handle_wait_for_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ):
            result = await _handle_wait_for_user({
                "prompt": "Test prompt",
                "timeout_seconds": 1,
            })
        
        assert result["ok"] is True
        assert result["timeout_seconds"] == 1


class TestWaitForUserExecution:
    """Tests for wait_for_user execution."""

    @pytest.mark.asyncio
    async def test_wait_for_user_sends_notification(self) -> None:
        """
        TC-N-06: Wait for user sends notification.
        
        // Given: Valid prompt
        // When: Calling wait_for_user
        // Then: Sends notification with prompt
        """
        from src.mcp.server import _handle_wait_for_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await _handle_wait_for_user({
                "prompt": "Please confirm the action",
            })
        
        assert result["ok"] is True
        assert result["status"] == "notification_sent"
        assert result["prompt"] == "Please confirm the action"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_user_includes_timeout(self) -> None:
        """
        TC-N-07: Wait for user includes timeout.
        
        // Given: Prompt with custom timeout
        // When: Calling wait_for_user
        // Then: Response includes timeout value
        """
        from src.mcp.server import _handle_wait_for_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ):
            result = await _handle_wait_for_user({
                "prompt": "Test prompt",
                "timeout_seconds": 600,
            })
        
        assert result["ok"] is True
        assert result["timeout_seconds"] == 600

    @pytest.mark.asyncio
    async def test_wait_for_user_default_timeout(self) -> None:
        """
        TC-N-08: Wait for user with default timeout.
        
        // Given: Prompt without timeout
        // When: Calling wait_for_user
        // Then: Uses default timeout of 300 seconds
        """
        from src.mcp.server import _handle_wait_for_user
        
        with patch(
            "src.utils.notification.notify_user",
            new_callable=AsyncMock,
        ):
            result = await _handle_wait_for_user({
                "prompt": "Test prompt",
            })
        
        assert result["timeout_seconds"] == 300


class TestNotificationToolDefinitions:
    """Tests for notification tool definitions."""

    def test_notify_user_in_tools(self) -> None:
        """
        Test that notify_user is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for notify_user
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "notify_user"), None)
        
        assert tool is not None
        assert "event" in tool.inputSchema["properties"]
        assert "payload" in tool.inputSchema["properties"]
        assert set(tool.inputSchema["required"]) == {"event", "payload"}
        
        # Check event enum
        event_prop = tool.inputSchema["properties"]["event"]
        assert "enum" in event_prop
        assert "auth_required" in event_prop["enum"]
        assert "task_progress" in event_prop["enum"]
        assert "task_complete" in event_prop["enum"]
        assert "error" in event_prop["enum"]
        assert "info" in event_prop["enum"]

    def test_wait_for_user_in_tools(self) -> None:
        """
        Test that wait_for_user is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for wait_for_user
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "wait_for_user"), None)
        
        assert tool is not None
        assert "prompt" in tool.inputSchema["properties"]
        assert "timeout_seconds" in tool.inputSchema["properties"]
        assert "options" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["prompt"]


class TestOldToolsRemoved:
    """Tests that old/deprecated tools are removed."""

    def test_deprecated_tools_not_in_tools(self) -> None:
        """
        Test that deprecated tools are removed from TOOLS.
        
        // Given: TOOLS list after Phase M refactoring
        // When: Searching for deprecated tool names
        // Then: None found
        """
        from src.mcp.server import TOOLS
        
        deprecated_tools = [
            "search_serp",
            "fetch_url",
            "extract_content",
            "rank_candidates",
            "llm_extract",
            "nli_judge",
            "get_pending_authentications",
            "start_authentication_session",
            "complete_authentication",
            "skip_authentication",
            "schedule_job",
            "get_task_status",
            "get_report_materials",
            "get_evidence_graph",
            "get_research_context",
            "execute_subquery",
            "get_exploration_status",
            "execute_refutation",
            "finalize_exploration",
            "decompose_question",
            "compress_with_chain_of_density",
        ]
        
        tool_names = {t.name for t in TOOLS}
        
        for deprecated in deprecated_tools:
            assert deprecated not in tool_names, f"Deprecated tool '{deprecated}' should be removed"

    def test_new_tools_count(self) -> None:
        """
        Test that exactly 11 tools are defined per §3.2.1.
        
        // Given: TOOLS list after Phase M refactoring
        // When: Counting tools
        // Then: Exactly 11 tools
        """
        from src.mcp.server import TOOLS
        
        assert len(TOOLS) == 11, f"Expected 11 tools per §3.2.1, got {len(TOOLS)}"

    def test_all_new_tools_present(self) -> None:
        """
        Test that all 11 new tools are present per §3.2.1.
        
        // Given: TOOLS list
        // When: Checking for required tools
        // Then: All 11 tools present
        """
        from src.mcp.server import TOOLS
        
        required_tools = [
            "create_task",
            "get_status",
            "search",
            "stop_task",
            "get_materials",
            "calibrate",
            "calibrate_rollback",
            "get_auth_queue",
            "resolve_auth",
            "notify_user",
            "wait_for_user",
        ]
        
        tool_names = {t.name for t in TOOLS}
        
        for required in required_tools:
            assert required in tool_names, f"Required tool '{required}' not found"

