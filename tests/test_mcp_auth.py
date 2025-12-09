"""Tests for get_auth_queue and resolve_auth MCP tools.

Tests authentication queue management per §3.2.1 and §3.6.1.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-N-01 | group_by=none | Equivalence – normal | Flat list of items | No grouping |
| TC-N-02 | group_by=domain | Equivalence – normal | Items grouped by domain | Domain grouping |
| TC-N-03 | group_by=type | Equivalence – normal | Items grouped by auth_type | Type grouping |
| TC-N-04 | task_id filter | Equivalence – normal | get_pending called with task_id | Task filtering |
| TC-N-05 | priority_filter | Equivalence – normal | get_pending called with priority | Priority filtering |
| TC-N-06 | action=complete, target=item | Equivalence – normal | Single item completed | Single completion |
| TC-N-07 | action=skip, target=item | Equivalence – normal | Single item skipped | Single skip |
| TC-N-08 | action=complete, target=domain | Equivalence – normal | All domain items completed | Domain completion |
| TC-N-09 | action=skip, target=domain | Equivalence – normal | All domain items skipped | Domain skip |
| TC-A-01 | Missing action | Equivalence – error | InvalidParamsError | Required param |
| TC-A-02 | target=item, missing queue_id | Equivalence – error | InvalidParamsError | Conditional required |
| TC-A-03 | target=domain, missing domain | Equivalence – error | InvalidParamsError | Conditional required |
| TC-A-04 | target=invalid | Equivalence – error | InvalidParamsError | Invalid enum |
| TC-A-05 | action=invalid | Equivalence – error | InvalidParamsError | Invalid enum |
| TC-B-01 | Empty queue (0 items) | Boundary – empty | total_count=0, items=[] | Zero items |
| TC-B-02 | Single item in queue | Boundary – min | total_count=1 | Minimal case |
| TC-B-03 | group_by with 0 items | Boundary – empty groups | groups={} empty dict | Empty grouping |
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


class TestGetAuthQueueExecution:
    """Tests for get_auth_queue execution."""

    @pytest.fixture
    def mock_pending_items(self) -> list[dict[str, Any]]:
        """Create mock pending authentication items."""
        return [
            {
                "id": "q_001",
                "task_id": "task_abc",
                "url": "https://example.com/page1",
                "domain": "example.com",
                "auth_type": "captcha",
                "priority": "high",
            },
            {
                "id": "q_002",
                "task_id": "task_abc",
                "url": "https://test.org/page1",
                "domain": "test.org",
                "auth_type": "cloudflare",
                "priority": "medium",
            },
            {
                "id": "q_003",
                "task_id": "task_abc",
                "url": "https://example.com/page2",
                "domain": "example.com",
                "auth_type": "captcha",
                "priority": "low",
            },
        ]

    @pytest.mark.asyncio
    async def test_get_auth_queue_no_grouping(
        self, mock_pending_items: list[dict[str, Any]]
    ) -> None:
        """
        TC-N-01: Get auth queue without grouping.
        
        // Given: Pending authentication items
        // When: Calling get_auth_queue with group_by=none
        // Then: Returns flat list of items
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = mock_pending_items
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({
                "group_by": "none",
            })
        
        assert result["ok"] is True
        assert result["group_by"] == "none"
        assert result["total_count"] == 3
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_get_auth_queue_group_by_domain(
        self, mock_pending_items: list[dict[str, Any]]
    ) -> None:
        """
        TC-N-02: Get auth queue grouped by domain.
        
        // Given: Pending items from multiple domains
        // When: Calling get_auth_queue with group_by=domain
        // Then: Returns items grouped by domain
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = mock_pending_items
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({
                "group_by": "domain",
            })
        
        assert result["ok"] is True
        assert result["group_by"] == "domain"
        assert result["total_count"] == 3
        assert "groups" in result
        assert "example.com" in result["groups"]
        assert "test.org" in result["groups"]
        assert len(result["groups"]["example.com"]) == 2
        assert len(result["groups"]["test.org"]) == 1

    @pytest.mark.asyncio
    async def test_get_auth_queue_group_by_type(
        self, mock_pending_items: list[dict[str, Any]]
    ) -> None:
        """
        TC-N-03: Get auth queue grouped by type.
        
        // Given: Pending items with different auth types
        // When: Calling get_auth_queue with group_by=type
        // Then: Returns items grouped by auth_type
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = mock_pending_items
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({
                "group_by": "type",
            })
        
        assert result["ok"] is True
        assert result["group_by"] == "type"
        assert "groups" in result
        assert "captcha" in result["groups"]
        assert "cloudflare" in result["groups"]
        assert len(result["groups"]["captcha"]) == 2
        assert len(result["groups"]["cloudflare"]) == 1

    @pytest.mark.asyncio
    async def test_get_auth_queue_with_task_filter(
        self, mock_pending_items: list[dict[str, Any]]
    ) -> None:
        """
        TC-N-04: Get auth queue filtered by task_id.
        
        // Given: task_id filter
        // When: Calling get_auth_queue
        // Then: Queue.get_pending called with task_id
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = mock_pending_items
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            await _handle_get_auth_queue({
                "task_id": "task_abc",
            })
        
        mock_queue.get_pending.assert_called_once()
        call_kwargs = mock_queue.get_pending.call_args
        assert call_kwargs[1].get("task_id") == "task_abc"

    @pytest.mark.asyncio
    async def test_get_auth_queue_with_priority_filter(
        self, mock_pending_items: list[dict[str, Any]]
    ) -> None:
        """
        TC-N-05: Get auth queue filtered by priority.
        
        // Given: priority_filter=high
        // When: Calling get_auth_queue
        // Then: Queue.get_pending called with priority
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = [mock_pending_items[0]]  # Only high priority
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({
                "priority_filter": "high",
            })
        
        mock_queue.get_pending.assert_called_once()
        call_kwargs = mock_queue.get_pending.call_args
        assert call_kwargs[1].get("priority") == "high"
        assert result["total_count"] == 1


