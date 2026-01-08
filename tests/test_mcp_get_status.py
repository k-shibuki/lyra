"""Tests for get_status MCP tool.

Tests the unified task and exploration status endpoint per ADR-0003.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetStatusValidation:
    """Tests for get_status parameter validation."""

    @pytest.mark.asyncio
    async def test_missing_task_id_raises_error(self) -> None:
        """
        TC-A-01: Missing task_id parameter.

        // Given: No task_id provided
        // When: Calling get_status with empty args
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_get_status({})

        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_empty_task_id_raises_error(self) -> None:
        """
        TC-A-02: Empty task_id parameter.

        // Given: Empty string task_id
        // When: Calling get_status
        // Then: Raises InvalidParamsError
        """
        from src.mcp.errors import InvalidParamsError
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        with pytest.raises(InvalidParamsError) as exc_info:
            await _handle_get_status({"task_id": ""})

        assert exc_info.value.details.get("param_name") == "task_id"

    @pytest.mark.asyncio
    async def test_nonexistent_task_raises_error(self) -> None:
        """
        TC-A-03: Non-existent task_id.

        // Given: task_id not in database
        // When: Calling get_status
        // Then: Raises TaskNotFoundError
        """
        from src.mcp.errors import TaskNotFoundError
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with pytest.raises(TaskNotFoundError) as exc_info:
                await _handle_get_status({"task_id": "nonexistent_task"})

        assert exc_info.value.details.get("task_id") == "nonexistent_task"


