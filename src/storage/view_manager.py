"""
View Manager for SQL template rendering.

Manages SQL view templates (Jinja2) for Evidence Graph analysis.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from src.storage.database import get_database
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default template directory
DEFAULT_VIEWS_DIR = Path(__file__).parent.parent.parent / "config" / "views"


class ViewManager:
    """Manages SQL view templates."""

    def __init__(self, views_dir: Path | None = None) -> None:
        """Initialize ViewManager with Jinja2 environment.

        Args:
            views_dir: Directory containing *.sql.j2 templates. Defaults to config/views.
        """
        self.views_dir = views_dir or DEFAULT_VIEWS_DIR
        if not self.views_dir.exists():
            self.views_dir.mkdir(parents=True, exist_ok=True)

        self.env = Environment(
            loader=FileSystemLoader(str(self.views_dir)),
            autoescape=False,  # SQL doesn't need HTML escaping
        )

    def render(self, view_name: str, **kwargs: Any) -> str:
        """Render SQL template.

        Args:
            view_name: Template name (without .sql.j2 extension).
            **kwargs: Template variables (e.g., task_id).

        Returns:
            Rendered SQL string.

        Raises:
            TemplateNotFound: If template doesn't exist.
        """
        template_path = f"{view_name}.sql.j2"
        try:
            template = self.env.get_template(template_path)
            return template.render(**kwargs)
        except TemplateNotFound:
            logger.error("View template not found", view_name=view_name)
            raise

    async def query(
        self,
        view_name: str,
        task_id: str | None = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Render and execute SQL template.

        Args:
            view_name: Template name.
            task_id: Optional task ID for scoping.
            limit: Maximum rows to return.
            **kwargs: Additional template variables.

        Returns:
            List of result dicts.
        """
        sql = self.render(view_name, task_id=task_id, **kwargs)
        sql_with_limit = f"{sql} LIMIT {limit}"

        db = await get_database()
        rows = await db.fetch_all(sql_with_limit)
        return [dict(row) for row in rows]

    def list_views(self) -> list[str]:
        """List available view templates.

        Returns:
            List of view names (without .sql.j2 extension).
        """
        if not self.views_dir.exists():
            return []

        views = []
        for path in self.views_dir.glob("*.sql.j2"):
            views.append(path.stem.replace(".sql", ""))

        return sorted(views)


# Global instance
_view_manager: ViewManager | None = None


def get_view_manager() -> ViewManager:
    """Get or create ViewManager instance.

    Returns:
        ViewManager instance.
    """
    global _view_manager
    if _view_manager is None:
        _view_manager = ViewManager()
    return _view_manager
