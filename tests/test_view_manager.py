"""
Tests for ViewManager.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-VM-N-01 | Render template with task_id | Equivalence – normal | Returns rendered SQL | - |
| TC-VM-N-02 | Render template without task_id | Equivalence – normal | Returns SQL without WHERE clause | - |
| TC-VM-N-03 | Query template | Equivalence – normal | Executes and returns results | - |
| TC-VM-N-04 | List available views | Equivalence – normal | Returns view names | - |
| TC-VM-A-01 | Template not found | Abnormal – missing | Raises TemplateNotFound | - |
| TC-VM-A-02 | Invalid template syntax | Abnormal – syntax error | Raises TemplateError | - |
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound

from src.storage.database import Database

pytestmark = pytest.mark.unit

from src.storage import view_manager


def test_view_manager_render_with_task_id(tmp_path: Path) -> None:
    """
    TC-VM-N-01: Render template with task_id returns SQL with WHERE clause.

    // Given: Template with task_id variable
    // When: Rendering with task_id
    // Then: Returns SQL with WHERE clause
    """
    views_dir = tmp_path / "views"
    views_dir.mkdir()
    template_file = views_dir / "test_view.sql.j2"
    template_file.write_text(
        "SELECT * FROM claims {% if task_id %}WHERE task_id = '{{ task_id }}'{% endif %}"
    )

    vm = view_manager.ViewManager()
    vm.env = Environment(loader=FileSystemLoader(str(views_dir)), autoescape=False)
    vm.views_dir = views_dir

    sql = vm.render("test_view", task_id="task_123")

    assert "WHERE task_id = 'task_123'" in sql


def test_view_manager_render_without_task_id(tmp_path: Path) -> None:
    """
    TC-VM-N-02: Render template without task_id returns SQL without WHERE.

    // Given: Template with optional task_id
    // When: Rendering without task_id
    // Then: Returns SQL without WHERE clause
    """
    views_dir = tmp_path / "views"
    views_dir.mkdir()
    template_file = views_dir / "test_view.sql.j2"
    template_file.write_text(
        "SELECT * FROM claims {% if task_id %}WHERE task_id = '{{ task_id }}'{% endif %}"
    )

    vm = view_manager.ViewManager()
    vm.env = Environment(loader=FileSystemLoader(str(views_dir)), autoescape=False)
    vm.views_dir = views_dir

    sql = vm.render("test_view")

    assert "WHERE" not in sql
    assert "SELECT * FROM claims" in sql


def test_view_manager_template_not_found() -> None:
    """
    TC-VM-A-01: Template not found raises TemplateNotFound.

    // Given: Non-existent template name
    // When: Rendering template
    // Then: Raises TemplateNotFound
    """
    vm = view_manager.ViewManager()

    with pytest.raises(TemplateNotFound):
        vm.render("nonexistent_view")


@pytest.mark.asyncio
async def test_view_manager_query(test_database: Database, tmp_path: Path) -> None:
    """
    TC-VM-N-03: Query template executes and returns results.

    // Given: Template and database with data
    // When: Calling query()
    // Then: Returns results from database
    """
    db = test_database
    await db.execute(
        "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
        ("task_1", "test query", "completed"),
    )

    views_dir = tmp_path / "views"
    views_dir.mkdir()
    template_file = views_dir / "test_view.sql.j2"
    template_file.write_text(
        "SELECT * FROM tasks {% if task_id %}WHERE id = '{{ task_id }}'{% endif %}"
    )

    vm = view_manager.ViewManager()
    vm.env = Environment(loader=FileSystemLoader(str(views_dir)), autoescape=False)

    results = await vm.query("test_view", task_id="task_1", limit=10)

    assert len(results) == 1
    assert results[0]["id"] == "task_1"


def test_view_manager_list_views(tmp_path: Path) -> None:
    """
    TC-VM-N-04: List available views returns view names.

    // Given: Multiple template files
    // When: Calling list_views()
    // Then: Returns sorted list of view names
    """
    views_dir = tmp_path / "views"
    views_dir.mkdir()
    (views_dir / "view1.sql.j2").write_text("SELECT 1")
    (views_dir / "view2.sql.j2").write_text("SELECT 2")
    (views_dir / "view3.sql.j2").write_text("SELECT 3")

    vm = view_manager.ViewManager(views_dir=views_dir)

    views = vm.list_views()

    assert len(views) == 3
    assert "view1" in views
    assert "view2" in views
    assert "view3" in views
