"""Intervention queue management for authentication challenges.

Manages authentication queue for batch processing with database persistence.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.storage.database import Database

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


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
        # Import here to avoid circular dependency
        from src.utils.batch_notification import _get_batch_notification_manager

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
                from src.crawler.browser_fetcher import BrowserFetcher

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
                    # Import here to avoid circular dependency
                    from src.utils.intervention_manager import get_intervention_manager

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

