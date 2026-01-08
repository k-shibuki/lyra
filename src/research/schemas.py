"""
Schemas for research module integration.

This file defines explicit contracts for data passed across modules.

Key contracts:
- WorkBibliography: Normalized bibliographic metadata stored in `works` table
- WorkAuthor: Author entry stored in `work_authors` table
- WorkIdentifier: Provider-specific identifier stored in `work_identifiers` table
- CanonicalWorkRef: Reference from pages to works via canonical_id
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, computed_field


class WorkAuthor(BaseModel):
    """Author entry for work_authors table.

    Stored with position to maintain author order (first author = position 0).
    """

    name: str = Field(..., description="Author display name")
    position: int = Field(..., ge=0, description="Author position (0 = first author)")
    affiliation: str | None = Field(None, description="Author affiliation")
    orcid: str | None = Field(None, description="ORCID iD (without URL prefix)")


class WorkIdentifier(BaseModel):
    """Provider-specific identifier for work_identifiers table.

    Maps provider paper IDs to canonical_id for lookup.
    """

    provider: str = Field(..., description="Provider name: semantic_scholar, openalex, web")
    provider_paper_id: str = Field(..., description="Provider-specific paper ID (e.g., s2:xxx)")
    doi: str | None = Field(None, description="DOI (normalized, no URL prefix)")
    pmid: str | None = Field(None, description="PubMed ID")
    pmcid: str | None = Field(None, description="PubMed Central ID")
    arxiv_id: str | None = Field(None, description="arXiv ID")


class WorkBibliography(BaseModel):
    """Normalized bibliographic metadata for works table.

    This is the single source of truth for bibliographic information.
    All fields are only populated when actually retrieved from source.
    NULL/None means "not available", not "unknown".
    """

    canonical_id: str = Field(..., description="Canonical ID (doi:xxx, meta:xxx, etc.)")
    title: str = Field(..., description="Work title")
    year: int | None = Field(None, description="Publication year")
    published_date: date | None = Field(None, description="Full publication date")
    venue: str | None = Field(None, description="Journal/Conference name")
    doi: str | None = Field(None, description="DOI (normalized)")
    citation_count: int = Field(default=0, ge=0, description="Citation count")
    reference_count: int = Field(default=0, ge=0, description="Reference count")
    is_open_access: bool = Field(default=False, description="Open access flag")
    oa_url: str | None = Field(None, description="Open access URL")
    pdf_url: str | None = Field(None, description="PDF URL")
    source_api: str = Field(..., description="Best source API for this work")

    # Authors stored separately in work_authors table
    authors: list[WorkAuthor] = Field(default_factory=list, description="Author list")

    # Identifiers stored separately in work_identifiers table
    identifiers: list[WorkIdentifier] = Field(
        default_factory=list, description="Provider identifiers"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def author_display(self) -> str:
        """Generate author display string (first author + et al.).

        Rules:
        - 0 authors: "unknown"
        - 1 author: "Author Name"
        - 2+ authors: "First Author et al."
        """
        if not self.authors:
            return "unknown"
        first = self.authors[0].name if self.authors else "unknown"
        if len(self.authors) == 1:
            return first
        return f"{first} et al."


class CanonicalWorkRef(BaseModel):
    """Reference from pages table to works table.

    Used when persisting academic pages to link them to normalized works.
    """

    canonical_id: str = Field(..., description="FK to works.canonical_id")
    provider_paper_id: str = Field(..., description="Provider paper ID (e.g., s2:xxx)")


class CitationGraphJobInput(BaseModel):
    """Input payload for citation_graph jobs."""

    task_id: str
    search_id: str
    query: str
    paper_ids: list[str] = Field(..., description="List of Paper.id values")


# =============================================================================
# Conversion utilities
# =============================================================================


def paper_to_work_bibliography(
    paper: Any,  # Paper from src.utils.schemas
    canonical_id: str,
) -> WorkBibliography:
    """Convert a Paper object to WorkBibliography.

    Args:
        paper: Paper object from academic API
        canonical_id: Pre-computed canonical ID

    Returns:
        WorkBibliography with normalized data
    """
    authors = [
        WorkAuthor(
            name=a.name,
            position=i,
            affiliation=a.affiliation,
            orcid=a.orcid,
        )
        for i, a in enumerate(paper.authors)
    ]

    identifiers = [
        WorkIdentifier(
            provider=paper.source_api,
            provider_paper_id=paper.id,
            doi=paper.doi,
            pmid=None,  # Not available from Paper object
            pmcid=None,  # Not available from Paper object
            arxiv_id=paper.arxiv_id,
        )
    ]

    return WorkBibliography(
        canonical_id=canonical_id,
        title=paper.title,
        year=paper.year,
        published_date=paper.published_date,
        venue=paper.venue,
        doi=paper.doi,
        citation_count=paper.citation_count,
        reference_count=paper.reference_count,
        is_open_access=paper.is_open_access,
        oa_url=paper.oa_url,
        pdf_url=paper.pdf_url,
        source_api=paper.source_api,
        authors=authors,
        identifiers=identifiers,
    )
