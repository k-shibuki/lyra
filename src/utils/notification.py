"""
User notification system for Lancet.
Handles toast notifications and authentication queue management.

Features per §3.6.1 (Safe Operation Policy):
- Toast notifications (Windows/Linux/WSL)
- Window bring-to-front via OS API only (no DOM operations)
- Authentication queue for batch processing
- User-driven completion (no timeout, no polling)
- Intervention tracking and domain cooldown

CDP Safety (§3.6.1):
- Allowed: Page.navigate, Network.enable (passive), Page.bringToFront
- Forbidden: Runtime.evaluate, DOM.*, Input.*, Emulation.*
"""

import asyncio
import platform
import subprocess
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.storage.database import get_database

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
    """Manages manual intervention flows with safe operation policy per §3.6.1.
    
    Safe Operation Policy:
    - Window bring-to-front via OS API only (no DOM operations)
    - No timeout enforcement (user-driven completion)
    - No polling or page content inspection
    - Toast notification for awareness
    - Skip domain after 3 consecutive failures
    
    CDP Safety:
    - Allowed: Page.bringToFront
    - Forbidden: Runtime.evaluate, DOM.*, Input.*, scrollIntoView, etc.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._pending_interventions: dict[str, dict] = {}
        self._domain_failures: dict[str, int] = {}  # domain -> consecutive failure count
        self._browser_page = None  # Current browser page for intervention
        self._intervention_lock = asyncio.Lock()
    
    @property
    def max_domain_failures(self) -> int:
        """Get max consecutive failures before skipping domain today."""
        return 3  # Per §3.1: 3回失敗で当該ドメインを当日スキップ
    
    @property
    def cooldown_minutes(self) -> int:
        """Get minimum cooldown period in minutes after timeout."""
        return 60  # Per §3.5: クールダウン（最小60分）
    
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
        """Request manual intervention with safe operation policy per §3.6.1.
        
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
        
        # Check if domain should be skipped
        if await self._should_skip_domain(domain):
            logger.info(
                "Domain skipped due to consecutive failures",
                domain=domain,
                failures=self._domain_failures.get(domain, 0),
            )
            return InterventionResult(
                intervention_id=f"{domain}_skipped",
                status=InterventionStatus.SKIPPED,
                skip_domain_today=True,
                notes="Domain skipped due to consecutive intervention failures",
            )
        
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
                (task_id, domain, intervention_type.value, datetime.now(timezone.utc).isoformat()),
            )
            
            # Store intervention state (minimal - no timeout, no element_selector)
            intervention_state = {
                "id": intervention_id,
                "type": intervention_type,
                "url": url,
                "domain": domain,
                "started_at": datetime.now(timezone.utc),
                "task_id": task_id,
            }
            self._pending_interventions[intervention_id] = intervention_state
            
            # Build notification message (no timeout info per §3.6.1)
            if message is None:
                message = self._build_intervention_message(intervention_type, url, domain)
            
            notification_msg = (
                f"{message}\n\n"
                f"URL: {url}\n"
                f"完了後、Cursorで complete_authentication を呼んでください"
            )
            
            # Step 1: Send toast notification
            title = f"Lancet: {intervention_type.value.upper()}"
            notification_sent = await self.send_toast(
                title,
                notification_msg,
                timeout_seconds=10,
            )
            
            # Step 2: Bring browser window to front via OS API only
            # Per §3.6.1: No DOM operations (scroll, highlight, focus)
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
    
    async def _bring_tab_to_front(self, page) -> bool:
        """Bring browser window to front using safe methods per §3.6.1.
        
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
            
            # Use CDP Page.bringToFront (allowed per §3.6.1)
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
        
        # Check for WSL
        is_wsl = "microsoft" in platform.release().lower()
        
        if system == "Windows" or is_wsl:
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
                    "-ExecutionPolicy", "Bypass",
                    "-Command", ps_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.wait(), timeout=5.0)
                logger.debug("Chrome window activated via PowerShell")
            except Exception as e:
                logger.debug("PowerShell window activation failed", error=str(e))
    
    # NOTE: _highlight_element, _wait_for_intervention, _has_challenge_indicators
    # have been removed per §3.6.1 (Safe Operation Policy).
    # DOM operations and polling are forbidden during authentication sessions.
    
    async def _handle_intervention_result(
        self,
        result: InterventionResult,
        intervention_state: dict,
        db,
    ) -> None:
        """Handle intervention result with cooldown and skip logic.
        
        Args:
            result: Intervention result.
            intervention_state: Intervention state dict.
            db: Database instance.
        """
        domain = intervention_state["domain"]
        intervention_type = intervention_state["type"]
        task_id = intervention_state.get("task_id")
        
        # Update intervention log
        await db.execute(
            """
            UPDATE intervention_log
            SET completed_at = ?, result = ?, duration_seconds = ?, notes = ?
            WHERE domain = ? AND intervention_type = ?
            ORDER BY notification_sent_at DESC
            LIMIT 1
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                result.status.value,
                int(result.elapsed_seconds),
                result.notes,
                domain,
                intervention_type.value,
            ),
        )
        
        if result.status == InterventionStatus.SUCCESS:
            # Reset failure counter
            self._domain_failures[domain] = 0
            logger.info(
                "Intervention succeeded",
                intervention_id=result.intervention_id,
                domain=domain,
                elapsed=result.elapsed_seconds,
            )
        else:
            # Increment failure counter
            failures = self._domain_failures.get(domain, 0) + 1
            self._domain_failures[domain] = failures
            
            logger.warning(
                "Intervention failed",
                intervention_id=result.intervention_id,
                domain=domain,
                status=result.status.value,
                failures=failures,
            )
            
            # Check if should skip domain
            if failures >= self.max_domain_failures:
                result.skip_domain_today = True
                
                # Mark domain for skip in database
                await db.execute(
                    """
                    UPDATE domains
                    SET cooldown_until = ?, skip_reason = ?
                    WHERE domain = ?
                    """,
                    (
                        (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                        f"Skipped after {failures} consecutive intervention failures",
                        domain,
                    ),
                )
                
                logger.info(
                    "Domain marked for skip today",
                    domain=domain,
                    failures=failures,
                )
            elif result.cooldown_until:
                # Apply cooldown
                await db.execute(
                    """
                    UPDATE domains
                    SET cooldown_until = ?
                    WHERE domain = ?
                    """,
                    (result.cooldown_until.isoformat(), domain),
                )
                
                logger.info(
                    "Domain cooldown applied",
                    domain=domain,
                    cooldown_until=result.cooldown_until.isoformat(),
                )
    
    async def _should_skip_domain(self, domain: str) -> bool:
        """Check if domain should be skipped due to consecutive failures.
        
        Args:
            domain: Domain name.
            
        Returns:
            True if domain should be skipped.
        """
        failures = self._domain_failures.get(domain, 0)
        if failures >= self.max_domain_failures:
            return True
        
        # Also check database for cooldown
        db = await get_database()
        domain_info = await db.fetch_one(
            "SELECT cooldown_until FROM domains WHERE domain = ?",
            (domain,),
        )
        
        if domain_info and domain_info.get("cooldown_until"):
            try:
                cooldown_until = datetime.fromisoformat(
                    domain_info["cooldown_until"].replace("Z", "+00:00")
                )
                if datetime.now(timezone.utc) < cooldown_until:
                    return True
            except Exception:
                pass
        
        return False
    
    async def send_toast(
        self,
        title: str,
        message: str,
        *,
        timeout_seconds: int = 10,
    ) -> bool:
        """Send a toast notification.
        
        Args:
            title: Notification title.
            message: Notification message.
            timeout_seconds: Display duration.
            
        Returns:
            True if notification was sent successfully.
        """
        system = platform.system()
        
        try:
            if system == "Linux":
                # Check if running in WSL
                if self._is_wsl():
                    return await self._send_wsl_toast(title, message, timeout_seconds)
                else:
                    return await self._send_linux_toast(title, message, timeout_seconds)
            elif system == "Windows":
                return await self._send_windows_toast(title, message, timeout_seconds)
            else:
                logger.warning("Unsupported platform for notifications", system=system)
                return False
                    
        except Exception as e:
            logger.error("Failed to send notification", error=str(e))
            return False
    
    def _is_wsl(self) -> bool:
        """Check if running in WSL."""
        try:
            with open("/proc/version", "r") as f:
                return "microsoft" in f.read().lower()
        except Exception:
            return "microsoft" in platform.release().lower()
    
    async def _send_linux_toast(
        self,
        title: str,
        message: str,
        timeout_seconds: int,
    ) -> bool:
        """Send notification using notify-send (Linux)."""
        try:
            timeout_ms = timeout_seconds * 1000
            process = await asyncio.create_subprocess_exec(
                "notify-send",
                "-t", str(timeout_ms),
                "-u", "critical",  # Use critical for intervention
                "-i", "dialog-warning",
                title,
                message,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            return process.returncode == 0
        except FileNotFoundError:
            logger.warning("notify-send not found, install libnotify")
            return False
    
    async def _send_windows_toast(
        self,
        title: str,
        message: str,
        timeout_seconds: int,
    ) -> bool:
        """Send notification using PowerShell (Windows)."""
        # Escape special characters
        title = title.replace("'", "''").replace("`", "``")
        message = message.replace("'", "''").replace("`", "``").replace("\n", "&#10;")
        
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        
        $template = @"
        <toast duration="long" scenario="reminder">
            <visual>
                <binding template="ToastText02">
                    <text id="1">{title}</text>
                    <text id="2">{message}</text>
                </binding>
            </visual>
            <audio src="ms-winsoundevent:Notification.Reminder"/>
        </toast>
"@
        
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Lancet").Show($toast)
        """
        
        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            return process.returncode == 0
        except Exception as e:
            logger.error("PowerShell notification failed", error=str(e))
            return False
    
    async def _send_wsl_toast(
        self,
        title: str,
        message: str,
        timeout_seconds: int,
    ) -> bool:
        """Send notification from WSL to Windows.
        
        Uses PowerShell BurntToast module or fallback to NotifyIcon.
        """
        # Escape for PowerShell
        title = title.replace("'", "''").replace('"', '`"').replace("\n", " ")
        message = message.replace("'", "''").replace('"', '`"').replace("\n", "\\n")
        
        # Try BurntToast first (better notifications)
        burnt_toast_script = f"""
        if (Get-Module -ListAvailable -Name BurntToast) {{
            Import-Module BurntToast
            New-BurntToastNotification -Text '{title}', '{message}' -Sound 'Reminder'
        }} else {{
            Add-Type -AssemblyName System.Windows.Forms
            $balloon = New-Object System.Windows.Forms.NotifyIcon
            $balloon.Icon = [System.Drawing.SystemIcons]::Warning
            $balloon.BalloonTipTitle = '{title}'
            $balloon.BalloonTipText = '{message}'
            $balloon.BalloonTipIcon = 'Warning'
            $balloon.Visible = $true
            $balloon.ShowBalloonTip({timeout_seconds * 1000})
            Start-Sleep -Seconds {timeout_seconds + 1}
            $balloon.Dispose()
        }}
        """
        
        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-Command", burnt_toast_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Don't wait for completion for balloon notifications
            # They run async and clean up themselves
            return True
        except Exception as e:
            logger.error("WSL notification failed", error=str(e))
            return False
    
    async def check_intervention_status(
        self,
        intervention_id: str,
    ) -> dict[str, Any]:
        """Check status of a pending intervention.
        
        Per §3.6.1: No timeout enforcement. User completes via complete_authentication.
        
        Args:
            intervention_id: Intervention ID.
            
        Returns:
            Status dict.
        """
        intervention = self._pending_interventions.get(intervention_id)
        
        if intervention is None:
            return {"status": "unknown", "intervention_id": intervention_id}
        
        elapsed = (datetime.now(timezone.utc) - intervention["started_at"]).total_seconds()
        
        # No timeout enforcement per §3.6.1
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
        
        elapsed = (datetime.now(timezone.utc) - intervention["started_at"]).total_seconds()
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
                datetime.now(timezone.utc).isoformat(),
                result,
                int(elapsed),
                notes,
                intervention["domain"],
                intervention["type"].value if isinstance(intervention["type"], InterventionType) else intervention["type"],
            ),
        )
        
        if success:
            self._domain_failures[intervention["domain"]] = 0
        
        logger.info(
            "Intervention completed",
            intervention_id=intervention_id,
            success=success,
            duration=elapsed,
        )
    
    def get_domain_failures(self, domain: str) -> int:
        """Get consecutive failure count for domain.
        
        Args:
            domain: Domain name.
            
        Returns:
            Failure count.
        """
        return self._domain_failures.get(domain, 0)
    
    def reset_domain_failures(self, domain: str) -> None:
        """Reset failure count for domain.
        
        Args:
            domain: Domain name.
        """
        self._domain_failures[domain] = 0


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
    """Send notification to user per §3.6.1 safe operation policy.
    
    Args:
        event: Event type (captcha, login_required, cookie_banner, cloudflare, etc.).
        payload: Event payload with keys:
            - url: Target URL
            - domain: Domain name
            - message: Custom message (optional)
            - task_id: Associated task ID (optional)
            - page: Playwright page object for window front-bring (optional)
        
        Note: element_selector and on_success_callback are no longer supported
        per §3.6.1 (no DOM operations during authentication sessions).
        
    Returns:
        Notification/intervention result.
    """
    manager = _get_manager()
    
    intervention_types = {"captcha", "login_required", "cookie_banner", "cloudflare", "turnstile", "js_challenge"}
    
    if event in intervention_types:
        # These require intervention flow (safe mode per §3.6.1)
        result = await manager.request_intervention(
            intervention_type=event,
            url=payload.get("url", ""),
            domain=payload.get("domain", "unknown"),
            message=payload.get("message"),
            task_id=payload.get("task_id"),
            page=payload.get("page"),
        )
        return result.to_dict()
    else:
        # Simple notification (no intervention flow)
        title = f"Lancet: {event.upper()}"
        message = payload.get("message", "")
        
        sent = await manager.send_toast(title, message)
        
        return {
            "shown": sent,
            "event": event,
        }


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
# Intervention Queue (半自動運用)
# ============================================================

class InterventionQueue:
    """Manages authentication queue for batch processing per §3.6.1.
    
    Safe Operation Policy:
    - Authentication challenges are queued instead of blocking
    - User processes at their convenience (no timeout)
    - start_session opens URLs and brings window to front only
    - NO DOM operations (scroll, highlight, focus) are performed
    - User completes via complete_authentication
    - Authenticated sessions can be reused for same domain
    """
    
    def __init__(self):
        self._db = None
    
    async def _ensure_db(self):
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
    ) -> str:
        """Add URL to authentication queue.
        
        Args:
            task_id: Task ID.
            url: URL requiring authentication.
            domain: Domain name.
            auth_type: Type of authentication (cloudflare, captcha, etc.).
            priority: Priority level (high, medium, low).
            expires_at: Queue expiration time.
            
        Returns:
            Queue item ID.
        """
        await self._ensure_db()
        
        import uuid
        queue_id = f"iq_{uuid.uuid4().hex[:12]}"
        
        # Default expiration: 1 hour from now
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        await self._db.execute(
            """
            INSERT INTO intervention_queue 
            (id, task_id, url, domain, auth_type, priority, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (queue_id, task_id, url, domain, auth_type, priority, expires_at.isoformat()),
        )
        
        logger.info(
            "Authentication queued",
            queue_id=queue_id,
            task_id=task_id,
            domain=domain,
            auth_type=auth_type,
            priority=priority,
        )
        
        return queue_id
    
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
        
        # Use ISO format for comparison with stored timestamps
        now_iso = datetime.now(timezone.utc).isoformat()
        
        query = """
            SELECT id, task_id, url, domain, auth_type, priority, status, 
                   queued_at, expires_at
            FROM intervention_queue
            WHERE status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
        """
        params = [now_iso]
        
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        
        query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, queued_at"
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
        
        # Use ISO format for comparison with stored timestamps
        now_iso = datetime.now(timezone.utc).isoformat()
        
        rows = await self._db.fetch_all(
            """
            SELECT priority, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
            GROUP BY priority
            """,
            (task_id, now_iso),
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
        
        Per §16.7.1: Provides authentication queue information for get_exploration_status.
        
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
        
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Get counts by priority
        priority_rows = await self._db.fetch_all(
            """
            SELECT priority, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
            GROUP BY priority
            """,
            (task_id, now_iso),
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
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY domain
            """,
            (task_id, now_iso),
        )
        domains = [row["domain"] for row in domain_rows]
        
        # Get oldest queued_at
        oldest_row = await self._db.fetch_one(
            """
            SELECT MIN(queued_at) as oldest
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (task_id, now_iso),
        )
        oldest_queued_at = oldest_row["oldest"] if oldest_row and oldest_row["oldest"] else None
        
        # Get counts by auth_type
        auth_type_rows = await self._db.fetch_all(
            """
            SELECT auth_type, COUNT(*) as count
            FROM intervention_queue
            WHERE task_id = ? AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > ?)
            GROUP BY auth_type
            """,
            (task_id, now_iso),
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
        """Start authentication session per §3.6.1 safe operation policy.
        
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
            # Use ISO format for comparison with stored timestamps
            now_iso = datetime.now(timezone.utc).isoformat()
            
            query = """
                SELECT id, url, domain, auth_type, priority
                FROM intervention_queue
                WHERE task_id = ? AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > ?)
            """
            params = [task_id, now_iso]
            
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
        
        return {
            "ok": True,
            "session_started": True,
            "count": len(items),
            "items": items,
        }
    
    async def complete(
        self,
        queue_id: str,
        success: bool,
        session_data: dict | None = None,
    ) -> dict[str, Any]:
        """Mark authentication as complete.
        
        Args:
            queue_id: Queue item ID.
            success: Whether authentication succeeded.
            session_data: Session data to store (cookies, etc.).
            
        Returns:
            Completion result.
        """
        await self._ensure_db()
        
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
    
    async def skip(
        self,
        task_id: str,
        queue_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Skip authentications.
        
        Args:
            task_id: Task ID.
            queue_ids: Specific queue IDs to skip (optional, skips all if omitted).
            
        Returns:
            Skip result.
        """
        await self._ensure_db()
        
        if queue_ids:
            placeholders = ",".join("?" * len(queue_ids))
            result = await self._db.execute(
                f"""
                UPDATE intervention_queue
                SET status = 'skipped', completed_at = datetime('now')
                WHERE id IN ({placeholders}) AND status IN ('pending', 'in_progress')
                """,
                queue_ids,
            )
            skipped = len(queue_ids)
        else:
            result = await self._db.execute(
                """
                UPDATE intervention_queue
                SET status = 'skipped', completed_at = datetime('now')
                WHERE task_id = ? AND status IN ('pending', 'in_progress')
                """,
                (task_id,),
            )
            # Get count (SQLite doesn't return affected rows easily)
            row = await self._db.fetch_one(
                "SELECT COUNT(*) as count FROM intervention_queue WHERE task_id = ? AND status = 'skipped'",
                (task_id,),
            )
            skipped = row["count"] if row else 0
        
        logger.info(
            "Authentications skipped",
            task_id=task_id,
            skipped=skipped,
        )
        
        return {
            "ok": True,
            "skipped": skipped,
        }
    
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
            return json.loads(row["session_data"])
        
        return None
    
    async def cleanup_expired(self) -> int:
        """Clean up expired queue items.
        
        Returns:
            Number of items cleaned up.
        """
        await self._ensure_db()
        
        # Use ISO format for comparison with stored timestamps
        now_iso = datetime.now(timezone.utc).isoformat()
        
        result = await self._db.execute(
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
