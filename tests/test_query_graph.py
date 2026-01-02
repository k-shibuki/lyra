"""
Tests for query_graph MCP tool.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-QG-N-01 | Valid SELECT query | Equivalence – normal | Returns rows successfully | - |
| TC-QG-N-02 | SELECT with JOIN | Equivalence – normal | Returns joined results | - |
| TC-QG-N-03 | SELECT with LIMIT | Equivalence – normal | Respects limit, sets truncated flag | - |
| TC-QG-N-04 | include_schema=true | Equivalence – normal | Returns schema information | - |
| TC-QG-A-01 | Missing sql parameter | Boundary – missing | Raises InvalidParamsError | - |
| TC-QG-A-02 | Empty sql string | Boundary – empty | Raises InvalidParamsError | - |
| TC-QG-A-03 | Multiple statements (;) | Boundary – multiple | Raises ValueError | - |
| TC-QG-A-04 | ATTACH statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-05 | INSERT statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-06 | UPDATE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-07 | DELETE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-08 | PRAGMA statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-09 | CREATE TABLE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-10 | DROP TABLE statement | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-11 | load_extension() | Abnormal – forbidden | Raises ValueError | - |
| TC-QG-A-12 | limit > 200 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-QG-A-13 | limit < 1 | Boundary – min exceeded | Raises InvalidParamsError | - |
| TC-QG-A-14 | timeout_ms > 2000 | Boundary – max exceeded | Raises InvalidParamsError | - |
| TC-QG-A-15 | Invalid SQL syntax | Abnormal – syntax error | Returns ok=False with error | - |
"""

import pytest

pytestmark = pytest.mark.unit

from src.mcp.errors import InvalidParamsError
from src.mcp.tools import sql


@pytest.mark.asyncio
async def test_query_graph_valid_select(test_database) -> None:
    """
    TC-QG-N-01: Valid SELECT query returns rows successfully.

    // Given: Valid SELECT query
    // When: Executing query_graph
    // Then: Returns rows with ok=True
    """
    # Setup: Insert test data
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
        ("test_task", "test query", "completed"),
    )

    result = await sql.handle_query_graph({"sql": "SELECT * FROM tasks WHERE id = 'test_task'"})

    assert result["ok"] is True
    assert result["row_count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["id"] == "test_task"
    assert "columns" in result
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_query_graph_with_limit(test_database) -> None:
    """
    TC-QG-N-03: SELECT with LIMIT respects limit and sets truncated flag.

    // Given: Query that returns more rows than limit
    // When: Executing with limit option
    // Then: Returns limited rows and sets truncated=True
    """
    db = test_database
    # Insert multiple tasks
    for i in range(5):
        await db.execute(
            "INSERT INTO tasks (id, query, status) VALUES (?, ?, ?)",
            (f"task_{i}", f"query {i}", "completed"),
        )

    result = await sql.handle_query_graph({"sql": "SELECT * FROM tasks", "options": {"limit": 3}})

    assert result["ok"] is True
    assert result["row_count"] == 3
    assert len(result["rows"]) == 3
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_query_graph_include_schema(test_database) -> None:
    """
    TC-QG-N-04: include_schema=true returns schema information.

    // Given: Query with include_schema=true
    // When: Executing query_graph
    // Then: Returns schema with tables and columns
    """
    result = await sql.handle_query_graph({"sql": "SELECT 1", "options": {"include_schema": True}})

    assert result["ok"] is True
    assert "schema" in result
    assert "tables" in result["schema"]
    assert isinstance(result["schema"]["tables"], list)
    # Check that tasks table is in schema
    table_names = [t["name"] for t in result["schema"]["tables"]]
    assert "tasks" in table_names


@pytest.mark.asyncio
async def test_query_graph_missing_sql() -> None:
    """
    TC-QG-A-01: Missing sql parameter raises InvalidParamsError.

    // Given: No sql parameter
    // When: Calling handle_query_graph
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({})

    assert "sql is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_empty_sql() -> None:
    """
    TC-QG-A-02: Empty sql string raises InvalidParamsError.

    // Given: Empty sql string
    // When: Calling handle_query_graph
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": ""})

    assert "sql is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_multiple_statements() -> None:
    """
    TC-QG-A-03: Multiple statements raises ValueError.

    // Given: SQL with semicolon separating statements
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "SELECT 1; SELECT 2"})

    assert "Multiple statements" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_attach() -> None:
    """
    TC-QG-A-04: ATTACH statement raises ValueError.

    // Given: SQL with ATTACH
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "ATTACH DATABASE 'test.db' AS test"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_insert() -> None:
    """
    TC-QG-A-05: INSERT statement raises ValueError.

    // Given: SQL with INSERT
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph(
            {"sql": "INSERT INTO tasks VALUES ('test', 'query', 'pending')"}
        )

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_update() -> None:
    """
    TC-QG-A-06: UPDATE statement raises ValueError.

    // Given: SQL with UPDATE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "UPDATE tasks SET status = 'completed'"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_delete() -> None:
    """
    TC-QG-A-07: DELETE statement raises ValueError.

    // Given: SQL with DELETE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "DELETE FROM tasks"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_pragma() -> None:
    """
    TC-QG-A-08: PRAGMA statement raises ValueError.

    // Given: SQL with PRAGMA
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "PRAGMA table_info(tasks)"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_create() -> None:
    """
    TC-QG-A-09: CREATE TABLE statement raises ValueError.

    // Given: SQL with CREATE TABLE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "CREATE TABLE test (id TEXT)"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_drop() -> None:
    """
    TC-QG-A-10: DROP TABLE statement raises ValueError.

    // Given: SQL with DROP TABLE
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "DROP TABLE tasks"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_forbidden_load_extension() -> None:
    """
    TC-QG-A-11: load_extension() raises ValueError.

    // Given: SQL with load_extension
    // When: Validating SQL
    // Then: Raises ValueError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "SELECT load_extension('test.so')"})

    assert "Forbidden SQL keyword" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_limit_too_high() -> None:
    """
    TC-QG-A-12: limit > 200 raises InvalidParamsError.

    // Given: limit option > 200
    // When: Calling handle_query_graph
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "SELECT 1", "options": {"limit": 201}})

    assert "limit must be between 1 and 200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_limit_too_low() -> None:
    """
    TC-QG-A-13: limit < 1 raises InvalidParamsError.

    // Given: limit option < 1
    // When: Calling handle_query_graph
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "SELECT 1", "options": {"limit": 0}})

    assert "limit must be between 1 and 200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_timeout_too_high() -> None:
    """
    TC-QG-A-14: timeout_ms > 2000 raises InvalidParamsError.

    // Given: timeout_ms option > 2000
    // When: Calling handle_query_graph
    // Then: Raises InvalidParamsError
    """
    with pytest.raises(InvalidParamsError) as exc_info:
        await sql.handle_query_graph({"sql": "SELECT 1", "options": {"timeout_ms": 2001}})

    assert "timeout_ms must be between 1 and 2000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_graph_invalid_sql_syntax(test_database) -> None:
    """
    TC-QG-A-15: Invalid SQL syntax returns ok=False with error.

    // Given: SQL with syntax error
    // When: Executing query_graph
    // Then: Returns ok=False with error message
    """
    result = await sql.handle_query_graph({"sql": "SELECT * FROM nonexistent_table"})

    assert result["ok"] is False
    assert "error" in result
    assert result["row_count"] == 0
    assert len(result["rows"]) == 0
