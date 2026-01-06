#!/usr/bin/env python3
"""Live test of notification providers across platforms.

This script tests actual notification display on:
- Linux (notify-send via LinuxNotifyProvider)
- Windows (toast via WindowsToastProvider)
- WSL2 (PowerShell bridge via WSLBridgeProvider)

Usage:
    uv run python scripts/test_notification_live.py
"""

import asyncio
import platform


async def detect_platform() -> str:
    """Detect current platform."""
    from src.utils.notification_provider import is_wsl

    system = platform.system()
    if system == "Windows":
        return "windows"
    elif system == "Linux":
        if is_wsl():
            return "wsl2"
        return "linux"
    elif system == "Darwin":
        return "macos"
    return "unknown"


async def test_registry_auto_detection() -> None:
    """Test NotificationProviderRegistry auto-detection."""
    print("Testing NotificationProviderRegistry auto-detection...")

    from src.utils.notification_provider import get_notification_registry

    registry = get_notification_registry()

    default = registry.get_default()
    print(f"  Default provider: {default.name if default else 'None'}")

    all_providers = registry.list_providers()
    print(f"  Registered providers: {all_providers}")


async def test_direct_provider() -> None:
    """Test platform-specific provider directly."""
    from src.utils.notification_provider import (
        LinuxNotifyProvider,
        NotificationOptions,
        WindowsToastProvider,
        WSLBridgeProvider,
    )

    plat = await detect_platform()
    print(f"\nTesting direct provider for platform: {plat}...")

    provider: LinuxNotifyProvider | WSLBridgeProvider | WindowsToastProvider
    if plat == "linux":
        provider = LinuxNotifyProvider()
    elif plat == "wsl2":
        provider = WSLBridgeProvider()
    elif plat == "windows":
        provider = WindowsToastProvider()
    else:
        print(f"  Skipping: unsupported platform {plat}")
        return

    options = NotificationOptions(timeout_seconds=10)
    result = await provider.send(
        title="Lyra: Test Notification",
        message=f"This is a test notification from Lyra.\nPlatform: {plat}\nProvider: {provider.name}",
        options=options,
    )
    print(f"  Result: ok={result.ok}, provider={result.provider}")
    if not result.ok:
        print(f"  Error: {result.error}")


async def test_batch_notification_format() -> None:
    """Test batch notification message format (simulated)."""
    print("\nTesting batch notification format...")

    from src.utils.notification_provider import NotificationOptions, get_notification_registry

    registry = get_notification_registry()
    provider = registry.get_default()

    if not provider:
        print("  No default provider available")
        return

    # Simulate batch notification message (same format as BatchNotificationManager)
    pending_items = [
        {"domain": "duckduckgo.com", "auth_type": "cloudflare"},
        {"domain": "duckduckgo.com", "auth_type": "turnstile"},
        {"domain": "google.com", "auth_type": "recaptcha"},
    ]

    by_domain: dict[str, list[dict]] = {}
    for item in pending_items:
        domain = item.get("domain", "unknown")
        by_domain.setdefault(domain, []).append(item)

    total_count = len(pending_items)
    lines = [f"Authentication required ({total_count} items)", ""]
    for domain, items in by_domain.items():
        types = {i.get("auth_type", "unknown") for i in items}
        lines.append(f"{domain}: {len(items)} items ({', '.join(types)})")
    lines.append("")
    lines.append("After resolving, tell the AI 'CAPTCHA solved'")

    message = "\n".join(lines)
    options = NotificationOptions(timeout_seconds=15)

    result = await provider.send(
        title="Lyra: Auth Pending",
        message=message,
        options=options,
    )
    print(f"  Result: ok={result.ok}")
    print(f"  Message preview:\n    {message.replace(chr(10), chr(10) + '    ')}")


async def test_via_intervention_manager() -> None:
    """Test via InterventionManager (same path as real usage)."""
    print("\nTesting via InterventionManager.send_toast()...")

    from src.utils.intervention_manager import _get_manager

    manager = _get_manager()

    success = await manager.send_toast(
        title="Lyra: E2E Test",
        message="Notification via InterventionManager.\nIf you see this, BatchNotification works correctly.",
        timeout_seconds=10,
    )

    print(f"  Toast sent: {success}")


async def main() -> None:
    """Run all tests."""
    plat = await detect_platform()

    print("=" * 60)
    print("Lyra Notification Live Test")
    print(f"Platform: {plat} ({platform.system()} {platform.release()})")
    print("=" * 60)
    print()

    await test_registry_auto_detection()
    await asyncio.sleep(1)

    await test_direct_provider()
    await asyncio.sleep(2)

    await test_batch_notification_format()
    await asyncio.sleep(2)

    await test_via_intervention_manager()

    print()
    print("=" * 60)
    print("Tests completed. Check if notifications appeared on your desktop.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
