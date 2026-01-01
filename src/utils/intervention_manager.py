"""Intervention manager for manual user interventions.

Manages manual intervention flows with safe operation policy.
"""

import asyncio
import platform
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.intervention_types import (
    InterventionResult,
    InterventionStatus,
    InterventionType,
)
from src.utils.logging import get_logger
from src.utils.notification_provider import (
    NotificationOptions,
    NotificationUrgency,
    get_notification_registry,
    is_wsl,
)

logger = get_logger(__name__)


class InterventionManager:
    """Manages manual intervention flows with safe operation policy.

    Safe Operation Policy:
    - Window bring-to-front via OS API only (no DOM operations)
    - No timeout enforcement (user-driven completion)
    - No polling or page content inspection
    - Toast notification for awareness

    CDP Safety:
    - Allowed: Page.bringToFront
    - Forbidden: Runtime.evaluate, DOM.*, Input.*, scrollIntoView, etc.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._pending_interventions: dict[str, dict] = {}
        self._browser_page = None  # Current browser page for intervention
        self._intervention_lock = asyncio.Lock()

    @property
    def cooldown_minutes(self) -> int:
        """Get minimum cooldown period in minutes after timeout."""
        return 60  # Minimum cooldown period in minutes after timeout

    async def request_intervention(
        self,
        intervention_type: InterventionType | str,
        url: str,
        domain: str,
        *,
        message: str | None = None,
        task_id: str | None = None,
        page: Any | None = None,
    ) -> InterventionResult:
        """Request manual intervention with safe operation policy.

        Safe Operation Policy:
        1. Sends toast notification to user
        2. Brings browser window to front via OS API (if page provided)
        3. Returns immediately with PENDING status
        4. User finds and resolves challenge themselves
        5. User calls complete_authentication when done

        NO DOM operations (scroll, highlight, focus) are performed.
        NO timeout is enforced - user-driven completion only.

        Args:
            intervention_type: Type of intervention needed.
            url: URL requiring intervention.
            domain: Domain name.
            message: Message to display.
            task_id: Associated task ID.
            page: Playwright page object for window front-bring (optional).

        Returns:
            InterventionResult with PENDING status (user completes via complete_authentication).
        """
        if isinstance(intervention_type, str):
            try:
                intervention_type = InterventionType(intervention_type)
            except ValueError:
                intervention_type = InterventionType.CAPTCHA

        async with self._intervention_lock:
            intervention_id = f"{domain}_{datetime.now().strftime('%H%M%S%f')}"

            # Log intervention start
            db = await get_database()
            await db.execute(
                """
                INSERT INTO intervention_log
                (task_id, domain, intervention_type, notification_sent_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, domain, intervention_type.value, datetime.now(UTC).isoformat()),
            )

            # Store intervention state (minimal - no timeout, no element_selector)
            intervention_state = {
                "id": intervention_id,
                "type": intervention_type,
                "url": url,
                "domain": domain,
                "started_at": datetime.now(UTC),
                "task_id": task_id,
            }
            self._pending_interventions[intervention_id] = intervention_state

            # Build notification message (no timeout info)
            if message is None:
                message = self._build_intervention_message(intervention_type, url, domain)

            notification_msg = (
                f"{message}\n\n"
                f"URL: {url}\n"
                f"完了後、Cursorで complete_authentication を呼んでください"
            )

            # Step 1: Send toast notification
            title = f"Lyra: {intervention_type.value.upper()}"
            notification_sent = await self.send_toast(
                title,
                notification_msg,
                timeout_seconds=10,
            )

            # Step 2: Bring browser window to front via OS API only
            # No DOM operations (scroll, highlight, focus)
            if page is not None:
                await self._bring_tab_to_front(page)

            logger.info(
                "Intervention requested (safe mode)",
                intervention_id=intervention_id,
                type=intervention_type.value,
                domain=domain,
                notification_sent=notification_sent,
            )

            # Return immediately with PENDING status
            # User will call complete_authentication when done
            return InterventionResult(
                intervention_id=intervention_id,
                status=InterventionStatus.PENDING,
                notes="Awaiting user completion via complete_authentication",
            )

    def _build_intervention_message(
        self,
        intervention_type: InterventionType,
        url: str,
        domain: str,
    ) -> str:
        """Build user-friendly intervention message.

        Args:
            intervention_type: Type of intervention.
            url: Target URL.
            domain: Target domain.

        Returns:
            User-friendly message.
        """
        messages = {
            InterventionType.CAPTCHA: f"CAPTCHAの解決が必要です\nサイト: {domain}",
            InterventionType.LOGIN_REQUIRED: f"ログインが必要です\nサイト: {domain}",
            InterventionType.COOKIE_BANNER: f"Cookie同意が必要です\nサイト: {domain}",
            InterventionType.CLOUDFLARE: f"Cloudflareチャレンジが必要です\nサイト: {domain}",
            InterventionType.TURNSTILE: f"Turnstile認証が必要です\nサイト: {domain}",
            InterventionType.JS_CHALLENGE: f"JavaScript検証が必要です\nサイト: {domain}",
        }
        return messages.get(intervention_type, f"手動操作が必要です\nサイト: {domain}")

    async def _bring_tab_to_front(self, page: Page) -> bool:
        """Bring browser window to front using safe methods.

        Safe Operation Policy:
        - Uses CDP Page.bringToFront (allowed)
        - Uses OS API for window activation (SetForegroundWindow/wmctrl)
        - Does NOT use: Runtime.evaluate, window.focus(), DOM operations

        Args:
            page: Playwright page object.

        Returns:
            True if successful.
        """
        try:
            # Get browser context
            context = page.context

            # Use CDP Page.bringToFront (allowed)
            cdp_session = await context.new_cdp_session(page)
            await cdp_session.send("Page.bringToFront")
            await cdp_session.detach()

            logger.info("Browser tab brought to front via CDP")

            # Also try OS-level window activation for better visibility
            try:
                await self._platform_activate_window()
            except Exception:
                pass  # Best effort

            return True

        except Exception as e:
            logger.warning("CDP bring to front failed", error=str(e))

            # Fallback: Try OS-level window activation only
            try:
                await self._platform_activate_window()
                logger.info("Window activated via OS API fallback")
                return True
            except Exception as e2:
                logger.debug("Platform window activation failed", error=str(e2))

            return False

    async def _platform_activate_window(self) -> None:
        """Platform-specific window activation fallback.

        For WSL2 -> Windows Chrome, uses PowerShell to activate Chrome window.
        """
        system = platform.system()

        # Check for WSL using the provider module's detection
        running_in_wsl = is_wsl()

        if system == "Windows" or running_in_wsl:
            # Activate Chrome window using PowerShell
            ps_script = """
            Add-Type @'
            using System;
            using System.Runtime.InteropServices;
            public class WindowHelper {
                [DllImport("user32.dll")]
                [return: MarshalAs(UnmanagedType.Bool)]
                public static extern bool SetForegroundWindow(IntPtr hWnd);

                [DllImport("user32.dll")]
                public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
            }
'@
            $chromeWindow = Get-Process -Name chrome -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowHandle -ne 0 } |
                Select-Object -First 1
            if ($chromeWindow) {
                [WindowHelper]::SetForegroundWindow($chromeWindow.MainWindowHandle)
            }
            """

            try:
                process = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.wait(), timeout=5.0)
                logger.debug("Chrome window activated via PowerShell")
            except Exception as e:
                logger.debug("PowerShell window activation failed", error=str(e))

    async def send_toast(
        self,
        title: str,
        message: str,
        *,
        timeout_seconds: int = 10,
    ) -> bool:
        """Send a toast notification using the provider abstraction layer.

        Uses NotificationProviderRegistry for platform-specific notifications
        with automatic fallback support.

        Args:
            title: Notification title.
            message: Notification message.
            timeout_seconds: Display duration.

        Returns:
            True if notification was sent successfully.
        """
        try:
            registry = get_notification_registry()
            options = NotificationOptions(
                timeout_seconds=timeout_seconds,
                urgency=NotificationUrgency.CRITICAL,  # Use critical for intervention
                icon="dialog-warning",
                sound=True,
            )
            result = await registry.send(title, message, options)

            if not result.ok:
                logger.warning(
                    "Notification send failed",
                    provider=result.provider,
                    error=result.error,
                )

            return result.ok

        except Exception as e:
            logger.error("Failed to send notification", error=str(e))
            return False

    async def check_intervention_status(
        self,
        intervention_id: str,
    ) -> dict[str, Any]:
        """Check status of a pending intervention.

        No timeout enforcement. User completes via complete_authentication.

        Args:
            intervention_id: Intervention ID.

        Returns:
            Status dict.
        """
        intervention = self._pending_interventions.get(intervention_id)

        if intervention is None:
            return {"status": "unknown", "intervention_id": intervention_id}

        elapsed = (datetime.now(UTC) - intervention["started_at"]).total_seconds()

        # No timeout enforcement
        return {
            "status": "pending",
            "intervention_id": intervention_id,
            "elapsed_seconds": elapsed,
            "note": "Awaiting user completion via complete_authentication",
        }

    async def complete_intervention(
        self,
        intervention_id: str,
        success: bool,
        notes: str | None = None,
    ) -> None:
        """Mark intervention as complete (manual completion).

        Args:
            intervention_id: Intervention ID.
            success: Whether intervention succeeded.
            notes: Optional notes.
        """
        intervention = self._pending_interventions.pop(intervention_id, None)

        if intervention is None:
            logger.warning("Unknown intervention completed", id=intervention_id)
            return

        elapsed = (datetime.now(UTC) - intervention["started_at"]).total_seconds()
        result = "success" if success else "failed"

        # Log completion
        db = await get_database()
        await db.execute(
            """
            UPDATE intervention_log
            SET completed_at = ?, result = ?, duration_seconds = ?, notes = ?
            WHERE domain = ? AND intervention_type = ?
            ORDER BY notification_sent_at DESC
            LIMIT 1
            """,
            (
                datetime.now(UTC).isoformat(),
                result,
                int(elapsed),
                notes,
                intervention["domain"],
                (
                    intervention["type"].value
                    if isinstance(intervention["type"], InterventionType)
                    else intervention["type"]
                ),
            ),
        )

        logger.info(
            "Intervention completed",
            intervention_id=intervention_id,
            success=success,
            duration=elapsed,
        )


