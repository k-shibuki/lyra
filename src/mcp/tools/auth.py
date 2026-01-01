"""Authentication queue handlers for MCP tools.

Handles get_auth_queue, resolve_auth, and related operations.
"""

from datetime import UTC, datetime
from typing import Any

from src.mcp.errors import InvalidParamsError
from src.search.circuit_breaker import get_circuit_breaker_manager
from src.storage.database import get_database
from src.utils.intervention_queue import get_intervention_queue
from src.utils.logging import ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


async def handle_get_auth_queue(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle get_auth_queue tool call.

    Implements ADR-0003: Get pending authentication queue.
    Supports grouping by domain/type and priority filtering.
    """
    task_id = args.get("task_id")
    group_by = args.get("group_by", "none")
    priority_filter = args.get("priority_filter", "all")

    queue = get_intervention_queue()

    # Get pending items using existing get_pending method
    items = await queue.get_pending(
        task_id=task_id,
        priority=priority_filter if priority_filter != "all" else None,
    )

    # Group if requested
    if group_by == "domain":
        grouped: dict[str, list] = {}
        for item in items:
            domain = item.get("domain", "unknown")
            if domain not in grouped:
                grouped[domain] = []
            grouped[domain].append(item)

        return {
            "ok": True,
            "group_by": "domain",
            "groups": grouped,
            "total_count": len(items),
        }

    elif group_by == "type":
        grouped = {}
        for item in items:
            auth_type = item.get("auth_type", "unknown")
            if auth_type not in grouped:
                grouped[auth_type] = []
            grouped[auth_type].append(item)

        return {
            "ok": True,
            "group_by": "type",
            "groups": grouped,
            "total_count": len(items),
        }

    else:  # no grouping
        return {
            "ok": True,
            "group_by": "none",
            "items": items,
            "total_count": len(items),
        }


async def capture_auth_session_cookies(domain: str) -> dict | None:
    """Capture cookies from browser for authentication session storage.

    Per ADR-0007: Capture session data after authentication completion
    so subsequent requests can reuse the authenticated session.

    This function connects to the existing Chrome browser via CDP and
    retrieves cookies from all existing contexts, filtering for the target domain.

    Args:
        domain: Domain to capture cookies for.

    Returns:
        Session data dict with cookies, or None if capture failed.
    """
    try:
        # Connect to existing Chrome browser via CDP
        from playwright.async_api import async_playwright

        from src.crawler.session_transfer import CookieData
        from src.utils.config import get_settings

        settings = get_settings()
        chrome_host = getattr(settings.browser, "chrome_host", "localhost")
        # Use base port (worker 0) for page retrieval
        chrome_port = getattr(settings.browser, "chrome_base_port", 9222)
        cdp_url = f"http://{chrome_host}:{chrome_port}"

        playwright = await async_playwright().start()

        try:
            # Connect to existing Chrome instance
            browser = await playwright.chromium.connect_over_cdp(cdp_url)

            # Get all existing contexts (these contain cookies from user's browser session)
            existing_contexts = browser.contexts

            if not existing_contexts:
                logger.debug(
                    "No browser contexts found, skipping cookie capture",
                    domain=domain,
                )
                await playwright.stop()
                return None

            # Collect cookies from all contexts
            all_cookies = []
            for context in existing_contexts:
                try:
                    context_cookies = await context.cookies()
                    all_cookies.extend(context_cookies)
                except Exception as e:
                    logger.debug(
                        "Failed to get cookies from context",
                        error=str(e),
                    )
                    continue

            # Filter cookies that match the domain
            # Per HTTP cookie spec: cookies set for subdomain should not be sent to parent domain
            # Only parent domain cookies can be sent to subdomains
            domain_cookies = []
            for cookie in all_cookies:
                cookie_data = CookieData.from_playwright_cookie(dict(cookie))
                # Use CookieData.matches_domain() which correctly implements HTTP cookie domain matching
                # - Exact match: cookie.domain == target_domain
                # - Parent -> subdomain: cookie.domain="example.com" matches "sub.example.com"
                # - Subdomain -> parent: NOT allowed (correctly rejected)
                if cookie_data.matches_domain(domain):
                    domain_cookies.append(dict(cookie))

            await playwright.stop()

            if not domain_cookies:
                logger.debug(
                    "No cookies found for domain",
                    domain=domain,
                )
                return None

            session_data = {
                "cookies": domain_cookies,
                "captured_at": datetime.now(UTC).isoformat(),
                "domain": domain,
            }

            logger.info(
                "Captured authentication session cookies",
                domain=domain,
                cookie_count=len(domain_cookies),
                contexts_checked=len(existing_contexts),
            )

            return session_data

        except Exception:
            await playwright.stop()
            raise

    except Exception as e:
        logger.warning(
            "Failed to capture authentication session cookies",
            domain=domain,
            error=str(e),
        )
        return None


async def handle_resolve_auth(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle resolve_auth tool call.

    Implements ADR-0003: Report authentication completion or skip.
    Per ADR-0007: Captures session cookies on completion for reuse.
    Supports single item, domain-batch, or task-batch operations.
    """
    target = args.get("target", "item")
    action = args.get("action")
    success = args.get("success", True)

    if not action:
        raise InvalidParamsError(
            "action is required",
            param_name="action",
            expected="one of: complete, skip",
        )

    valid_actions = {"complete", "skip"}
    if action not in valid_actions:
        raise InvalidParamsError(
            f"Invalid action: {action}",
            param_name="action",
            expected="one of: complete, skip",
        )

    valid_targets = {"item", "domain", "task"}
    if target not in valid_targets:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain, task",
        )

    queue = get_intervention_queue()

    if target == "item":
        queue_id = args.get("queue_id")
        if not queue_id:
            raise InvalidParamsError(
                "queue_id is required when target=item",
                param_name="queue_id",
                expected="non-empty string",
            )

        if action == "complete":
            # Get domain from queue item for cookie capture
            item = await queue.get_item(queue_id)
            session_data = None
            if item and success:
                domain = item.get("domain")
                if domain:
                    session_data = await capture_auth_session_cookies(domain)

            result = await queue.complete(queue_id, success=success, session_data=session_data)
        else:  # skip
            result = await queue.skip(queue_ids=[queue_id])

        return {
            "ok": True,
            "target": "item",
            "queue_id": queue_id,
            "action": action,
            "success": success if action == "complete" else None,
        }

    elif target == "domain":
        domain = args.get("domain")
        if not domain:
            raise InvalidParamsError(
                "domain is required when target=domain",
                param_name="domain",
                expected="non-empty string",
            )

        if action == "complete":
            # Capture cookies for the domain
            session_data = None
            if success:
                session_data = await capture_auth_session_cookies(domain)

            result = await queue.complete_domain(domain, success=success, session_data=session_data)
            count = result.get("resolved_count", 0)

            # ADR-0007: Auto-requeue awaiting_auth jobs and reset circuit breaker
            requeued_count = 0
            if success:
                requeued_count = await requeue_awaiting_auth_jobs(domain)
                await reset_circuit_breaker_for_engine(domain)
        else:  # skip
            result = await queue.skip(domain=domain)
            count = result.get("skipped", 0)
            requeued_count = 0

        return {
            "ok": True,
            "target": "domain",
            "domain": domain,
            "action": action,
            "resolved_count": count,
            "requeued_count": requeued_count,  # ADR-0007
        }

    elif target == "task":
        task_id = args.get("task_id")
        if not task_id:
            raise InvalidParamsError(
                "task_id is required when target=task",
                param_name="task_id",
                expected="non-empty string",
            )

        if action == "complete":
            # Get all pending items for this task
            pending_items = await queue.get_pending(task_id=task_id)
            if not pending_items:
                return {
                    "ok": True,
                    "target": "task",
                    "task_id": task_id,
                    "action": action,
                    "resolved_count": 0,
                    "requeued_count": 0,
                }

            # Complete each item individually to capture session data per domain
            completed_count = 0
            domains_processed: set[str] = set()
            for item in pending_items:
                queue_id = item.get("id")
                domain = item.get("domain")
                if not queue_id:
                    continue

                # Capture session data only once per domain
                session_data = None
                if success and domain and domain not in domains_processed:
                    session_data = await capture_auth_session_cookies(domain)
                    domains_processed.add(domain)

                await queue.complete(queue_id, success=success, session_data=session_data)
                completed_count += 1

            # ADR-0007: Auto-requeue awaiting_auth jobs for all affected domains
            requeued_count = 0
            if success:
                for domain in domains_processed:
                    requeued_count += await requeue_awaiting_auth_jobs(domain)
                    await reset_circuit_breaker_for_engine(domain)

            return {
                "ok": True,
                "target": "task",
                "task_id": task_id,
                "action": action,
                "resolved_count": completed_count,
                "requeued_count": requeued_count,
            }
        else:  # skip
            result = await queue.skip(task_id=task_id)
            count = result.get("skipped", 0)

            return {
                "ok": True,
                "target": "task",
                "task_id": task_id,
                "action": action,
                "resolved_count": count,
                "requeued_count": 0,
            }

    else:
        raise InvalidParamsError(
            f"Invalid target: {target}",
            param_name="target",
            expected="one of: item, domain, task",
        )


