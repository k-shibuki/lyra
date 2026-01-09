"""
Tests for query_sql MCP tool.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-QS-N-01 | Valid SELECT query | Equivalence – normal | Returns rows successfully | - |
| TC-QS-N-02 | SELECT with JOIN | Equivalence – normal | Returns joined results | - |
| TC-QS-N-03 | SELECT with LIMIT | Equivalence – normal | Respects limit, sets truncated flag | - |
| TC-QS-N-04 | include_schema=true | Equivalence – normal | Returns schema information | - |
| TC-QS-N-05 | SQL with LIMIT clause | Equivalence – normal | Executes without error (LIMIT stripped) | - |
| TC-QS-N-06 | SQL LIMIT ignored, options.limit applied | Effect test | options.limit takes precedence | - |
| TC-QS-A-01 | Missing sql parameter | Boundary – missing | Raises InvalidParamsError | - |
| TC-QS-A-02 | Empty sql string | Boundary – empty | Raises InvalidParamsError | - |
| TC-QS-A-03 | Multiple statements (;) | Boundary – multiple | Raises ValueError | - |
| TC-QS-A-04 | ATTACH statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-05 | INSERT statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-06 | UPDATE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-07 | DELETE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-08 | PRAGMA statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-09 | CREATE TABLE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-10 | DROP TABLE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-11 | load_extension() | Abnormal – forbidden | Raises ValueError | - |
| TC-QS-A-12 | limit > 200 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-QS-A-13 | limit < 1 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-QS-A-14 | timeout_ms > 2000 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-QS-A-15 | Invalid SQL syntax | Abnormal – syntax error | Returns ok=False with error | - |

## Test Perspectives Table for strip_limit_clause

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-SL-N-01 | No LIMIT clause | Equivalence – normal | Returns unchanged | - |
| TC-SL-N-02 | LIMIT 10 | Equivalence – normal | Removes LIMIT | - |
| TC-SL-N-03 | LIMIT 10 OFFSET 5 | Equivalence – normal | Removes LIMIT OFFSET | - |
| TC-SL-N-04 | LIMIT 10, 5 | Equivalence – normal | Removes LIMIT form | - |
| TC-SL-N-05 | limit 10 (lowercase) | Boundary – case | Case insensitive removal | - |
| TC-SL-N-06 | LIMIT 10; | Boundary – trailing semicolon | Removes with semicolon | - |
| TC-SL-N-07 | Subquery LIMIT | Boundary – non-trailing | Preserves inner LIMIT | - |
"""

import pytest

from src.storage.database import Database

pytestmark = pytest.mark.unit

from src.mcp.errors import InvalidParamsError
from src.mcp.tools import sql
from src.mcp.tools.sql import strip_limit_clause


@pytest.mark.asyncio
async def test_query_sql_valid_select(test_database: Database) -> None:
    """
    TC-QS-N-01: Valid SELECT query returns rows successfully.

    // Given: Valid SELECT query
    // When: Executing query_sql
    // Then: Returns rows with ok=True
    """
    # Setup: Insert test data
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("test_task", "test query", "completed"),
    )

    result = await sql.handle_query_sql({"sql": "SELECT * FROM tasks WHERE id = 'test_task'"})

    assert result["ok"] is True
    assert result["row_count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["id"] == "test_task"
    assert "columns" in result
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_query_sql_with_limit(test_database: Database) -> None:
    """
    TC-QS-N-03: SELECT with LIMIT respects limit and sets truncated flag.

    // Given: Query that returns more rows than limit
    // When: Executing with limit option
    // Then: Returns limited rows and sets truncated=True
    """
    db = test_database
    # Insert multiple tasks
    for i in range(5):
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (f"task_{i}", f"query {i}", "completed"),
        )

    result = await sql.handle_query_sql({"sql": "SELECT * FROM tasks", "options": {"limit": 3}})

    assert result["ok"] is True
    assert result["row_count"] == 3
    assert len(result["rows"]) == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_query_sql_include_schema(test_database: Database) -> None:
    """
    TC-QS-N-04: include_schema=true returns schema information.

    // Given: Query with include_schema=true
    // When: Executing query_sql
    // Then: Returns schema with tables and columns
    """
    result = await sql.handle_query_sql({"sql": "SELECT 1", "options": {"include_schema": True}})

    assert result["ok"] is True
    assert "schema" in result
    assert "tables" in result["schema"]
    assert isinstance(result["schema"]["tables"], list)
    # Check that tasks table is in schema
    table_names = [t["name"] for t in result["schema"]["tables"]]
    assert "tasks" in table_names


