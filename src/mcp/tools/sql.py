"""SQL query handler for MCP tools.

Handles query_sql operation (read-only SQL execution).
"""

import asyncio
import re
import sqlite3
import time
from typing import Any

import aiosqlite

from src.mcp.errors import InvalidParamsError
from src.storage.database import get_database
from src.utils.logging import ensure_logging_configured, get_logger

ensure_logging_configured()
logger = get_logger(__name__)

# Forbidden SQL patterns (security)
FORBIDDEN_PATTERNS = [
    r"\bATTACH\b",  # file system access via attach
    r"\bDETACH\b",
    r"\bload_extension\b",  # arbitrary code execution
    r"\bCREATE\b",
    r"\bDROP\b",
    r"\bALTER\b",  # DDL
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bREPLACE\b",  # DML
    r"\bPRAGMA\b",  # avoid toggling query_only/trusted_schema/etc from user SQL
]


def _get_sql_error_hint(error_msg: str) -> str | None:
    """Generate helpful hints for common SQL errors.

    Args:
        error_msg: SQLite error message.

    Returns:
        Hint string or None if no hint available.
    """
    error_lower = error_msg.lower()

    # Computed columns (only in views, not base tables)
    if "no such column" in error_lower:
        # v_claim_evidence_summary computed columns
        if "bayesian_truth_confidence" in error_msg:
            return (
                "bayesian_truth_confidence is a computed column available only in "
                "v_claim_evidence_summary view. Use: SELECT * FROM v_claim_evidence_summary "
                "WHERE task_id = '...'"
            )
        if "support_count" in error_msg or "refute_count" in error_msg:
            return (
                "support_count/refute_count are computed columns available only in "
                "v_claim_evidence_summary view."
            )
        if "neutral_count" in error_msg or "evidence_count" in error_msg:
            return (
                "neutral_count/evidence_count are computed columns available only in "
                "v_claim_evidence_summary view."
            )
        if "controversy_score" in error_msg:
            return "controversy_score is a computed column available only in v_contradictions view."

        # task_id not present in some tables
        if "task_id" in error_msg:
            if "pages" in error_lower or "page" in error_lower:
                return (
                    "pages table does NOT have task_id (URL-based deduplication, global scope). "
                    "To filter by task, JOIN with claims or fragments via edges."
                )
            if "fragments" in error_lower or "fragment" in error_lower:
                return (
                    "fragments table does NOT have task_id. "
                    "Use: JOIN pages ON fragments.page_id = pages.id, then JOIN via edges to claims."
                )
            if "edges" in error_lower or "edge" in error_lower:
                return (
                    "edges table does NOT have task_id. "
                    "Use: JOIN claims c ON edges.target_id = c.id WHERE c.task_id = '...'"
                )

    # Table not found - guide to correct table
    if "no such table" in error_lower:
        # Guide users looking for bibliographic/metadata info
        if "metadata" in error_lower or "paper" in error_lower:
            return (
                "For bibliographic metadata (title, year, venue, doi, authors), use 'works' table. "
                "Pages link to works via pages.canonical_id → works.canonical_id."
            )
        if "author" in error_lower:
            return (
                "Author data is in 'work_authors' table (canonical_id, position, name, affiliation, orcid). "
                "JOIN with works: SELECT * FROM works w JOIN work_authors wa ON w.canonical_id = wa.canonical_id"
            )

    # Column not in expected table - guide to correct table
    if "no such column" in error_lower:
        # Authors column doesn't exist on works - use work_authors table
        if "authors" in error_msg and "work" in error_lower:
            return (
                "works table does not have 'authors' column. Use work_authors table instead: "
                "SELECT w.*, wa.name FROM works w JOIN work_authors wa ON w.canonical_id = wa.canonical_id"
            )
        # paper_id lookup
        if "paper_id" in error_msg:
            return (
                "To look up by paper_id (e.g., 's2:xxx', 'openalex:Wxxx'), use work_identifiers table: "
                "SELECT * FROM work_identifiers WHERE provider_paper_id = '...'"
            )

    return None


def validate_sql_text(sql: str) -> None:
    """Reject dangerous SQL patterns and multi-statement payloads.

    Args:
        sql: SQL query string.

    Raises:
        ValueError: If SQL contains forbidden patterns or multiple statements.
    """
    # Check for multiple statements
    sql_stripped = sql.strip().rstrip(";")
    if ";" in sql_stripped:
        raise ValueError("Multiple statements are not allowed")

    # Check for forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            raise ValueError(f"Forbidden SQL keyword detected: {pattern}")


