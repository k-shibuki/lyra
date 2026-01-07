"""Target queue handler for MCP tools.

Handles queue_targets operation (unified query + URL queueing).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from src.mcp.errors import InvalidParamsError, TaskNotFoundError
from src.storage.database import get_database
from src.utils.logging import LogContext, ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)

# Supported academic APIs (matches AcademicSearchProvider.API_PRIORITY.keys())
SUPPORTED_ACADEMIC_APIS: frozenset[str] = frozenset({"semantic_scholar", "openalex"})

# Valid URL schemes for url targets
VALID_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Valid reasons for URL ingestion
VALID_URL_REASONS: frozenset[str] = frozenset({"citation_chase", "manual"})


def _get_available_serp_engines() -> list[str]:
    """Get list of available SERP engines (parser + config)."""
    from src.search.parsers import get_available_parsers

    return get_available_parsers()


def _validate_serp_engines(serp_engines: list[str] | None) -> None:
    """Validate serp_engines option.

    Args:
        serp_engines: List of SERP engine names to validate.

    Raises:
        InvalidParamsError: If any engine is unknown or list is empty.
    """
    if serp_engines is None:
        return  # None means auto-selection (valid)

    if not isinstance(serp_engines, list):
        raise InvalidParamsError(
            "serp_engines must be an array of strings",
            param_name="options.serp_engines",
            expected="array of strings",
        )

    if len(serp_engines) == 0:
        raise InvalidParamsError(
            "serp_engines cannot be empty; omit the field for auto-selection",
            param_name="options.serp_engines",
            expected="non-empty array or omit",
        )

    available = set(_get_available_serp_engines())
    unknown = [e for e in serp_engines if e not in available]

    if unknown:
        raise InvalidParamsError(
            f"Unknown SERP engine(s): {unknown}. Available: {sorted(available)}",
            param_name="options.serp_engines",
            expected=f"one of {sorted(available)}",
        )


def _validate_academic_apis(academic_apis: list[str] | None) -> None:
    """Validate academic_apis option.

    Args:
        academic_apis: List of academic API names to validate.

    Raises:
        InvalidParamsError: If any API is unknown or list is empty.
    """
    if academic_apis is None:
        return  # None means default (both APIs)

    if not isinstance(academic_apis, list):
        raise InvalidParamsError(
            "academic_apis must be an array of strings",
            param_name="options.academic_apis",
            expected="array of strings",
        )

    if len(academic_apis) == 0:
        raise InvalidParamsError(
            "academic_apis cannot be empty; omit the field for default (both APIs)",
            param_name="options.academic_apis",
            expected="non-empty array or omit",
        )

    unknown = [a for a in academic_apis if a not in SUPPORTED_ACADEMIC_APIS]

    if unknown:
        raise InvalidParamsError(
            f"Unknown academic API(s): {unknown}. Available: {sorted(SUPPORTED_ACADEMIC_APIS)}",
            param_name="options.academic_apis",
            expected=f"one of {sorted(SUPPORTED_ACADEMIC_APIS)}",
        )


def _validate_url(url: str, index: int) -> None:
    """Validate a URL for URL target.

    Args:
        url: URL string to validate.
        index: Target index for error messages.

    Raises:
        InvalidParamsError: If URL is invalid.
    """
    if not url or not isinstance(url, str):
        raise InvalidParamsError(
            f"targets[{index}].url must be a non-empty string",
            param_name=f"targets[{index}].url",
            expected="non-empty URL string",
        )

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise InvalidParamsError(
            f"targets[{index}].url is not a valid URL: {url[:100]}",
            param_name=f"targets[{index}].url",
            expected="valid URL",
        ) from e

    if parsed.scheme not in VALID_URL_SCHEMES:
        raise InvalidParamsError(
            f"targets[{index}].url must use http or https scheme: {url[:100]}",
            param_name=f"targets[{index}].url",
            expected="http or https URL",
        )

    if not parsed.netloc:
        raise InvalidParamsError(
            f"targets[{index}].url must have a valid host: {url[:100]}",
            param_name=f"targets[{index}].url",
            expected="URL with valid host",
        )


def _validate_doi(doi: str, index: int) -> None:
    """Validate a DOI for DOI target.

    Args:
        doi: DOI string to validate.
        index: Target index for error messages.

    Raises:
        InvalidParamsError: If DOI is invalid.
    """
    import re

    if not doi or not isinstance(doi, str):
        raise InvalidParamsError(
            f"targets[{index}].doi must be a non-empty string",
            param_name=f"targets[{index}].doi",
            expected="non-empty DOI string",
        )

    # Basic DOI format validation: starts with 10. and has a /
    # DOI format: 10.XXXX/YYYY (prefix/suffix)
    doi_pattern = re.compile(r"^10\.\d{4,}/\S+$")
    if not doi_pattern.match(doi):
        raise InvalidParamsError(
            f"targets[{index}].doi is not a valid DOI format: {doi[:100]}",
            param_name=f"targets[{index}].doi",
            expected="DOI in format 10.XXXX/suffix",
        )


def _validate_target(target: dict[str, Any], index: int) -> Literal["query", "url", "doi"]:
    """Validate a single target and return its kind.

    Args:
        target: Target dict to validate.
        index: Target index for error messages.

    Returns:
        Target kind ('query', 'url', or 'doi').

    Raises:
        InvalidParamsError: If target is invalid.
    """
    if not isinstance(target, dict):
        raise InvalidParamsError(
            f"targets[{index}] must be an object",
            param_name=f"targets[{index}]",
            expected="object with kind field",
        )

    kind = target.get("kind")
    if kind not in ("query", "url", "doi"):
        raise InvalidParamsError(
            f"targets[{index}].kind must be 'query', 'url', or 'doi', got: {kind}",
            param_name=f"targets[{index}].kind",
            expected="'query', 'url', or 'doi'",
        )

    if kind == "query":
        query = target.get("query")
        if not query or not isinstance(query, str):
            raise InvalidParamsError(
                f"targets[{index}].query must be a non-empty string",
                param_name=f"targets[{index}].query",
                expected="non-empty query string",
            )
    elif kind == "url":
        _validate_url(target.get("url", ""), index)

        # Validate depth
        depth = target.get("depth", 0)
        if not isinstance(depth, int) or depth < 0:
            raise InvalidParamsError(
                f"targets[{index}].depth must be a non-negative integer",
                param_name=f"targets[{index}].depth",
                expected="non-negative integer",
            )

        # Validate reason
        reason = target.get("reason", "manual")
        if reason not in VALID_URL_REASONS:
            raise InvalidParamsError(
                f"targets[{index}].reason must be one of {sorted(VALID_URL_REASONS)}",
                param_name=f"targets[{index}].reason",
                expected=f"one of {sorted(VALID_URL_REASONS)}",
            )
    else:  # kind == "doi"
        _validate_doi(target.get("doi", ""), index)

        # Validate reason (optional, defaults to 'manual')
        reason = target.get("reason", "manual")
        if reason not in VALID_URL_REASONS:  # Same valid reasons as URL
            raise InvalidParamsError(
                f"targets[{index}].reason must be one of {sorted(VALID_URL_REASONS)}",
                param_name=f"targets[{index}].reason",
                expected=f"one of {sorted(VALID_URL_REASONS)}",
            )

    return kind  # type: ignore


async def handle_queue_targets(args: dict[str, Any]) -> dict[str, Any]:
    """
    Handle queue_targets tool call.

    Queues multiple targets (queries or URLs) for background execution.
    Returns immediately with queued count and target IDs.

    Supports two target kinds:
    - kind='query': Search query execution
    - kind='url': Direct URL ingestion for citation chasing

    Args:
        task_id: Task ID
        targets: List of target objects with kind='query' or kind='url'
        options: Optional options (applied to all targets)

    Returns:
        {ok: true, queued_count: N, target_ids: [...], ...}
    """
    task_id = args.get("task_id")
    targets = args.get("targets", [])
    options = args.get("options", {})

    # Validation
    if not task_id:
        raise InvalidParamsError(
            "task_id is required",
            param_name="task_id",
            expected="non-empty string",
        )

    if not targets or len(targets) == 0:
        raise InvalidParamsError(
            "targets must not be empty",
            param_name="targets",
            expected="non-empty array of target objects",
        )

    # Validate all targets first
    for i, target in enumerate(targets):
        _validate_target(target, i)

    # Validate serp_engines and academic_apis for query targets
    _validate_serp_engines(options.get("serp_engines"))
    _validate_academic_apis(options.get("academic_apis"))

    with LogContext(task_id=task_id):
        # Verify task exists and check status
        db = await get_database()
        task = await db.fetch_one(
            "SELECT id, status FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            raise TaskNotFoundError(task_id)

        # Get task status (supports both dict and tuple access)
        task_status = task["status"] if isinstance(task, dict) else task[1]

        # Reject failed tasks (terminal state)
        if task_status == "failed":
            raise InvalidParamsError(
                "Cannot queue targets on a failed task",
                param_name="task_id",
                expected="task in created, exploring, or paused state",
            )

        # Log resume for paused tasks (this is the expected resumption flow)
        if task_status == "paused":
            logger.info(
                "Resuming paused task with new targets",
                task_id=task_id,
                previous_status=task_status,
            )

        # Determine priority value from string
        priority_str = options.get("priority", "medium")
        priority_map = {"high": 10, "medium": 50, "low": 90}
        priority_value = priority_map.get(priority_str, 50)

        # Queue each target (with duplicate detection)
        target_ids: list[str] = []
        skipped_count = 0
        now = datetime.now(UTC).isoformat()

        for target in targets:
            kind = target["kind"]

            if kind == "query":
                query = target["query"]
                # Check for duplicate query in same task (queued or running)
                existing = await db.fetch_one(
                    """
                    SELECT id FROM jobs
                    WHERE task_id = ? AND kind = 'target_queue'
                      AND state IN ('queued', 'running')
                      AND json_extract(input_json, '$.target.kind') = 'query'
                      AND json_extract(input_json, '$.target.query') = ?
                    """,
                    (task_id, query),
                )
                if existing:
                    logger.debug(
                        "Skipping duplicate query",
                        task_id=task_id,
                        query=query[:50],
                        existing_id=(
                            existing.get("id") if isinstance(existing, dict) else existing[0]
                        ),
                    )
                    skipped_count += 1
                    continue

                target_id = f"tq_{uuid.uuid4().hex[:12]}"
                input_data = {
                    "target": {
                        "kind": "query",
                        "query": query,
                        "options": target.get("options", {}),
                    },
                    "options": {k: v for k, v in options.items() if k != "priority"},
                }

            elif kind == "url":
                url = target["url"]
                depth = target.get("depth", 0)
                reason = target.get("reason", "manual")

                # Check for duplicate URL in same task (queued or running)
                existing = await db.fetch_one(
                    """
                    SELECT id FROM jobs
                    WHERE task_id = ? AND kind = 'target_queue'
                      AND state IN ('queued', 'running')
                      AND json_extract(input_json, '$.target.kind') = 'url'
                      AND json_extract(input_json, '$.target.url') = ?
                    """,
                    (task_id, url),
                )
                if existing:
                    logger.debug(
                        "Skipping duplicate URL",
                        task_id=task_id,
                        url=url[:100],
                        existing_id=(
                            existing.get("id") if isinstance(existing, dict) else existing[0]
                        ),
                    )
                    skipped_count += 1
                    continue

                target_id = f"tu_{uuid.uuid4().hex[:12]}"
                input_data = {
                    "target": {
                        "kind": "url",
                        "url": url,
                        "depth": depth,
                        "reason": reason,
                        "context": target.get("context", {}),
                        "policy": target.get("policy", {}),
                    },
                    "options": {k: v for k, v in options.items() if k != "priority"},
                }

            else:  # kind == "doi"
                doi = target["doi"]
                reason = target.get("reason", "manual")

                # Check for duplicate DOI in same task (queued or running)
                existing = await db.fetch_one(
                    """
                    SELECT id FROM jobs
                    WHERE task_id = ? AND kind = 'target_queue'
                      AND state IN ('queued', 'running')
                      AND json_extract(input_json, '$.target.kind') = 'doi'
                      AND json_extract(input_json, '$.target.doi') = ?
                    """,
                    (task_id, doi),
                )
                if existing:
                    logger.debug(
                        "Skipping duplicate DOI",
                        task_id=task_id,
                        doi=doi[:50],
                        existing_id=(
                            existing.get("id") if isinstance(existing, dict) else existing[0]
                        ),
                    )
                    skipped_count += 1
                    continue

                target_id = f"td_{uuid.uuid4().hex[:12]}"
                input_data = {
                    "target": {
                        "kind": "doi",
                        "doi": doi,
                        "reason": reason,
                        "context": target.get("context", {}),
                    },
                    "options": {k: v for k, v in options.items() if k != "priority"},
                }

            # Insert into jobs table (kind='target_queue')
            await db.execute(
                """
                INSERT INTO jobs
                    (id, task_id, kind, priority, slot, state, input_json, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    task_id,
                    "target_queue",
                    priority_value,
                    "network_client",
                    "queued",
                    json.dumps(input_data, ensure_ascii=False),
                    now,
                ),
            )
            target_ids.append(target_id)

        query_count = sum(1 for t in targets if t["kind"] == "query")
        url_count = sum(1 for t in targets if t["kind"] == "url")
        logger.info(
            "Targets queued",
            task_id=task_id,
            queued=len(target_ids),
            skipped=skipped_count,
            queries=query_count,
            urls=url_count,
            priority=priority_str,
        )

        # Update task status to exploring if new targets were queued
        # This resumes paused tasks automatically
        if len(target_ids) > 0 and task_status in ("paused", "created"):
            await db.execute(
                "UPDATE tasks SET status = 'exploring' WHERE id = ?",
                (task_id,),
            )
            logger.debug(
                "Task status updated to exploring",
                task_id=task_id,
                previous_status=task_status,
            )

        message = f"{len(target_ids)} targets queued"
        if skipped_count > 0:
            message += f" ({skipped_count} duplicates skipped)"
        message += ". Use get_status(wait=180) to monitor progress."

        # Include resume info for previously paused tasks
        was_resumed = task_status == "paused" and len(target_ids) > 0
        return {
            "ok": True,
            "queued_count": len(target_ids),
            "skipped_count": skipped_count,
            "target_ids": target_ids,
            "message": message,
            "task_resumed": was_resumed,
        }