# Global manager instance
_manager: InterventionManager | None = None


def _get_manager() -> InterventionManager:
    """Get or create intervention manager."""
    global _manager
    if _manager is None:
        _manager = InterventionManager()
    return _manager


async def notify_user(
    event: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send notification to user per safe operation policy.

    Args:
        event: Event type (captcha, login_required, cookie_banner, cloudflare,
               domain_blocked, etc.).
        payload: Event payload with keys:
            - url: Target URL
            - domain: Domain name
            - message: Custom message (optional)
            - task_id: Associated task ID (optional)
            - page: Playwright page object for window front-bring (optional)
            - reason: Reason for domain_blocked events (optional)

        Note: element_selector and on_success_callback are no longer supported
        (no DOM operations during authentication sessions).

    Returns:
        Notification/intervention result.
    """
    manager = _get_manager()

    intervention_types = {
        "captcha",
        "login_required",
        "cookie_banner",
        "cloudflare",
        "turnstile",
        "js_challenge",
    }

    if event in intervention_types:
        # These require intervention flow (safe mode)
        result = await manager.request_intervention(
            intervention_type=event,
            url=payload.get("url", ""),
            domain=payload.get("domain", "unknown"),
            message=payload.get("message"),
            task_id=payload.get("task_id"),
            page=payload.get("page"),
        )
        return result.to_dict()
    elif event == "domain_blocked":
        # Domain blocked notification - informational, queued for tracking
        domain = payload.get("domain", "unknown")
        reason = payload.get("reason", "Verification failure")
        task_id = payload.get("task_id")

        # Queue to intervention queue for tracking (no user action needed)
        # Import here to avoid circular dependency
        from src.utils.intervention_queue import get_intervention_queue

        queue = get_intervention_queue()
        queue_id = await queue.enqueue(
            task_id=task_id or "",
            url=payload.get("url", f"https://{domain}/"),
            domain=domain,
            auth_type="domain_blocked",
            priority="low",  # Informational, low priority
        )

        # Send toast notification
        message = payload.get("message") or f"Domain {domain} blocked: {reason}"
        sent = await manager.send_toast("Lyra: DOMAIN BLOCKED", message)

        logger.warning(
            "Domain blocked notification sent",
            domain=domain,
            reason=reason,
            task_id=task_id,
            queue_id=queue_id,
        )

        return {
            "shown": sent,
            "event": event,
            "domain": domain,
            "reason": reason,
            "queue_id": queue_id,
        }
    else:
        # Simple notification (no intervention flow)
        title = f"Lyra: {event.upper()}"
        message = payload.get("message", "")

        sent = await manager.send_toast(title, message)

        return {
            "shown": sent,
            "event": event,
        }


async def notify_domain_blocked(
    domain: str,
    reason: str,
    task_id: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Convenience function to notify that a domain has been blocked.

    Called when SourceVerifier demotes a domain to BLOCKED.
    This informs the MCP client that the domain will be excluded from future results.

    Args:
        domain: Domain name that was blocked.
        reason: Reason for blocking (e.g., "High rejection rate (75%)").
        task_id: Associated task ID (optional).
        url: URL that triggered the block (optional).

    Returns:
        Notification result dict with queue_id.
    """
    return await notify_user(
        event="domain_blocked",
        payload={
            "domain": domain,
            "reason": reason,
            "task_id": task_id,
            "url": url or f"https://{domain}/",
        },
    )


async def check_intervention_status(intervention_id: str) -> dict[str, Any]:
    """Check status of a pending intervention.

    Args:
        intervention_id: Intervention ID.

    Returns:
        Status dict.
    """
    manager = _get_manager()
    return await manager.check_intervention_status(intervention_id)


async def complete_intervention(
    intervention_id: str,
    success: bool,
    notes: str | None = None,
) -> None:
    """Mark intervention as complete.

    Args:
        intervention_id: Intervention ID.
        success: Whether intervention succeeded.
        notes: Optional notes.
    """
    manager = _get_manager()
    await manager.complete_intervention(intervention_id, success, notes)


def get_intervention_manager() -> InterventionManager:
    """Get the global intervention manager instance.

    Returns:
        InterventionManager instance.
    """
    return _get_manager()
