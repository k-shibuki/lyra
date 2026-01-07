"""Batch notification management for CAPTCHA/auth queues.

Manages batched notifications per ADR-0007: Human-in-the-Loop Authentication.
"""

import asyncio
from datetime import UTC, datetime

from src.utils.logging import get_logger

logger = get_logger(__name__)


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

    async def on_target_queue_empty(self) -> None:
        """Called when the target queue becomes empty.

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
        # Import here to avoid circular dependency
        from src.utils.intervention_queue import get_intervention_queue

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
        # Import here to avoid circular dependency
        from src.utils.intervention_manager import _get_manager

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


async def notify_target_queue_empty() -> None:
    """Notify batch manager that target queue is empty.

    Called by TargetQueueWorkerManager when queue becomes empty.
    """
    await _get_batch_notification_manager().on_target_queue_empty()
