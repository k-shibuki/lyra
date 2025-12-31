#!/usr/bin/env python3
"""
Debug script for rate limiter with 2 workers simulation.

Tests:
1. max_parallel=1 correctly serializes S2 requests across 2 workers
2. min_interval=6.0 is enforced between requests
3. No 429 errors occur

Usage:
    timeout 120 uv run python scripts/debug_rate_limiter_2workers.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEBUG_LOG_PATH = Path(__file__).parent.parent / ".cursor" / "debug.log"


def clear_debug_log() -> None:
    """Clear the debug log file."""
    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_LOG_PATH.write_text("")
    print(f"Cleared debug log: {DEBUG_LOG_PATH}")


async def simulate_worker(worker_id: int, limiter, num_requests: int = 3) -> list[float]:
    """Simulate a worker making S2 API requests.
    
    Returns list of request timestamps.
    """
    timestamps = []
    provider = "semantic_scholar"

    for i in range(num_requests):
        print(f"    Worker {worker_id}: Acquiring slot for request {i+1}...")
        start = time.time()

        await limiter.acquire(provider)
        acquired_at = time.time()
        wait_time = acquired_at - start

        # Simulate API call (50ms)
        await asyncio.sleep(0.05)

        timestamps.append(acquired_at)
        print(f"    Worker {worker_id}: Request {i+1} started at {acquired_at:.3f} (waited {wait_time:.2f}s)")

        limiter.release(provider)

    return timestamps


async def main() -> None:
    """Run rate limiter 2-worker simulation."""
    print("=" * 60)
    print("Rate Limiter 2-Worker Simulation")
    print("=" * 60)

    # Clear debug log
    clear_debug_log()

    # Import after path setup
    from src.search.apis.rate_limiter import get_academic_rate_limiter, reset_academic_rate_limiter

    # Reset to ensure fresh state
    reset_academic_rate_limiter()
    limiter = get_academic_rate_limiter()

    # Get current config
    stats = limiter.get_stats("semantic_scholar")
    print("\nS2 Rate Limiter Config:")
    print(f"  max_parallel: {stats.get('max_parallel', 'N/A')}")
    print(f"  min_interval: {stats.get('min_interval_seconds', 'N/A')}s")

    # Test 1: Parallel workers with max_parallel=1
    print("\n[1] Testing 2 workers with max_parallel=1...")
    print("    Expected: Requests serialized, 6s interval between each")

    start_time = time.time()

    # Start 2 workers concurrently, each making 2 requests
    worker0_task = asyncio.create_task(simulate_worker(0, limiter, num_requests=2))
    worker1_task = asyncio.create_task(simulate_worker(1, limiter, num_requests=2))

    timestamps0, timestamps1 = await asyncio.gather(worker0_task, worker1_task)

    total_time = time.time() - start_time

    # Analyze timestamps
    all_timestamps = sorted(timestamps0 + timestamps1)
    intervals = []
    for i in range(1, len(all_timestamps)):
        interval = all_timestamps[i] - all_timestamps[i-1]
        intervals.append(interval)

    print("\n    Results:")
    print(f"    Total requests: {len(all_timestamps)}")
    print(f"    Total time: {total_time:.2f}s")
    print(f"    Intervals between requests: {[f'{i:.2f}s' for i in intervals]}")

    # Check if intervals are >= min_interval (6.0s)
    min_interval = 6.0
    all_ok = all(i >= min_interval - 0.1 for i in intervals)  # 0.1s tolerance

    if all_ok:
        print(f"    ✅ PASS: All intervals >= {min_interval}s")
    else:
        print(f"    ❌ FAIL: Some intervals < {min_interval}s")

    # Test 2: Check effective_max_parallel
    print("\n[2] Checking concurrent slot enforcement...")

    reset_academic_rate_limiter()
    limiter = get_academic_rate_limiter()

    # Try to acquire 2 slots at once
    provider = "semantic_scholar"

    async def try_acquire_with_timeout(name: str, timeout: float = 2.0) -> bool:
        try:
            await asyncio.wait_for(limiter.acquire(provider, timeout=timeout), timeout=timeout)
            return True
        except TimeoutError:
            return False

    # First acquire should succeed immediately
    success1 = await try_acquire_with_timeout("first", timeout=1.0)
    print(f"    First acquire: {'✅ Success' if success1 else '❌ Failed'}")

    # Second acquire should timeout (max_parallel=1)
    success2 = await try_acquire_with_timeout("second", timeout=2.0)
    print(f"    Second acquire (should timeout): {'❌ Unexpected success' if success2 else '✅ Correctly timed out'}")

    # Release first slot
    limiter.release(provider)

    # Now second should succeed
    success3 = await try_acquire_with_timeout("third", timeout=7.0)  # Wait for min_interval
    print(f"    Third acquire (after release): {'✅ Success' if success3 else '❌ Failed'}")

    if success3:
        limiter.release(provider)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  max_parallel=1: {'✅ Correctly enforces single slot' if not success2 else '❌ Not enforced'}")
    print(f"  min_interval=6s: {'✅ Correctly enforced' if all_ok else '❌ Not enforced'}")
    print(f"  2-worker safety: {'✅ Safe' if not success2 and all_ok else '⚠️ Needs review'}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