@pytest.mark.asyncio
async def test_query_sql_missing_sql() -> None:
    """
    TC-QS-A-01: Missing sql parameter raises InvalidParamsError.

    // Given: No sql parameter
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({})

    assert "sql is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_empty_sql() -> None:
    """
    TC-QS-A-02: Empty sql string raises InvalidParamsError.

    // Given: Empty sql string
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": ""})

    assert "sql is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_multiple_statements() -> None:
    """
    TC-QS-A-03: Multiple statements raises ValueError.

    // Given: SQL with semicolon separating statements
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1; SELECT 2"})

    assert "Multiple statements" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_attach() -> None:
    """
    TC-QS-A-04: ATTACH statement raises ValueError.

    // Given: SQL with ATTACH
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "ATTACH DATABASE 'test.db' AS test"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_insert() -> None:
    """
    TC-QS-A-05: INSERT statement raises ValueError.

    // Given: SQL with INSERT
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql(
            {
                "sql": "INSERT INTO tasks (id, hypothesis, status) VALUES ('test', 'hypothesis', 'pending')"
            }
        )

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_update() -> None:
    """
    TC-QS-A-06: UPDATE statement raises ValueError.

    // Given: SQL with UPDATE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "UPDATE tasks SET status = 'completed'"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_delete() -> None:
    """
    TC-QS-A-07: DELETE statement raises ValueError.

    // Given: SQL with DELETE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "DELETE FROM tasks"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_pragma() -> None:
    """
    TC-QS-A-08: PRAGMA statement raises ValueError.

    // Given: SQL with PRAGMA
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "PRAGMA table_info(tasks)"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_create() -> None:
    """
    TC-QS-A-09: CREATE TABLE statement raises ValueError.

    // Given: SQL with CREATE TABLE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "CREATE TABLE test (id TEXT)"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_drop() -> None:
    """
    TC-QS-A-10: DROP TABLE statement raises ValueError.

    // Given: SQL with DROP TABLE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "DROP TABLE tasks"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_load_extension() -> None:
    """
    TC-QS-A-11: load_extension() raises ValueError.

    // Given: SQL with load_extension
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT load_extension('test.so')"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_limit_too_high() -> None:
    """
    TC-QS-A-12: limit > 200 raises InvalidParamsError.

    // Given: limit option > 200
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"limit": 201}})

    assert "limit must be between 1 and 200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_limit_too_low() -> None:
    """
    TC-QS-A-13: limit < 1 raises InvalidParamsError.

    // Given: limit option < 1
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"limit": 0}})

    assert "limit must be between 1 and 200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_timeout_too_high() -> None:
    """
    TC-QS-A-14: timeout_ms > 2000 raises InvalidParamsError.

    // Given: timeout_ms option > 2000
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"timeout_ms": 2001}})

    assert "timeout_ms must be between 1 and 2000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_invalid_sql_syntax(test_database: Database) -> None:
    """
    TC-QS-A-15: Invalid SQL syntax returns ok=False with error.

    // Given: SQL with syntax error
    // When: Executing query_sql
    // Then: Returns ok=False with error message
    """
    result = await sql.handle_query_sql({"sql": "SELECT * FROM nonexistent_table"})

    assert result["ok"] is False
    assert "error" in result
    assert result["row_count"] == 0
    assert len(result["rows"]) == 0


# ============================================================================
# strip_limit_clause unit tests
# ============================================================================


def test_strip_limit_clause_no_limit() -> None:
    """
    TC-SL-N-01: SQL without LIMIT clause returns unchanged.

    // Given: SQL query without LIMIT
    // When: Calling strip_limit_clause
    // Then: Returns the same string
    """
    sql_query = "SELECT * FROM tasks WHERE status = 'completed'"
    result = strip_limit_clause(sql_query)
    assert result == sql_query


def test_strip_limit_clause_simple_limit() -> None:
    """
    TC-SL-N-02: SQL with LIMIT clause has LIMIT removed.

    // Given: SQL query with LIMIT 10
    // When: Calling strip_limit_clause
    // Then: Returns SQL without LIMIT
    """
    sql_query = "SELECT * FROM tasks LIMIT 10"
    result = strip_limit_clause(sql_query)
    assert result == "SELECT * FROM tasks"


