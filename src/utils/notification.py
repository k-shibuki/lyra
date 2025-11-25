"""
User notification system for Lancet.
Handles toast notifications and manual intervention flows.
"""

import asyncio
import platform
import subprocess
from datetime import datetime
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.storage.database import get_database

logger = get_logger(__name__)


class NotificationManager:
    """Manages user notifications and interventions."""
    
    def __init__(self):
        self._settings = get_settings()
        self._pending_interventions: dict[str, dict] = {}
    
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
                return await self._send_linux_toast(title, message, timeout_seconds)
            elif system == "Windows":
                return await self._send_windows_toast(title, message, timeout_seconds)
            else:
                # WSL detection
                if "microsoft" in platform.release().lower():
                    return await self._send_wsl_toast(title, message, timeout_seconds)
                else:
                    logger.warning("Unsupported platform for notifications", system=system)
                    return False
                    
        except Exception as e:
            logger.error("Failed to send notification", error=str(e))
            return False
    
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
                "-u", "normal",
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
        title = title.replace("'", "''")
        message = message.replace("'", "''")
        
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        
        $template = @"
        <toast duration="long">
            <visual>
                <binding template="ToastText02">
                    <text id="1">{title}</text>
                    <text id="2">{message}</text>
                </binding>
            </visual>
            <audio src="ms-winsoundevent:Notification.Default"/>
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
        """Send notification from WSL to Windows."""
        # Escape for PowerShell
        title = title.replace("'", "''").replace('"', '`"')
        message = message.replace("'", "''").replace('"', '`"')
        
        ps_command = f"""
        Add-Type -AssemblyName System.Windows.Forms
        $balloon = New-Object System.Windows.Forms.NotifyIcon
        $balloon.Icon = [System.Drawing.SystemIcons]::Information
        $balloon.BalloonTipTitle = "{title}"
        $balloon.BalloonTipText = "{message}"
        $balloon.Visible = $true
        $balloon.ShowBalloonTip({timeout_seconds * 1000})
        Start-Sleep -Seconds {timeout_seconds + 1}
        $balloon.Dispose()
        """
        
        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Don't wait for completion (notification runs async)
            return True
        except Exception as e:
            logger.error("WSL notification failed", error=str(e))
            return False
    
    async def request_intervention(
        self,
        event_type: str,
        url: str,
        domain: str,
        message: str,
        timeout_seconds: int | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Request manual intervention from user.
        
        Args:
            event_type: Type of intervention needed.
            url: URL requiring intervention.
            domain: Domain name.
            message: Message to display.
            timeout_seconds: Timeout for intervention.
            task_id: Associated task ID.
            
        Returns:
            Intervention result.
        """
        if timeout_seconds is None:
            timeout_seconds = self._settings.notification.intervention_timeout
        
        intervention_id = f"{domain}_{datetime.now().strftime('%H%M%S')}"
        
        # Log intervention start
        db = await get_database()
        await db.execute(
            """
            INSERT INTO intervention_log 
            (task_id, domain, intervention_type, notification_sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, domain, event_type, datetime.utcnow().isoformat()),
        )
        
        # Send notification
        title = f"Lancet: {event_type.upper()}"
        notify_message = f"{message}\n\nURL: {url}\nTimeout: {timeout_seconds}秒"
        
        sent = await self.send_toast(title, notify_message, timeout_seconds=timeout_seconds)
        
        if not sent:
            logger.warning("Notification not sent", event_type=event_type, domain=domain)
        
        # Store pending intervention
        self._pending_interventions[intervention_id] = {
            "event_type": event_type,
            "url": url,
            "domain": domain,
            "started_at": datetime.utcnow(),
            "timeout_seconds": timeout_seconds,
            "task_id": task_id,
        }
        
        logger.info(
            "Intervention requested",
            intervention_id=intervention_id,
            event_type=event_type,
            domain=domain,
            timeout=timeout_seconds,
        )
        
        return {
            "shown": sent,
            "intervention_id": intervention_id,
            "deadline_at": (
                datetime.utcnow().isoformat() + f"+{timeout_seconds}s"
            ),
        }
    
    async def check_intervention_status(
        self,
        intervention_id: str,
    ) -> dict[str, Any]:
        """Check status of a pending intervention.
        
        Args:
            intervention_id: Intervention ID.
            
        Returns:
            Status dict.
        """
        intervention = self._pending_interventions.get(intervention_id)
        
        if intervention is None:
            return {"status": "unknown", "intervention_id": intervention_id}
        
        elapsed = (datetime.utcnow() - intervention["started_at"]).total_seconds()
        timeout = intervention["timeout_seconds"]
        
        if elapsed >= timeout:
            return {
                "status": "timeout",
                "intervention_id": intervention_id,
                "elapsed_seconds": elapsed,
            }
        
        return {
            "status": "pending",
            "intervention_id": intervention_id,
            "remaining_seconds": timeout - elapsed,
        }
    
    async def complete_intervention(
        self,
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
        intervention = self._pending_interventions.pop(intervention_id, None)
        
        if intervention is None:
            logger.warning("Unknown intervention completed", id=intervention_id)
            return
        
        elapsed = (datetime.utcnow() - intervention["started_at"]).total_seconds()
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
                datetime.utcnow().isoformat(),
                result,
                int(elapsed),
                notes,
                intervention["domain"],
                intervention["event_type"],
            ),
        )
        
        logger.info(
            "Intervention completed",
            intervention_id=intervention_id,
            success=success,
            duration=elapsed,
        )


# Global manager
_manager: NotificationManager | None = None


def _get_manager() -> NotificationManager:
    """Get or create notification manager."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager


async def notify_user(
    event: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send notification to user.
    
    Args:
        event: Event type.
        payload: Event payload.
        
    Returns:
        Notification result.
    """
    manager = _get_manager()
    
    if event in ("captcha", "login_required", "cookie_banner", "cloudflare"):
        # These require intervention
        return await manager.request_intervention(
            event_type=event,
            url=payload.get("url", ""),
            domain=payload.get("domain", "unknown"),
            message=payload.get("message", f"{event} detected"),
            timeout_seconds=payload.get("timeout_seconds"),
            task_id=payload.get("task_id"),
        )
    else:
        # Simple notification
        title = f"Lancet: {event.upper()}"
        message = payload.get("message", "")
        
        sent = await manager.send_toast(title, message)
        
        return {
            "shown": sent,
            "event": event,
        }

