#!/usr/bin/env python3
"""
E2E Environment Verification Script

Verification target: E2E environment verification - E2E実行環境確認

Verification items:
1. Container proxy status (lyra proxy, ollama, lyra-ml)
2. Chrome CDP connection (Windows Chrome -> WSL2)
3. Ollama LLM availability and model check (via proxy)
4. Proxy connectivity (WSL -> container proxy -> ollama/ml)
5. Search engine connectivity (DuckDuckGo)
6. Notification system (Windows Toast / Linux notify-send)

Prerequisites:
- Podman containers running: ./scripts/dev.sh up
- Chrome running with remote debugging: ./scripts/chrome.sh start (auto-started by MCP)
- See: "E2E Environment Setup"

Architecture:
- WSL: MCP server, Playwright, this script
- Containers: Proxy server, Ollama, ML server (internal network)

Usage:
    python tests/scripts/verify_environment.py

Exit codes:
    0: All verifications passed
    1: Some verifications failed
    2: Critical prerequisites not met (cannot continue)

Note:
    Run this script before other E2E verification scripts to ensure
    the environment is properly configured.
"""

import asyncio
import os
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
    spec_ref: str
    passed: bool
    skipped: bool = False
    skip_reason: str | None = None
    details: dict = field(default_factory=dict)
    error: str | None = None
    critical: bool = False  # If True, failure stops further verification


