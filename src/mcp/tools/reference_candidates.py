"""Reference candidates handler for MCP tools.

Handles queue_reference_candidates operation for Citation Chasing UX.
Provides include/exclude control over v_reference_candidates.
"""

import re
import uuid
from typing import Any

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.storage.database import get_database
from src.storage.view_manager import ViewManager
from src.utils.logging import CausalTrace, LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)


def _extract_doi_from_url(url: str) -> str | None:
    """Extract DOI from URL if possible.

    Supports:
    - https://doi.org/10.xxxx/...
    - https://dx.doi.org/10.xxxx/...
    - URLs containing /10.xxxx/ pattern

    Args:
        url: URL to extract DOI from

    Returns:
        DOI string or None
    """
    # Direct DOI URLs
    doi_url_patterns = [
        r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,}/\S+)",
        r"(?:https?://)?.*/(10\.\d{4,}/[^/\s]+)",
    ]

    for pattern in doi_url_patterns:
        match = re.search(pattern, url)
        if match:
            doi = match.group(1)
            # Clean up trailing punctuation
            doi = doi.rstrip(".,;:)")
            return doi.lower()

    return None


async def handle_queue_reference_candidates(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle queue_reference_candidates tool call.

    Queries v_reference_candidates and enqueues selected candidates to target_queue.
    Provides include/exclude control for explicit candidate selection.

    Args (from MCP):
        task_id: Task ID (required)
        include_ids: List of citation_edge_ids to include (whitelist mode)
        exclude_ids: List of citation_edge_ids to exclude (blacklist mode)
        limit: Maximum candidates to enqueue (default: 10)
        dry_run: If true, return candidates without enqueuing (default: false)
        options: Queue options (priority, etc.)

    Logic:
        - If include_ids provided: Only enqueue those specific candidates
        - If exclude_ids provided: Enqueue all except those
        - If neither: Enqueue up to limit candidates (sorted by view's ORDER BY)

    DOI Optimization:
        - If candidate URL can be resolved to a DOI, uses kind='doi' for Academic API fast path
        - Otherwise uses kind='url' for web fetch

    Returns:
        {ok: true, queued_count: N, candidates: [...], dry_run: bool, ...}
    """
    task_id = args.get("task_id")
    include_ids = args.get("include_ids", [])
    exclude_ids = args.get("exclude_ids", [])
    limit = args.get("limit", 10)
    dry_run = args.get("dry_run", False)
    options = args.get("options", {})

    # Validation
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if include_ids and exclude_ids:
        raise InvalidParamsError(
            "Cannot specify both include_ids and exclude_ids",
            param_name="include_ids/exclude_ids",
            expected="only one of include_ids or exclude_ids",
        )

    if not isinstance(limit, int) or limit < 1:
        raise InvalidParamsError(
            "limit must be a positive integer",
            param_name="limit",
            expected="positive integer",
        )

    with LogContext(task_id=task_id):
        db = await get_database()

        # Verify task exists
        task = await db.fetch_one(
            "SELECT id, status FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        task_status = task["status"] if isinstance(task, dict) else task[1]

        if task_status == "failed":
            raise InvalidParamsError(
                "Cannot queue reference candidates on a failed task",
                param_name="task_id",
                expected="task in created, exploring, or paused state",
            )

        # Query v_reference_candidates view
        view_manager = ViewManager()
        view_sql = view_manager.render("v_reference_candidates", task_id=task_id)

        # Execute view query
        rows = await db.fetch_all(view_sql)

        if not rows:
            logger.info(
                "No reference candidates found",
                task_id=task_id,
            )
            return {
                "ok": True,
                "queued_count": 0,
                "skipped_count": 0,
                "candidates": [],
                "dry_run": dry_run,
                "message": "No reference candidates found for this task",
            }

        # Convert rows to list of dicts
        candidates = []
        for row in rows:
            if isinstance(row, dict):
                candidates.append(row)
            else:
                # Tuple/sqlite3.Row - convert using column names from view
                candidates.append(
                    {
                        "citation_edge_id": row[0],
                        "candidate_page_id": row[1],
                        "candidate_url": row[2],
                        "candidate_domain": row[3],
                        "candidate_html_path": row[4],
                        "citation_context": row[5],
                        "citation_source": row[6],
                        "citing_page_id": row[7],
                        "citing_page_url": row[8],
                        "citing_domain": row[9],
                        "citing_depth": row[10],
                        "citing_reason": row[11],
                        "citation_created_at": row[12],
                    }
                )

        # Apply include/exclude filtering
        if include_ids:
            include_set = set(include_ids)
            candidates = [c for c in candidates if c["citation_edge_id"] in include_set]
        elif exclude_ids:
            exclude_set = set(exclude_ids)
            candidates = [c for c in candidates if c["citation_edge_id"] not in exclude_set]

        # Apply limit
        candidates = candidates[:limit]

        if not candidates:
            logger.info(
                "No candidates after filtering",
                task_id=task_id,
                include_ids=len(include_ids) if include_ids else 0,
                exclude_ids=len(exclude_ids) if exclude_ids else 0,
            )
            return {
                "ok": True,
                "queued_count": 0,
                "skipped_count": 0,
                "candidates": [],
                "dry_run": dry_run,
                "message": "No candidates remaining after include/exclude filtering",
            }

        # Prepare targets for queueing
        targets_to_queue: list[dict[str, Any]] = []
        for candidate in candidates:
            url = candidate["candidate_url"]
            citing_page_id = candidate["citing_page_id"]
            citation_context = candidate.get("citation_context", "")

            # Try to extract DOI for fast path
            doi = _extract_doi_from_url(url)

            target: dict[str, Any]
            if doi:
                # DOI target (Academic API fast path)
                target = {
                    "kind": "doi",
                    "doi": doi,
                    "reason": "citation_chase",
                    "context": {
                        "source_page_id": citing_page_id,
                        "citation_context": citation_context[:500] if citation_context else None,
                        "original_url": url,
                    },
                }
            else:
                # URL target (web fetch)
                target = {
                    "kind": "url",
                    "url": url,
                    "depth": 1,  # Citation chase is always depth 1 from citing page
                    "reason": "citation_chase",
                    "context": {
                        "source_page_id": citing_page_id,
                        "citation_context": citation_context[:500] if citation_context else None,
                    },
                }

            targets_to_queue.append(
                {
                    "target": target,
                    "candidate": candidate,
                }
            )

        # If dry_run, return candidates without queueing
        if dry_run:
            logger.info(
                "Dry run: returning candidates without queueing",
                task_id=task_id,
                candidate_count=len(targets_to_queue),
            )
            return {
                "ok": True,
                "queued_count": 0,
                "skipped_count": 0,
                "candidates": [
                    {
                        "citation_edge_id": t["candidate"]["citation_edge_id"],
                        "url": t["candidate"]["candidate_url"],
                        "kind": t["target"]["kind"],
                        "doi": t["target"].get("doi"),
                        "citing_url": t["candidate"]["citing_page_url"],
                        "citation_context": t["candidate"].get("citation_context", "")[:200],
                    }
                    for t in targets_to_queue
                ],
                "dry_run": True,
                "message": f"Dry run: {len(targets_to_queue)} candidates would be queued",
            }

        # Queue targets via JobScheduler
        from src.scheduler.jobs import JobKind, get_scheduler

        scheduler = await get_scheduler()

        priority_str = options.get("priority", "medium")
        priority_map = {"high": 10, "medium": 50, "low": 90}
        priority_value = priority_map.get(priority_str, 50)

        target_ids = []
        skipped_count = 0

        # Create a causal trace for this queue_reference_candidates operation
        trace = CausalTrace()

        for item in targets_to_queue:
            target = item["target"]
            kind = target["kind"]

            # Check for duplicates
            if kind == "doi":
                existing = await db.fetch_one(
                    """
                    SELECT id FROM jobs
                    WHERE task_id = ? AND kind = 'target_queue'
                      AND state IN ('queued', 'running')
                      AND json_extract(input_json, '$.target.kind') = 'doi'
                      AND json_extract(input_json, '$.target.doi') = ?
                    """,
                    (task_id, target["doi"]),
                )
            else:
                existing = await db.fetch_one(
                    """
                    SELECT id FROM jobs
                    WHERE task_id = ? AND kind = 'target_queue'
                      AND state IN ('queued', 'running')
                      AND json_extract(input_json, '$.target.kind') = 'url'
                      AND json_extract(input_json, '$.target.url') = ?
                    """,
                    (task_id, target["url"]),
                )

            if existing:
                skipped_count += 1
                continue

            input_data = {
                "target": target,
                "options": {k: v for k, v in options.items() if k != "priority"},
            }

            # Submit to JobScheduler (ADR-0010: unified job execution)
            result = await scheduler.submit(
                kind=JobKind.TARGET_QUEUE,
                input_data=input_data,
                priority=priority_value,
                task_id=task_id,
                cause_id=trace.id,
            )
            if result.get("accepted"):
                target_ids.append(result["job_id"])

        # Update task status to exploring if needed
        if len(target_ids) > 0 and task_status in ("paused", "created"):
            await db.execute(
                "UPDATE tasks SET status = 'exploring' WHERE id = ?",
                (task_id,),
            )

        doi_count = sum(1 for t in targets_to_queue if t["target"]["kind"] == "doi")
        url_count = len(targets_to_queue) - doi_count

        logger.info(
            "Reference candidates queued",
            task_id=task_id,
            queued=len(target_ids),
            skipped=skipped_count,
            doi_targets=doi_count,
            url_targets=url_count,
            priority=priority_str,
        )

        message = f"{len(target_ids)} reference candidates queued"
        if skipped_count > 0:
            message += f" ({skipped_count} duplicates skipped)"
        message += ". Use get_status(wait=180) to monitor progress."

        return {
            "ok": True,
            "queued_count": len(target_ids),
            "skipped_count": skipped_count,
            "target_ids": target_ids,
            "candidates": [
                {
                    "citation_edge_id": item["candidate"]["citation_edge_id"],
                    "url": item["candidate"]["candidate_url"],
                    "kind": item["target"]["kind"],
                    "doi": item["target"].get("doi"),
                    "queued": item["target"]["kind"] == "doi"
                    and f"td_{uuid.uuid4().hex[:12]}" in target_ids
                    or item["target"]["kind"] == "url"
                    and f"tu_{uuid.uuid4().hex[:12]}" in target_ids,
                }
                for item in targets_to_queue
            ][:10],  # Limit response size
            "dry_run": False,
            "message": message,
            "summary": {
                "total_candidates": len(candidates),
                "doi_targets": doi_count,
                "url_targets": url_count,
            },
        }
