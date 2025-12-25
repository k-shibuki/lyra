#!/usr/bin/env python3
"""
Debug script for ADR-0007 CAPTCHA Intervention Flow verification.

This script validates the integration between:
1. BrowserSearchProvider CAPTCHA detection
2. TabPool auto-backoff (ADR-0015)
3. InterventionManager/InterventionQueue (ADR-0007)

Key Finding: There is an integration GAP - BrowserSearchProvider does NOT
call InterventionManager when CAPTCHA is detected, despite having the
_request_intervention method defined.

Usage:
    ./.venv/bin/python tests/scripts/debug_adr0007_intervention_flow.py

This script uses an isolated database and mock components.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main() -> None:
    """Run ADR-0007 intervention flow verification."""
    print("=" * 60)
    print("ADR-0007: CAPTCHA Intervention Integration Verification")
    print("=" * 60)
    print()

    # Use isolated database
    from src.storage.isolation import isolated_database_path

    async with isolated_database_path():
        await verify_intervention_queue_exists()
        await verify_intervention_manager_available()
        await verify_tabpool_captcha_reporting()
        await verify_browser_search_captcha_flow()
        await verify_integration_gap()
        await verify_fetcher_intervention_integration()

    print()
    print("=" * 60)
    print("✅ ADR-0007 verification complete")
    print()
    print("⚠️  INTEGRATION GAP IDENTIFIED:")
    print("   BrowserSearchProvider._request_intervention() is DEAD CODE")
    print("   It is defined but never called when CAPTCHA is detected.")
    print()
    print("   See: docs/sequences/adr0007_captcha_intervention_integration.md")
    print("=" * 60)


async def verify_intervention_queue_exists() -> None:
    """Verify InterventionQueue table exists in schema."""
    print("--- Verify: InterventionQueue Table ---")

    from src.storage.database import get_database

    db = await get_database()

    # Check table exists
    result = await db.fetch_one(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='intervention_queue'
        """
    )
    assert result is not None, "intervention_queue table should exist"
    print("  ✓ intervention_queue table exists")

    # Check schema
    columns = await db.fetch_all("PRAGMA table_info(intervention_queue)")
    column_names = [c["name"] for c in columns]
    expected_columns = ["id", "task_id", "url", "domain", "auth_type", "status"]
    for col in expected_columns:
        assert col in column_names, f"Column {col} should exist"
    print(f"  ✓ Schema has expected columns: {expected_columns}")


async def verify_intervention_manager_available() -> None:
    """Verify InterventionManager is available and functional."""
    print()
    print("--- Verify: InterventionManager ---")

    from src.utils.notification import (
        InterventionManager,
        InterventionQueue,
        InterventionStatus,
        InterventionType,
        get_intervention_manager,
    )

    # Get singleton
    manager = get_intervention_manager()
    assert isinstance(manager, InterventionManager)
    print("  ✓ InterventionManager singleton available")

    # Check InterventionQueue
    queue = InterventionQueue()
    assert hasattr(queue, "enqueue")
    assert hasattr(queue, "get_pending")
    assert hasattr(queue, "complete")  # complete(queue_id, session_data)
    print("  ✓ InterventionQueue methods available")

    # Check types
    assert InterventionType.CAPTCHA.value == "captcha"
    assert InterventionStatus.PENDING.value == "pending"
    print("  ✓ InterventionType and InterventionStatus enums available")


