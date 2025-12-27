#!/usr/bin/env python3
"""Debug script for Chrome auto-start lock flow verification.

This script validates the race condition prevention mechanism for Chrome CDP auto-start.

Usage:
    ./.venv/bin/python tests/scripts/debug_chrome_auto_start_flow.py

What it tests:
1. Lock singleton behavior
2. CDP availability check function
3. Concurrent lock acquisition (simulated)
4. chrome.sh start-worker command availability

Note: This does NOT actually start Chrome - it only validates the lock mechanism.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_lock_singleton() -> bool:
    """Test that the lock is a singleton."""
    print("\n=== Test 1: Lock Singleton ===")
    from src.search.browser_search_provider import _get_chrome_start_lock

    lock1 = _get_chrome_start_lock()
    lock2 = _get_chrome_start_lock()

    if lock1 is lock2:
        print("✓ Lock is singleton (same instance)")
        return True
    else:
        print("✗ Lock is NOT singleton (different instances)")
        return False


async def test_cdp_check_unavailable() -> bool:
    """Test that CDP check returns False for unavailable port."""
    print("\n=== Test 2: CDP Check (Unavailable) ===")
    from src.search.browser_search_provider import _check_cdp_available

    # Use a port that definitely has nothing listening
    result = await _check_cdp_available("localhost", 59999, timeout=1.0)

    if result is False:
        print("✓ CDP check returns False for unavailable port")
        return True
    else:
        print("✗ CDP check should return False for unavailable port")
        return False


async def test_concurrent_lock_acquisition() -> bool:
    """Test that lock serializes concurrent access."""
    print("\n=== Test 3: Concurrent Lock Acquisition ===")
    from src.search.browser_search_provider import _get_chrome_start_lock

    lock = _get_chrome_start_lock()
    execution_log: list[str] = []

    async def worker(worker_id: int) -> None:
        async with lock:
            execution_log.append(f"enter_{worker_id}")
            await asyncio.sleep(0.05)  # Simulate work
            execution_log.append(f"exit_{worker_id}")

    # Run 3 workers concurrently
    await asyncio.gather(worker(0), worker(1), worker(2))

    # Check that enter/exit pairs are contiguous (not interleaved)
    success = True
    for i in range(0, len(execution_log), 2):
        enter_id = execution_log[i].split("_")[1]
        exit_id = execution_log[i + 1].split("_")[1]
        if enter_id != exit_id:
            print(f"✗ Lock did not serialize: {execution_log}")
            success = False
            break

    if success:
        print(f"✓ Lock serialized concurrent access: {execution_log}")
    return success


def test_chrome_sh_start_worker() -> bool:
    """Test that chrome.sh start-worker command is available."""
    print("\n=== Test 4: chrome.sh start-worker Command ===")

    chrome_sh = PROJECT_ROOT / "scripts" / "chrome.sh"
    if not chrome_sh.exists():
        print(f"✗ chrome.sh not found at {chrome_sh}")
        return False

    # Check help output includes start-worker
    result = subprocess.run(
        [str(chrome_sh), "help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if "start-worker" in result.stdout:
        print("✓ chrome.sh help includes 'start-worker' command")
        return True
    else:
        print("✗ chrome.sh help does NOT include 'start-worker' command")
        print(f"  stdout: {result.stdout[:500]}")
        return False


async def main() -> int:
    """Run all tests and report results."""
    print("=" * 60)
    print("Chrome Auto-Start Lock Flow Debug Script")
    print("=" * 60)

    results = []

    # Test 1: Lock singleton
    results.append(("Lock Singleton", await test_lock_singleton()))

    # Test 2: CDP check
    results.append(("CDP Check Unavailable", await test_cdp_check_unavailable()))

    # Test 3: Concurrent lock
    results.append(("Concurrent Lock", await test_concurrent_lock_acquisition()))

    # Test 4: chrome.sh command
    results.append(("chrome.sh start-worker", test_chrome_sh_start_worker()))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed = 0
    failed = 0
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {name}")
        if success:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