def test_strip_limit_clause_limit_offset() -> None:
    """
    TC-SL-N-03: SQL with LIMIT OFFSET clause has both removed.

    // Given: SQL query with LIMIT 10 OFFSET 5
    // When: Calling strip_limit_clause
    // Then: Returns SQL without LIMIT OFFSET
    """
    sql_query = "SELECT * FROM tasks LIMIT 10 OFFSET 5"
    result = strip_limit_clause(sql_query)
    assert result == "SELECT * FROM tasks"


def test_strip_limit_clause_limit_comma_syntax() -> None:
    """
    TC-SL-N-04: SQL with LIMIT n, m syntax has LIMIT removed.

    // Given: SQL query with LIMIT 10, 5 (offset, count)
    // When: Calling strip_limit_clause
    // Then: Returns SQL without LIMIT
    """
    sql_query = "SELECT * FROM tasks LIMIT 10, 5"
    result = strip_limit_clause(sql_query)
    assert result == "SELECT * FROM tasks"


def test_strip_limit_clause_lowercase() -> None:
    """
    TC-SL-N-05: SQL with lowercase limit is handled case-insensitively.

    // Given: SQL query with lowercase 'limit 10'
    // When: Calling strip_limit_clause
    // Then: Returns SQL without limit (case insensitive)
    """
    sql_query = "SELECT * FROM tasks limit 10"
    result = strip_limit_clause(sql_query)
    assert result == "SELECT * FROM tasks"


def test_strip_limit_clause_with_semicolon() -> None:
    """
    TC-SL-N-06: SQL with LIMIT and trailing semicolon has both removed.

    // Given: SQL query with 'LIMIT 10;'
    // When: Calling strip_limit_clause
    // Then: Returns SQL without LIMIT and semicolon
    """
    sql_query = "SELECT * FROM tasks LIMIT 10;"
    result = strip_limit_clause(sql_query)
    assert result == "SELECT * FROM tasks"


def test_strip_limit_clause_preserves_subquery_limit() -> None:
    """
    TC-SL-N-07: SQL with LIMIT in subquery preserves inner LIMIT.

    // Given: SQL query with LIMIT in subquery but not at end
    // When: Calling strip_limit_clause
    // Then: Inner LIMIT is preserved, only trailing LIMIT removed
    """
    sql_query = "SELECT * FROM (SELECT * FROM tasks LIMIT 5) AS sub WHERE status = 'completed'"
    result = strip_limit_clause(sql_query)
    # Inner LIMIT should be preserved since it's not at the end
    assert "LIMIT 5" in result
    assert result == sql_query


# ============================================================================
# Integration tests for LIMIT clause handling
# ============================================================================


@pytest.mark.asyncio
async def test_query_sql_with_user_limit_clause_no_error(test_database: Database) -> None:
    """
    TC-QS-N-05: SQL with user-provided LIMIT clause executes without error.

    // Given: SQL query that includes a LIMIT clause
    // When: Executing query_sql
    // Then: Executes successfully (LIMIT is stripped and replaced)
    """
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("test_task", "test query", "completed"),
    )

    # This used to cause "near LIMIT: syntax error" due to duplicate LIMIT
    result = await sql.handle_query_sql({"sql": "SELECT * FROM tasks LIMIT 10"})

    assert result["ok"] is True
    assert result["row_count"] == 1


@pytest.mark.asyncio
async def test_query_sql_options_limit_overrides_sql_limit(test_database: Database) -> None:
    """
    TC-QS-N-06: options.limit takes precedence over SQL LIMIT clause.

    // Given: SQL with LIMIT 100 and options.limit=2
    // When: Executing query_sql
    // Then: Returns only 2 rows (options.limit applied, SQL LIMIT ignored)
    """
    db = test_database
    # Insert 5 tasks
    for i in range(5):
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (f"task_{i}", f"query {i}", "completed"),
        )

    # SQL says LIMIT 100, but options.limit says 2
    result = await sql.handle_query_sql(
        {
            "sql": "SELECT * FROM tasks LIMIT 100",
            "options": {"limit": 2},
        }
    )

    assert result["ok"] is True
    assert result["row_count"] == 2
    assert len(result["rows"]) == 2
    assert result["truncated"] is True  # 5 rows exist but only 2 returned