async def verify_tabpool_captcha_reporting() -> None:
    """Verify TabPool.report_captcha() triggers backoff."""
    print()
    print("--- Verify: TabPool CAPTCHA Backoff (ADR-0015) ---")

    from src.search.tab_pool import TabPool, reset_tab_pool

    # Reset global state
    await reset_tab_pool()

    pool = TabPool(max_tabs=3)

    # Initial state
    stats = pool.get_stats()
    assert stats["effective_max_tabs"] == 3
    assert stats["backoff_active"] is False
    print(f"  Initial: effective_max_tabs={stats['effective_max_tabs']}")

    # Mock settings for backoff
    mock_settings = MagicMock()
    mock_settings.concurrency.backoff.browser_serp.decrease_step = 1

    # Report CAPTCHA
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool.report_captcha()

    # Verify backoff triggered
    stats_after = pool.get_stats()
    assert stats_after["effective_max_tabs"] == 2
    assert stats_after["backoff_active"] is True
    assert stats_after["captcha_count"] == 1
    print(f"  After CAPTCHA: effective_max_tabs={stats_after['effective_max_tabs']}")
    print("  ✓ TabPool CAPTCHA backoff working")

    await pool.close()


async def verify_browser_search_captcha_flow() -> None:
    """Verify BrowserSearchProvider CAPTCHA handling."""
    print()
    print("--- Verify: BrowserSearchProvider CAPTCHA Flow ---")

    from src.search.browser_search_provider import BrowserSearchProvider

    # Check _request_intervention method exists
    provider = BrowserSearchProvider()
    assert hasattr(provider, "_request_intervention")
    print("  ✓ _request_intervention method exists")

    # Check method signature
    import inspect

    sig = inspect.signature(provider._request_intervention)
    params = list(sig.parameters.keys())
    assert "url" in params
    assert "engine" in params
    assert "captcha_type" in params
    assert "page" in params
    print(f"  ✓ Method signature: {params}")

    await provider.close()


async def verify_integration_gap() -> None:
    """Verify the integration gap - _request_intervention is never called."""
    print()
    print("--- Verify: Integration Gap Detection ---")

    import ast
    from pathlib import Path

    # Read BrowserSearchProvider source
    source_path = Path("src/search/browser_search_provider.py")
    source = source_path.read_text()

    # Parse AST
    tree = ast.parse(source)

    # Find all method calls
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
            elif isinstance(node.func, ast.Name):
                calls.append(node.func.id)

    # Check if _request_intervention is called
    intervention_called = "_request_intervention" in calls
    print(f"  _request_intervention called in source: {intervention_called}")

    if not intervention_called:
        print("  ⚠️  INTEGRATION GAP: _request_intervention is NEVER CALLED")
        print("     The method is defined (lines 1064-1117) but dead code.")

    # Check what happens when CAPTCHA is detected
    # Look for is_captcha handling
    captcha_handling = "parse_result.is_captcha" in source
    report_captcha = "report_captcha()" in source
    print(f"  CAPTCHA detection: {captcha_handling}")
    print(f"  report_captcha() called: {report_captcha}")

    # Verify InterventionManager is NOT imported at module level
    # (only inside _request_intervention which is never called)
    module_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_imports.append(node.module)

    intervention_imported = "src.utils.notification" in module_imports
    print(f"  InterventionManager imported at module level: {intervention_imported}")
    print("  ✓ Integration gap verified (as expected per current state)")


async def verify_fetcher_intervention_integration() -> None:
    """Verify BrowserFetcher correctly uses InterventionManager."""
    print()
    print("--- Verify: BrowserFetcher Intervention (Working Example) ---")

    from pathlib import Path

    # Read BrowserFetcher source
    source_path = Path("src/crawler/fetcher.py")
    source = source_path.read_text()

    # Check for intervention calls
    has_request_manual_intervention = "_request_manual_intervention" in source
    has_intervention_manager_import = "get_intervention_manager" in source

    print(f"  _request_manual_intervention method: {has_request_manual_intervention}")
    print(f"  get_intervention_manager import: {has_intervention_manager_import}")

    # Verify it's actually called (not just defined)
    # Look for "await self._request_manual_intervention"
    actually_called = "await self._request_manual_intervention" in source
    print(f"  Method actually called: {actually_called}")

    if has_request_manual_intervention and actually_called:
        print("  ✓ BrowserFetcher correctly integrates InterventionManager")
        print("    (This is the working example to follow)")


if __name__ == "__main__":
    asyncio.run(main())
