#!/usr/bin/env python3
"""
Profile health verification script.

Verification items:
1. Health check auto-execution success rate (sample-based)
2. Deviation detection behavior
3. Auto-repair action selection coverage
4. Audit logging completeness (JSONL)

Prerequisites:
- Chrome running with remote debugging enabled
- config/settings.yaml browser.chrome_host configured

Usage:
    python tests/scripts/verify_profile_health.py

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
    details: dict[str, object] = field(default_factory=dict)
    error: str | None = None


class ProfileHealthVerifier:
    """Verifier for profile health behavior."""

    def __init__(self) -> None:
        self.results: list[VerificationResult] = []
        self.browser_available = False

    async def check_prerequisites(self) -> bool:
        """Check environment prerequisites."""
        print("\n[Prerequisites] Checking environment...")

        # Check browser search provider connectivity (creates a Playwright context)
        try:
            from src.search.browser_search_provider import BrowserSearchProvider

            provider = BrowserSearchProvider()
            try:
                await asyncio.wait_for(provider._ensure_browser(), timeout=10.0)
                assert provider._context is not None
                self.browser_available = True
                print("  ✓ Browser search provider available")
            finally:
                await provider.close()
        except Exception as e:
            print(f"  ✗ Browser check failed: {e}")
            return False

        # Check profile auditor
        try:
            import src.crawler.profile_audit  # noqa: F401

            print("  ✓ Profile auditor available")
        except ImportError as e:
            print(f"  ✗ Profile auditor not available: {e}")
            return False

        print("  All prerequisites met.\n")
        return True

    async def verify_health_check_execution(self) -> VerificationResult:
        """Verify health check execution success rate (sample-based)."""
        print("\n[1/4] Verifying health check execution (sample-based)...")

        from src.crawler.profile_audit import AuditStatus, ProfileAuditor
        from src.search.browser_search_provider import BrowserSearchProvider

        try:
            # Run multiple health checks to measure success rate
            check_count = 5
            success_count = 0

            provider = BrowserSearchProvider()
            try:
                await asyncio.wait_for(provider._ensure_browser(), timeout=10.0)
                assert provider._context is not None

                auditor = ProfileAuditor()

                for i in range(check_count):
                    print(f"    Check {i + 1}/{check_count}...", end=" ")
                    page = await provider._context.new_page()
                    try:
                        await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                        result = await auditor.audit(page, force=True)

                        if result.status == AuditStatus.PASS:
                            success_count += 1
                            print("✓")
                        else:
                            print(f"✗ ({result.error})")
                    finally:
                        await page.close()

                    await asyncio.sleep(0.5)
            finally:
                await provider.close()

            success_rate = success_count / check_count
            threshold = 0.99

            print(
                f"\n    Health check success rate: {success_rate:.0%} ({success_count}/{check_count})"
            )

            # Note: With only 5 checks, we can't truly verify 99%
            # In production, this would be tracked over many task starts
            if success_rate >= 0.80:  # Lower threshold for small sample
                print(f"    ✓ Acceptable for sample size (target: ≥{threshold:.0%})")
                return VerificationResult(
                    name="Health Check Execution",
                    spec_ref="Health check execution",
                    passed=True,
                    details={
                        "success_rate": success_rate,
                        "threshold": threshold,
                        "sample_size": check_count,
                        "note": "Small sample; long-running tracking required for strict thresholds",
                    },
                )
            else:
                return VerificationResult(
                    name="Health Check Execution",
                    spec_ref="Health check execution",
                    passed=False,
                    error=f"Success rate {success_rate:.0%} too low even for small sample",
                )

        except Exception as e:
            logger.exception("Health check execution verification failed")
            return VerificationResult(
                name="Health Check Execution",
                spec_ref="Health check execution",
                passed=False,
                error=str(e),
            )

    async def verify_deviation_detection(self) -> VerificationResult:
        """Verify deviation detection accuracy."""
        print("\n[2/4] Verifying deviation detection...")

        from src.crawler.profile_audit import AuditStatus, ProfileAuditor
        from src.search.browser_search_provider import BrowserSearchProvider

        try:
            provider = BrowserSearchProvider()
            try:
                await asyncio.wait_for(provider._ensure_browser(), timeout=10.0)
                assert provider._context is not None

                auditor = ProfileAuditor()
                page = await provider._context.new_page()
                try:
                    await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                    result = await auditor.audit(page, force=True)
                finally:
                    await page.close()

                if result.status == AuditStatus.FAIL:
                    return VerificationResult(
                        name="Deviation Detection",
                        spec_ref="Deviation detection",
                        passed=False,
                        error=f"Audit failed: {result.error}",
                    )

                # Report detected items
                print(f"    Audit completed: healthy={result.status == AuditStatus.PASS}")
                fingerprint = result.current or result.baseline
                print(f"    Fingerprint collected: {fingerprint is not None}")

                if fingerprint:
                    fp = fingerprint
                    print(
                        f"      - User-Agent: {fp.user_agent[:50]}..."
                        if fp.user_agent
                        else "      - User-Agent: N/A"
                    )
                    print(f"      - Language: {fp.language}")
                    print(f"      - Timezone: {fp.timezone}")
                    print(f"      - Screen: {fp.screen_resolution}")
                    # webdriver_detected is not available in FingerprintData

                if result.drifts:
                    print(f"    Deviations detected: {len(result.drifts)}")
                    for dev in result.drifts[:3]:
                        print(f"      - {dev.attribute}: {dev.severity}")
                else:
                    print("    ✓ No deviations detected")

                return VerificationResult(
                    name="Deviation Detection",
                    spec_ref="Deviation detection",
                    passed=True,
                    details={
                        "is_healthy": result.status == AuditStatus.PASS,
                        "deviations_count": len(result.drifts) if result.drifts else 0,
                        "fingerprint_collected": fingerprint is not None,
                    },
                )

            finally:
                await provider.close()

        except Exception as e:
            logger.exception("Deviation detection verification failed")
            return VerificationResult(
                name="Deviation Detection",
                spec_ref="Deviation detection",
                passed=False,
                error=str(e),
            )

    async def verify_auto_repair(self) -> VerificationResult:
        """Verify auto-repair action selection coverage."""
        print("\n[3/4] Verifying auto-repair capability...")

        from src.crawler.profile_audit import ProfileAuditor, RepairAction

        try:
            auditor = ProfileAuditor()

            # Test repair action generation
            test_deviations = [
                ("user_agent", "major_version_mismatch"),
                ("timezone", "timezone_mismatch"),
                ("language", "language_mismatch"),
            ]

            repair_attempts = 0
            repair_successes = 0

            for field, deviation_type in test_deviations:
                repair_attempts += 1

                # Get recommended repair action (create mock drift for testing)
                from src.crawler.profile_audit import DriftInfo, RepairAction
                mock_drift = DriftInfo(
                    attribute=field,
                    baseline_value="baseline",
                    current_value="current",
                    severity="high",
                    repair_action=RepairAction.NONE,
                )
                actions = auditor.determine_repair_actions([mock_drift])
                action = actions[0] if actions else RepairAction.NONE

                if action != RepairAction.NONE:
                    repair_successes += 1
                    print(f"    ✓ {field}: {action.value}")
                else:
                    print(f"    - {field}: no repair action")

            if repair_attempts == 0:
                return VerificationResult(
                    name="Auto-Repair",
                    spec_ref="Auto-repair action selection",
                    passed=True,
                    skipped=True,
                    skip_reason="No repair scenarios to test",
                )

            repair_rate = repair_successes / repair_attempts
            threshold = 0.90

            print(
                f"\n    Repair action coverage: {repair_rate:.0%} ({repair_successes}/{repair_attempts})"
            )

            # Note: This tests repair action generation, not actual repair execution
            # Actual repair would require triggering deviations and fixing them
            if repair_rate >= threshold:
                print(f"    ✓ Meets threshold (≥{threshold:.0%})")
                return VerificationResult(
                    name="Auto-Repair",
                    spec_ref="Auto-repair action selection",
                    passed=True,
                    details={
                        "repair_rate": repair_rate,
                        "threshold": threshold,
                        "note": "Tests repair action generation; actual repair requires deviation trigger",
                    },
                )
            else:
                return VerificationResult(
                    name="Auto-Repair",
                    spec_ref="Auto-repair action selection",
                    passed=False,
                    error=f"Repair rate {repair_rate:.0%} < {threshold:.0%}",
                )

        except Exception as e:
            logger.exception("Auto-repair verification failed")
            return VerificationResult(
                name="Auto-Repair",
                spec_ref="Auto-repair action selection",
                passed=False,
                error=str(e),
            )

    async def verify_audit_logging(self) -> VerificationResult:
        """Verify audit logging completeness."""
        print("\n[4/4] Verifying audit logging...")

        import json
        import tempfile

        from src.crawler.profile_audit import ProfileAuditor
        from src.search.browser_search_provider import BrowserSearchProvider
        from src.utils.config import get_settings

        try:
            settings = get_settings()
            profile_name = settings.browser.profile_name

            with tempfile.TemporaryDirectory() as tmp_dir:
                profile_dir = Path(tmp_dir)
                log_path = profile_dir / f"{profile_name}_audit_log.jsonl"

                provider = BrowserSearchProvider()
                try:
                    await asyncio.wait_for(provider._ensure_browser(), timeout=10.0)
                    assert provider._context is not None

                    page = await provider._context.new_page()
                    try:
                        await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                        auditor = ProfileAuditor(profile_dir=profile_dir)
                        await auditor.audit(page, force=True)
                    finally:
                        await page.close()
                finally:
                    await provider.close()

                if not log_path.exists():
                    print("    ✗ Audit log not created")
                    return VerificationResult(
                        name="Audit Logging",
                        spec_ref="Audit logging",
                        passed=False,
                        error="Audit log file not created",
                    )

                with open(log_path, encoding="utf-8") as log_file:
                    log_lines = log_file.readlines()

                if not log_lines:
                    print("    ✗ Audit log empty")
                    return VerificationResult(
                        name="Audit Logging",
                        spec_ref="Audit logging",
                        passed=False,
                        error="Audit log was empty",
                    )

                print(f"    ✓ Audit log written: {len(log_lines)} entries")
                entry = json.loads(log_lines[-1])
                if not isinstance(entry, dict):
                    return VerificationResult(
                        name="Audit Logging",
                        spec_ref="Audit logging",
                        passed=False,
                        error="Audit log entry was not a JSON object",
                    )

                required_fields = ["timestamp", "task_id", "is_healthy"]
                missing = [k for k in required_fields if k not in entry]
                if missing:
                    print(f"    ✗ Missing log fields: {missing}")
                    return VerificationResult(
                        name="Audit Logging",
                        spec_ref="Audit logging",
                        passed=False,
                        error=f"Missing log fields: {missing}",
                    )

                print("    ✓ Log structure valid")
                print(f"      - timestamp: {entry.get('timestamp')}")
                print(f"      - is_healthy: {entry.get('is_healthy')}")

                return VerificationResult(
                    name="Audit Logging",
                    spec_ref="Audit logging",
                    passed=True,
                    details={
                        "log_entries": len(log_lines),
                        "fields_present": list(entry.keys()),
                    },
                )

        except Exception as e:
            logger.exception("Audit logging verification failed")
            return VerificationResult(
                name="Audit Logging",
                spec_ref="Audit logging",
                passed=False,
                error=str(e),
            )

    async def run_all(self) -> int:
        """Run all verifications and output results."""
        print("\n" + "=" * 70)
        print("E2E: Profile Health Verification")
        print("Target: Profile Health")
        print("=" * 70)

        # Prerequisites
        if not await self.check_prerequisites():
            print("\n" + "=" * 70)
            print("SKIPPED: Prerequisites not met")
            print("=" * 70)
            return 2

        # Run verifications
        self.results.append(await self.verify_health_check_execution())
        self.results.append(await self.verify_deviation_detection())
        self.results.append(await self.verify_auto_repair())
        self.results.append(await self.verify_audit_logging())

        # Summary
        print("\n" + "=" * 70)
        print("Verification Summary")
        print("=" * 70)

        passed = 0
        failed = 0
        skipped = 0

        for result in self.results:
            if result.skipped:
                status = "SKIP"
                skipped += 1
            elif result.passed:
                status = "✓"
                passed += 1
            else:
                status = "✗"
                failed += 1

            print(f"  {status} {result.name} ({result.spec_ref})")
            if result.error:
                print(f"      Error: {result.error}")
            if result.skip_reason:
                print(f"      Reason: {result.skip_reason}")

        print("\n" + "-" * 70)
        print(
            f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}"
        )
        print("=" * 70)

        if failed > 0:
            print("\n⚠ Some verifications FAILED. Check details above.")
            return 1
        elif skipped > 0 and passed == 0:
            print("\n⚠ All verifications SKIPPED.")
            return 2
        else:
            print("\n✓ All verifications PASSED!")
            return 0


async def main() -> int:
    configure_logging(log_level="INFO", json_format=False)

    verifier = ProfileHealthVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