class TestGetStatusWithExplorationState:
    """Tests for get_status with active exploration.

    Note: Tests use detail="summary" are in TestGetStatusSummaryMode.
    """

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_abc123",
            "hypothesis": "Test research question",
            "status": "exploring",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:30:00Z",
        }

    @pytest.fixture
    def mock_exploration_status(self) -> dict[str, Any]:
        """Create mock exploration status."""
        return {
            "ok": True,
            "task_id": "task_abc123",
            "task_status": "exploring",
            "searches": [
                {
                    "id": "sq_001",
                    "text": "Search query 1",  # Changed from "query" to "text" per state.py
                    "status": "satisfied",
                    "pages_fetched": 15,
                    "useful_fragments": 8,
                    "harvest_rate": 0.53,
                    "satisfaction_score": 0.85,
                    "has_primary_source": True,
                },
                {
                    "id": "sq_002",
                    "text": "Search query 2",  # Changed from "query" to "text" per state.py
                    "status": "partial",
                    "pages_fetched": 10,
                    "useful_fragments": 3,
                    "harvest_rate": 0.30,
                    "satisfaction_score": 0.45,
                    "has_primary_source": False,
                },
            ],
            "metrics": {
                "satisfied_count": 1,
                "partial_count": 1,
                "pending_count": 0,
                "exhausted_count": 0,
                "total_pages": 25,
                "total_fragments": 11,
                "total_claims": 5,
                "elapsed_seconds": 300,
            },
            "budget": {
                "budget_pages_used": 25,
                "budget_pages_limit": 120,
                "time_used_seconds": 300,
                "time_limit_seconds": 3600,
            },
            "authentication_queue": None,
            "warnings": [],
        }

    @pytest.mark.asyncio
    async def test_returns_unified_status(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-01: Valid task_id with exploration state.

        // Given: Task exists with active exploration
        // When: Calling get_status
        // Then: Returns unified status with searches, metrics, budget
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        # Mock queue/pending_auth cursors
        cursor_queue = AsyncMock()
        cursor_queue.fetchall.return_value = []
        cursor_pending_count = AsyncMock()
        cursor_pending_count.fetchone.return_value = (0,)
        cursor_pending_rows = AsyncMock()
        cursor_pending_rows.fetchall.return_value = []

        mock_db.execute.side_effect = [
            cursor_queue,
            cursor_pending_count,
            cursor_pending_rows,
        ]

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        # Mock get_metrics_from_db to return expected values
        mock_metrics = {
            "total_searches": 2,
            "satisfied_count": 0,
            "total_pages": 25,
            "total_fragments": 11,
            "total_claims": 5,
            "elapsed_seconds": 300,
        }

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                with patch(
                    "src.mcp.tools.task.get_metrics_from_db",
                    new=AsyncMock(return_value=mock_metrics),
                ):
                    result = await _handle_get_status({"task_id": "task_abc123", "detail": "full"})

        assert result["ok"] is True
        assert result["task_id"] == "task_abc123"
        assert result["status"] == "exploring"
        assert result["hypothesis"] == "Test research question"
        assert len(result["searches_detail"]) == 2
        assert result["metrics"]["total_claims"] == 5
        assert result["progress"]["searches"]["satisfied"] == 1
        assert result["budget"]["pages_used"] == 25

    @pytest.mark.asyncio
    async def test_db_only_overrides_total_counts(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-DB-01: db_only overrides total_* counts from DB even when ExplorationState exists.

        // Given: ExplorationState reports total_claims=0 (stale), but DB has claims/pages/fragments
        // When: Calling get_status
        // Then: total_* metrics reflect DB counts (db_only)
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        # Given: ExplorationState has stale totals
        mock_exploration_status["metrics"]["total_pages"] = 0
        mock_exploration_status["metrics"]["total_fragments"] = 0
        mock_exploration_status["metrics"]["total_claims"] = 0

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        # Mock queue/pending_auth cursors
        cursor_queue = AsyncMock()
        cursor_queue.fetchall.return_value = []
        cursor_pending_count = AsyncMock()
        cursor_pending_count.fetchone.return_value = (0,)
        cursor_pending_rows = AsyncMock()
        cursor_pending_rows.fetchall.return_value = []

        mock_db.execute.side_effect = [
            cursor_queue,
            cursor_pending_count,
            cursor_pending_rows,
        ]

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        # Mock get_metrics_from_db to return DB values that differ from ExplorationState
        mock_metrics = {
            "total_searches": 2,
            "satisfied_count": 0,
            "total_pages": 3,
            "total_fragments": 5,
            "total_claims": 7,
            "elapsed_seconds": 300,
        }

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                with patch(
                    "src.mcp.tools.task.get_metrics_from_db",
                    new=AsyncMock(return_value=mock_metrics),
                ):
                    result = await _handle_get_status({"task_id": "task_abc123", "detail": "full"})

        # Then: totals come from DB counts (db_only)
        assert result["metrics"]["total_pages"] == 3
        assert result["metrics"]["total_fragments"] == 5
        assert result["metrics"]["total_claims"] == 7

    @pytest.mark.asyncio
    async def test_search_field_mapping(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-05: Search field mapping.

        // Given: Exploration status with subqueries
        // When: Calling get_status
        // Then: Fields correctly mapped to ADR-0003 schema
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123", "detail": "full"})

        # Verify search structure per ADR-0003 (in searches_detail for full mode)
        search = result["searches_detail"][0]
        assert "id" in search
        assert "query" in search
        assert "status" in search
        assert "pages_fetched" in search
        assert "useful_fragments" in search
        assert "harvest_rate" in search
        assert "satisfaction_score" in search
        assert "has_primary_source" in search

        # Verify values
        assert search["id"] == "sq_001"
        assert search["query"] == "Search query 1"
        assert search["status"] == "satisfied"
        assert search["pages_fetched"] == 15
        assert search["harvest_rate"] == 0.53

    @pytest.mark.asyncio
    async def test_includes_auth_queue(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-03: Task with auth_queue pending.

        // Given: Exploration has pending authentications
        // When: Calling get_status
        // Then: Includes auth_queue in response
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        # Add auth queue to exploration status
        mock_exploration_status["authentication_queue"] = {
            "pending_count": 3,
            "high_priority_count": 1,
            "domains": ["example.com", "test.org"],
            "oldest_queued_at": "2024-01-15T10:20:00Z",
        }

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                # Note: auth_queue is not in the new response structure
                # pending_auth_count is available in both summary and full modes
                result = await _handle_get_status({"task_id": "task_abc123", "detail": "full"})

        # auth_queue was removed in the new structure, but pending_auth_detail is available
        assert result["pending_auth_count"] == 0  # From mock pending_auth

    @pytest.mark.asyncio
    async def test_includes_warnings(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-04: Task with warnings.

        // Given: Exploration has warnings
        // When: Calling get_status
        // Then: Includes warnings array
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        # Add warnings to exploration status
        mock_exploration_status["warnings"] = [
            "Budget limit approaching: 80% pages used",
            "2件のサブクエリが収穫逓減で停止",
        ]

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123"})

        # warnings is available in both summary and full modes
        assert len(result["warnings"]) == 2
        assert "Budget limit" in result["warnings"][0]


class TestGetStatusWithoutExplorationState:
    """Tests for get_status without exploration state."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_xyz789",
            "hypothesis": "Another research question",
            "status": "pending",
            "created_at": "2024-01-15T11:00:00Z",
            "updated_at": "2024-01-15T11:00:00Z",
        }

    @pytest.mark.asyncio
    async def test_returns_minimal_status(self, mock_task: dict[str, Any]) -> None:
        """
        TC-N-02: Valid task_id without exploration state.

        // Given: Task exists but no exploration started
        // When: Calling get_status
        // Then: Returns minimal status with empty searches
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        # Mock cursor for _get_metrics_from_db and other helper functions
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (0,)  # Zero count for each query
        mock_cursor.fetchall.return_value = []  # Empty list for fetchall queries
        mock_db.execute.return_value = mock_cursor

        # Simulate no exploration state
        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                result = await _handle_get_status({"task_id": "task_xyz789"})

        assert result["ok"] is True
        assert result["task_id"] == "task_xyz789"
        assert result["status"] == "pending"  # DB status is returned when no exploration state
        assert result["hypothesis"] == "Another research question"
        # Summary mode: searches is in progress.searches
        assert result["progress"]["searches"]["total"] == 0
        assert result["metrics"]["total_pages"] == 0
        # Budget is now always populated with defaults
        assert result["budget"]["pages_used"] == 0
        assert result["budget"]["pages_limit"] == 500
        assert result["budget"]["remaining_percent"] == 100
        assert result["warnings"] == []


class TestGetStatusStatusMapping:
    """Tests for status field mapping."""

    @pytest.fixture
    def mock_task_base(self) -> dict[str, Any]:
        """Create base mock task."""
        return {
            "id": "task_test",
            "hypothesis": "Test query",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:00:00Z",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_status,expected_status",
        [
            ("exploring", "exploring"),
            ("paused", "paused"),
            ("failed", "failed"),
            ("pending", "exploring"),
        ],
    )
    async def test_status_mapping(
        self,
        mock_task_base: dict[str, Any],
        task_status: str,
        expected_status: str,
    ) -> None:
        """
        Test status field mapping from exploration state.

        // Given: Exploration with specific task_status
        // When: Calling get_status
        // Then: Status is correctly mapped per ADR-0003
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_task = {**mock_task_base, "status": task_status}
        mock_exploration = {
            "ok": True,
            "task_id": "task_test",
            "task_status": task_status,
            "subqueries": [],
            "metrics": {},
            "budget": {},
            "authentication_queue": None,
            "warnings": [],
        }

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration)

        # Mock _get_evidence_summary to avoid DB calls for count queries
        mock_evidence_summary = {
            "total_claims": 10,
            "total_fragments": 20,
            "total_pages": 5,
            "supporting_edges": 15,
            "refuting_edges": 3,
            "neutral_edges": 2,
            "top_domains": ["example.com"],
        }

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.tools.task.get_exploration_state", return_value=mock_state):
                with patch(
                    "src.mcp.tools.task._get_evidence_summary",
                    new=AsyncMock(return_value=mock_evidence_summary),
                ):
                    result = await _handle_get_status({"task_id": "task_test"})

        assert result["status"] == expected_status
        # When completed, evidence_summary should be present
        if expected_status == "completed":
            assert "evidence_summary" in result


class TestGetStatusToolDefinition:
    """Tests for get_status tool definition."""

    def test_get_status_in_tools(self) -> None:
        """
        Test that get_status is defined in TOOLS.

        // Given: TOOLS list
        // When: Searching for get_status
        // Then: Found with correct schema
        """
        from src.mcp.server import TOOLS

        tool = next((t for t in TOOLS if t.name == "get_status"), None)

        assert tool is not None
        assert "task_id" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["task_id"]


class TestGetStatusBlockedDomains:
    """Tests for blocked_domains in get_status response (full mode only)."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_blocked_test",
            "hypothesis": "Test blocked domains",
            "status": "exploring",
            "created_at": "2024-01-15T10:00:00Z",
        }

    @pytest.mark.asyncio
    async def test_get_status_includes_blocked_domains(self, mock_task: dict[str, Any]) -> None:
        """
        Test that get_status response includes blocked_domains in full mode.

        // Given: Task exists and verifier has blocked domains
        // When: Calling get_status with detail="full"
        // Then: Response includes blocked_domains array
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "spam-site.com",
                "blocked_at": "2024-01-15T10:30:00Z",
                "reason": "High rejection rate (40%)",
                "cause_id": None,
                "original_domain_category": "unverified",
                "domain_block_reason": "high_rejection_rate",
                "domain_unblock_risk": "low",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert "blocked_domains" in result
        assert len(result["blocked_domains"]) == 1
        assert result["blocked_domains"][0]["domain"] == "spam-site.com"
        assert result["blocked_domains"][0]["domain_block_reason"] == "high_rejection_rate"
        assert result["blocked_domains"][0]["domain_unblock_risk"] == "low"

    @pytest.mark.asyncio
    async def test_get_status_empty_blocked_domains(self, mock_task: dict[str, Any]) -> None:
        """
        Test that blocked_domains is empty when no domains blocked.

        // Given: Task exists and no blocked domains
        // When: Calling get_status
        // Then: Response includes empty blocked_domains array
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = []

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert "blocked_domains" in result
        assert result["blocked_domains"] == []

    @pytest.mark.asyncio
    async def test_blocked_domain_has_reason(self, mock_task: dict[str, Any]) -> None:
        """
        Test that blocked domain info includes reason.

        // Given: Task exists with blocked domain
        // When: Calling get_status
        // Then: Blocked domain has reason field
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "bad-site.com",
                "blocked_at": "2024-01-15T11:00:00Z",
                "reason": "Contradiction detected with pubmed.gov",
                "cause_id": "abc123",
                "original_domain_category": "unverified",
                "domain_block_reason": "unknown",
                "domain_unblock_risk": "high",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert len(result["blocked_domains"]) == 1
        blocked = result["blocked_domains"][0]
        assert "reason" in blocked
        assert "Contradiction" in blocked["reason"]
        assert blocked["cause_id"] == "abc123"
        assert blocked["domain_block_reason"] == "unknown"
        assert blocked["domain_unblock_risk"] == "high"

    @pytest.mark.asyncio
    async def test_blocked_domain_dangerous_pattern(self, mock_task: dict[str, Any]) -> None:
        """
        TC-N-01: dangerous_pattern でブロックされたドメイン.

        // Given: Task exists with domain blocked due to dangerous pattern
        // When: Calling get_status
        // Then: domain_block_reason="dangerous_pattern", domain_unblock_risk="high"
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "malicious-site.com",
                "blocked_at": "2024-01-15T12:00:00Z",
                "reason": "Dangerous pattern detected (L2/L4)",
                "cause_id": "xyz789",
                "original_domain_category": "unverified",
                "domain_block_reason": "dangerous_pattern",
                "domain_unblock_risk": "high",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert len(result["blocked_domains"]) == 1
        blocked = result["blocked_domains"][0]
        assert blocked["domain_block_reason"] == "dangerous_pattern"
        assert blocked["domain_unblock_risk"] == "high"

    @pytest.mark.asyncio
    async def test_blocked_domain_denylist(self, mock_task: dict[str, Any]) -> None:
        """
        TC-N-03: denylist でブロックされたドメイン.

        // Given: Task exists with domain blocked via denylist
        // When: Calling get_status
        // Then: domain_block_reason="denylist", domain_unblock_risk="low"
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "spam-aggregator.com",
                "blocked_at": "2024-01-15T13:00:00Z",
                "reason": "Domain in denylist",
                "cause_id": None,
                "original_domain_category": "unverified",
                "domain_block_reason": "denylist",
                "domain_unblock_risk": "low",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert len(result["blocked_domains"]) == 1
        blocked = result["blocked_domains"][0]
        assert blocked["domain_block_reason"] == "denylist"
        assert blocked["domain_unblock_risk"] == "low"

    @pytest.mark.asyncio
    async def test_blocked_domain_manual(self, mock_task: dict[str, Any]) -> None:
        """
        TC-N-04: manual でブロックされたドメイン.

        // Given: Task exists with domain blocked via manual feedback
        // When: Calling get_status
        // Then: domain_block_reason="manual", domain_unblock_risk="low"
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "user-blocked.com",
                "blocked_at": "2024-01-15T14:00:00Z",
                "reason": "Manual block via feedback",
                "cause_id": None,
                "original_domain_category": "low",
                "domain_block_reason": "manual",
                "domain_unblock_risk": "low",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        assert len(result["blocked_domains"]) == 1
        blocked = result["blocked_domains"][0]
        assert blocked["domain_block_reason"] == "manual"
        assert blocked["domain_unblock_risk"] == "low"

    @pytest.mark.asyncio
    async def test_blocked_domain_schema_sanitization(self, mock_task: dict[str, Any]) -> None:
        """
        TC-A-02: スキーマサニタイズ後も新フィールドが残る.

        // Given: Task exists with blocked domain
        // When: Calling get_status and schema sanitization is applied
        // Then: domain_block_reason and domain_unblock_risk remain after sanitization
        """
        from src.mcp.response_sanitizer import sanitize_response
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = [
            {
                "domain": "test-site.com",
                "blocked_at": "2024-01-15T15:00:00Z",
                "reason": "Test reason",
                "cause_id": None,
                "original_domain_category": "unverified",
                "domain_block_reason": "high_rejection_rate",
                "domain_unblock_risk": "low",
                "restore_via": "config/domains.yaml user_overrides or feedback(domain_unblock)",
            }
        ]

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status(
                        {"task_id": "task_blocked_test", "detail": "full"}
                    )

        # Sanitize response (simulating MCP response sanitization)
        sanitized = sanitize_response(result, "get_status")

        assert len(sanitized["blocked_domains"]) == 1
        blocked = sanitized["blocked_domains"][0]
        # Verify new fields are present after sanitization
        assert "domain_block_reason" in blocked
        assert "domain_unblock_risk" in blocked
        assert blocked["domain_block_reason"] == "high_rejection_rate"
        assert blocked["domain_unblock_risk"] == "low"


class TestGetStatusJobsSummary:
    """Tests for jobs summary in get_status response (ADR-0015).

    Note: jobs_by_kind is only in full mode. Summary mode has progress.jobs_by_phase.
    """

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_jobs_test",
            "hypothesis": "Test research question",
            "status": "exploring",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:30:00Z",
        }

    @pytest.mark.asyncio
    async def test_jobs_summary_in_response(self, mock_task: dict[str, Any]) -> None:
        """
        TC-JS-01: get_status includes jobs summary.

        // Given: Task with multiple job types
        // When: Calling get_status
        // Then: Response includes jobs field with summary
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        # Mock various helper functions
        mock_jobs_summary = {
            "total_queued": 2,
            "total_running": 1,
            "total_completed": 5,
            "total_failed": 0,
            "by_kind": {
                "target_queue": {"queued": 1, "running": 0, "completed": 3},
                "verify_nli": {"queued": 1, "running": 1, "completed": 2},
            },
        }

        mock_metrics = {
            "total_searches": 3,
            "satisfied_count": 0,
            "total_pages": 10,
            "total_fragments": 25,
            "total_claims": 15,
            "elapsed_seconds": 120,
        }

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state", side_effect=KeyError("No state")
            ):
                with patch(
                    "src.mcp.tools.task.get_task_jobs_summary",
                    new=AsyncMock(return_value=mock_jobs_summary),
                ):
                    with patch(
                        "src.mcp.tools.task.get_metrics_from_db",
                        new=AsyncMock(return_value=mock_metrics),
                    ):
                        with patch(
                            "src.mcp.tools.task.get_target_queue_status",
                            new=AsyncMock(return_value={"depth": 0, "running": 0, "items": []}),
                        ):
                            with patch(
                                "src.mcp.tools.task.get_pending_auth_info",
                                new=AsyncMock(
                                    return_value={
                                        "awaiting_auth_jobs": 0,
                                        "pending_captchas": 0,
                                        "domains": [],
                                    }
                                ),
                            ):
                                with patch(
                                    "src.mcp.tools.task.get_domain_overrides",
                                    new=AsyncMock(return_value=[]),
                                ):
                                    result = await _handle_get_status(
                                        {"task_id": "task_jobs_test", "detail": "full"}
                                    )

        assert result["ok"] is True
        # Full mode has jobs_by_kind
        assert "jobs_by_kind" in result
        assert "target_queue" in result["jobs_by_kind"]
        assert "verify_nli" in result["jobs_by_kind"]
        # Summary info is in progress.jobs_by_phase
        jobs_by_phase = result["progress"]["jobs_by_phase"]
        assert jobs_by_phase["exploration"]["queued"] == 1
        assert jobs_by_phase["exploration"]["completed"] == 3
        assert jobs_by_phase["verification"]["queued"] == 1
        assert jobs_by_phase["verification"]["running"] == 1

    @pytest.mark.asyncio
    async def test_jobs_summary_with_citation_graph(self, mock_task: dict[str, Any]) -> None:
        """
        TC-JS-02: jobs summary includes citation_graph kind.

        // Given: Task with citation_graph jobs
        // When: Calling get_status
        // Then: jobs.by_kind includes citation_graph
        """
        from src.mcp.tools.task import handle_get_status as _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_jobs_summary = {
            "total_queued": 1,
            "total_running": 0,
            "total_completed": 1,
            "total_failed": 0,
            "by_kind": {
                "citation_graph": {"queued": 1, "running": 0, "completed": 1},
            },
        }

        mock_metrics = {
            "total_searches": 1,
            "satisfied_count": 0,
            "total_pages": 5,
            "total_fragments": 10,
            "total_claims": 5,
            "elapsed_seconds": 60,
        }

        with patch("src.mcp.tools.task.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.tools.task.get_exploration_state", side_effect=KeyError("No state")
            ):
                with patch(
                    "src.mcp.tools.task.get_task_jobs_summary",
                    new=AsyncMock(return_value=mock_jobs_summary),
                ):
                    with patch(
                        "src.mcp.tools.task.get_metrics_from_db",
                        new=AsyncMock(return_value=mock_metrics),
                    ):
                        with patch(
                            "src.mcp.tools.task.get_target_queue_status",
                            new=AsyncMock(return_value={"depth": 0, "running": 0, "items": []}),
                        ):
                            with patch(
                                "src.mcp.tools.task.get_pending_auth_info",
                                new=AsyncMock(
                                    return_value={
                                        "awaiting_auth_jobs": 0,
                                        "pending_captchas": 0,
                                        "domains": [],
                                    }
                                ),
                            ):
                                with patch(
                                    "src.mcp.tools.task.get_domain_overrides",
                                    new=AsyncMock(return_value=[]),
                                ):
                                    result = await _handle_get_status(
                                        {"task_id": "task_jobs_test", "detail": "full"}
                                    )

        assert result["ok"] is True
        assert "citation_graph" in result["jobs_by_kind"]
