"""
User notification system for Lyra.
Handles toast notifications and authentication queue management.

Features (Safe Operation Policy):
- Toast notifications (Windows/Linux/WSL)
- Window bring-to-front via OS API only (no DOM operations)
- Authentication queue for batch processing
- User-driven completion (no timeout, no polling)
- Intervention tracking and domain cooldown

CDP Safety:
- Allowed: Page.navigate, Network.enable (passive), Page.bringToFront
- Forbidden: Runtime.evaluate, DOM.*, Input.*, Emulation.*

Provider Abstraction:
- NotificationProvider protocol for platform-specific implementations
- Automatic platform detection and provider selection
- Fallback mechanism for reliability
"""

import asyncio
import platform
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.storage.database import Database

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.notification_provider import (
    NotificationOptions,
    NotificationUrgency,
    get_notification_registry,
    is_wsl,
)

logger = get_logger(__name__)


class InterventionStatus(Enum):
    """Status of an intervention request."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"
    SKIPPED = "skipped"


class InterventionType(Enum):
    """Type of intervention needed."""

    CAPTCHA = "captcha"
    LOGIN_REQUIRED = "login_required"
    COOKIE_BANNER = "cookie_banner"
    CLOUDFLARE = "cloudflare"
    TURNSTILE = "turnstile"
    JS_CHALLENGE = "js_challenge"
    # Domain blocked notification (informational, no user action needed)
    DOMAIN_BLOCKED = "domain_blocked"


class InterventionResult:
    """Result of an intervention attempt."""

    def __init__(
        self,
        intervention_id: str,
        status: InterventionStatus,
        *,
        elapsed_seconds: float = 0.0,
        should_retry: bool = False,
        cooldown_until: datetime | None = None,
        skip_domain_today: bool = False,
        notes: str | None = None,
    ):
        self.intervention_id = intervention_id
        self.status = status
        self.elapsed_seconds = elapsed_seconds
        self.should_retry = should_retry
        self.cooldown_until = cooldown_until
        self.skip_domain_today = skip_domain_today
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "status": self.status.value,
            "elapsed_seconds": self.elapsed_seconds,
            "should_retry": self.should_retry,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "skip_domain_today": self.skip_domain_today,
            "notes": self.notes,
        }


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

    async def _bring_tab_to_front(self, page: "Page") -> bool:
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


# ============================================================
# Batch Notification Manager
# ============================================================
# Per ADR-0007: Human-in-the-Loop Authentication
# Integrates with search queue workers for authentication workflow


class BatchNotificationManager:
    """Manages batch notifications for CAPTCHA/auth queues.

    Per ADR-0007: Instead of notifying per-CAPTCHA, notifications are batched:
    - First notification after 30 seconds from first pending item
    - Or when search queue becomes empty
    - Groups by domain for user convenience
    """

    BATCH_TIMEOUT_SECONDS = 30

    def __init__(self) -> None:
        self._first_pending_time: datetime | None = None
        self._notification_timer: asyncio.Task | None = None
        self._notified = False
        self._lock = asyncio.Lock()

    async def on_captcha_queued(self, queue_id: str, domain: str) -> None:
        """Called when a CAPTCHA is queued.

        Starts the batch timer if not already running.
        """
        async with self._lock:
            if self._first_pending_time is None:
                self._first_pending_time = datetime.now(UTC)
                self._notified = False
                # Start timer for batch notification
                self._notification_timer = asyncio.create_task(
                    self._wait_and_notify(),
                    name="batch_notification_timer",
                )
                logger.debug(
                    "Batch notification timer started",
                    queue_id=queue_id,
                    domain=domain,
                )

    async def on_search_queue_empty(self) -> None:
        """Called when the search queue becomes empty.

        Triggers immediate batch notification if there are pending items.
        """
        async with self._lock:
            if self._first_pending_time is not None and not self._notified:
                await self._send_batch_notification()

    async def _wait_and_notify(self) -> None:
        """Wait for timeout then send batch notification."""
        try:
            await asyncio.sleep(self.BATCH_TIMEOUT_SECONDS)
            async with self._lock:
                if not self._notified:
                    await self._send_batch_notification()
        except asyncio.CancelledError:
            pass

    async def _send_batch_notification(self) -> None:
        """Send grouped notification for all pending CAPTCHAs."""
        self._notified = True
        if self._notification_timer and not self._notification_timer.done():
            self._notification_timer.cancel()

        # Get pending items
        queue = get_intervention_queue()
        pending = await queue.get_pending()

        if not pending:
            self._reset()
            return

        # Group by domain
        by_domain: dict[str, list[dict]] = {}
        for item in pending:
            domain = item.get("domain", "unknown")
            by_domain.setdefault(domain, []).append(item)

        # Build notification message
        total_count = len(pending)
        lines = [f"認証が必要です（{total_count}件）", ""]
        for domain, items in by_domain.items():
            types = {i.get("auth_type", "unknown") for i in items}
            lines.append(f"{domain}: {len(items)}件 ({', '.join(types)})")
        lines.append("")
        lines.append("解決後、AIに「CAPTCHA解決した」と伝えてください")

        # Send toast notification
        manager = _get_manager()
        await manager.send_toast(
            "Lyra: 認証待ち",
            "\n".join(lines),
            timeout_seconds=15,
        )

        logger.info(
            "Batch notification sent",
            total_count=total_count,
            domains=list(by_domain.keys()),
        )

        self._reset()

    def _reset(self) -> None:
        """Reset state for next batch."""
        self._first_pending_time = None
        self._notified = False
        self._notification_timer = None


# Global batch notification manager
_batch_notification_manager: BatchNotificationManager | None = None


def _get_batch_notification_manager() -> BatchNotificationManager:
    """Get or create the batch notification manager singleton."""
    global _batch_notification_manager
    if _batch_notification_manager is None:
        _batch_notification_manager = BatchNotificationManager()
    return _batch_notification_manager


async def notify_search_queue_empty() -> None:
    """Notify batch manager that search queue is empty.

    Called by SearchQueueWorkerManager when queue becomes empty.
    """
    await _get_batch_notification_manager().on_search_queue_empty()


# ============================================================
# Intervention Queue (Semi-automated Operation)
# ============================================================


class InterventionQueue:
    """Manages authentication queue for batch processing.

    Safe Operation Policy:
    - Authentication challenges are queued instead of blocking
    - User processes at their convenience (no timeout)
    - start_session opens URLs and brings window to front only
    - NO DOM operations (scroll, highlight, focus) are performed
    - User completes via complete_authentication
    - Authenticated sessions can be reused for same domain
    """

    def __init__(self) -> None:
        self._db: Database | None = None

    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()

    async def enqueue(
        self,
        task_id: str,
        url: str,
        domain: str,
        auth_type: str,
        priority: str = "medium",
        expires_at: datetime | None = None,
        search_job_id: str | None = None,
    ) -> str:
        """Add URL to authentication queue.

        Per ADR-0007: Human-in-the-Loop Authentication.
        When search_job_id is provided, resolve_auth will auto-requeue the job.

        Args:
            task_id: Task ID.
            url: URL requiring authentication.
            domain: Domain name.
            auth_type: Type of authentication (cloudflare, captcha, etc.).
            priority: Priority level (high, medium, low).
            expires_at: Queue expiration time.
            search_job_id: Related search job ID (for auto-requeue on resolve).

        Returns:
            Queue item ID.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        import uuid

        queue_id = f"iq_{uuid.uuid4().hex[:12]}"

        # Default expiration: use config value
        if expires_at is None:
            settings = get_settings()
            ttl_hours = settings.task_limits.auth_queue_ttl_hours
            expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        await self._db.execute(
            """
            INSERT INTO intervention_queue
            (id, task_id, url, domain, auth_type, priority, status, expires_at, search_job_id)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                queue_id,
                task_id,
                url,
                domain,
                auth_type,
                priority,
                expires_at.isoformat(),
                search_job_id,
            ),
        )

        logger.info(
            "Authentication queued",
            queue_id=queue_id,
            task_id=task_id,
            domain=domain,
            auth_type=auth_type,
            priority=priority,
            search_job_id=search_job_id,
        )

        # Notify batch notification manager about new pending item
        await _get_batch_notification_manager().on_captcha_queued(queue_id, domain)

        return queue_id

    async def get_item(self, queue_id: str) -> dict[str, Any] | None:
        """Get a specific queue item by ID.

        Args:
            queue_id: Queue item ID.

        Returns:
            Queue item dict or None if not found.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        row = await self._db.fetch_one(
            """
            SELECT id, task_id, url, domain, auth_type, priority, status,
                   queued_at, expires_at, session_data
            FROM intervention_queue
            WHERE id = ?
            """,
            (queue_id,),
        )

        if not row:
            return None

        return dict(row)

    async def get_pending(
        self,
        task_id: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get pending authentications.

        Args:
            task_id: Filter by task ID (optional).
            priority: Filter by priority (optional).
            limit: Maximum number of items.

        Returns:
            List of pending queue items.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        query = """
            SELECT id, task_id, url, domain, auth_type, priority, status,
                   queued_at, expires_at
            FROM intervention_queue
            WHERE status = 'pending'
        """
        params: list[Any] = []

        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)

        if priority:
            query += " AND priority = ?"
            params.append(priority)

        query += (
            " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, queued_at"
        )
        query += f" LIMIT {limit}"

        rows = await self._db.fetch_all(query, params)

        return [dict(row) for row in rows]

    async def get_pending_count(self, task_id: str) -> dict[str, int]:
        """Get count of pending authentications by priority.

        Args:
            task_id: Task ID.

        Returns:
            Dict with counts by priority and total.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        rows = await self._db.fetch_all(
            """
            SELECT priority, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            GROUP BY priority
            """,
            (task_id,),
        )

        counts = {"high": 0, "medium": 0, "low": 0, "total": 0}
        for row in rows:
            priority = row["priority"]
            count = row["count"]
            counts[priority] = count
            counts["total"] += count

        return counts

    async def get_authentication_queue_summary(self, task_id: str) -> dict[str, Any]:
        """Get comprehensive summary of authentication queue for exploration status.

        Provides authentication queue information for get_exploration_status.

        Args:
            task_id: Task ID.

        Returns:
            Summary dict with:
            - pending_count: Total pending authentications
            - high_priority_count: High priority (primary sources) count
            - domains: List of distinct domains awaiting authentication
            - oldest_queued_at: ISO timestamp of oldest queued item
            - by_auth_type: Count by auth_type (cloudflare, captcha, etc.)
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        # Get counts by priority
        priority_rows = await self._db.fetch_all(
            """
            SELECT priority, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            GROUP BY priority
            """,
            (task_id,),
        )

        pending_count = 0
        high_priority_count = 0
        for row in priority_rows:
            count = row["count"]
            pending_count += count
            if row["priority"] == "high":
                high_priority_count = count

        # Get distinct domains
        domain_rows = await self._db.fetch_all(
            """
            SELECT DISTINCT domain
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            ORDER BY domain
            """,
            (task_id,),
        )
        domains = [row["domain"] for row in domain_rows]

        # Get oldest queued_at
        oldest_row = await self._db.fetch_one(
            """
            SELECT MIN(queued_at) as oldest
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            """,
            (task_id,),
        )
        oldest_queued_at = oldest_row["oldest"] if oldest_row and oldest_row["oldest"] else None

        # Get counts by auth_type
        auth_type_rows = await self._db.fetch_all(
            """
            SELECT auth_type, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
            GROUP BY auth_type
            """,
            (task_id,),
        )
        by_auth_type = {row["auth_type"]: row["count"] for row in auth_type_rows}

        return {
            "pending_count": pending_count,
            "high_priority_count": high_priority_count,
            "domains": domains,
            "oldest_queued_at": oldest_queued_at,
            "by_auth_type": by_auth_type,
        }

    async def start_session(
        self,
        task_id: str,
        queue_ids: list[str] | None = None,
        priority_filter: str | None = None,
    ) -> dict[str, Any]:
        """Start authentication session per safe operation policy.

        This method only marks items as in_progress and returns URLs.
        Browser window opening and front-bringing should be done separately
        via OS API (no DOM operations).

        Safe Operation Policy:
        - Returns URLs for user to process
        - NO DOM operations are performed
        - User finds and resolves challenges themselves
        - User calls complete_authentication when done

        Args:
            task_id: Task ID.
            queue_ids: Specific queue IDs to process (optional).
            priority_filter: Process only this priority level (optional).

        Returns:
            Session info with URLs to process.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        # Get items to process
        if queue_ids:
            placeholders = ",".join("?" * len(queue_ids))
            rows = await self._db.fetch_all(
                f"""
                SELECT id, url, domain, auth_type, priority
                FROM intervention_queue
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                queue_ids,
            )
        else:
            query = """
                SELECT id, url, domain, auth_type, priority
                FROM intervention_queue
                WHERE task_id = ? AND status = 'pending'
            """
            params: list[Any] = [task_id]

            if priority_filter and priority_filter != "all":
                query += " AND priority = ?"
                params.append(priority_filter)

            query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, queued_at"

            rows = await self._db.fetch_all(query, params)

        if not rows:
            return {
                "ok": True,
                "session_started": False,
                "message": "No pending authentications",
                "count": 0,
                "items": [],
            }

        # Mark as in_progress
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(ids))
        await self._db.execute(
            f"""
            UPDATE intervention_queue
            SET status = 'in_progress', started_at = datetime('now')
            WHERE id IN ({placeholders})
            """,
            ids,
        )

        items = [dict(row) for row in rows]

        logger.info(
            "Authentication session started",
            task_id=task_id,
            count=len(items),
        )

        # Open browser and navigate to first URL
        # Use BrowserFetcher for consistency with authentication session handling
        if items:
            try:
                logger.debug("Opening browser for authentication URL", item_count=len(items))
                from src.crawler.fetcher import BrowserFetcher

                browser_fetcher = BrowserFetcher()
                logger.debug("Calling BrowserFetcher._ensure_browser(headful=True)")
                browser, context = await browser_fetcher._ensure_browser(
                    headful=True, task_id=task_id
                )
                logger.debug(
                    "BrowserFetcher._ensure_browser() returned",
                    has_browser=browser is not None,
                    has_context=context is not None,
                )

                if context:
                    # Open first URL in browser
                    logger.debug("Creating new page")
                    page = await context.new_page()
                    first_url = items[0]["url"]
                    logger.debug("Navigating to URL", url=first_url[:80])

                    await page.goto(first_url, wait_until="domcontentloaded", timeout=10000)
                    logger.debug("Page navigation completed")

                    # Bring window to front (safe operation)
                    manager = get_intervention_manager()
                    await manager._bring_tab_to_front(page)

                    logger.info(
                        "Opened authentication URL in browser",
                        url=first_url[:80],
                        total_count=len(items),
                        task_id=task_id,
                    )
                else:
                    logger.warning(
                        "Browser context not available, returning URLs only",
                        task_id=task_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to open browser, returning URLs only",
                    error=str(e),
                    task_id=task_id,
                )
                # Continue with URL-only response (user can open manually)

        return {
            "ok": True,
            "session_started": True,
            "count": len(items),
            "items": items,
        }

    async def get_pending_by_domain(self) -> dict[str, Any]:
        """Get pending authentications grouped by domain.

        Returns a summary of pending authentications organized by domain,
        including affected tasks and priority information.

        Returns:
            Dict with:
            - ok: Success status
            - total_domains: Number of distinct domains with pending auth
            - total_pending: Total number of pending items
            - domains: List of domain info dicts
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        # Get all pending items
        rows = await self._db.fetch_all(
            """
            SELECT id, task_id, url, domain, auth_type, priority
            FROM intervention_queue
            WHERE status = 'pending'
            ORDER BY domain,
                     CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                     queued_at
            """,
            None,
        )

        # Group by domain
        domain_map: dict[str, dict] = {}
        for row in rows:
            domain = row["domain"]
            if domain not in domain_map:
                domain_map[domain] = {
                    "domain": domain,
                    "pending_count": 0,
                    "high_priority_count": 0,
                    "affected_tasks": set(),
                    "auth_types": set(),
                    "urls": [],
                }

            info = domain_map[domain]
            info["pending_count"] += 1
            if row["priority"] == "high":
                info["high_priority_count"] += 1
            info["affected_tasks"].add(row["task_id"])
            info["auth_types"].add(row["auth_type"])
            info["urls"].append(row["url"])

        # Convert sets to lists for JSON serialization
        domains = []
        for info in domain_map.values():
            domains.append(
                {
                    "domain": info["domain"],
                    "pending_count": info["pending_count"],
                    "high_priority_count": info["high_priority_count"],
                    "affected_tasks": list(info["affected_tasks"]),
                    "auth_types": list(info["auth_types"]),
                    "urls": info["urls"],
                }
            )

        # Sort by high priority count desc, then pending count desc
        domains.sort(key=lambda d: (-d["high_priority_count"], -d["pending_count"]))

        total_pending = sum(d["pending_count"] for d in domains)

        return {
            "ok": True,
            "total_domains": len(domains),
            "total_pending": total_pending,
            "domains": domains,
        }

    async def complete(
        self,
        queue_id: str,
        success: bool,
        session_data: dict | None = None,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark authentication as complete.

        Args:
            queue_id: Queue item ID.
            success: Whether authentication succeeded.
            session_data: Session data to store (cookies, etc.).
            task_id: Task ID (optional, for legacy API compatibility).

        Returns:
            Completion result.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        import json

        session_json = json.dumps(session_data) if session_data else None
        status = "completed" if success else "skipped"

        await self._db.execute(
            """
            UPDATE intervention_queue
            SET status = ?, completed_at = datetime('now'), session_data = ?
            WHERE id = ?
            """,
            (status, session_json, queue_id),
        )

        # Get the item for return
        row = await self._db.fetch_one(
            "SELECT url, domain FROM intervention_queue WHERE id = ?",
            (queue_id,),
        )

        logger.info(
            "Authentication completed",
            queue_id=queue_id,
            success=success,
            domain=row["domain"] if row else None,
        )

        return {
            "ok": True,
            "queue_id": queue_id,
            "status": status,
            "url": row["url"] if row else None,
            "domain": row["domain"] if row else None,
        }

    async def complete_domain(
        self,
        domain: str,
        success: bool,
        session_data: dict | None = None,
    ) -> dict[str, Any]:
        """Complete authentication for all pending items of a domain.

        This resolves all pending authentication requests for the given domain
        across all tasks. Session data is stored and can be reused for
        subsequent requests to the same domain.

        Args:
            domain: Domain name to complete authentication for.
            success: Whether authentication succeeded.
            session_data: Session data to store (cookies, etc.).

        Returns:
            Dict with:
            - ok: Success status
            - domain: The domain that was completed
            - resolved_count: Number of items resolved
            - affected_tasks: List of task IDs affected
            - session_stored: Whether session data was stored
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        import json

        session_json = json.dumps(session_data) if session_data else None
        status = "completed" if success else "skipped"

        # Get affected items before updating
        affected_rows = await self._db.fetch_all(
            """
            SELECT id, task_id, url
            FROM intervention_queue
            WHERE domain = ? AND status IN ('pending', 'in_progress')
            """,
            (domain,),
        )

        if not affected_rows:
            return {
                "ok": True,
                "domain": domain,
                "resolved_count": 0,
                "affected_tasks": [],
                "session_stored": False,
            }

        # Update all items for this domain
        await self._db.execute(
            """
            UPDATE intervention_queue
            SET status = ?, completed_at = datetime('now'), session_data = ?
            WHERE domain = ? AND status IN ('pending', 'in_progress')
            """,
            (status, session_json, domain),
        )

        # Collect affected task IDs
        affected_tasks = list({row["task_id"] for row in affected_rows})

        logger.info(
            "Domain authentication completed",
            domain=domain,
            success=success,
            resolved_count=len(affected_rows),
            affected_tasks=affected_tasks,
        )

        return {
            "ok": True,
            "domain": domain,
            "resolved_count": len(affected_rows),
            "affected_tasks": affected_tasks,
            "session_stored": session_data is not None,
        }

    async def skip(
        self,
        task_id: str | None = None,
        queue_ids: list[str] | None = None,
        *,
        domain: str | None = None,
        status: str = "skipped",
    ) -> dict[str, Any]:
        """Skip authentications.

        Can skip by:
        - Specific queue IDs (queue_ids parameter)
        - All pending items for a domain (domain parameter)
        - All pending items for a task (task_id parameter, when no queue_ids or domain)

        Args:
            task_id: Task ID (optional, used when no queue_ids or domain specified).
            queue_ids: Specific queue IDs to skip (optional).
            domain: Domain to skip all pending items for (optional).
            status: Status to set ('skipped' or 'cancelled'). Defaults to 'skipped'.

        Returns:
            Skip result with affected_tasks for domain-based skips.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db
        affected_tasks: list[str] = []

        if queue_ids:
            # Skip specific queue IDs
            placeholders = ",".join("?" * len(queue_ids))
            await self._db.execute(
                f"""
                UPDATE intervention_queue
                SET status = ?, completed_at = datetime('now')
                WHERE id IN ({placeholders}) AND status IN ('pending', 'in_progress')
                """,
                (status, *queue_ids),
            )
            skipped = len(queue_ids)

            logger.info(
                "Authentications skipped by queue_ids",
                queue_ids=queue_ids,
                skipped=skipped,
            )
        elif domain:
            # Skip all pending items for a domain
            # First get affected tasks
            affected_rows = await self._db.fetch_all(
                """
                SELECT DISTINCT task_id
                FROM intervention_queue
                WHERE domain = ? AND status IN ('pending', 'in_progress')
                """,
                (domain,),
            )
            affected_tasks = [row["task_id"] for row in affected_rows]

            # Count pending before update
            count_row = await self._db.fetch_one(
                """
                SELECT COUNT(*) as count
                FROM intervention_queue
                WHERE domain = ? AND status IN ('pending', 'in_progress')
                """,
                (domain,),
            )
            skipped = count_row["count"] if count_row else 0

            # Update
            await self._db.execute(
                """
                UPDATE intervention_queue
                SET status = ?, completed_at = datetime('now')
                WHERE domain = ? AND status IN ('pending', 'in_progress')
                """,
                (status, domain),
            )

            logger.info(
                "Authentications skipped by domain",
                domain=domain,
                skipped=skipped,
                affected_tasks=affected_tasks,
            )
        elif task_id:
            # Skip all pending items for a task
            await self._db.execute(
                """
                UPDATE intervention_queue
                SET status = ?, completed_at = datetime('now')
                WHERE task_id = ? AND status IN ('pending', 'in_progress')
                """,
                (status, task_id),
            )
            # Get count
            row = await self._db.fetch_one(
                "SELECT COUNT(*) as count FROM intervention_queue WHERE task_id = ? AND status = ?",
                (task_id, status),
            )
            skipped = row["count"] if row else 0

            logger.info(
                "Authentications skipped by task_id",
                task_id=task_id,
                skipped=skipped,
            )
        else:
            # No filter specified
            return {
                "ok": False,
                "error": "Must specify task_id, queue_ids, or domain",
                "skipped": 0,
            }

        result: dict[str, Any] = {
            "ok": True,
            "skipped": skipped,
        }

        # Include affected_tasks for domain-based skips
        if domain and affected_tasks:
            result["affected_tasks"] = affected_tasks

        return result

    async def get_session_for_domain(
        self,
        domain: str,
        task_id: str | None = None,
    ) -> dict | None:
        """Get stored session data for a domain.

        Args:
            domain: Domain name.
            task_id: Task ID (optional, for task-scoped sessions).

        Returns:
            Session data dict or None.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        import json

        query = """
            SELECT session_data
            FROM intervention_queue
            WHERE domain = ? AND status = 'completed' AND session_data IS NOT NULL
        """
        params = [domain]

        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)

        # Use rowid as secondary sort to ensure most recent insert wins on ties
        query += " ORDER BY completed_at DESC, rowid DESC LIMIT 1"

        row = await self._db.fetch_one(query, params)

        if row and row["session_data"]:
            return cast(dict[Any, Any], json.loads(row["session_data"]))

        return None

    async def cleanup_expired(self) -> int:
        """Clean up expired queue items.

        Returns:
            Number of items cleaned up.
        """
        await self._ensure_db()
        assert self._db is not None  # Type narrowing after _ensure_db

        # Use ISO format for comparison with stored timestamps
        now_iso = datetime.now(UTC).isoformat()

        await self._db.execute(
            """
            UPDATE intervention_queue
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < ?
            """,
            (now_iso,),
        )

        # Count expired
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as count FROM intervention_queue WHERE status = 'expired'",
        )

        return row["count"] if row else 0


# Global queue instance
_queue: InterventionQueue | None = None


def get_intervention_queue() -> InterventionQueue:
    """Get the global intervention queue instance.

    Returns:
        InterventionQueue instance.
    """
    global _queue
    if _queue is None:
        _queue = InterventionQueue()
    return _queue
