"""Tests for get_auth_queue and resolve_auth MCP tools.

Tests authentication queue management per ADR-0003 and ADR-0007.

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
| TC-N-10 | action=complete, target=task | Equivalence – normal | All task items completed | Task completion |
| TC-N-11 | action=skip, target=task | Equivalence – normal | All task items skipped | Task skip |
| TC-A-01 | Missing action | Equivalence – error | InvalidParamsError | Required param |
| TC-A-02 | target=item, missing queue_id | Equivalence – error | InvalidParamsError | Conditional required |
| TC-A-03 | target=domain, missing domain | Equivalence – error | InvalidParamsError | Conditional required |
| TC-A-04 | target=task, missing task_id | Equivalence – error | InvalidParamsError | Conditional required |
| TC-A-05 | target=invalid | Equivalence – error | InvalidParamsError | Invalid enum |
| TC-A-06 | action=invalid | Equivalence – error | InvalidParamsError | Invalid enum |
| TC-B-01 | Empty queue (0 items) | Boundary – empty | total_count=0, items=[] | Zero items |
| TC-B-02 | Single item in queue | Boundary – min | total_count=1 | Minimal case |
| TC-B-03 | group_by with 0 items | Boundary – empty groups | groups={} empty dict | Empty grouping |
| TC-B-04 | target=task with 0 items | Boundary – empty | ok=True, resolved_count=0 | Empty task queue |
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
            result = await _handle_get_auth_queue(
                {
                    "group_by": "none",
                }
            )

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
            result = await _handle_get_auth_queue(
                {
                    "group_by": "domain",
                }
            )

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
            result = await _handle_get_auth_queue(
                {
                    "group_by": "type",
                }
            )

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
            await _handle_get_auth_queue(
                {
                    "task_id": "task_abc",
                }
            )

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
            result = await _handle_get_auth_queue(
                {
                    "priority_filter": "high",
                }
            )

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
        mock_queue.get_pending.return_value = [
            {
                "id": "q_001",
                "task_id": "task_abc",
                "url": "https://example.com",
                "domain": "example.com",
                "auth_type": "captcha",
                "priority": "high",
            }
        ]

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
            result = await _handle_get_auth_queue(
                {
                    "group_by": "domain",
                }
            )

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
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

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
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth(
                {
                    "target": "item",
                    "action": "complete",
                }
            )

        assert exc_info.value.details.get("param_name") == "queue_id"

    @pytest.mark.asyncio
    async def test_domain_target_missing_domain_raises_error(self) -> None:
        """
        TC-A-03: Missing domain for domain target.

        // Given: target=domain but no domain
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth(
                {
                    "target": "domain",
                    "action": "complete",
                }
            )

        assert exc_info.value.details.get("param_name") == "domain"

    @pytest.mark.asyncio
    async def test_invalid_target_raises_error(self) -> None:
        """
        TC-A-04: Invalid target value.

        // Given: target=invalid
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth(
                {
                    "target": "invalid",
                    "action": "complete",
                }
            )

        assert "target" in str(exc_info.value.details.get("param_name"))

    @pytest.mark.asyncio
    async def test_invalid_action_raises_error(self) -> None:
        """
        TC-A-05: Invalid action value.

        // Given: action=invalid_action
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth(
                {
                    "target": "item",
                    "queue_id": "q_001",
                    "action": "invalid_action",
                }
            )

        assert "action" in str(exc_info.value.details.get("param_name"))

    @pytest.mark.asyncio
    async def test_task_target_missing_task_id_raises_error(self) -> None:
        """
        TC-A-04: Missing task_id for task target.

        // Given: target=task but no task_id
        // When: Calling resolve_auth
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.server import _handle_resolve_auth

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_resolve_auth(
                {
                    "target": "task",
                    "action": "complete",
                }
            )

        assert exc_info.value.details.get("param_name") == "task_id"


class TestResolveAuthExecution:
    """Tests for resolve_auth execution."""

    @pytest.mark.asyncio
    async def test_complete_single_item(self) -> None:
        """
        TC-N-06: Complete single auth item.

        // Given: Valid queue_id
        // When: Calling resolve_auth with action=complete, target=item
        // Then: Completes the item with session_data capture attempt
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.get_item.return_value = {
            "id": "q_001",
            "domain": "example.com",
            "url": "https://example.com/page",
        }
        mock_queue.complete.return_value = {
            "ok": True,
            "queue_id": "q_001",
            "status": "completed",
        }

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_capture,
        ):
            result = await _handle_resolve_auth(
                {
                    "target": "item",
                    "queue_id": "q_001",
                    "action": "complete",
                    "success": True,
                }
            )

        assert result["ok"] is True
        assert result["target"] == "item"
        assert result["queue_id"] == "q_001"
        assert result["action"] == "complete"
        # Verify get_item was called to get domain for cookie capture
        mock_queue.get_item.assert_called_once_with("q_001")
        # Verify cookie capture was attempted
        mock_capture.assert_called_once_with("example.com")
        # Verify complete was called with session_data
        mock_queue.complete.assert_called_once_with("q_001", success=True, session_data=None)

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
            result = await _handle_resolve_auth(
                {
                    "target": "item",
                    "queue_id": "q_001",
                    "action": "skip",
                }
            )

        assert result["ok"] is True
        assert result["action"] == "skip"
        mock_queue.skip.assert_called_once_with(queue_ids=["q_001"])

    @pytest.mark.asyncio
    async def test_complete_domain(self) -> None:
        """
        TC-N-08: Complete all auth items for a domain.

        // Given: Valid domain
        // When: Calling resolve_auth with action=complete, target=domain
        // Then: Completes all items for that domain with cookie capture
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.complete_domain.return_value = {
            "ok": True,
            "domain": "example.com",
            "resolved_count": 3,
            "affected_tasks": ["task_abc"],
        }

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await _handle_resolve_auth(
                {
                    "target": "domain",
                    "domain": "example.com",
                    "action": "complete",
                    "success": True,
                }
            )

        assert result["ok"] is True
        assert result["target"] == "domain"
        assert result["domain"] == "example.com"
        assert result["resolved_count"] == 3
        mock_queue.complete_domain.assert_called_once_with(
            "example.com", success=True, session_data=None
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
            result = await _handle_resolve_auth(
                {
                    "target": "domain",
                    "domain": "example.com",
                    "action": "skip",
                }
            )

        assert result["ok"] is True
        assert result["target"] == "domain"
        assert result["resolved_count"] == 2
        mock_queue.skip.assert_called_once_with(domain="example.com")

    @pytest.mark.asyncio
    async def test_complete_task(self) -> None:
        """
        TC-N-10: Complete all auth items for a task.

        // Given: Valid task_id with pending items
        // When: Calling resolve_auth with action=complete, target=task
        // Then: Completes all items for that task
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = [
            {
                "id": "q_001",
                "domain": "example.com",
                "url": "https://example.com/page1",
            },
            {
                "id": "q_002",
                "domain": "test.org",
                "url": "https://test.org/page1",
            },
            {
                "id": "q_003",
                "domain": "example.com",
                "url": "https://example.com/page2",
            },
        ]
        mock_queue.complete.return_value = {
            "ok": True,
            "queue_id": "q_001",
            "status": "completed",
        }

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value={"cookies": []},
            ) as mock_capture,
            patch(
                "src.mcp.server._requeue_awaiting_auth_jobs",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_requeue,
            patch(
                "src.mcp.server._reset_circuit_breaker_for_engine",
                new_callable=AsyncMock,
            ) as mock_reset,
        ):
            result = await _handle_resolve_auth(
                {
                    "target": "task",
                    "task_id": "task_abc",
                    "action": "complete",
                    "success": True,
                }
            )

        assert result["ok"] is True
        assert result["target"] == "task"
        assert result["task_id"] == "task_abc"
        assert result["action"] == "complete"
        assert result["resolved_count"] == 3
        assert result["requeued_count"] == 4  # 2 per domain (example.com + test.org)
        # Verify get_pending was called with task_id
        mock_queue.get_pending.assert_called_once_with(task_id="task_abc")
        # Verify complete was called for each item
        assert mock_queue.complete.call_count == 3
        # Verify cookie capture was called once per unique domain
        assert mock_capture.call_count == 2  # example.com and test.org
        # Verify requeue was called for each domain
        assert mock_requeue.call_count == 2
        assert mock_reset.call_count == 2

    @pytest.mark.asyncio
    async def test_skip_task(self) -> None:
        """
        TC-N-11: Skip all auth items for a task.

        // Given: Valid task_id
        // When: Calling resolve_auth with action=skip, target=task
        // Then: Skips all items for that task
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.skip.return_value = {
            "ok": True,
            "skipped": 3,
        }

        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth(
                {
                    "target": "task",
                    "task_id": "task_abc",
                    "action": "skip",
                }
            )

        assert result["ok"] is True
        assert result["target"] == "task"
        assert result["task_id"] == "task_abc"
        assert result["action"] == "skip"
        assert result["resolved_count"] == 3
        assert result["requeued_count"] == 0
        mock_queue.skip.assert_called_once_with(task_id="task_abc")

    @pytest.mark.asyncio
    async def test_complete_task_empty_queue(self) -> None:
        """
        TC-B-04: Complete task with empty queue.

        // Given: task_id with no pending items
        // When: Calling resolve_auth with action=complete, target=task
        // Then: Returns ok=True with resolved_count=0
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.get_pending.return_value = []

        with patch(
            "src.utils.notification.get_intervention_queue",
            return_value=mock_queue,
        ):
            result = await _handle_resolve_auth(
                {
                    "target": "task",
                    "task_id": "task_abc",
                    "action": "complete",
                    "success": True,
                }
            )

        assert result["ok"] is True
        assert result["target"] == "task"
        assert result["task_id"] == "task_abc"
        assert result["resolved_count"] == 0
        assert result["requeued_count"] == 0
        mock_queue.get_pending.assert_called_once_with(task_id="task_abc")
        mock_queue.complete.assert_not_called()


