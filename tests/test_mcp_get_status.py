"""Tests for get_status MCP tool.

Tests the unified task and exploration status endpoint per §3.2.1.
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
        from src.mcp.server import _handle_get_status

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
        from src.mcp.server import _handle_get_status

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
        from src.mcp.server import _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with pytest.raises(TaskNotFoundError) as exc_info:
                await _handle_get_status({"task_id": "nonexistent_task"})

        assert exc_info.value.details.get("task_id") == "nonexistent_task"


class TestGetStatusWithExplorationState:
    """Tests for get_status with active exploration."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_abc123",
            "query": "Test research question",
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
                "pages_used": 25,
                "pages_limit": 120,
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
        from src.mcp.server import _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123"})

        assert result["ok"] is True
        assert result["task_id"] == "task_abc123"
        assert result["status"] == "exploring"
        assert result["query"] == "Test research question"
        assert len(result["searches"]) == 2
        assert result["metrics"]["total_searches"] == 2
        assert result["metrics"]["satisfied_count"] == 1
        assert result["budget"]["pages_used"] == 25

    @pytest.mark.asyncio
    async def test_subquery_to_search_field_mapping(
        self, mock_task: dict[str, Any], mock_exploration_status: dict[str, Any]
    ) -> None:
        """
        TC-N-05: Subquery to search field mapping.

        // Given: Exploration status with subqueries
        // When: Calling get_status
        // Then: Fields correctly mapped to §3.2.1 schema
        """
        from src.mcp.server import _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123"})

        # Verify search structure per §3.2.1
        search = result["searches"][0]
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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123"})

        assert result["auth_queue"] is not None
        assert result["auth_queue"]["pending_count"] == 3
        assert result["auth_queue"]["high_priority_count"] == 1

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
        from src.mcp.server import _handle_get_status

        # Add warnings to exploration status
        mock_exploration_status["warnings"] = [
            "Budget limit approaching: 80% pages used",
            "2件のサブクエリが収穫逓減で停止",
        ]

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_state = MagicMock()
        mock_state.get_status = AsyncMock(return_value=mock_exploration_status)

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_abc123"})

        assert len(result["warnings"]) == 2
        assert "Budget limit" in result["warnings"][0]


class TestGetStatusWithoutExplorationState:
    """Tests for get_status without exploration state."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_xyz789",
            "query": "Another research question",
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
        from src.mcp.server import _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        # Simulate no exploration state
        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                result = await _handle_get_status({"task_id": "task_xyz789"})

        assert result["ok"] is True
        assert result["task_id"] == "task_xyz789"
        assert result["status"] == "pending"  # DB status is returned when no exploration state
        assert result["query"] == "Another research question"
        assert result["searches"] == []
        assert result["metrics"]["total_searches"] == 0
        assert result["metrics"]["total_pages"] == 0
        # Budget is now always populated with defaults
        assert result["budget"]["pages_used"] == 0
        assert result["budget"]["pages_limit"] == 120
        assert result["budget"]["remaining_percent"] == 100
        assert result["auth_queue"] is None
        assert result["warnings"] == []


class TestGetStatusStatusMapping:
    """Tests for status field mapping."""

    @pytest.fixture
    def mock_task_base(self) -> dict[str, Any]:
        """Create base mock task."""
        return {
            "id": "task_test",
            "query": "Test query",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:00:00Z",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_status,expected_status",
        [
            ("exploring", "exploring"),
            ("paused", "paused"),
            ("completed", "completed"),
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
        // Then: Status is correctly mapped per §3.2.1
        """
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch("src.mcp.server._get_exploration_state", return_value=mock_state):
                result = await _handle_get_status({"task_id": "task_test"})

        assert result["status"] == expected_status


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

    def test_get_status_description_mentions_section(self) -> None:
        """
        Test that description references section 3.2.1.

        // Given: get_status tool definition
        // When: Reading description
        // Then: Contains §3.2.1 reference
        """
        from src.mcp.server import TOOLS

        tool = next((t for t in TOOLS if t.name == "get_status"), None)

        assert tool is not None
        assert tool.description is not None
        assert "3.2.1" in tool.description


class TestGetStatusBlockedDomains:
    """Tests for blocked_domains in get_status response."""

    @pytest.fixture
    def mock_task(self) -> dict[str, Any]:
        """Create mock task data."""
        return {
            "id": "task_blocked_test",
            "query": "Test blocked domains",
            "status": "exploring",
            "created_at": "2024-01-15T10:00:00Z",
        }

    @pytest.mark.asyncio
    async def test_get_status_includes_blocked_domains(self, mock_task: dict[str, Any]) -> None:
        """
        Test that get_status response includes blocked_domains.

        // Given: Task exists and verifier has blocked domains
        // When: Calling get_status
        // Then: Response includes blocked_domains array
        """
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = mock_task

        mock_verifier = MagicMock()
        mock_verifier.get_blocked_domains_info.return_value = []

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

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
        from src.mcp.server import _handle_get_status

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

        with patch("src.mcp.server.get_database", new=AsyncMock(return_value=mock_db)):
            with patch(
                "src.mcp.server._get_exploration_state",
                side_effect=KeyError("No state"),
            ):
                with patch(
                    "src.filter.source_verification.get_source_verifier",
                    return_value=mock_verifier,
                ):
                    result = await _handle_get_status({"task_id": "task_blocked_test"})

        # Sanitize response (simulating MCP response sanitization)
        sanitized = sanitize_response(result, "get_status")

        assert len(sanitized["blocked_domains"]) == 1
        blocked = sanitized["blocked_domains"][0]
        # Verify new fields are present after sanitization
        assert "domain_block_reason" in blocked
        assert "domain_unblock_risk" in blocked
        assert blocked["domain_block_reason"] == "high_rejection_rate"
        assert blocked["domain_unblock_risk"] == "low"