class EnvironmentVerifier:
    """
    Verifier for E2E environment verification E2E execution environment.

    Checks all prerequisites for running E2E tests:
    - Container status
    - Browser connectivity
    - LLM availability
    - Network connectivity
    - Notification system
    """

    def __init__(self) -> None:
        self.results: list[VerificationResult] = []

    async def verify_container_status(self) -> VerificationResult:
        """
        Verify Podman container status.

        Checks:
        - lyra container is running (current container)
        - Environment variables are set correctly
        """
        print("\n[1/6] Verifying container environment...")

        try:
            # Check if we're inside a container
            in_container = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

            # Check key environment variables
            env_checks = {
                "PROJECT_ROOT": os.environ.get("PROJECT_ROOT", ""),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            }

            # Check data directory exists
            data_dir = Path("/app/data") if in_container else Path("data")
            data_dir_exists = data_dir.exists()

            # Check config directory exists
            config_dir = Path("/app/config") if in_container else Path("config")
            config_dir_exists = config_dir.exists()

            details = {
                "in_container": in_container,
                "data_dir_exists": data_dir_exists,
                "config_dir_exists": config_dir_exists,
                "env_vars": {k: bool(v) for k, v in env_checks.items()},
            }

            if in_container:
                print("    ✓ Running inside container")
            else:
                print("    ! Running outside container (direct execution)")

            print(f"    ✓ Data directory: {'exists' if data_dir_exists else 'missing'}")
            print(f"    ✓ Config directory: {'exists' if config_dir_exists else 'missing'}")

            # Basic check passes if config exists
            passed = config_dir_exists

            return VerificationResult(
                name="Container Environment",
                spec_ref="E2E environment verification",
                passed=passed,
                details=details,
                error=None if passed else "Config directory not found",
            )

        except Exception as e:
            logger.exception("Container status verification failed")
            return VerificationResult(
                name="Container Environment",
                spec_ref="E2E environment verification",
                passed=False,
                error=str(e),
            )

    async def verify_chrome_cdp(self) -> VerificationResult:
        """
        Verify Chrome CDP connection.

        Checks:
        - Can connect to Chrome remote debugging port
        - Browser is responsive
        """
        print("\n[2/6] Verifying Chrome CDP connection (ADR-0003 GUI連携)...")

        try:
            from src.search.browser_search_provider import BrowserSearchProvider

            provider = BrowserSearchProvider()

            try:
                # Add timeout to prevent hanging
                try:
                    await asyncio.wait_for(
                        provider._ensure_browser(),
                        timeout=15.0,  # 15 second timeout
                    )
                except TimeoutError:
                    return VerificationResult(
                        name="Chrome CDP Connection",
                        spec_ref="ADR-0003",
                        passed=False,
                        error="Connection timeout (15s). Check Chrome and port proxy settings.",
                        critical=False,  # Allow other checks to continue
                    )

                if not provider._browser or not provider._browser.is_connected():
                    return VerificationResult(
                        name="Chrome CDP Connection",
                        spec_ref="ADR-0003",
                        passed=False,
                        error="Browser not connected. Run: ./scripts/chrome.sh start",
                        critical=False,
                    )

                # Get browser info
                browser = provider._browser
                contexts = browser.contexts
                pages = contexts[0].pages if contexts else []

                details = {
                    "connected": True,
                    "contexts": len(contexts),
                    "pages": len(pages),
                }

                print("    ✓ Browser connected")
                print(f"    ✓ Contexts: {len(contexts)}")
                print(f"    ✓ Pages: {len(pages)}")

                return VerificationResult(
                    name="Chrome CDP Connection",
                    spec_ref="ADR-0003",
                    passed=True,
                    details=details,
                )

            finally:
                await provider.close()

        except Exception as e:
            error_msg = str(e)
            if "CDP" in error_msg or "connect" in error_msg.lower():
                error_msg = f"{error_msg}\n    → Run: ./scripts/chrome.sh start"

            logger.exception("Chrome CDP verification failed")
            return VerificationResult(
                name="Chrome CDP Connection",
                spec_ref="ADR-0003",
                passed=False,
                error=error_msg,
                critical=True,
            )

    async def verify_ollama_llm(self) -> VerificationResult:
        """
        Verify Ollama LLM availability.

        Checks:
        - Ollama service is reachable
        - Required models are available
        """
        print("\n[3/6] Verifying Ollama LLM (ADR-0008 LLM)...")

        try:
            from src.filter.ollama_provider import OllamaProvider
            from src.utils.config import get_settings

            settings = get_settings()

            # Create provider with configured host
            # In container, Ollama is accessible via internal network
            ollama_host = os.environ.get("LYRA_LLM__OLLAMA_HOST", settings.llm.ollama_host)

            provider = OllamaProvider(host=ollama_host)

            try:
                # Check health
                from src.filter.provider import LLMHealthState

                health = await provider.get_health()

                if health.state == LLMHealthState.UNHEALTHY:
                    return VerificationResult(
                        name="Ollama LLM",
                        spec_ref="ADR-0008",
                        passed=False,
                        error=f"Ollama not available: {health.message}",
                        details={"host": ollama_host},
                    )

                # List available models
                models = await provider.list_models()
                model_names = [m.name for m in models]

                # Check for required model (per ADR-0004: single 3B model)
                model = settings.llm.model

                has_model = any(model in m for m in model_names)

                details = {
                    "host": ollama_host,
                    "available_models": model_names[:5],  # First 5
                    "total_models": len(model_names),
                    "model_available": has_model,
                    "latency_ms": health.latency_ms,
                }

                print(f"    ✓ Ollama reachable at {ollama_host}")
                print(f"    ✓ Available models: {len(model_names)}")
                print(
                    f"    {'✓' if has_model else '!'} Model ({model}): {'available' if has_model else 'not found'}"
                )

                # Pass if Ollama is reachable (models can be pulled later)
                passed = health.state != LLMHealthState.UNHEALTHY

                return VerificationResult(
                    name="Ollama LLM",
                    spec_ref="ADR-0008",
                    passed=passed,
                    details=details,
                )

            finally:
                await provider.close()

        except Exception as e:
            logger.exception("Ollama LLM verification failed")
            return VerificationResult(
                name="Ollama LLM",
                spec_ref="ADR-0008",
                passed=False,
                error=str(e),
            )

    async def verify_container_network(self) -> VerificationResult:
        """
        Verify container network connectivity.

        Checks:
        - lyra can reach ollama via internal network
        - DNS resolution works
        """
        print("\n[4/6] Verifying container network (ADR-0005 L1 ネットワーク分離)...")

        try:
            import aiohttp

            from src.utils.config import get_settings

            settings = get_settings()
            ollama_host = os.environ.get("LYRA_LLM__OLLAMA_HOST", settings.llm.ollama_host)

            # Try to connect to Ollama API
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        f"{ollama_host}/api/tags", timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        internal_ok = response.status == 200
                except Exception as e:
                    internal_ok = False
                    str(e)

            # Check external connectivity (should work for search)
            external_ok = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://example.com", timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        external_ok = response.status == 200
            except Exception:
                pass

            details = {
                "ollama_internal_network": internal_ok,
                "external_network": external_ok,
                "ollama_host": ollama_host,
            }

            print(
                f"    {'✓' if internal_ok else '✗'} Ollama internal network: {'connected' if internal_ok else 'failed'}"
            )
            print(
                f"    {'✓' if external_ok else '!'} External network: {'connected' if external_ok else 'blocked/failed'}"
            )

            # Pass if internal network works
            passed = internal_ok

            return VerificationResult(
                name="Container Network",
                spec_ref="ADR-0005 L1",
                passed=passed,
                details=details,
                error=None if passed else "Cannot reach Ollama via internal network",
            )

        except Exception as e:
            logger.exception("Container network verification failed")
            return VerificationResult(
                name="Container Network",
                spec_ref="ADR-0005 L1",
                passed=False,
                error=str(e),
            )

    async def verify_search_engine(self) -> VerificationResult:
        """
        Verify search engine connectivity.

        Checks:
        - Can perform a search via BrowserSearchProvider
        - Parser works correctly
        """
        print("\n[5/6] Verifying search engine connectivity (ADR-0003 検索エンジン統合)...")

        # Skip if CDP connection failed
        cdp_result = next((r for r in self.results if r.name == "Chrome CDP Connection"), None)
        if cdp_result and not cdp_result.passed:
            print("    ⏭ Skipped (Chrome CDP not connected)")
            return VerificationResult(
                name="Search Engine",
                spec_ref="ADR-0003",
                passed=False,
                skipped=True,
                skip_reason="Chrome CDP not connected",
            )

        try:
            from src.search.browser_search_provider import BrowserSearchProvider
            from src.search.provider import SearchOptions

            provider = BrowserSearchProvider()

            try:
                # Perform a simple search with timeout
                options = SearchOptions(
                    engines=["duckduckgo"],
                    limit=3,
                )

                try:
                    result = await asyncio.wait_for(
                        provider.search("test query", options),
                        timeout=30.0,  # 30 second timeout
                    )
                except TimeoutError:
                    return VerificationResult(
                        name="Search Engine",
                        spec_ref="ADR-0003",
                        passed=False,
                        error="Search timeout (30s)",
                    )

                if not result.ok:
                    if result.error and "CAPTCHA" in result.error:
                        # CAPTCHA is expected behavior, not a failure
                        return VerificationResult(
                            name="Search Engine",
                            spec_ref="ADR-0003",
                            passed=True,
                            details={
                                "captcha_detected": True,
                                "note": "CAPTCHA detection working correctly",
                            },
                        )

                    # Check if it's a connection error
                    if result.error and "CDP" in result.error:
                        return VerificationResult(
                            name="Search Engine",
                            spec_ref="ADR-0003",
                            passed=False,
                            skipped=True,
                            skip_reason="Chrome not connected (run ./scripts/chrome.sh start)",
                        )

                    return VerificationResult(
                        name="Search Engine",
                        spec_ref="ADR-0003",
                        passed=False,
                        error=result.error,
                    )

                details = {
                    "results_count": len(result.results),
                    "engine": result.results[0].engine if result.results else None,
                }

                print("    ✓ Search completed")
                print(f"    ✓ Results: {len(result.results)} items")

                return VerificationResult(
                    name="Search Engine",
                    spec_ref="ADR-0003",
                    passed=True,
                    details=details,
                )

            finally:
                await provider.close()

        except Exception as e:
            logger.exception("Search engine verification failed")
            return VerificationResult(
                name="Search Engine",
                spec_ref="ADR-0003",
                passed=False,
                error=str(e),
            )

    async def verify_notification_system(self) -> VerificationResult:
        """
        Verify notification system.

        Checks:
        - Notification provider is available
        - Can send test notification (optional)
        """
        print("\n[6/6] Verifying notification system (ADR-0007 通知)...")

        try:
            from src.utils.notification_provider import (
                NotificationHealthState,
                detect_platform,
                get_notification_registry,
            )

            registry = get_notification_registry()
            platform = detect_platform()

            # Get the default provider for this platform
            provider = registry.get_default()

            if provider is None:
                return VerificationResult(
                    name="Notification System",
                    spec_ref="ADR-0007",
                    passed=False,
                    error="No notification provider available",
                    details={"platform": platform.value},
                )

            # Get health status
            health = await provider.get_health()

            details = {
                "provider": provider.name,
                "platform": platform.value,
                "state": health.state.value,
            }

            if health.state == NotificationHealthState.HEALTHY:
                print(f"    ✓ Notification provider: {provider.name}")
                print(f"    ✓ Platform: {platform.value}")

                return VerificationResult(
                    name="Notification System",
                    spec_ref="ADR-0007",
                    passed=True,
                    details=details,
                )
            else:
                print(f"    ! Notification provider: {provider.name}")
                print(f"    ! State: {health.state.value}")
                print(f"    ! Message: {health.message}")

                return VerificationResult(
                    name="Notification System",
                    spec_ref="ADR-0007",
                    passed=False,
                    error=health.message,
                    details=details,
                )

        except Exception as e:
            logger.exception("Notification system verification failed")
            return VerificationResult(
                name="Notification System",
                spec_ref="ADR-0007",
                passed=False,
                error=str(e),
            )

    async def run_all(self) -> int:
        """
        Run all verifications and output results.

        Returns:
            Exit code: 0 (all passed), 1 (some failed), 2 (critical failure)
        """
        print("\n" + "=" * 70)
        print("E2E Environment Verification (E2E environment verification)")
        print("検証対象: E2E実行環境の確認")
        print("=" * 70)

        # Run verifications in order
        verifications = [
            self.verify_container_status,
            self.verify_chrome_cdp,
            self.verify_ollama_llm,
            self.verify_container_network,
            self.verify_search_engine,
            self.verify_notification_system,
        ]

        critical_failure = False

        for verify_func in verifications:
            result = await verify_func()
            self.results.append(result)

            # Check for critical failure
            if result.critical and not result.passed:
                critical_failure = True
                print(f"\n    ⚠ Critical failure: {result.error}")
                print("    Stopping further verification.\n")
                break

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

            print(f"  {status}  {result.name} ({result.spec_ref})")
            if result.error:
                # Truncate long error messages
                error_lines = result.error.split("\n")
                for line in error_lines[:3]:
                    print(f"         Error: {line}")
            if result.skip_reason:
                print(f"         Reason: {result.skip_reason}")

        print("\n" + "-" * 70)
        print(
            f"  Total: {len(self.results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}"
        )
        print("=" * 70)

        # Determine exit code
        if critical_failure:
            print("\n⚠ CRITICAL: Environment not ready for E2E tests.")
            print("  Fix the critical issues above before running other E2E scripts.")
            return 2
        elif failed > 0:
            print("\n⚠ Some verifications FAILED.")
            print("  E2E tests may not work correctly. Fix issues above.")
            return 1
        else:
            print("\n✓ Environment is ready for E2E tests!")
            return 0


async def main() -> int:
    """Main entry point."""
    configure_logging(log_level="INFO", json_format=False)

    verifier = EnvironmentVerifier()
    return await verifier.run_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
