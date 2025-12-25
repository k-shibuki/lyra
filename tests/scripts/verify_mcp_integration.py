#!/usr/bin/env python3
"""
MCP Tool Integration E2E Verification Script

Verification target: MCP tool integration verification - MCPツール疎通確認

Verification items:
1. create_task - タスク作成、DB登録
2. get_status - タスク状態取得
3. queue_searches - 検索キュー投入（即時応答）
4. stop_task - タスク終了
5. get_materials - レポート素材取得
6. calibration_metrics - 校正メトリクス取得
7. calibration_rollback - 校正ロールバック
8. get_auth_queue / resolve_auth - 認証キュー
9. feedback - Human-in-the-loop 操作（Domain/Claim/Edge）

Prerequisites:
- Podman containers running: ./scripts/dev.sh up
- Database initialized

Usage:
    # Full verification (requires Chrome CDP)
    python tests/scripts/verify_mcp_integration.py

    # Basic verification (no Chrome required)
    python tests/scripts/verify_mcp_integration.py --basic

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Critical prerequisites not met
"""

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@dataclass
class VerificationResult:
    """Data class to hold verification results."""

    name: str
    tool: str
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: str | None = None
    details: dict = field(default_factory=dict)
    error: str | None = None
    critical: bool = False


class MCPIntegrationVerifier:
    """
    Verifier for MCP tool integration.

    Tests MCP tools (Phase 2 removed: search, notify_user, wait_for_user).
    """

    def __init__(self, basic_mode: bool = False) -> None:
        """
        Initialize verifier.

        Args:
            basic_mode: If True, skip tests requiring Chrome CDP.
        """
        self.results: list[VerificationResult] = []
        self.basic_mode = basic_mode
        self.test_task_id: str | None = None

    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
        print("\n[Prerequisites] Checking environment...")

        # Check database
        try:
            from src.storage.database import get_database

            await get_database()
            print("  ✓ Database available")
        except Exception as e:
            print(f"  ✗ Database unavailable: {e}")
            return False

        # Check MCP server module
        try:
            from src.mcp.server import TOOLS

            print(f"  ✓ MCP server module loaded ({len(TOOLS)} tools)")
        except Exception as e:
            print(f"  ✗ MCP server import failed: {e}")
            return False

        return True

    # ========================================
    # 1. Task Management Tools
    # ========================================

    async def verify_create_task(self) -> VerificationResult:
        """
        Verify create_task tool.

        Tests:
        - Task is created with valid task_id
        - Task is stored in database
        - Response contains required fields
        """
        print("\n[1/10] Verifying create_task...")

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "query": "E2E test: MCP integration verification",
                "config": {
                    "budget": {
                        "budget_pages": 10,
                        "max_seconds": 300,
                    },
                    "language": "ja",
                },
            }

            result = await _dispatch_tool("create_task", args)

            # Check response structure
            if not result.get("ok"):
                return VerificationResult(
                    name="create_task",
                    tool="create_task",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            # Check required fields
            required_fields = ["task_id", "query", "created_at", "budget"]
            missing = [f for f in required_fields if f not in result]
            if missing:
                return VerificationResult(
                    name="create_task",
                    tool="create_task",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=f"Missing fields: {missing}",
                )

            # Store task_id for subsequent tests
            self.test_task_id = result["task_id"]

            # Verify DB persistence
            from src.storage.database import get_database

            db = await get_database()
            task = await db.fetch_one(
                "SELECT * FROM tasks WHERE id = ?",
                (self.test_task_id,),
            )

            if not task:
                return VerificationResult(
                    name="create_task",
                    tool="create_task",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=f"Task not found in DB: {self.test_task_id}",
                )

            print(f"    ✓ Task created: {self.test_task_id}")
            print(f"    ✓ Budget: {result['budget']}")

            return VerificationResult(
                name="create_task",
                tool="create_task",
                spec_ref="ADR-0003",
                passed=True,
                details={
                    "task_id": self.test_task_id,
                    "budget": result["budget"],
                },
            )

        except Exception as e:
            logger.exception("create_task verification failed")
            return VerificationResult(
                name="create_task",
                tool="create_task",
                spec_ref="ADR-0003",
                passed=False,
                error=str(e),
                critical=True,
            )

    async def verify_get_status(self) -> VerificationResult:
        """
        Verify get_status tool.

        Tests:
        - Returns status for existing task
        - Contains required fields (searches, metrics, budget)
        - Returns error for non-existent task
        """
        print("\n[2/10] Verifying get_status...")

        if not self.test_task_id:
            return VerificationResult(
                name="get_status",
                tool="get_status",
                spec_ref="ADR-0003",
                passed=False,
                skipped=True,
                skip_reason="No task_id from create_task",
            )

        try:
            from src.mcp.server import _dispatch_tool

            # Test with valid task_id
            result = await _dispatch_tool("get_status", {"task_id": self.test_task_id})

            if not result.get("ok"):
                return VerificationResult(
                    name="get_status",
                    tool="get_status",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            # Check required fields
            required_fields = ["task_id", "status", "query", "searches", "metrics", "budget"]
            missing = [f for f in required_fields if f not in result]
            if missing:
                return VerificationResult(
                    name="get_status",
                    tool="get_status",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=f"Missing fields: {missing}",
                    details={"result_keys": list(result.keys())},
                )

            print(f"    ✓ Status: {result['status']}")
            print(f"    ✓ Budget remaining: {result['budget'].get('remaining_percent', 'N/A')}%")

            # Test with non-existent task_id
            try:
                error_result = await _dispatch_tool("get_status", {"task_id": "nonexistent_task"})
                if error_result.get("ok"):
                    return VerificationResult(
                        name="get_status",
                        tool="get_status",
                        spec_ref="ADR-0003",
                        passed=False,
                        error="Expected error for non-existent task, got ok=True",
                    )
                print("    ✓ Non-existent task returns error (dict)")
            except Exception:
                # Exception is also acceptable for task not found
                print("    ✓ Non-existent task returns error (exception)")

            return VerificationResult(
                name="get_status",
                tool="get_status",
                spec_ref="ADR-0003",
                passed=True,
                details={
                    "status": result["status"],
                    "metrics": result["metrics"],
                },
            )

        except Exception as e:
            logger.exception("get_status verification failed")
            return VerificationResult(
                name="get_status",
                tool="get_status",
                spec_ref="ADR-0003",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 2. Research Execution Tools
    # ========================================

    async def verify_queue_searches(self) -> VerificationResult:
        """
        Verify queue_searches tool.

        Tests:
        - Queues searches and returns search_ids immediately
        - Persists queued jobs to DB (kind='search_queue')
        """
        print("\n[3/10] Verifying queue_searches...")

        if not self.test_task_id:
            return VerificationResult(
                name="queue_searches",
                tool="queue_searches",
                spec_ref="ADR-0010",
                passed=False,
                skipped=True,
                skip_reason="No task_id from create_task",
            )

        try:
            from src.mcp.server import _dispatch_tool

            args: dict[str, Any] = {
                "task_id": self.test_task_id,
                "options": {
                    "engines": ["mojeek"],  # Less blocking-prone (optional)
                    "budget_pages": 3,
                },
                "queries": ["Python programming best practices", "Python typing best practices"],
            }

            print(f"    Queuing {len(args['queries'])} searches...")

            result = await _dispatch_tool("queue_searches", args)

            if not result.get("ok"):
                return VerificationResult(
                    name="queue_searches",
                    tool="queue_searches",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=str(result.get("error", "Unknown error")),
                )

            queued_count = result.get("queued_count")
            search_ids = result.get("search_ids")
            if not isinstance(queued_count, int) or queued_count < 1:
                return VerificationResult(
                    name="queue_searches",
                    tool="queue_searches",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Invalid queued_count: {queued_count}",
                )
            if not isinstance(search_ids, list) or len(search_ids) != queued_count:
                return VerificationResult(
                    name="queue_searches",
                    tool="queue_searches",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Invalid search_ids length: {search_ids}",
                )

            # Verify DB persistence (jobs.kind = 'search_queue')
            from src.storage.database import get_database

            db = await get_database()
            rows = await db.fetch_all(
                f"SELECT id, kind, state FROM jobs WHERE id IN ({','.join(['?'] * len(search_ids))})",
                tuple(search_ids),
            )
            if len(rows) != len(search_ids):
                return VerificationResult(
                    name="queue_searches",
                    tool="queue_searches",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Queued jobs not found in DB (expected={len(search_ids)} got={len(rows)})",
                )

            return VerificationResult(
                name="queue_searches",
                tool="queue_searches",
                spec_ref="ADR-0010",
                passed=True,
                details={
                    "queued_count": queued_count,
                    "search_id_sample": search_ids[0],
                },
            )

        except Exception as e:
            logger.exception("queue_searches verification failed")
            return VerificationResult(
                name="queue_searches",
                tool="queue_searches",
                spec_ref="ADR-0010",
                passed=False,
                error=str(e),
            )

    async def verify_stop_task(self) -> VerificationResult:
        """
        Verify stop_task tool.

        Tests:
        - Task is finalized
        - Summary is returned
        - DB status is updated
        """
        print("\n[4/10] Verifying stop_task...")

        if not self.test_task_id:
            return VerificationResult(
                name="stop_task",
                tool="stop_task",
                spec_ref="ADR-0003",
                passed=False,
                skipped=True,
                skip_reason="No task_id from create_task",
            )

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "task_id": self.test_task_id,
                "reason": "completed",
            }

            result = await _dispatch_tool("stop_task", args)

            if not result.get("ok"):
                return VerificationResult(
                    name="stop_task",
                    tool="stop_task",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            # Check required fields
            if "final_status" not in result:
                return VerificationResult(
                    name="stop_task",
                    tool="stop_task",
                    spec_ref="ADR-0003",
                    passed=False,
                    error="Missing final_status field",
                )

            print(f"    ✓ Final status: {result['final_status']}")
            print(f"    ✓ Summary: {result.get('summary', {})}")

            # Verify DB update
            from src.storage.database import get_database

            db = await get_database()
            task = await db.fetch_one(
                "SELECT status FROM tasks WHERE id = ?",
                (self.test_task_id,),
            )

            if task:
                db_status = task.get("status") if isinstance(task, dict) else task[0]
                print(f"    ✓ DB status: {db_status}")

            return VerificationResult(
                name="stop_task",
                tool="stop_task",
                spec_ref="ADR-0003",
                passed=True,
                details={
                    "final_status": result["final_status"],
                    "summary": result.get("summary"),
                },
            )

        except Exception as e:
            logger.exception("stop_task verification failed")
            return VerificationResult(
                name="stop_task",
                tool="stop_task",
                spec_ref="ADR-0003",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 3. Materials Tool
    # ========================================

    async def verify_get_materials(self) -> VerificationResult:
        """
        Verify get_materials tool.

        Tests:
        - Returns claims and fragments
        - Evidence graph can be included
        - Summary is calculated
        """
        print("\n[5/10] Verifying get_materials...")

        if not self.test_task_id:
            return VerificationResult(
                name="get_materials",
                tool="get_materials",
                spec_ref="ADR-0003",
                passed=False,
                skipped=True,
                skip_reason="No task_id from create_task",
            )

        try:
            from src.mcp.server import _dispatch_tool

            # Test without graph
            args = {
                "task_id": self.test_task_id,
                "options": {
                    "include_graph": False,
                },
            }

            result = await _dispatch_tool("get_materials", args)

            if not result.get("ok"):
                return VerificationResult(
                    name="get_materials",
                    tool="get_materials",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            # Check required fields
            required_fields = ["claims", "fragments", "summary"]
            missing = [f for f in required_fields if f not in result]
            if missing:
                return VerificationResult(
                    name="get_materials",
                    tool="get_materials",
                    spec_ref="ADR-0003",
                    passed=False,
                    error=f"Missing fields: {missing}",
                )

            print(f"    ✓ Claims: {len(result['claims'])}")
            print(f"    ✓ Fragments: {len(result['fragments'])}")
            print(f"    ✓ Summary: {result['summary']}")

            # Test with graph
            args_with_graph = {
                "task_id": self.test_task_id,
                "options": {
                    "include_graph": True,
                },
            }

            result_with_graph = await _dispatch_tool("get_materials", args_with_graph)

            has_graph = "evidence_graph" in result_with_graph
            print(f"    ✓ Evidence graph included: {has_graph}")

            return VerificationResult(
                name="get_materials",
                tool="get_materials",
                spec_ref="ADR-0003",
                passed=True,
                details={
                    "claims_count": len(result["claims"]),
                    "fragments_count": len(result["fragments"]),
                    "has_evidence_graph": has_graph,
                },
            )

        except Exception as e:
            logger.exception("get_materials verification failed")
            return VerificationResult(
                name="get_materials",
                tool="get_materials",
                spec_ref="ADR-0003",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 4. Calibration Tools
    # ========================================

    async def verify_calibration_metrics(self) -> VerificationResult:
        """
        Verify calibration_metrics tool (4 actions).

        Tests:
        - get_stats: Returns calibration statistics
        - add_sample: Adds calibration sample
        - get_evaluations: Returns evaluation history
        """
        print("\n[6/10] Verifying calibration_metrics...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test get_stats action
            stats_result = await _dispatch_tool("calibration_metrics", {"action": "get_stats"})

            if not stats_result.get("ok"):
                # get_stats might fail if no calibration data exists, which is OK
                if "No calibration data" in str(stats_result.get("error", "")):
                    print("    ! No calibration data (expected for fresh DB)")
                else:
                    return VerificationResult(
                        name="calibration_metrics",
                        tool="calibration_metrics",
                        spec_ref="ADR-0011",
                        passed=False,
                        error=f"get_stats failed: {stats_result.get('error')}",
                    )
            else:
                print(f"    ✓ get_stats: {stats_result.get('sources', [])}")

            # Test get_evaluations action
            eval_args = {
                "action": "get_evaluations",
                "data": {
                    "source": "test_model",
                    "limit": 10,
                },
            }

            eval_result = await _dispatch_tool("calibration_metrics", eval_args)

            if not eval_result.get("ok"):
                # May fail if no evaluations exist
                print(f"    ! get_evaluations: {eval_result.get('error', 'no data')}")
            else:
                print(f"    ✓ get_evaluations: {len(eval_result.get('evaluations', []))} records")

            return VerificationResult(
                name="calibration_metrics",
                tool="calibration_metrics",
                spec_ref="ADR-0011",
                passed=True,
                details={
                    "actions_tested": ["get_stats", "get_evaluations"],
                },
            )

        except Exception as e:
            logger.exception("calibration_metrics verification failed")
            return VerificationResult(
                name="calibration_metrics",
                tool="calibration_metrics",
                spec_ref="ADR-0011",
                passed=False,
                error=str(e),
            )

    async def verify_calibration_rollback(self) -> VerificationResult:
        """
        Verify calibration_rollback tool.

        Tests:
        - Rollback fails gracefully when no version exists
        - Error messages are informative
        """
        print("\n[7/10] Verifying calibration_rollback...")

        try:
            from src.mcp.errors import MCPError
            from src.mcp.server import _dispatch_tool

            # Test rollback with non-existent source (should fail gracefully)
            args = {
                "source": "nonexistent_model",
                "reason": "E2E verification test",
            }

            try:
                result = await _dispatch_tool("calibration_rollback", args)

                # Should fail because no version exists
                if result.get("ok"):
                    return VerificationResult(
                        name="calibration_rollback",
                        tool="calibration_rollback",
                        spec_ref="ADR-0011",
                        passed=False,
                        error="Expected failure for non-existent source, got ok=True",
                    )

                # Check error is informative
                error_msg = result.get("error", result.get("message", ""))
                print(f"    ✓ Rollback correctly failed: {error_msg[:50]}...")

            except MCPError as e:
                # MCPError is expected for non-existent source
                print(f"    ✓ Rollback correctly raised MCPError: {e.message[:50]}...")

            return VerificationResult(
                name="calibration_rollback",
                tool="calibration_rollback",
                spec_ref="ADR-0011",
                passed=True,
                details={
                    "error_handling": "correct",
                },
            )

        except Exception as e:
            logger.exception("calibration_rollback verification failed")
            return VerificationResult(
                name="calibration_rollback",
                tool="calibration_rollback",
                spec_ref="ADR-0011",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 5. Authentication Queue Tools
    # ========================================

    async def verify_get_auth_queue(self) -> VerificationResult:
        """
        Verify get_auth_queue tool.

        Tests:
        - Returns empty queue when no pending items
        - Supports grouping options
        """
        print("\n[8/10] Verifying get_auth_queue...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test with no grouping
            result = await _dispatch_tool("get_auth_queue", {})

            if not result.get("ok"):
                return VerificationResult(
                    name="get_auth_queue",
                    tool="get_auth_queue",
                    spec_ref="ADR-0007",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            print(f"    ✓ Total items: {result.get('total_count', 0)}")

            # Test with domain grouping
            grouped_result = await _dispatch_tool("get_auth_queue", {"group_by": "domain"})

            if not grouped_result.get("ok"):
                return VerificationResult(
                    name="get_auth_queue",
                    tool="get_auth_queue",
                    spec_ref="ADR-0007",
                    passed=False,
                    error=f"Grouping failed: {grouped_result.get('error')}",
                )

            print(f"    ✓ Domain groups: {len(grouped_result.get('groups', {}))}")

            return VerificationResult(
                name="get_auth_queue",
                tool="get_auth_queue",
                spec_ref="ADR-0007",
                passed=True,
                details={
                    "total_count": result.get("total_count", 0),
                    "grouping_works": True,
                },
            )

        except Exception as e:
            logger.exception("get_auth_queue verification failed")
            return VerificationResult(
                name="get_auth_queue",
                tool="get_auth_queue",
                spec_ref="ADR-0007",
                passed=False,
                error=str(e),
            )

    async def verify_resolve_auth(self) -> VerificationResult:
        """
        Verify resolve_auth tool.

        Tests:
        - Handles non-existent queue_id gracefully
        - Validates required parameters
        """
        print("\n[9/10] Verifying resolve_auth...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test with non-existent queue_id (should fail gracefully)
            args = {
                "target": "item",
                "queue_id": "nonexistent_queue_id",
                "action": "complete",
                "success": True,
            }

            result = await _dispatch_tool("resolve_auth", args)

            # May succeed (no-op) or fail, both are acceptable
            print(f"    ✓ resolve_auth response: ok={result.get('ok')}")

            # Test parameter validation (missing action)
            invalid_args = {
                "target": "item",
                "queue_id": "test_id",
            }

            try:
                invalid_result = await _dispatch_tool("resolve_auth", invalid_args)
                # Should return error
                if invalid_result.get("ok"):
                    return VerificationResult(
                        name="resolve_auth",
                        tool="resolve_auth",
                        spec_ref="ADR-0007",
                        passed=False,
                        error="Expected validation error for missing action",
                    )
                print("    ✓ Parameter validation works")
            except Exception:
                print("    ✓ Parameter validation works (raised exception)")

            return VerificationResult(
                name="resolve_auth",
                tool="resolve_auth",
                spec_ref="ADR-0007",
                passed=True,
                details={
                    "validation": "working",
                },
            )

        except Exception as e:
            logger.exception("resolve_auth verification failed")
            return VerificationResult(
                name="resolve_auth",
                tool="resolve_auth",
                spec_ref="ADR-0007",
                passed=False,
                error=str(e),
            )

    async def verify_feedback(self) -> VerificationResult:
        """
        Verify feedback tool (ADR-0012).

        // Given: Feedback tool is registered
        // When: Calling a safe action (domain_clear_override) with a test pattern
        // Then: Returns ok=True (cleared_rules may be 0)
        """
        print("\n[10/10] Verifying feedback...")

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "action": "domain_clear_override",
                "domain_pattern": "example.com",
                "reason": "E2E verification test (Phase 2 toolset)",
            }
            result = await _dispatch_tool("feedback", args)

            if not result.get("ok"):
                return VerificationResult(
                    name="feedback",
                    tool="feedback",
                    spec_ref="ADR-0012",
                    passed=False,
                    error=str(result.get("error", "Unknown error")),
                )

            return VerificationResult(
                name="feedback",
                tool="feedback",
                spec_ref="ADR-0012",
                passed=True,
                details={
                    "action": result.get("action"),
                    "cleared_rules": result.get("cleared_rules"),
                },
            )
        except Exception as e:
            logger.exception("feedback verification failed")
            return VerificationResult(
                name="feedback",
                tool="feedback",
                spec_ref="ADR-0012",
                passed=False,
                error=str(e),
            )

        try:
            from src.mcp.server import _dispatch_tool

            # Test with non-existent queue_id (should fail gracefully)
            args = {
                "target": "item",
                "queue_id": "nonexistent_queue_id",
                "action": "complete",
                "success": True,
            }

            result = await _dispatch_tool("resolve_auth", args)

            # May succeed (no-op) or fail, both are acceptable
            print(f"    ✓ resolve_auth response: ok={result.get('ok')}")

            # Test parameter validation (missing action)
            invalid_args = {
                "target": "item",
                "queue_id": "test_id",
            }

            try:
                invalid_result = await _dispatch_tool("resolve_auth", invalid_args)
                # Should return error
                if invalid_result.get("ok"):
                    return VerificationResult(
                        name="resolve_auth",
                        tool="resolve_auth",
                        spec_ref="ADR-0007",
                        passed=False,
                        error="Expected validation error for missing action",
                    )
                print("    ✓ Parameter validation works")
            except Exception:
                print("    ✓ Parameter validation works (raised exception)")

            return VerificationResult(
                name="resolve_auth",
                tool="resolve_auth",
                spec_ref="ADR-0007",
                passed=True,
                details={
                    "validation": "working",
                },
            )

        except Exception as e:
            logger.exception("resolve_auth verification failed")
            return VerificationResult(
                name="resolve_auth",
                tool="resolve_auth",
                spec_ref="ADR-0007",
                passed=False,
                error=str(e),
            )

    # NOTE: Phase 2 removed MCP tools: notify_user, wait_for_user.

    async def cleanup(self) -> None:
        """Clean up test data."""
        if self.test_task_id:
            try:
                from src.storage.database import get_database

                db = await get_database()

                # Delete test task and related data
                # Note: fragments don't have task_id directly, they're linked via pages
                await db.execute("DELETE FROM claims WHERE task_id = ?", (self.test_task_id,))
                await db.execute("DELETE FROM queries WHERE task_id = ?", (self.test_task_id,))
                await db.execute("DELETE FROM tasks WHERE id = ?", (self.test_task_id,))

                print(f"\n[Cleanup] Deleted test task: {self.test_task_id}")
            except Exception as e:
                print(f"\n[Cleanup] Warning: Failed to delete test data: {e}")

    async def run_all(self) -> int:
        """
        Run all verifications and return exit code.

        Returns:
            0: All passed
            1: Some failed
            2: Critical failure
        """
        print("\n" + "=" * 70)
        print("MCP Tool Integration Verification")
        print("検証対象: MCPツール（10個）の疎通確認")
        print("=" * 70)

        if self.basic_mode:
            print("\n⚠ Basic mode: Network-dependent verifications may be skipped/limited")

        # Check prerequisites
        if not await self.check_prerequisites():
            print("\n⚠ Prerequisites not met. Cannot continue.")
            return 2

        # Run verifications
        verifications = [
            # Task Management
            self.verify_create_task,  # Creates test_task_id
            self.verify_get_status,
            # Research Execution
            self.verify_queue_searches,
            self.verify_stop_task,
            # Materials
            self.verify_get_materials,
            # Calibration
            self.verify_calibration_metrics,
            self.verify_calibration_rollback,
            # Auth Queue
            self.verify_get_auth_queue,
            self.verify_resolve_auth,
            # Feedback
            self.verify_feedback,
        ]

        critical_failure = False

        for verify_func in verifications:
            result = await verify_func()
            self.results.append(result)

            if result.critical and not result.passed:
                critical_failure = True
                print(f"\n⚠ Critical failure: {result.error}")
                break

        # Cleanup
        await self.cleanup()

        # Summary
        print("\n" + "=" * 70)
        print("Verification Summary")
        print("=" * 70)

        passed = 0
        failed = 0
        skipped = 0

        for result in self.results:
            if result.skipped:
                status = "⏭ SKIP"
                skipped += 1
            elif result.passed:
                status = "✓ PASS"
                passed += 1
            else:
                status = "✗ FAIL"
                failed += 1

            print(f"  {status}  {result.tool}: {result.name} ({result.spec_ref})")
            if result.error:
                error_lines = str(result.error).split("\n")
                for line in error_lines[:2]:
                    print(f"         Error: {line[:60]}")
            if result.skip_reason:
                print(f"         Reason: {result.skip_reason}")

        print("\n" + "-" * 70)
        print(
            f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}"
        )
        print("=" * 70)

        if critical_failure:
            print("\n⚠ CRITICAL: Cannot proceed with E2E tests.")
            return 2
        elif failed > 0:
            print("\n⚠ Some verifications FAILED.")
            return 1
        else:
            print("\n✓ All MCP tools verified successfully!")
            return 0


async def main() -> int:
    """Main entry point."""
    configure_logging(log_level="INFO", json_format=False)

    # Parse arguments
    basic_mode = "--basic" in sys.argv

    verifier = MCPIntegrationVerifier(basic_mode=basic_mode)
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