class TestGetAuthQueueBoundaryValues:
    """Tests for get_auth_queue boundary values."""

    @pytest.mark.asyncio
    async def test_empty_queue(self) -> None:
        """
        TC-B-01: Empty queue (0 items).
        
        // Given: No pending items in queue
        // When: Calling get_auth_queue
        // Then: Returns total_count=0 and empty items list
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = []
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({})
        
        assert result["ok"] is True
        assert result["total_count"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_single_item_queue(self) -> None:
        """
        TC-B-02: Single item in queue.
        
        // Given: Exactly 1 pending item
        // When: Calling get_auth_queue
        // Then: Returns total_count=1
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = [{
            "id": "q_001",
            "task_id": "task_abc",
            "url": "https://example.com",
            "domain": "example.com",
            "auth_type": "captcha",
            "priority": "high",
        }]
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({})
        
        assert result["ok"] is True
        assert result["total_count"] == 1
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_empty_group_by_domain(self) -> None:
        """
        TC-B-03: group_by with 0 items returns empty groups.
        
        // Given: Empty queue
        // When: Calling get_auth_queue with group_by=domain
        // Then: Returns groups as empty dict
        """
        from src.mcp.server import _handle_get_auth_queue
        
        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = []
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_get_auth_queue({
                "group_by": "domain",
            })
        
        assert result["ok"] is True
        assert result["total_count"] == 0
        assert result["groups"] == {}


class TestResolveAuthValidation:
    """Tests for resolve_auth parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_action_raises_error(self) -> None:
        """
        TC-A-01: Missing action parameter.
        
        // Given: No action provided
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_resolve_auth
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth({})
        
        assert exc_info.value.details.get("param_name") == "action"

    @pytest.mark.asyncio
    async def test_item_target_missing_queue_id_raises_error(self) -> None:
        """
        TC-A-02: Missing queue_id for item target.
        
        // Given: target=item but no queue_id
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_resolve_auth
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth({
                "target": "item",
                "action": "complete",
            })
        
        assert exc_info.value.details.get("param_name") == "queue_id"

    @pytest.mark.asyncio
    async def test_domain_target_missing_domain_raises_error(self) -> None:
        """
        TC-A-03: Missing domain for domain target.
        
        // Given: target=domain but no domain
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_resolve_auth
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth({
                "target": "domain",
                "action": "complete",
            })
        
        assert exc_info.value.details.get("param_name") == "domain"

    @pytest.mark.asyncio
    async def test_invalid_target_raises_error(self) -> None:
        """
        TC-A-04: Invalid target value.
        
        // Given: target=invalid
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_resolve_auth
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth({
                "target": "invalid",
                "action": "complete",
            })
        
        assert "target" in str(exc_info.value.details.get("param_name"))

    @pytest.mark.asyncio
    async def test_invalid_action_raises_error(self) -> None:
        """
        TC-A-05: Invalid action value.
        
        // Given: action=invalid_action
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.server import _handle_resolve_auth
        from src.mcp.errors import InvalidParamsError
        
        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth({
                "target": "item",
                "queue_id": "q_001",
                "action": "invalid_action",
            })
        
        assert "action" in str(exc_info.value.details.get("param_name"))


