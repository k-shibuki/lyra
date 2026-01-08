"""
Work persistence utilities for normalized bibliographic tables.

Handles upsert logic for works, work_authors, work_identifiers tables.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.storage.database import Database
    from src.utils.schemas import Paper

logger = get_logger(__name__)


async def persist_work(
    db: Database,
    paper: Paper,
    canonical_id: str,
) -> None:
    """Persist paper to normalized works tables.

    Upserts to works, work_authors, and work_identifiers tables.

    Args:
        db: Database connection
        paper: Paper object from academic API
        canonical_id: Pre-computed canonical ID
    """
    # Upsert works table
    await db.execute(
        """
        INSERT INTO works (
            canonical_id, title, year, published_date, venue, doi,
            citation_count, reference_count, is_open_access, oa_url, pdf_url, source_api
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_id) DO UPDATE SET
            citation_count = MAX(works.citation_count, excluded.citation_count),
            reference_count = MAX(works.reference_count, excluded.reference_count),
            is_open_access = COALESCE(excluded.is_open_access, works.is_open_access),
            oa_url = COALESCE(excluded.oa_url, works.oa_url),
            pdf_url = COALESCE(excluded.pdf_url, works.pdf_url)
        """,
        (
            canonical_id,
            paper.title,
            paper.year,
            str(paper.published_date) if paper.published_date else None,
            paper.venue,
            paper.doi,
            paper.citation_count,
            paper.reference_count,
            paper.is_open_access,
            paper.oa_url,
            paper.pdf_url,
            paper.source_api,
        ),
    )

    # Insert authors (skip if already exists for this canonical_id)
    existing_authors = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM work_authors WHERE canonical_id = ?",
        (canonical_id,),
    )
    has_authors = existing_authors and existing_authors.get("cnt", 0) > 0

    if not has_authors:
        for pos, author in enumerate(paper.authors):
            author_id = f"wa_{uuid.uuid4().hex[:12]}"
            await db.execute(
                """
                INSERT OR IGNORE INTO work_authors (id, canonical_id, position, name, affiliation, orcid)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (author_id, canonical_id, pos, author.name, author.affiliation, author.orcid),
            )

    # Insert identifier (upsert)
    identifier_id = f"wi_{uuid.uuid4().hex[:12]}"
    await db.execute(
        """
        INSERT INTO work_identifiers (id, canonical_id, provider, provider_paper_id, doi, arxiv_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, provider_paper_id) DO UPDATE SET
            doi = COALESCE(excluded.doi, work_identifiers.doi),
            arxiv_id = COALESCE(excluded.arxiv_id, work_identifiers.arxiv_id)
        """,
        (
            identifier_id,
            canonical_id,
            paper.source_api,
            paper.id,
            paper.doi,
            paper.arxiv_id,
        ),
    )

    logger.debug(
        "Persisted work to normalized tables",
        canonical_id=canonical_id,
        paper_id=paper.id,
        authors_count=len(paper.authors),
    )


async def resolve_paper_id_to_page_id(
    db: Database,
    paper_id: str,
) -> str | None:
    """Resolve paper_id to page_id via work_identifiers.

    Args:
        db: Database connection
        paper_id: Provider paper ID (e.g., "s2:xxx", "openalex:Wxxx")

    Returns:
        page_id or None if not found
    """
    row = await db.fetch_one(
        """
        SELECT p.id AS page_id
        FROM work_identifiers wi
        JOIN pages p ON p.canonical_id = wi.canonical_id
        WHERE wi.provider_paper_id = ?
        LIMIT 1
        """,
        (paper_id,),
    )
    if row:
        page_id = row.get("page_id")
        return str(page_id) if page_id is not None else None
    return None


async def get_canonical_id_for_paper_id(
    db: Database,
    paper_id: str,
) -> str | None:
    """Get canonical_id for a paper_id.

    Args:
        db: Database connection
        paper_id: Provider paper ID (e.g., "s2:xxx", "openalex:Wxxx")

    Returns:
        canonical_id or None if not found
    """
    row = await db.fetch_one(
        "SELECT canonical_id FROM work_identifiers WHERE provider_paper_id = ?",
        (paper_id,),
    )
    if row:
        canonical_id = row.get("canonical_id")
        return str(canonical_id) if canonical_id is not None else None
    return None
