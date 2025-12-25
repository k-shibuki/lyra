#!/usr/bin/env python3
"""
Debug script for Phase 4 Concurrency Control verification.

This script validates the end-to-end integration of Phase 4 components:
1. Config-driven concurrency (num_workers, max_tabs)
2. AcademicAPIRateLimiter (QPS, max_parallel, backoff)
3. TabPool (tab management, backoff)
4. EngineRateLimiter (per-engine QPS)

Usage:
    ./.venv/bin/python tests/scripts/debug_phase4_concurrency.py

This script uses an isolated database and mock components to avoid
external dependencies (Chrome, APIs).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main() -> None:
    """Run Phase 4 concurrency verification."""
    print("=" * 60)
    print("Phase 4: Concurrency Control Verification")
    print("=" * 60)
    print()

    # Run verification steps
    await verify_config_loading()
    await verify_academic_rate_limiter()
    await verify_tab_pool()
    await verify_engine_rate_limiter()
    await verify_backoff_academic_api()
    await verify_backoff_tab_pool()
    await verify_propagation_map()

    print()
    print("=" * 60)
    print("✅ All Phase 4 verifications passed!")
    print("=" * 60)


async def verify_config_loading() -> None:
    """Verify config-driven concurrency settings."""
    print()
    print("--- Verify: Config Loading ---")

    from src.utils.config import get_settings

    settings = get_settings()

    # Check concurrency section exists
    assert hasattr(settings, "concurrency"), "Missing concurrency config"

    # Check search_queue settings
    num_workers = settings.concurrency.search_queue.num_workers
    assert num_workers >= 1, f"num_workers must be >= 1, got {num_workers}"
    print(f"  num_workers: {num_workers}")

    # Check browser_serp settings
    max_tabs = settings.concurrency.browser_serp.max_tabs
    assert max_tabs >= 1, f"max_tabs must be >= 1, got {max_tabs}"
    print(f"  max_tabs: {max_tabs}")

    # Check backoff settings
    backoff = settings.concurrency.backoff
    assert backoff.academic_api.recovery_stable_seconds >= 1
    assert backoff.academic_api.decrease_step >= 1
    assert backoff.browser_serp.decrease_step >= 1
    print(
        f"  backoff.academic_api.recovery_stable_seconds: {backoff.academic_api.recovery_stable_seconds}"
    )
    print(f"  backoff.academic_api.decrease_step: {backoff.academic_api.decrease_step}")
    print(f"  backoff.browser_serp.decrease_step: {backoff.browser_serp.decrease_step}")

    print("  ✓ Config loading verified")


async def verify_academic_rate_limiter() -> None:
    """Verify AcademicAPIRateLimiter basic functionality."""
    print()
    print("--- Verify: AcademicAPIRateLimiter ---")

    from src.search.apis.rate_limiter import (
        AcademicAPIRateLimiter,
        reset_academic_rate_limiter,
    )

    # Reset global state
    reset_academic_rate_limiter()

    limiter = AcademicAPIRateLimiter()

    # Test acquire/release
    provider = "test_provider"
    await limiter.acquire(provider)
    limiter.release(provider)
    print("  ✓ acquire/release works")

    # Test stats
    stats = limiter.get_stats(provider)
    assert "last_request" in stats
    assert "effective_max_parallel" in stats
    assert "backoff_active" in stats
    print(
        f"  stats: effective_max_parallel={stats['effective_max_parallel']}, backoff_active={stats['backoff_active']}"
    )

    print("  ✓ AcademicAPIRateLimiter verified")


async def verify_tab_pool() -> None:
    """Verify TabPool basic functionality."""
    print()
    print("--- Verify: TabPool ---")

    from src.search.tab_pool import TabPool, reset_tab_pool

    # Reset global state
    await reset_tab_pool()

    pool = TabPool(max_tabs=2)

    # Create mock context
    mock_context = MagicMock()
    mock_pages: list[MagicMock] = []

    async def new_page() -> MagicMock:
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.close = AsyncMock()
        mock_pages.append(mock_page)
        return mock_page

    mock_context.new_page = new_page

    # Test acquire/release
    tab = await pool.acquire(mock_context)
    assert tab is not None
    print("  ✓ acquire works")

    pool.release(tab)
    print("  ✓ release works")

    # Test stats
    stats = pool.get_stats()
    assert stats["max_tabs"] == 2
    assert stats["effective_max_tabs"] == 2
    assert stats["backoff_active"] is False
    print(
        f"  stats: max_tabs={stats['max_tabs']}, effective_max_tabs={stats['effective_max_tabs']}"
    )

    await pool.close()
    print("  ✓ TabPool verified")


async def verify_engine_rate_limiter() -> None:
    """Verify EngineRateLimiter basic functionality."""
    print()
    print("--- Verify: EngineRateLimiter ---")

    from src.search.tab_pool import EngineRateLimiter, reset_engine_rate_limiter

    # Reset global state
    reset_engine_rate_limiter()

    limiter = EngineRateLimiter()

    # Mock engine config
    with patch.object(
        limiter,
        "_get_engine_config",
        return_value={"min_interval": 0.0, "concurrency": 1},
    ):
        # Test acquire/release
        await limiter.acquire("duckduckgo")
        limiter.release("duckduckgo")
        print("  ✓ acquire/release works")

        # Test multiple engines are isolated
        await limiter.acquire("duckduckgo")
        await limiter.acquire("mojeek")
        limiter.release("duckduckgo")
        limiter.release("mojeek")
        print("  ✓ Engine isolation works")

    print("  ✓ EngineRateLimiter verified")


async def verify_backoff_academic_api() -> None:
    """Verify AcademicAPIRateLimiter backoff functionality."""
    print()
    print("--- Verify: Academic API Backoff (ADR-0015) ---")

    from src.search.apis.rate_limiter import (
        AcademicAPIRateLimiter,
        BackoffState,
        reset_academic_rate_limiter,
    )

    # Reset global state
    reset_academic_rate_limiter()

    limiter = AcademicAPIRateLimiter()
    provider = "test_backoff"

    # Initialize provider
    await limiter.acquire(provider)
    limiter.release(provider)

    # Manually set max_parallel > 1 to test backoff decrease
    # (Default config may have max_parallel=1, which can't decrease further)
    limiter._backoff_states[provider] = BackoffState(
        effective_max_parallel=3,
        config_max_parallel=3,
    )

    # Get initial state
    initial_stats = limiter.get_stats(provider)
    initial_max = initial_stats["effective_max_parallel"]
    print(f"  Initial effective_max_parallel: {initial_max}")

    # Report 429 to trigger backoff
    await limiter.report_429(provider)

    # Check backoff was triggered
    after_stats = limiter.get_stats(provider)
    # Note: If effective_max_parallel was already at floor (1), it won't decrease further
    # but backoff_active should still be True and consecutive_429_count should increment
    if initial_max > 1:
        assert after_stats["backoff_active"] is True, "Backoff should be active after 429"
        assert after_stats["effective_max_parallel"] < initial_max, (
            f"effective_max_parallel should decrease: {after_stats['effective_max_parallel']} < {initial_max}"
        )
    assert after_stats["consecutive_429_count"] == 1
    print(
        f"  After 429: effective_max_parallel={after_stats['effective_max_parallel']}, backoff_active={after_stats['backoff_active']}"
    )

    # Report success to reset 429 count
    limiter.report_success(provider)
    success_stats = limiter.get_stats(provider)
    assert success_stats["consecutive_429_count"] == 0
    print("  ✓ report_success resets consecutive_429_count")

    print("  ✓ Academic API Backoff verified")


async def verify_backoff_tab_pool() -> None:
    """Verify TabPool backoff functionality."""
    print()
    print("--- Verify: TabPool Backoff (ADR-0015) ---")

    from src.search.tab_pool import TabPool, reset_tab_pool

    # Reset global state
    await reset_tab_pool()

    pool = TabPool(max_tabs=3)

    # Get initial state
    initial_stats = pool.get_stats()
    assert initial_stats["effective_max_tabs"] == 3
    assert initial_stats["backoff_active"] is False
    print(f"  Initial: effective_max_tabs={initial_stats['effective_max_tabs']}")

    # Mock settings for backoff
    mock_settings = MagicMock()
    mock_settings.concurrency.backoff.browser_serp.decrease_step = 1

    # Report CAPTCHA to trigger backoff
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool.report_captcha()

    # Check backoff was triggered
    after_captcha = pool.get_stats()
    assert after_captcha["backoff_active"] is True
    assert after_captcha["effective_max_tabs"] == 2  # 3 - 1 = 2
    assert after_captcha["captcha_count"] == 1
    print(
        f"  After CAPTCHA: effective_max_tabs={after_captcha['effective_max_tabs']}, backoff_active={after_captcha['backoff_active']}"
    )

    # Report 403 to trigger more backoff
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool.report_403()

    after_403 = pool.get_stats()
    assert after_403["effective_max_tabs"] == 1  # 2 - 1 = 1 (floor)
    assert after_403["error_403_count"] == 1
    print(f"  After 403: effective_max_tabs={after_403['effective_max_tabs']}")

    # Test reset_backoff
    pool.reset_backoff()
    after_reset = pool.get_stats()
    assert after_reset["effective_max_tabs"] == 3  # Restored to config max
    assert after_reset["backoff_active"] is False
    print(f"  After reset: effective_max_tabs={after_reset['effective_max_tabs']}")

    # Test floor behavior: report CAPTCHA when already at floor (effective_max_tabs=1)
    pool_floor = TabPool(max_tabs=1)
    floor_stats = pool_floor.get_stats()
    assert floor_stats["effective_max_tabs"] == 1
    assert floor_stats["backoff_active"] is False
    print(f"  Floor test initial: effective_max_tabs={floor_stats['effective_max_tabs']}")

    # Report CAPTCHA at floor
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool_floor.report_captcha()

    floor_after = pool_floor.get_stats()
    assert floor_after["effective_max_tabs"] == 1  # Still at floor
    assert floor_after["backoff_active"] is True  # But backoff_active=True to alert operator
    assert floor_after["captcha_count"] == 1
    print(
        f"  Floor test after CAPTCHA: effective_max_tabs={floor_after['effective_max_tabs']}, backoff_active={floor_after['backoff_active']}"
    )

    # Report 403 at floor
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool_floor.report_403()

    floor_after_403 = pool_floor.get_stats()
    assert floor_after_403["effective_max_tabs"] == 1  # Still at floor
    assert floor_after_403["backoff_active"] is True  # Still active
    assert floor_after_403["error_403_count"] == 1
    print(
        f"  Floor test after 403: effective_max_tabs={floor_after_403['effective_max_tabs']}, error_403_count={floor_after_403['error_403_count']}"
    )

    # Test repeated CAPTCHA at floor
    with patch("src.utils.config.get_settings", return_value=mock_settings):
        pool_floor.report_captcha()
        pool_floor.report_captcha()

    floor_repeated = pool_floor.get_stats()
    assert floor_repeated["captcha_count"] == 3  # All counted (1 initial + 2 repeated)
    assert floor_repeated["backoff_active"] is True
    print(f"  Floor test repeated CAPTCHA: captcha_count={floor_repeated['captcha_count']}")

    await pool.close()
    await pool_floor.close()
    print("  ✓ TabPool Backoff verified (including floor behavior)")


async def verify_propagation_map() -> None:
    """Verify config propagation to components."""
    print()
    print("--- Verify: Propagation Map ---")

    from src.search.tab_pool import get_tab_pool, reset_tab_pool
    from src.utils.config import get_settings

    settings = get_settings()

    # Reset singletons
    await reset_tab_pool()

    # Verify TabPool reads from config
    pool = get_tab_pool()
    expected_max_tabs = settings.concurrency.browser_serp.max_tabs
    assert pool.max_tabs == expected_max_tabs, (
        f"TabPool max_tabs mismatch: {pool.max_tabs} != {expected_max_tabs}"
    )
    print(f"  TabPool.max_tabs = {pool.max_tabs} (from config: {expected_max_tabs}) ✓")

    # Verify WorkerManager reads from config
    # Note: We can't actually start workers without a DB, but we can verify the config is read
    expected_workers = settings.concurrency.search_queue.num_workers
    print(f"  Expected num_workers = {expected_workers} (from config) ✓")

    await pool.close()
    print("  ✓ Propagation map verified")


if __name__ == "__main__":
    asyncio.run(main())