class TestCaptureAuthSessionCookies:
    """Tests for _capture_auth_session_cookies function (Auth cookie capture compliance).

    Per ADR-0007: Capture session data after authentication for reuse.
    """

    @pytest.mark.asyncio
    async def test_capture_returns_cookies_when_browser_connected(self) -> None:
        """
        TC-CC-N-01: Cookie capture when browser connected with cookies.

        // Given: Browser connected with cookies for domain
        // When: Calling _capture_auth_session_cookies
        // Then: Returns session_data with cookies
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock context with cookies
        mock_context = AsyncMock()
        mock_context.cookies.return_value = [
            {"name": "session", "value": "abc123", "domain": "example.com"},
            {"name": "auth", "value": "xyz789", "domain": ".example.com"},
            {"name": "other", "value": "other", "domain": "other.com"},  # Different domain
        ]

        # Mock browser with contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_context]

        # Mock playwright chain: async_playwright() -> start() -> chromium -> connect_over_cdp()
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                result = await _capture_auth_session_cookies("example.com")

        assert result is not None, "Should return session data"
        assert "cookies" in result, "Should have cookies field"
        assert len(result["cookies"]) == 2, "Should have 2 matching cookies"
        assert "captured_at" in result, "Should have captured_at timestamp"
        assert result["domain"] == "example.com", "Should have domain"

    @pytest.mark.asyncio
    async def test_capture_returns_none_when_browser_not_connected(self) -> None:
        """
        TC-CC-B-01: Cookie capture when browser not connected.

        // Given: Browser not connected (no contexts)
        // When: Calling _capture_auth_session_cookies
        // Then: Returns None
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock browser with no contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = []

        # Mock playwright chain
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                result = await _capture_auth_session_cookies("example.com")

        assert result is None, "Should return None when browser not connected"

    @pytest.mark.asyncio
    async def test_capture_returns_none_when_no_matching_cookies(self) -> None:
        """
        TC-CC-B-02: Cookie capture when no matching cookies.

        // Given: Browser connected but no cookies for domain
        // When: Calling _capture_auth_session_cookies
        // Then: Returns None
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock context with cookies for different domain
        mock_context = AsyncMock()
        mock_context.cookies.return_value = [
            {"name": "session", "value": "abc123", "domain": "other.com"},
        ]

        # Mock browser with contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_context]

        # Mock playwright chain
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                result = await _capture_auth_session_cookies("example.com")

        assert result is None, "Should return None when no matching cookies"

    @pytest.mark.asyncio
    async def test_capture_excludes_subdomain_cookies_for_parent_domain(self) -> None:
        """
        TC-CC-B-03: Cookie capture excludes subdomain cookies for parent domain.

        Per HTTP cookie spec: cookies set for subdomain should not be sent to parent domain.
        Only parent domain cookies can be sent to subdomains.

        // Given: Browser connected with cookies for subdomain (sub.example.com)
        // When: Calling _capture_auth_session_cookies with parent domain (example.com)
        // Then: Subdomain cookies are NOT included in result
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock context with cookies for subdomain
        mock_context = AsyncMock()
        mock_context.cookies.return_value = [
            {"name": "subdomain_session", "value": "sub123", "domain": "sub.example.com"},
            {"name": "parent_session", "value": "parent123", "domain": "example.com"},
        ]

        # Mock browser with contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_context]

        # Mock playwright chain
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                # Capture for parent domain
                result = await _capture_auth_session_cookies("example.com")

        assert result is not None, "Should return session data"
        assert "cookies" in result, "Should have cookies field"
        # Only parent domain cookie should be included, subdomain cookie should be excluded
        assert len(result["cookies"]) == 1, "Should have 1 matching cookie (parent domain only)"
        assert (
            result["cookies"][0]["name"] == "parent_session"
        ), "Should include parent domain cookie"
        assert (
            result["cookies"][0]["domain"] == "example.com"
        ), "Cookie domain should be example.com"

    @pytest.mark.asyncio
    async def test_capture_includes_parent_cookies_for_subdomain(self) -> None:
        """
        TC-CC-N-02: Cookie capture includes parent domain cookies for subdomain.

        Per HTTP cookie spec: cookies set for parent domain can be sent to subdomains.

        // Given: Browser connected with cookies for parent domain (example.com)
        // When: Calling _capture_auth_session_cookies with subdomain (sub.example.com)
        // Then: Parent domain cookies ARE included in result
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock context with cookies for parent domain
        mock_context = AsyncMock()
        mock_context.cookies.return_value = [
            {"name": "parent_session", "value": "parent123", "domain": "example.com"},
            {"name": "parent_auth", "value": "parent456", "domain": ".example.com"},
        ]

        # Mock browser with contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_context]

        # Mock playwright chain
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                # Capture for subdomain
                result = await _capture_auth_session_cookies("sub.example.com")

        assert result is not None, "Should return session data"
        assert "cookies" in result, "Should have cookies field"
        # Parent domain cookies should be included for subdomain
        assert len(result["cookies"]) == 2, "Should have 2 matching cookies (parent domain cookies)"
        cookie_names = {c["name"] for c in result["cookies"]}
        assert "parent_session" in cookie_names, "Should include parent_session cookie"
        assert "parent_auth" in cookie_names, "Should include parent_auth cookie"

    @pytest.mark.asyncio
    async def test_capture_handles_exception_gracefully(self) -> None:
        """
        TC-CC-A-01: Cookie capture handles exceptions.

        // Given: Exception during cookie capture
        // When: Calling _capture_auth_session_cookies
        // Then: Returns None (no exception raised)
        """
        from src.mcp.server import _capture_auth_session_cookies

        # Mock context that raises exception
        mock_context = AsyncMock()
        mock_context.cookies.side_effect = Exception("Browser disconnected")

        # Mock browser with contexts
        mock_browser = AsyncMock()
        mock_browser.contexts = [mock_context]

        # Mock playwright chain
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.stop = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.start = AsyncMock(return_value=mock_playwright_instance)

        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            with patch("src.utils.config.get_settings") as mock_settings:
                mock_settings.return_value.browser.chrome_host = "localhost"
                mock_settings.return_value.browser.chrome_port = 9222

                result = await _capture_auth_session_cookies("example.com")

        assert result is None, "Should return None on exception"


class TestResolveAuthCookieCapture:
    """Tests for resolve_auth cookie capture integration (Auth cookie capture compliance)."""

    @pytest.mark.asyncio
    async def test_complete_item_captures_cookies(self) -> None:
        """
        TC-RA-N-01: resolve_auth complete captures cookies.

        // Given: Browser connected with cookies
        // When: Calling resolve_auth action=complete with success=True
        // Then: Cookies captured and passed to complete()
        """
        from src.mcp.server import _handle_resolve_auth

        session_data = {
            "cookies": [{"name": "auth", "value": "test"}],
            "captured_at": "2025-12-11T00:00:00Z",
            "domain": "example.com",
        }

        mock_queue = AsyncMock()
        mock_queue.get_item.return_value = {
            "id": "q_001",
            "domain": "example.com",
        }
        mock_queue.complete.return_value = {"ok": True, "status": "completed"}

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value=session_data,
            ),
        ):
            await _handle_resolve_auth(
                {
                    "target": "item",
                    "queue_id": "q_001",
                    "action": "complete",
                    "success": True,
                }
            )

        # Verify complete was called with session_data
        mock_queue.complete.assert_called_once_with(
            "q_001", success=True, session_data=session_data
        )

    @pytest.mark.asyncio
    async def test_complete_failure_skips_cookie_capture(self) -> None:
        """
        TC-RA-N-02: resolve_auth with success=False skips cookie capture.

        // Given: Auth failed
        // When: Calling resolve_auth action=complete with success=False
        // Then: Cookie capture not attempted
        """
        from src.mcp.server import _handle_resolve_auth

        mock_queue = AsyncMock()
        mock_queue.get_item.return_value = {
            "id": "q_001",
            "domain": "example.com",
        }
        mock_queue.complete.return_value = {"ok": True, "status": "skipped"}

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
            ) as mock_capture,
        ):
            await _handle_resolve_auth(
                {
                    "target": "item",
                    "queue_id": "q_001",
                    "action": "complete",
                    "success": False,
                }
            )

        # Verify cookie capture was NOT called (success=False)
        mock_capture.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_domain_captures_cookies(self) -> None:
        """
        TC-RA-N-03: resolve_auth domain complete captures cookies.

        // Given: Domain auth complete
        // When: Calling resolve_auth target=domain action=complete
        // Then: Cookies captured and passed to complete_domain()
        """
        from src.mcp.server import _handle_resolve_auth

        session_data = {
            "cookies": [{"name": "cf_clearance", "value": "xyz"}],
            "captured_at": "2025-12-11T00:00:00Z",
            "domain": "example.com",
        }

        mock_queue = AsyncMock()
        mock_queue.complete_domain.return_value = {
            "ok": True,
            "resolved_count": 3,
        }

        with (
            patch(
                "src.utils.notification.get_intervention_queue",
                return_value=mock_queue,
            ),
            patch(
                "src.mcp.server._capture_auth_session_cookies",
                new_callable=AsyncMock,
                return_value=session_data,
            ),
        ):
            await _handle_resolve_auth(
                {
                    "target": "domain",
                    "domain": "example.com",
                    "action": "complete",
                    "success": True,
                }
            )

        # Verify complete_domain was called with session_data
        mock_queue.complete_domain.assert_called_once_with(
            "example.com", success=True, session_data=session_data
        )


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
