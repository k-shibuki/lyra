"""
Schemas for research module integration.

This file defines explicit contracts for data passed across modules.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AcademicPageMetadata(BaseModel):
    """Metadata stored in pages.paper_metadata for academic pages.

    Integration contract:
    - citation_graph jobs refer to papers using Paper.id (e.g., "s2:...", "openalex:...").
    - pages.paper_metadata.paper_id MUST store that Paper.id so citation_graph can map
      paper_id -> page_id reliably.
    """

    paper_id: str = Field(..., description="Paper.id (e.g., 's2:...', 'openalex:...')")
    doi: str | None = Field(None, description="DOI")
    arxiv_id: str | None = Field(None, description="arXiv ID")
    title: str | None = Field(None, description="Paper title")
    authors: list[dict[str, Any]] = Field(default_factory=list, description="Author list")
    year: int | None = Field(None, description="Publication year")
    venue: str | None = Field(None, description="Journal/venue name")
    citation_count: int = Field(default=0, ge=0, description="Citation count")
    reference_count: int = Field(default=0, ge=0, description="Reference count")
    is_open_access: bool = Field(default=False, description="Open access flag")
    oa_url: str | None = Field(None, description="Open access URL")
    pdf_url: str | None = Field(None, description="PDF URL")
    source_api: str | None = Field(None, description="Source API name")


class CitationGraphJobInput(BaseModel):
    """Input payload for citation_graph jobs."""

    task_id: str
    search_id: str
    query: str
    paper_ids: list[str] = Field(..., description="List of Paper.id values")