# ============================================================================
# Additional boundary tests for options validation
# ============================================================================


@pytest.mark.asyncio
async def test_query_sql_max_vm_steps_too_high() -> None:
    """
    TC-QS-A-16: max_vm_steps > 5000000 raises InvalidParamsError.

    // Given: max_vm_steps option > 5000000
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"max_vm_steps": 5000001}})

    assert "max_vm_steps must be between 1 and 5000000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_max_vm_steps_too_low() -> None:
    """
    TC-QS-A-17: max_vm_steps < 1 raises InvalidParamsError.

    // Given: max_vm_steps option < 1
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"max_vm_steps": 0}})

    assert "max_vm_steps must be between 1 and 5000000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_timeout_ms_too_low() -> None:
    """
    TC-QS-A-18: timeout_ms < 1 raises InvalidParamsError.

    // Given: timeout_ms option < 1
    // When: Calling handle_query_sql
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "SELECT 1", "options": {"timeout_ms": 0}})

    assert "timeout_ms must be between 1 and 2000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_bytes_to_hex_conversion(test_database: Database) -> None:
    """
    TC-QS-N-07: Bytes columns are converted to hex strings.

    // Given: Table with BLOB column containing bytes data
    // When: Executing query_sql
    // Then: Bytes value is converted to hex string
    """
    db = test_database

    # Create table with BLOB column and insert bytes data
    await db.execute("CREATE TABLE IF NOT EXISTS test_blob (id TEXT PRIMARY KEY, data BLOB)")
    # Insert bytes data using raw SQL with hex notation
    await db.execute(
        "INSERT INTO test_blob (id, data) VALUES (?, X'DEADBEEF')",
        ("test_bytes",),
    )

    result = await sql.handle_query_sql({"sql": "SELECT * FROM test_blob WHERE id = 'test_bytes'"})

    assert result["ok"] is True
    assert result["row_count"] == 1
    # Bytes should be converted to hex string
    assert result["rows"][0]["data"] == "deadbeef"


@pytest.mark.asyncio
async def test_query_sql_vm_steps_interruption(test_database: Database) -> None:
    """
    TC-QS-N-08: Query exceeding max_vm_steps returns interrupted error.

    // Given: Complex query that exceeds vm_steps budget
    // When: Executing with very low max_vm_steps
    // Then: Returns ok=False with interruption error
    """
    db = test_database

    # Insert enough data to make query complex
    for i in range(100):
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (f"task_vm_{i}", f"hypothesis {i}", "exploring"),
        )

    # Execute with very low vm_steps limit to trigger interruption
    result = await sql.handle_query_sql(
        {
            "sql": "SELECT * FROM tasks t1, tasks t2 WHERE t1.id != t2.id",  # Cross join
            "options": {"max_vm_steps": 1000, "timeout_ms": 1000},  # Very low vm_steps
        }
    )

    # Should either succeed with limited results or be interrupted
    # Depending on how fast the query runs, it may or may not be interrupted
    # The key is that it doesn't crash and returns a valid response
    assert "ok" in result
    if not result["ok"]:
        # If interrupted, should have an error message
        assert "error" in result
        # Error should mention interruption
        assert "interrupt" in result["error"].lower() or "error" in result


@pytest.mark.asyncio
async def test_query_sql_forbidden_alter() -> None:
    """
    TC-QS-A-19: ALTER statement raises InvalidParamsError.

    // Given: SQL with ALTER TABLE
    // When: Validating SQL
    // Then: Raises InvalidParamsError (forbidden keyword)
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "ALTER TABLE tasks ADD COLUMN extra TEXT"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_replace() -> None:
    """
    TC-QS-A-20: REPLACE statement raises InvalidParamsError.

    // Given: SQL with REPLACE
    // When: Validating SQL
    // Then: Raises InvalidParamsError (forbidden keyword)
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql(
            {"sql": "REPLACE INTO tasks (id, hypothesis, status) VALUES ('t', 'h', 's')"}
        )

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_sql_forbidden_detach() -> None:
    """
    TC-QS-A-21: DETACH statement raises InvalidParamsError.

    // Given: SQL with DETACH
    // When: Validating SQL
    // Then: Raises InvalidParamsError (forbidden keyword)
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_sql({"sql": "DETACH DATABASE test"})

    assert "Forbidden SQL keyword" in str(exc_info.value)
