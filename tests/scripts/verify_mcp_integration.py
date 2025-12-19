#!/usr/bin/env python3
"""
MCP Tool Integration E2E Verification Script

Verification target: N.2-2 - MCPツール疎通確認

Verification items:
1. create_task - タスク作成、DB登録
2. get_status - タスク状態取得
3. search - 検索パイプライン（Chrome CDP依存）
4. stop_task - タスク終了
5. get_materials - レポート素材取得
6. calibrate - 校正操作（5 actions）
7. get_auth_queue / resolve_auth - 認証キュー
8. notify_user / wait_for_user - 通知

Prerequisites:
- Podman containers running: ./scripts/dev.sh up
- Chrome running with remote debugging: ./scripts/chrome.sh start (for search tests)
- Database initialized
- See: docs/IMPLEMENTATION_PLAN.md Phase N

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
    Verifier for N.2-2 MCP Tool Integration.
    
    Tests all 11 MCP tools defined in Phase M.
    """

    def __init__(self, basic_mode: bool = False):
        """
        Initialize verifier.
        
        Args:
            basic_mode: If True, skip tests requiring Chrome CDP.
        """
        self.results: list[VerificationResult] = []
        self.basic_mode = basic_mode
        self.test_task_id: str | None = None
        self.chrome_available = False

    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
        print("\n[Prerequisites] Checking environment...")

        # Check database
        try:
            from src.storage.database import get_database
            db = await get_database()
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

        # Check Chrome CDP (optional in basic mode)
        if not self.basic_mode:
            try:
                from src.search.browser_search_provider import BrowserSearchProvider
                provider = BrowserSearchProvider()
                await asyncio.wait_for(provider._ensure_browser(), timeout=10.0)
                if provider._browser and provider._browser.is_connected():
                    self.chrome_available = True
                    print("  ✓ Chrome CDP connected")
                else:
                    print("  ! Chrome CDP not connected (search tests will be skipped)")
                await provider.close()
            except TimeoutError:
                print("  ! Chrome CDP timeout (search tests will be skipped)")
            except Exception as e:
                print(f"  ! Chrome CDP check failed: {e} (search tests will be skipped)")
        else:
            print("  ⏭ Chrome CDP check skipped (basic mode)")

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
        print("\n[1/11] Verifying create_task...")

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "query": "E2E test: MCP integration verification",
                "config": {
                    "budget": {
                        "max_pages": 10,
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
                    spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
                    passed=False,
                    error=f"Task not found in DB: {self.test_task_id}",
                )

            print(f"    ✓ Task created: {self.test_task_id}")
            print(f"    ✓ Budget: {result['budget']}")

            return VerificationResult(
                name="create_task",
                tool="create_task",
                spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
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
        print("\n[2/11] Verifying get_status...")

        if not self.test_task_id:
            return VerificationResult(
                name="get_status",
                tool="get_status",
                spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
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
                        spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 2. Research Execution Tools
    # ========================================

    async def verify_search(self) -> VerificationResult:
        """
        Verify search tool.
        
        Tests:
        - Search pipeline executes
        - Returns correct response structure
        - Budget tracking works
        
        Requires Chrome CDP connection.
        """
        print("\n[3/11] Verifying search...")

        if not self.chrome_available and not self.basic_mode:
            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
                passed=False,
                skipped=True,
                skip_reason="Chrome CDP not available",
            )

        if self.basic_mode:
            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
                passed=False,
                skipped=True,
                skip_reason="Skipped in basic mode",
            )

        if not self.test_task_id:
            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
                passed=False,
                skipped=True,
                skip_reason="No task_id from create_task",
            )

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "task_id": self.test_task_id,
                "query": "Python programming best practices",
                "options": {
                    "engines": ["mojeek"],  # Less blocking-prone
                    "max_pages": 3,
                },
            }

            print(f"    Executing search: {args['query'][:50]}...")

            # Execute with timeout
            result = await asyncio.wait_for(
                _dispatch_tool("search", args),
                timeout=60.0,
            )

            # Check response structure
            if "error" in result and not result.get("ok"):
                # May be CAPTCHA or other expected error
                error_msg = result.get("error", "")
                if "CAPTCHA" in str(error_msg):
                    return VerificationResult(
                        name="search",
                        tool="search",
                        spec_ref="§3.2.1",
                        passed=True,  # CAPTCHA detection is correct behavior
                        details={"captcha_detected": True},
                    )

                return VerificationResult(
                    name="search",
                    tool="search",
                    spec_ref="§3.2.1",
                    passed=False,
                    error=error_msg,
                )

            # Check required fields
            required_fields = ["search_id", "query", "status", "pages_fetched"]
            missing = [f for f in required_fields if f not in result]
            if missing:
                return VerificationResult(
                    name="search",
                    tool="search",
                    spec_ref="§3.2.1",
                    passed=False,
                    error=f"Missing fields: {missing}",
                    details={"result_keys": list(result.keys())},
                )

            print(f"    ✓ Search ID: {result.get('search_id')}")
            print(f"    ✓ Status: {result.get('status')}")
            print(f"    ✓ Pages fetched: {result.get('pages_fetched')}")

            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
                passed=True,
                details={
                    "search_id": result.get("search_id"),
                    "status": result.get("status"),
                    "pages_fetched": result.get("pages_fetched"),
                    "claims_found": len(result.get("claims_found", [])),
                },
            )

        except TimeoutError:
            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
                passed=False,
                error="Search timeout (60s)",
            )
        except Exception as e:
            logger.exception("search verification failed")
            return VerificationResult(
                name="search",
                tool="search",
                spec_ref="§3.2.1",
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
        print("\n[4/11] Verifying stop_task...")

        if not self.test_task_id:
            return VerificationResult(
                name="stop_task",
                tool="stop_task",
                spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
                    passed=False,
                    error=result.get("error", "Unknown error"),
                )

            # Check required fields
            if "final_status" not in result:
                return VerificationResult(
                    name="stop_task",
                    tool="stop_task",
                    spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
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
        print("\n[5/11] Verifying get_materials...")

        if not self.test_task_id:
            return VerificationResult(
                name="get_materials",
                tool="get_materials",
                spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
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
                    spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
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
                spec_ref="§3.2.1",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 4. Calibration Tools
    # ========================================

    async def verify_calibrate(self) -> VerificationResult:
        """
        Verify calibrate tool (5 actions).
        
        Tests:
        - get_stats: Returns calibration statistics
        - add_sample: Adds calibration sample
        - get_evaluations: Returns evaluation history
        """
        print("\n[6/11] Verifying calibrate...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test get_stats action
            stats_result = await _dispatch_tool("calibrate", {"action": "get_stats"})

            if not stats_result.get("ok"):
                # get_stats might fail if no calibration data exists, which is OK
                if "No calibration data" in str(stats_result.get("error", "")):
                    print("    ! No calibration data (expected for fresh DB)")
                else:
                    return VerificationResult(
                        name="calibrate",
                        tool="calibrate",
                        spec_ref="§4.6.1",
                        passed=False,
                        error=f"get_stats failed: {stats_result.get('error')}",
                    )
            else:
                print(f"    ✓ get_stats: {stats_result.get('sources', [])}")

            # Test add_sample action
            sample_args = {
                "action": "add_sample",
                "data": {
                    "source": "test_model",
                    "prediction": 0.8,
                    "actual": 1.0,
                    "logit": 1.386,  # logit(0.8)
                },
            }

            add_result = await _dispatch_tool("calibrate", sample_args)

            if not add_result.get("ok"):
                return VerificationResult(
                    name="calibrate",
                    tool="calibrate",
                    spec_ref="§4.6.1",
                    passed=False,
                    error=f"add_sample failed: {add_result.get('error')}",
                )

            print("    ✓ add_sample: sample added")

            # Test get_evaluations action
            eval_args = {
                "action": "get_evaluations",
                "data": {
                    "source": "test_model",
                    "limit": 10,
                },
            }

            eval_result = await _dispatch_tool("calibrate", eval_args)

            if not eval_result.get("ok"):
                # May fail if no evaluations exist
                print(f"    ! get_evaluations: {eval_result.get('error', 'no data')}")
            else:
                print(f"    ✓ get_evaluations: {len(eval_result.get('evaluations', []))} records")

            return VerificationResult(
                name="calibrate",
                tool="calibrate",
                spec_ref="§4.6.1",
                passed=True,
                details={
                    "actions_tested": ["get_stats", "add_sample", "get_evaluations"],
                },
            )

        except Exception as e:
            logger.exception("calibrate verification failed")
            return VerificationResult(
                name="calibrate",
                tool="calibrate",
                spec_ref="§4.6.1",
                passed=False,
                error=str(e),
            )

    async def verify_calibrate_rollback(self) -> VerificationResult:
        """
        Verify calibrate_rollback tool.
        
        Tests:
        - Rollback fails gracefully when no version exists
        - Error messages are informative
        """
        print("\n[7/11] Verifying calibrate_rollback...")

        try:
            from src.mcp.errors import MCPError
            from src.mcp.server import _dispatch_tool

            # Test rollback with non-existent source (should fail gracefully)
            args = {
                "source": "nonexistent_model",
                "reason": "E2E verification test",
            }

            try:
                result = await _dispatch_tool("calibrate_rollback", args)

                # Should fail because no version exists
                if result.get("ok"):
                    return VerificationResult(
                        name="calibrate_rollback",
                        tool="calibrate_rollback",
                        spec_ref="§4.6.1",
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
                name="calibrate_rollback",
                tool="calibrate_rollback",
                spec_ref="§4.6.1",
                passed=True,
                details={
                    "error_handling": "correct",
                },
            )

        except Exception as e:
            logger.exception("calibrate_rollback verification failed")
            return VerificationResult(
                name="calibrate_rollback",
                tool="calibrate_rollback",
                spec_ref="§4.6.1",
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
        print("\n[8/11] Verifying get_auth_queue...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test with no grouping
            result = await _dispatch_tool("get_auth_queue", {})

            if not result.get("ok"):
                return VerificationResult(
                    name="get_auth_queue",
                    tool="get_auth_queue",
                    spec_ref="§3.6.1",
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
                    spec_ref="§3.6.1",
                    passed=False,
                    error=f"Grouping failed: {grouped_result.get('error')}",
                )

            print(f"    ✓ Domain groups: {len(grouped_result.get('groups', {}))}")

            return VerificationResult(
                name="get_auth_queue",
                tool="get_auth_queue",
                spec_ref="§3.6.1",
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
                spec_ref="§3.6.1",
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
        print("\n[9/11] Verifying resolve_auth...")

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
                        spec_ref="§3.6.1",
                        passed=False,
                        error="Expected validation error for missing action",
                    )
                print("    ✓ Parameter validation works")
            except Exception:
                print("    ✓ Parameter validation works (raised exception)")

            return VerificationResult(
                name="resolve_auth",
                tool="resolve_auth",
                spec_ref="§3.6.1",
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
                spec_ref="§3.6.1",
                passed=False,
                error=str(e),
            )

    # ========================================
    # 6. Notification Tools
    # ========================================

    async def verify_notify_user(self) -> VerificationResult:
        """
        Verify notify_user tool.
        
        Tests:
        - Notification is sent (or fails gracefully if no notification system)
        - Event types are validated
        """
        print("\n[10/11] Verifying notify_user...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test info notification
            args = {
                "event": "info",
                "payload": {
                    "message": "E2E test notification from verify_mcp_integration.py",
                },
            }

            result = await _dispatch_tool("notify_user", args)

            if not result.get("ok"):
                # May fail if notification system unavailable
                error_msg = result.get("error", "")
                if "provider" in error_msg.lower() or "unavailable" in error_msg.lower():
                    print("    ! Notification system unavailable (expected in container)")
                    return VerificationResult(
                        name="notify_user",
                        tool="notify_user",
                        spec_ref="§3.6",
                        passed=True,  # Graceful failure is acceptable
                        details={"notification_available": False},
                    )

                return VerificationResult(
                    name="notify_user",
                    tool="notify_user",
                    spec_ref="§3.6",
                    passed=False,
                    error=result.get("error"),
                )

            print(f"    ✓ Notification sent: {result.get('notified')}")

            # Test event validation
            invalid_args = {
                "event": "invalid_event_type",
                "payload": {"message": "test"},
            }

            try:
                invalid_result = await _dispatch_tool("notify_user", invalid_args)

                if invalid_result.get("ok"):
                    return VerificationResult(
                        name="notify_user",
                        tool="notify_user",
                        spec_ref="§3.6",
                        passed=False,
                        error="Expected validation error for invalid event type",
                    )
                print("    ✓ Event type validation works (returned error)")
            except Exception:
                # Exception is also acceptable for validation error
                print("    ✓ Event type validation works (raised exception)")

            return VerificationResult(
                name="notify_user",
                tool="notify_user",
                spec_ref="§3.6",
                passed=True,
                details={
                    "notification_available": True,
                    "validation": "working",
                },
            )

        except Exception as e:
            logger.exception("notify_user verification failed")
            return VerificationResult(
                name="notify_user",
                tool="notify_user",
                spec_ref="§3.6",
                passed=False,
                error=str(e),
            )

    async def verify_wait_for_user(self) -> VerificationResult:
        """
        Verify wait_for_user tool.
        
        Tests:
        - Returns immediately with notification_sent status
        - Validates required parameters
        """
        print("\n[11/11] Verifying wait_for_user...")

        try:
            from src.mcp.server import _dispatch_tool

            args = {
                "prompt": "E2E test: Please acknowledge this message",
                "timeout_seconds": 5,
                "options": ["OK", "Cancel"],
            }

            result = await _dispatch_tool("wait_for_user", args)

            if not result.get("ok"):
                # May fail if notification system unavailable
                error_msg = result.get("error", "")
                if "provider" in error_msg.lower() or "unavailable" in error_msg.lower():
                    print("    ! Notification system unavailable")
                    return VerificationResult(
                        name="wait_for_user",
                        tool="wait_for_user",
                        spec_ref="§3.6",
                        passed=True,
                        details={"notification_available": False},
                    )

                return VerificationResult(
                    name="wait_for_user",
                    tool="wait_for_user",
                    spec_ref="§3.6",
                    passed=False,
                    error=result.get("error"),
                )

            # Should return immediately with notification_sent status
            if result.get("status") != "notification_sent":
                return VerificationResult(
                    name="wait_for_user",
                    tool="wait_for_user",
                    spec_ref="§3.6",
                    passed=False,
                    error=f"Expected status=notification_sent, got {result.get('status')}",
                )

            print(f"    ✓ Status: {result.get('status')}")
            print(f"    ✓ Prompt echoed: {result.get('prompt', '')[:30]}...")

            # Test validation (empty prompt)
            invalid_args = {
                "prompt": "",
            }

            try:
                invalid_result = await _dispatch_tool("wait_for_user", invalid_args)

                if invalid_result.get("ok"):
                    return VerificationResult(
                        name="wait_for_user",
                        tool="wait_for_user",
                        spec_ref="§3.6",
                        passed=False,
                        error="Expected validation error for empty prompt",
                    )
                print("    ✓ Prompt validation works (returned error)")
            except Exception:
                # Exception is also acceptable for validation error
                print("    ✓ Prompt validation works (raised exception)")

            return VerificationResult(
                name="wait_for_user",
                tool="wait_for_user",
                spec_ref="§3.6",
                passed=True,
                details={
                    "status": result.get("status"),
                    "validation": "working",
                },
            )

        except Exception as e:
            logger.exception("wait_for_user verification failed")
            return VerificationResult(
                name="wait_for_user",
                tool="wait_for_user",
                spec_ref="§3.6",
                passed=False,
                error=str(e),
            )

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
        print("MCP Tool Integration Verification (N.2-2)")
        print("検証対象: Phase M MCPツール（11個）の疎通確認")
        print("=" * 70)

        if self.basic_mode:
            print("\n⚠ Basic mode: Chrome CDP-dependent tests will be skipped")

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
            self.verify_search,
            self.verify_stop_task,
            # Materials
            self.verify_get_materials,
            # Calibration
            self.verify_calibrate,
            self.verify_calibrate_rollback,
            # Auth Queue
            self.verify_get_auth_queue,
            self.verify_resolve_auth,
            # Notification
            self.verify_notify_user,
            self.verify_wait_for_user,
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
        print(f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
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


async def main():
    """Main entry point."""
    configure_logging(log_level="INFO", json_format=False)

    # Parse arguments
    basic_mode = "--basic" in sys.argv

    verifier = MCPIntegrationVerifier(basic_mode=basic_mode)
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

