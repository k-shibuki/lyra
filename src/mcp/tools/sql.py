"""SQL query handler for MCP tools.

Handles query_graph operation (read-only SQL execution).
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
        param2: str | None,
        dbname: str | None,
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


async def handle_query_graph(args: dict[str, Any]) -> dict[str, Any]:
    """Handle query_graph tool call.

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
            sql_with_limit = f"{sql.rstrip(';')} LIMIT {limit + 1}"

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
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": str(e),
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
        logger.error("Unexpected error in query_graph", error=str(e), exc_info=True)
        return {
            "ok": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "truncated": False,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "error": str(e),
        }
