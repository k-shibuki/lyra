"""
Pydantic data contracts for MCP tool boundaries.

These models are used for integration validation and debug flows.
They are not used as runtime validators for MCP calls (JSON schemas are used for L7).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QuerySqlOptions(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    timeout_ms: int = Field(300, ge=1, le=2000)
    max_vm_steps: int = Field(500000, ge=1, le=5_000_000)
    include_schema: bool = False


class QuerySqlRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    options: QuerySqlOptions = Field(
        default_factory=lambda: QuerySqlOptions(
            limit=50,
            timeout_ms=300,
            max_vm_steps=500000,
            include_schema=False,
        )
    )


class QuerySqlSchemaTable(BaseModel):
    name: str
    columns: list[str]


class QuerySqlSchemaSnapshot(BaseModel):
    tables: list[QuerySqlSchemaTable] = Field(default_factory=list)


class QuerySqlResponse(BaseModel):
    ok: bool
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    columns: list[str] = Field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0
    schema_: QuerySqlSchemaSnapshot | None = Field(default=None, alias="schema")
    error: str | None = None


class VectorSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    target: Literal["fragments", "claims"] = "claims"
    task_id: str | None = None
    top_k: int = Field(10, ge=1, le=50)
    min_similarity: float = Field(0.5, ge=0.0, le=1.0)


class VectorSearchResult(BaseModel):
    id: str
    similarity: float
    text_preview: str = ""


class VectorSearchResponse(BaseModel):
    ok: bool
    results: list[VectorSearchResult] = Field(default_factory=list)
    total_searched: int = 0
    error: str | None = None


class QueryViewRequest(BaseModel):
    view_name: str = Field(..., min_length=1)
    task_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(50, ge=1, le=200)


class QueryViewResponse(BaseModel):
    ok: bool
    view_name: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    columns: list[str] = Field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0
    error: str | None = None


class ViewInfo(BaseModel):
    name: str
    description: str = ""


class ListViewsResponse(BaseModel):
    ok: bool
    views: list[ViewInfo] = Field(default_factory=list)
    count: int = 0