def strip_limit_clause(sql: str) -> str:
    """Remove any trailing LIMIT clause from SQL to avoid conflicts with auto-added LIMIT.

    Args:
        sql: SQL query string.

    Returns:
        SQL string with LIMIT clause removed.
    """
    # Pattern matches LIMIT [number] [OFFSET number] at end of query
    # Handles: LIMIT 10, LIMIT 10 OFFSET 5, LIMIT 10, 5
    pattern = r"\s+LIMIT\s+\d+(?:\s*,\s*\d+|\s+OFFSET\s+\d+)?\s*;?\s*$"
    return re.sub(pattern, "", sql, flags=re.IGNORECASE)


def _get_underlying_sqlite3_connection(conn: aiosqlite.Connection) -> sqlite3.Connection:
    """
    Return the underlying sqlite3.Connection from an aiosqlite connection.

    aiosqlite uses an internal sqlite3 connection stored as a private attribute.
    This helper keeps the access in one place and fails loudly if the library
    changes internals.
    """
    raw: object | None = getattr(conn, "_conn", None) or getattr(conn, "connection", None)
    if raw is None or not isinstance(raw, sqlite3.Connection):
        raise RuntimeError("Failed to access underlying sqlite3.Connection from aiosqlite")
    return raw


def install_sqlite_guards(
    conn: aiosqlite.Connection, *, timeout_ms: int, max_vm_steps: int
) -> None:
    """
    Install SQLite authorizer + progress handler guards.

    Guards:
    - Deny risky opcodes (ATTACH/DETACH/PRAGMA, DDL/DML, extension loading)
    - Interrupt long-running queries by time budget and VM step budget
    """
    deadline = time.time() + (timeout_ms / 1000)
    step_budget = max_vm_steps
    # progress handler callback frequency (instructions between calls)
    callback_n = max(1000, step_budget // 1000)
    steps_used = 0

    # NOTE: sqlite3 in Python does not expose all opcode constants; use numeric codes.
    SQLITE_ATTACH = 26
    SQLITE_DETACH = 27
    SQLITE_PRAGMA = 19
    SQLITE_CREATE_INDEX = 1
    SQLITE_CREATE_TABLE = 2
    SQLITE_DROP_INDEX = 3
    SQLITE_DROP_TABLE = 4
    SQLITE_INSERT = 18
    SQLITE_UPDATE = 23
    SQLITE_DELETE = 9
    SQLITE_TRANSACTION = 22
    SQLITE_SAVEPOINT = 32
    SQLITE_FUNCTION = 31  # Can be used to call load_extension()

    def authorizer(
        action_code: int,
        param1: str | None,
        _param2: str | None,
        _dbname: str | None,
        source: str | None,
    ) -> int:
        # Deny file access / pragma / mutations / transactions.
        if action_code in (
            SQLITE_ATTACH,
            SQLITE_DETACH,
            SQLITE_PRAGMA,
            SQLITE_CREATE_INDEX,
            SQLITE_CREATE_TABLE,
            SQLITE_DROP_INDEX,
            SQLITE_DROP_TABLE,
            SQLITE_INSERT,
            SQLITE_UPDATE,
            SQLITE_DELETE,
            SQLITE_TRANSACTION,
            SQLITE_SAVEPOINT,
        ):
            return sqlite3.SQLITE_DENY

        # Deny only extension loading (keep other builtin functions usable)
        if action_code == SQLITE_FUNCTION and (param1 or "").lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def progress_handler() -> int:
        nonlocal steps_used
        steps_used += callback_n
        if steps_used >= step_budget:
            return 1
        if time.time() >= deadline:
            return 1
        return 0

    raw = _get_underlying_sqlite3_connection(conn)
    raw.set_authorizer(authorizer)
    raw.set_progress_handler(progress_handler, callback_n)


async def handle_query_sql(args: dict[str, Any]) -> dict[str, Any]:
    """Handle query_sql tool call.

    Executes read-only SQL against Evidence Graph database.

    Args:
        args: Tool arguments with 'sql' and optional 'options'.

    Returns:
        Query result dict with 'ok', 'rows', 'row_count', 'columns', etc.
    """
    sql = args.get("sql")
    options = args.get("options", {})

    if not sql:
        raise InvalidParamsError(
            "sql is required",
            param_name="sql",
            expected="non-empty string",
        )

    # Validate SQL
    try:
        validate_sql_text(sql)
    except ValueError as e:
        raise InvalidParamsError(
            str(e),
            param_name="sql",
            expected="read-only SELECT query",
        ) from e

    # Get options
    limit = options.get("limit", 50)
    timeout_ms = options.get("timeout_ms", 300)
    max_vm_steps = options.get("max_vm_steps", 500000)
    include_schema = options.get("include_schema", False)

    # Validate limits
    if limit < 1 or limit > 200:
        raise InvalidParamsError(
            "limit must be between 1 and 200",
            param_name="options.limit",
            expected="integer 1-200",
        )

    if timeout_ms < 1 or timeout_ms > 2000:
        raise InvalidParamsError(
            "timeout_ms must be between 1 and 2000",
            param_name="options.timeout_ms",
            expected="integer 1-2000",
        )

    if max_vm_steps < 1 or max_vm_steps > 5_000_000:
        raise InvalidParamsError(
            "max_vm_steps must be between 1 and 5000000",
            param_name="options.max_vm_steps",
            expected="integer 1-5000000",
        )

    start_time = time.time()

    try:
        db = await get_database()
        db_path = db.db_path

        # Use read-only connection with timeout
        async with aiosqlite.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=timeout_ms / 1000,
            # Required so we can install guards on the underlying sqlite3 connection.
            # The connection itself is still used via aiosqlite's worker thread.
            check_same_thread=False,
        ) as conn:
            conn.row_factory = aiosqlite.Row
            install_sqlite_guards(conn, timeout_ms=timeout_ms, max_vm_steps=max_vm_steps)

            # Execute query with limit (wrapped in asyncio.wait_for for timeout)
            # Strip any user-provided LIMIT clause to avoid duplication
            sql_clean = strip_limit_clause(sql.rstrip(";"))
            sql_with_limit = f"{sql_clean} LIMIT {limit + 1}"

            try:
                cursor = await asyncio.wait_for(
                    conn.execute(sql_with_limit),
                    timeout=timeout_ms / 1000,
                )
                rows = await cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
            except TimeoutError as e:
                raise ValueError(f"Query timeout after {timeout_ms}ms") from e

            # Check if truncated (convert to list for len/indexing)
            rows_list = list(rows)
            truncated = len(rows_list) > limit
            if truncated:
                rows_list = rows_list[:limit]

            # Convert rows to dicts
            result_rows = []
            for row in rows_list:
                row_dict = {}
                for col in columns:
                    value = row[col]
                    # Convert bytes to hex string
                    if isinstance(value, bytes):
                        value = value.hex()
                    row_dict[col] = value
                result_rows.append(row_dict)

            elapsed_ms = int((time.time() - start_time) * 1000)

            result: dict[str, Any] = {
                "ok": True,
                "rows": result_rows,
                "row_count": len(result_rows),
                "columns": columns,
                "truncated": truncated,
                "elapsed_ms": elapsed_ms,
            }

            # Add schema if requested (safe, predefined queries only)
            if include_schema:
                schema_tables = []
                # Do NOT use PRAGMA here (blocked by authorizer). Instead, parse sqlite_master.sql.
                schema_cursor = await conn.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'fts_%' "
                    "ORDER BY name"
                )
                tables = await schema_cursor.fetchall()

                def _parse_columns(create_sql: str | None) -> list[str]:
                    if not create_sql:
                        return []
                    # Extract "(...)" section and split by commas.
                    m = re.search(r"\\((.*)\\)", create_sql, re.DOTALL)
                    if not m:
                        return []
                    body = m.group(1)
                    cols: list[str] = []
                    for part in body.split(","):
                        token = part.strip().split()
                        if not token:
                            continue
                        head = token[0].strip('"`[]')
                        # Skip constraints / table-level clauses
                        if head.upper() in {"FOREIGN", "PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT"}:
                            continue
                        cols.append(head)
                    return cols

                for table_row in tables:
                    table_name = table_row["name"]
                    create_sql = table_row["sql"]
                    column_names = _parse_columns(create_sql)
                    schema_tables.append({"name": table_name, "columns": column_names})

                result["schema"] = {"tables": schema_tables}

            return result

    except aiosqlite.OperationalError as e:
        logger.warning("SQL execution error", error=str(e))

        # Common failure mode when SQLite interrupts due to progress handler.
        if "interrupted" in str(e).lower():
            return {
                "ok": False,
                "rows": [],
                "row_count": 0,
                "columns": [],
                "truncated": False,
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "error": "Query interrupted (timeout or max_vm_steps exceeded)",
            }

        # Provide helpful hints for common column/table errors
        error_msg = str(e)
        hint = _get_sql_error_hint(error_msg)

        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": error_msg,
            "hint": hint,
        }
    except ValueError as e:
        # Validation errors (timeout, forbidden patterns)
        logger.warning("SQL validation error", error=str(e))
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": str(e),
        }
    except Exception as e:
        logger.error("Unexpected error in query_sql", error=str(e), exc_info=True)
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": str(e),
        }