class TestResolveAuthExecution:
    """Tests for resolve_auth execution."""

    @pytest.mark.asyncio
    async def test_complete_single_item(self) -> None:
        """
        TC-N-06: Complete single auth item.
        
        // Given: Valid queue_id
        // When: Calling resolve_auth with action=complete, target=item
        // Then: Completes the item
        """
        from src.mcp.server import _handle_resolve_auth
        
        mock_queue = AsyncMock()
        mock_queue.complete.return_value = {
            "ok": True,
            "queue_id": "q_001",
            "status": "completed",
        }
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth({
                "target": "item",
                "queue_id": "q_001",
                "action": "complete",
                "success": True,
            })
        
        assert result["ok"] is True
        assert result["target"] == "item"
        assert result["queue_id"] == "q_001"
        assert result["action"] == "complete"
        mock_queue.complete.assert_called_once_with("q_001", success=True)

    @pytest.mark.asyncio
    async def test_skip_single_item(self) -> None:
        """
        TC-N-07: Skip single auth item.
        
        // Given: Valid queue_id
        // When: Calling resolve_auth with action=skip, target=item
        // Then: Skips the item
        """
        from src.mcp.server import _handle_resolve_auth
        
        mock_queue = AsyncMock()
        mock_queue.skip.return_value = {"ok": True, "skipped": 1}
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth({
                "target": "item",
                "queue_id": "q_001",
                "action": "skip",
            })
        
        assert result["ok"] is True
        assert result["action"] == "skip"
        mock_queue.skip.assert_called_once_with(queue_ids=["q_001"])

    @pytest.mark.asyncio
    async def test_complete_domain(self) -> None:
        """
        TC-N-08: Complete all auth items for a domain.
        
        // Given: Valid domain
        // When: Calling resolve_auth with action=complete, target=domain
        // Then: Completes all items for that domain
        """
        from src.mcp.server import _handle_resolve_auth
        
        mock_queue = AsyncMock()
        mock_queue.complete_domain.return_value = {
            "ok": True,
            "domain": "example.com",
            "resolved_count": 3,
            "affected_tasks": ["task_abc"],
        }
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth({
                "target": "domain",
                "domain": "example.com",
                "action": "complete",
                "success": True,
            })
        
        assert result["ok"] is True
        assert result["target"] == "domain"
        assert result["domain"] == "example.com"
        assert result["resolved_count"] == 3
        mock_queue.complete_domain.assert_called_once_with(
            "example.com", success=True
        )

    @pytest.mark.asyncio
    async def test_skip_domain(self) -> None:
        """
        TC-N-09: Skip all auth items for a domain.
        
        // Given: Valid domain
        // When: Calling resolve_auth with action=skip, target=domain
        // Then: Skips all items for that domain
        """
        from src.mcp.server import _handle_resolve_auth
        
        mock_queue = AsyncMock()
        mock_queue.skip.return_value = {
            "ok": True,
            "skipped": 2,
            "affected_tasks": ["task_abc"],
        }
        
        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth({
                "target": "domain",
                "domain": "example.com",
                "action": "skip",
            })
        
        assert result["ok"] is True
        assert result["target"] == "domain"
        assert result["resolved_count"] == 2
        mock_queue.skip.assert_called_once_with(domain="example.com")


class TestAuthToolDefinitions:
    """Tests for auth tool definitions."""

    def test_get_auth_queue_in_tools(self) -> None:
        """
        Test that get_auth_queue is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for get_auth_queue
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "get_auth_queue"), None)
        
        assert tool is not None
        assert "task_id" in tool.inputSchema["properties"]
        assert "group_by" in tool.inputSchema["properties"]
        assert "priority_filter" in tool.inputSchema["properties"]

    def test_resolve_auth_in_tools(self) -> None:
        """
        Test that resolve_auth is defined in TOOLS.
        
        // Given: TOOLS list
        // When: Searching for resolve_auth
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS
        
        tool = next((t for t in TOOLS if t.name == "resolve_auth"), None)
        
        assert tool is not None
        assert "target" in tool.inputSchema["properties"]
        assert "queue_id" in tool.inputSchema["properties"]
        assert "domain" in tool.inputSchema["properties"]
        assert "action" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["action"]