async def requeue_awaiting_auth_jobs(domain: str) -> int:
    """Requeue jobs that were awaiting authentication for a domain.

    Per ADR-0007: When CAPTCHA is resolved, automatically requeue
    the associated search jobs so they are retried.

    Args:
        domain: The domain/engine that was authenticated.

    Returns:
        Number of jobs requeued.
    """
    db = await get_database()

    # Find and requeue awaiting_auth jobs linked to this domain
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        """
        UPDATE jobs
        SET state = 'queued', queued_at = ?, error_message = NULL
        WHERE id IN (
            SELECT search_job_id FROM intervention_queue
            WHERE domain = ? AND status = 'completed' AND search_job_id IS NOT NULL
        ) AND state = 'awaiting_auth'
        """,
        (now, domain),
    )

    requeued_count = getattr(cursor, "rowcount", 0)

    if requeued_count > 0:
        logger.info(
            "Requeued awaiting_auth jobs after auth resolution",
            domain=domain,
            requeued_count=requeued_count,
        )

    return requeued_count


async def reset_circuit_breaker_for_engine(engine: str) -> None:
    """Reset circuit breaker for an engine after auth resolution.

    Per ADR-0007: When auth is resolved, reset the circuit breaker
    so the engine becomes available immediately.

    Args:
        engine: The engine/domain to reset.
    """
    try:
        manager = await get_circuit_breaker_manager()
        breaker = await manager.get_breaker(engine)
        breaker.force_close()

        logger.info(
            "Circuit breaker reset after auth resolution",
            engine=engine,
        )
    except Exception as e:
        logger.warning(
            "Failed to reset circuit breaker",
            engine=engine,
            error=str(e),
        )
