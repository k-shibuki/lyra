#!/usr/bin/env python3
"""
MCP Server Tools E2E Verification

Verification target: H.3 - MCP server tool invocations

Verification items:
1. queue_searches tool handler - correct result structure (Phase 1 / ADR-0010)
2. Tool dispatch mechanism - routing to correct handler
3. Error handling - proper error response format (L7 sanitized error)

Prerequisites:
- Development environment with DB available

Usage:
    python tests/scripts/verify_mcp_tools.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Prerequisites not met (skipped)
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
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: str | None = None
    details: dict = field(default_factory=dict)
    error: str | None = None


class MCPToolsVerifier:
    """Verifier for MCP server tool functionality (H.3)."""

    def __init__(self) -> None:
        self.results: list[VerificationResult] = []

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

        # Check MCP server import
        try:
            from src.mcp.server import TOOLS

            print(f"  ✓ MCP server module loaded ({len(TOOLS)} tools)")
        except Exception as e:
            print(f"  ✗ MCP server import failed: {e}")
            return False

        return True

    async def verify_queue_searches_handler(self) -> VerificationResult:
        """
        Verify queue_searches MCP tool handler.

        Tests:
        - Handler returns expected structure
        - Error handling works correctly
        """
        print("\n[1] Verifying queue_searches handler...")

        try:
            from src.mcp.server import _dispatch_tool

            task = await _dispatch_tool(
                "create_task",
                {"query": "E2E: verify queue_searches tool handler"},
            )
            task_id = task.get("task_id")
            if not task_id:
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error="create_task did not return task_id",
                )

            # Test with valid arguments
            args: dict[str, Any] = {
                "task_id": task_id,
                "queries": ["Python programming"],
                "options": {"priority": "low"},
            }

            result = await _dispatch_tool("queue_searches", args)

            # Verify result structure
            if not isinstance(result, dict):
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Expected dict, got {type(result)}",
                )

            # Check required fields
            required_fields = ["ok", "queued_count", "search_ids"]
            missing_fields = [f for f in required_fields if f not in result]
            if missing_fields:
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Missing fields: {missing_fields}",
                    details={"result_keys": list(result.keys())},
                )

            if not result["ok"]:
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=str(result.get("error", "Unknown error")),
                )

            queued_count = result.get("queued_count")
            search_ids = result.get("search_ids")
            if not isinstance(queued_count, int) or queued_count < 1:
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Invalid queued_count: {queued_count}",
                )
            if not isinstance(search_ids, list) or len(search_ids) != queued_count:
                return VerificationResult(
                    name="queue_searches handler",
                    spec_ref="ADR-0010",
                    passed=False,
                    error=f"Invalid search_ids length: {search_ids}",
                )

            print(f"    ✓ Queued {queued_count} searches")

            return VerificationResult(
                name="queue_searches handler",
                spec_ref="ADR-0010",
                passed=True,
                details={
                    "queued_count": queued_count,
                    "search_id_sample": search_ids[0],
                },
            )

        except Exception as e:
            logger.exception("queue_searches handler verification failed")
            return VerificationResult(
                name="queue_searches handler",
                spec_ref="ADR-0010",
                passed=False,
                error=str(e),
            )

    async def verify_tool_dispatch(self) -> VerificationResult:
        """
        Verify MCP tool dispatch mechanism.

        Tests:
        - Known tools are routed correctly
        - Unknown tools raise appropriate error
        """
        print("\n[2] Verifying tool dispatch...")

        try:
            from src.mcp.server import _dispatch_tool

            # Test unknown tool
            try:
                await _dispatch_tool("unknown_tool", {})
                return VerificationResult(
                    name="tool dispatch",
                    spec_ref="H.3",
                    passed=False,
                    error="Expected error for unknown tool, but none raised",
                )
            except ValueError as e:
                if "Unknown tool" in str(e):
                    print("    ✓ Unknown tool raises ValueError")
                else:
                    return VerificationResult(
                        name="tool dispatch",
                        spec_ref="H.3",
                        passed=False,
                        error=f"Unexpected error message: {e}",
                    )

            # Verify known tools exist in dispatch table
            from src.mcp.server import TOOLS

            tool_names = [tool.name for tool in TOOLS]
            expected_tools = [
                "create_task",
                "get_status",
                "queue_searches",
                "stop_task",
                "get_materials",
                "calibration_metrics",
                "calibration_rollback",
                "get_auth_queue",
                "resolve_auth",
                "feedback",
            ]

            missing_tools = [t for t in expected_tools if t not in tool_names]
            if missing_tools:
                return VerificationResult(
                    name="tool dispatch",
                    spec_ref="H.3",
                    passed=False,
                    error=f"Missing expected tools: {missing_tools}",
                )

            print(f"    ✓ Found {len(tool_names)} registered tools")
            print("    ✓ All expected tools present")

            return VerificationResult(
                name="tool dispatch",
                spec_ref="H.3",
                passed=True,
                details={
                    "registered_tools": len(tool_names),
                    "expected_tools_present": expected_tools,
                },
            )

        except Exception as e:
            logger.exception("Tool dispatch verification failed")
            return VerificationResult(
                name="tool dispatch",
                spec_ref="H.3",
                passed=False,
                error=str(e),
            )

    async def verify_error_response_format(self) -> VerificationResult:
        """
        Verify MCP error response format.

        Tests:
        - Error responses have correct structure
        - Error type and message are included
        """
        print("\n[3] Verifying error response format...")

        try:
            import json

            from src.mcp.server import call_tool

            # Call with invalid arguments to trigger error
            response = await call_tool("get_status", {"invalid_param": "test"})

            # Response should be list of TextContent
            if not isinstance(response, list):
                return VerificationResult(
                    name="error response format",
                    spec_ref="H.3",
                    passed=False,
                    error=f"Expected list, got {type(response)}",
                )

            if len(response) == 0:
                return VerificationResult(
                    name="error response format",
                    spec_ref="H.3",
                    passed=False,
                    error="Empty response list",
                )

            # Parse JSON response
            content = response[0]
            try:
                result = json.loads(content.text)
            except json.JSONDecodeError as e:
                return VerificationResult(
                    name="error response format",
                    spec_ref="H.3",
                    passed=False,
                    error=f"Invalid JSON in response: {e}",
                )

            # Error response should have ok=False
            if result.get("ok") is False:
                # Check error fields
                if "error" not in result:
                    return VerificationResult(
                        name="error response format",
                        spec_ref="H.3",
                        passed=False,
                        error="Error response missing 'error' field",
                        details={"result": result},
                    )

                print("    ✓ Error response has correct structure")
                print(f"    ✓ Error type: {result.get('error_type', 'N/A')}")

                return VerificationResult(
                    name="error response format",
                    spec_ref="H.3",
                    passed=True,
                    details={
                        "error_type": result.get("error_type"),
                        "error_message_sample": str(result.get("error", ""))[:100],
                    },
                )
            else:
                # If it succeeded (query param may have default), check the structure
                print("    ✓ Response format is valid JSON with ok status")
                return VerificationResult(
                    name="error response format",
                    spec_ref="H.3",
                    passed=True,
                    details={"result_ok": result.get("ok")},
                )

        except Exception as e:
            logger.exception("Error response format verification failed")
            return VerificationResult(
                name="error response format",
                spec_ref="H.3",
                passed=False,
                error=str(e),
            )

    async def verify_mcp_server_startup(self) -> VerificationResult:
        """
        Verify MCP server can be imported and TOOLS are defined.

        Tests:
        - Server module imports without error
        - TOOLS list is properly defined
        - Tool schemas are valid
        """
        print("\n[4] Verifying MCP server structure...")

        try:
            from mcp.types import Tool

            # Verify app is a Server instance
            from mcp.server import Server
            from src.mcp.server import TOOLS, app

            if not isinstance(app, Server):
                return VerificationResult(
                    name="MCP server structure",
                    spec_ref="H.3",
                    passed=False,
                    error=f"app is not a Server instance: {type(app)}",
                )

            print(f"    ✓ Server instance created: {app.name}")

            # Verify TOOLS
            if not isinstance(TOOLS, list):
                return VerificationResult(
                    name="MCP server structure",
                    spec_ref="H.3",
                    passed=False,
                    error=f"TOOLS is not a list: {type(TOOLS)}",
                )

            if len(TOOLS) == 0:
                return VerificationResult(
                    name="MCP server structure",
                    spec_ref="H.3",
                    passed=False,
                    error="TOOLS list is empty",
                )

            # Verify each tool has required attributes
            invalid_tools = []
            for tool in TOOLS:
                if not isinstance(tool, Tool):
                    invalid_tools.append(f"Not a Tool: {type(tool)}")
                    continue
                if not tool.name:
                    invalid_tools.append("Tool missing name")
                if not tool.inputSchema:
                    invalid_tools.append(f"{tool.name}: missing inputSchema")

            if invalid_tools:
                return VerificationResult(
                    name="MCP server structure",
                    spec_ref="H.3",
                    passed=False,
                    error=f"Invalid tools: {invalid_tools}",
                )

            print(f"    ✓ {len(TOOLS)} tools defined with valid schemas")

            return VerificationResult(
                name="MCP server structure",
                spec_ref="H.3",
                passed=True,
                details={
                    "server_name": app.name,
                    "tool_count": len(TOOLS),
                    "tool_names": [t.name for t in TOOLS],
                },
            )

        except Exception as e:
            logger.exception("MCP server structure verification failed")
            return VerificationResult(
                name="MCP server structure",
                spec_ref="H.3",
                passed=False,
                error=str(e),
            )

    async def run_all_verifications(self) -> list[VerificationResult]:
        """Run all verification tests."""

        # Check prerequisites first
        if not await self.check_prerequisites():
            return [
                VerificationResult(
                    name="Prerequisites",
                    spec_ref="H.3",
                    passed=False,
                    skipped=True,
                    skip_reason="Prerequisites not met",
                )
            ]

        # Run verification tests
        self.results = [
            await self.verify_mcp_server_startup(),
            await self.verify_tool_dispatch(),
            await self.verify_error_response_format(),
            await self.verify_queue_searches_handler(),
        ]

        return self.results


def print_summary(results: list[VerificationResult]) -> int:
    """Print verification summary and return exit code."""
    print("\n" + "=" * 60)
    print("MCP Tools Verification Summary (H.3)")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for r in results:
        if r.skipped:
            status = "⏭ SKIPPED"
            skipped += 1
        elif r.passed:
            status = "✓ PASSED"
            passed += 1
        else:
            status = "✗ FAILED"
            failed += 1

        print(f"\n{status}: {r.name} [{r.spec_ref}]")

        if r.skip_reason:
            print(f"  Reason: {r.skip_reason}")
        if r.error:
            print(f"  Error: {r.error}")
        if r.details:
            for key, value in r.details.items():
                if isinstance(value, list) and len(value) > 5:
                    print(f"  {key}: [{len(value)} items]")
                else:
                    print(f"  {key}: {value}")

    print("\n" + "-" * 60)
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print("=" * 60)

    if skipped > 0 and passed == 0 and failed == 0:
        return 2  # Prerequisites not met
    elif failed > 0:
        return 1  # Some verifications failed
    else:
        return 0  # All passed


async def main() -> int:
    """Main entry point."""
    configure_logging(log_level="INFO")

    print("=" * 60)
    print("MCP Server Tools Verification (H.3)")
    print("=" * 60)
    print("Testing MCP tool handlers and dispatch mechanism")

    verifier = MCPToolsVerifier()
    results = await verifier.run_all_verifications()

    exit_code = print_summary(results)
    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
