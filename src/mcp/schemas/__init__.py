"""
MCP Response Schemas.

Provides JSON Schema definitions for all MCP tool responses.
Used by ResponseSanitizer for allowlist-based field filtering.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

# Cache for loaded schemas (tool_name -> schema)
_schema_cache: dict[str, dict[str, Any]] = {}
# Cache for schema file mtimes (tool_name -> mtime)
_schema_mtime: dict[str, float] = {}

SCHEMAS_DIR = Path(__file__).parent


def get_schema(tool_name: str) -> dict[str, Any] | None:
    """
    Load schema for a tool.

    Args:
        tool_name: Tool name (e.g., 'create_task', 'get_status').

    Returns:
        Schema dict or None if not found.
    """
    schema_path = SCHEMAS_DIR / f"{tool_name}.json"
    if not schema_path.exists():
        return None

    # Hot-reload schema if file changed (keeps allowlist in sync without requiring restart)
    try:
        mtime = schema_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if tool_name in _schema_cache and _schema_mtime.get(tool_name) == mtime:
        return _schema_cache[tool_name]

    with open(schema_path, encoding="utf-8") as f:
        schema = cast(dict[str, Any], json.load(f))

    _schema_cache[tool_name] = schema
    _schema_mtime[tool_name] = mtime
    return schema


def get_error_schema() -> dict[str, Any]:
    """Get the common error response schema."""
    return get_schema("error") or {}


def list_available_schemas() -> list[str]:
    """List all available schema names."""
    return [p.stem for p in SCHEMAS_DIR.glob("*.json") if p.stem != "common"]


def clear_cache() -> None:
    """Clear the schema cache (for testing)."""
    _schema_cache.clear()
    _schema_mtime.clear()
