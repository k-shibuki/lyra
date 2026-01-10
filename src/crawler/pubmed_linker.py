"""
PubMed page -> normalized work linker.

Why: Browser-fetched PubMed pages are stored in `pages` without `canonical_id`,
so reports show unknown author/year. This module enriches such pages by:
  - extracting PMID from URL
  - fetching structured metadata via academic APIs (Semantic Scholar)
  - persisting to normalized tables (works/work_authors/work_identifiers)
  - updating pages.canonical_id

This is intentionally small and safe. It is gated by a feature flag at call sites.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


def _enabled() -> bool:
    from src.utils.config import get_settings

    return bool(get_settings().crawler.pubmed_enrichment_enabled)


def _enrich_timeout_seconds() -> float:
    from src.utils.config import get_settings

    try:
        return float(get_settings().crawler.pubmed_enrichment_timeout_seconds)
    except Exception:
        return 5.0


def _is_pubmed_domain(domain: str) -> bool:
    d = (domain or "").lower()
    return "pubmed.ncbi.nlm.nih.gov" in d or "pmc.ncbi.nlm.nih.gov" in d


async def enrich_pubmed_page_canonical_id(
    *,
    db: Any,
    page_id: str,
    url: str,
    domain: str,
) -> str | None:
    """If this is a PubMed page, link it to works and set pages.canonical_id.

    Returns the canonical_id if linked, else None.
    """
    if not _enabled():
        return None
    if not _is_pubmed_domain(domain):
        return None

    try:
        # Check current state (avoid rewriting)
        page = await db.fetch_one("SELECT canonical_id FROM pages WHERE id = ?", (page_id,))
        if page and page.get("canonical_id"):
            return str(page["canonical_id"])
    except Exception:
        # If DB query fails, do not break fetch flow.
        return None

    # Extract PMID
    from src.search.identifier_extractor import IdentifierExtractor

    identifier = IdentifierExtractor().extract(url)
    pmid = identifier.pmid
    pmcid = getattr(identifier, "pmcid", None)

    # If PMCID is present but PMID is missing, resolve via NCBI idconv
    if not pmid and pmcid:
        from src.search.id_resolver import IDResolver

        resolver = IDResolver()
        try:
            try:
                resolved = await asyncio.wait_for(
                    resolver.resolve_pmcid(pmcid),
                    timeout=_enrich_timeout_seconds(),
                )
            except TimeoutError:
                resolved = None
        finally:
            await resolver.close()

        if resolved:
            pmid = resolved.get("pmid") or None
            # If DOI is known, prefer DOI-based fetch
            resolved_doi = resolved.get("doi") or None
        else:
            resolved_doi = None
    else:
        resolved_doi = None

    # Fetch structured metadata (Semantic Scholar supports PMID: prefix)
    from src.search.apis.semantic_scholar import SemanticScholarClient

    client = SemanticScholarClient()
    try:
        # Best-effort with a hard timeout to avoid slowing fetch pipeline.
        pid = None
        if resolved_doi:
            pid = f"DOI:{resolved_doi}"
        elif pmid:
            pid = f"PMID:{pmid}"
        else:
            pid = None

        if not pid:
            return None

        try:
            paper = await asyncio.wait_for(
                client.get_paper(pid),
                timeout=_enrich_timeout_seconds(),
            )
        except TimeoutError:
            return None
    finally:
        await client.close()

    if not paper:
        return None

    # Persist to normalized tables
    from src.search.canonical_index import CanonicalPaperIndex
    from src.storage.works import persist_work

    index = CanonicalPaperIndex()
    canonical_id = index.register_paper(paper, paper.source_api)
    await persist_work(db, paper, canonical_id)

    # Link page -> work
    await db.update(
        "pages",
        {"canonical_id": canonical_id, "title": paper.title, "page_type": "academic_paper"},
        "id = ?",
        (page_id,),
    )

    logger.info("Linked PubMed page to canonical work", page_id=page_id, canonical_id=canonical_id)
    return canonical_id
