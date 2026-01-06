"""
Citation graph processing as a deferred job.

Per ADR-0015: Citation graph processing is separated from the search pipeline
to ensure web page fetching is prioritized within timeout budgets.

This module provides:
- enqueue_citation_graph_job: Enqueue a citation graph job for deferred processing
- process_citation_graph: Execute citation graph processing (called by job handler)
"""

import json
import uuid
from typing import Any

from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def enqueue_citation_graph_job(
    task_id: str,
    search_id: str,
    query: str,
    paper_ids: list[str],
) -> str | None:
    """Enqueue a citation graph job for deferred processing.

    Per ADR-0015: Citation graph processing runs as a separate job
    after the search pipeline completes, not consuming search budget.

    Args:
        task_id: Task ID.
        search_id: Search ID.
        query: Search query (for relevance filtering).
        paper_ids: List of paper IDs with abstracts to process.

    Returns:
        Job ID if enqueued, None if skipped.
    """
    if not paper_ids:
        return None

    from src.scheduler.jobs import JobKind, JobScheduler

    db = await get_database()
    scheduler = JobScheduler()

    input_data = {
        "task_id": task_id,
        "search_id": search_id,
        "query": query,
        "paper_ids": paper_ids,
    }

    # Check if job already exists for this search_id (avoid duplicates)
    # Look for any citation_graph job with same search_id
    existing = await db.fetch_one(
        """
        SELECT id FROM jobs
        WHERE kind = 'citation_graph' AND input_json LIKE ?
        """,
        (f'%"search_id": "{search_id}"%',),
    )
    if existing:
        existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
        logger.debug("Citation graph job already exists", job_id=existing_id)
        return None

    # Submit job (job_id is auto-generated)
    result = await scheduler.submit(
        kind=JobKind.CITATION_GRAPH,
        input_data=input_data,
        task_id=task_id,
    )

    job_id = result.get("job_id")
    logger.info(
        "Enqueued citation graph job",
        job_id=job_id,
        task_id=task_id,
        paper_count=len(paper_ids),
    )

    return job_id


async def process_citation_graph(
    task_id: str,
    search_id: str,
    query: str,
    paper_ids: list[str],
) -> dict[str, Any]:
    """Process citation graph for papers (deferred job execution).

    Performs:
    1. Get citation graph from academic API for each paper
    2. Filter relevant citations
    3. Persist citation papers (with/without abstracts)
    4. Create CITES edges

    This runs outside the search budget (per ADR-0015).

    Args:
        task_id: Task ID.
        search_id: Search ID.
        query: Search query for relevance filtering.
        paper_ids: List of paper IDs to process.

    Returns:
        Result dict with processing stats.
    """
    from src.filter.evidence_graph import (
        NodeType,
        add_academic_page_with_citations,
        get_evidence_graph,
    )
    from src.search.academic_provider import AcademicSearchProvider

    settings = get_settings()
    db = await get_database()
    academic_provider = AcademicSearchProvider()

    # Build paper_to_page_map from existing data
    paper_to_page_map: dict[str, str] = {}

    for paper_id in paper_ids:
        # Find page by paper_id in paper_metadata JSON
        row = await db.fetch_one(
            """
            SELECT id FROM pages
            WHERE paper_metadata LIKE ?
            LIMIT 1
            """,
            (f'%"paper_id": "{paper_id}"%',),
        )
        if row:
            page_id = row["id"] if isinstance(row, dict) else row[0]
            paper_to_page_map[paper_id] = page_id

    result = {
        "ok": True,
        "papers_processed": 0,
        "citations_found": 0,
        "edges_created": 0,
        "papers_persisted": 0,
        "placeholders_created": 0,
    }

    top_n = settings.search.citation_graph_top_n_papers
    depth = settings.search.citation_graph_depth
    direction = settings.search.citation_graph_direction

    # Limit papers to process
    papers_to_process = paper_ids[:top_n]

    try:
        for paper_id in papers_to_process:
            if paper_id not in paper_to_page_map:
                continue

            try:
                # Get citation graph
                related_papers, citations = await academic_provider.get_citation_graph(
                    paper_id=paper_id,
                    depth=depth,
                    direction=direction,
                )

                result["papers_processed"] += 1
                result["citations_found"] += len(citations)

                # Relevance filtering
                try:
                    from src.search.citation_filter import filter_relevant_citations

                    # Need to get Paper object for filtering
                    # Try to get from academic API
                    paper = None
                    for api_name in ["semantic_scholar", "openalex"]:
                        try:
                            client = await academic_provider._get_client(api_name)
                            paper = await client.get_paper(paper_id)
                            if paper:
                                break
                        except Exception:
                            continue

                    if paper:
                        filtered = await filter_relevant_citations(
                            query=query,
                            source_paper=paper,
                            candidate_papers=related_papers,
                        )
                    else:
                        filtered = []
                except Exception as e:
                    logger.debug(
                        "Citation relevance filtering failed",
                        paper_id=paper_id,
                        error=str(e),
                    )
                    filtered = []

                # Persist relevant citation papers
                for scored in filtered:
                    rp = scored.paper
                    if rp.id in paper_to_page_map:
                        continue

                    if rp.abstract:
                        # Full persist with abstract
                        try:
                            page_id = await _persist_citation_paper(
                                paper=rp,
                                task_id=task_id,
                                search_id=search_id,
                            )
                            if page_id:
                                paper_to_page_map[rp.id] = page_id
                                graph = await get_evidence_graph(task_id)
                                graph.add_node(NodeType.PAGE, page_id)
                                result["papers_persisted"] += 1
                        except Exception as e:
                            logger.debug(
                                "Failed to persist citation paper",
                                paper_id=rp.id,
                                error=str(e),
                            )
                    else:
                        # No abstract: create placeholder
                        try:
                            placeholder_id = await _create_citation_placeholder(
                                paper=rp,
                                task_id=task_id,
                            )
                            if placeholder_id:
                                paper_to_page_map[rp.id] = placeholder_id
                                graph = await get_evidence_graph(task_id)
                                graph.add_node(NodeType.PAGE, placeholder_id)
                                result["placeholders_created"] += 1
                        except Exception as e:
                            logger.debug(
                                "Failed to create citation placeholder",
                                paper_id=rp.id,
                                error=str(e),
                            )

                # Look up page_id from mapping
                mapped_page_id = paper_to_page_map.get(paper_id)

                if mapped_page_id and citations and paper:
                    # Build paper_metadata
                    paper_metadata = {
                        "paper_id": paper.id,
                        "doi": paper.doi,
                        "arxiv_id": paper.arxiv_id,
                        "authors": [
                            {"name": a.name, "affiliation": a.affiliation, "orcid": a.orcid}
                            for a in paper.authors
                        ],
                        "year": paper.year,
                        "venue": paper.venue,
                        "citation_count": paper.citation_count,
                        "reference_count": paper.reference_count,
                        "is_open_access": paper.is_open_access,
                        "oa_url": paper.oa_url,
                        "pdf_url": paper.pdf_url,
                        "source_api": paper.source_api,
                    }

                    await add_academic_page_with_citations(
                        page_id=mapped_page_id,
                        paper_metadata=paper_metadata,
                        citations=citations,
                        task_id=task_id,
                        paper_to_page_map=paper_to_page_map,
                    )

                    result["edges_created"] += len(citations)

                    logger.debug(
                        "Added citation graph",
                        paper_id=paper_id,
                        page_id=mapped_page_id,
                        citation_count=len(citations),
                    )

            except Exception as e:
                logger.warning(
                    "Failed to process citation graph",
                    paper_id=paper_id,
                    error=str(e),
                )

    finally:
        await academic_provider.close()

    logger.info(
        "Citation graph processing completed",
        task_id=task_id,
        papers_processed=result["papers_processed"],
        citations_found=result["citations_found"],
        edges_created=result["edges_created"],
    )

    return result


async def _persist_citation_paper(
    paper: Any,
    task_id: str,
    search_id: str,
) -> str | None:
    """Persist a citation paper with abstract.

    Args:
        paper: Paper object with abstract.
        task_id: Task ID.
        search_id: Search ID.

    Returns:
        Page ID if persisted, None otherwise.
    """
    db = await get_database()

    # Build reference URL
    reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else "")
    if not reference_url:
        reference_url = f"https://paper/{paper.id}"

    # Check for existing page
    existing = await db.fetch_one(
        "SELECT id FROM pages WHERE url = ?",
        (reference_url,),
    )
    if existing:
        page_id_val = existing["id"] if isinstance(existing, dict) else existing[0]
        return str(page_id_val)

    # Create page
    page_id = str(uuid.uuid4())
    domain = _extract_domain(reference_url)

    paper_metadata = {
        "paper_id": paper.id,
        "doi": paper.doi,
        "arxiv_id": getattr(paper, "arxiv_id", None),
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "citation_count": paper.citation_count,
        "source_api": paper.source_api,
    }

    await db.insert(
        "pages",
        {
            "id": page_id,
            "url": reference_url,
            "domain": domain,
            "page_type": "academic",
            "title": paper.title,
            "paper_metadata": json.dumps(paper_metadata),
        },
        or_ignore=True,
    )

    # Create fragment for abstract
    fragment_id = str(uuid.uuid4())
    await db.insert(
        "fragments",
        {
            "id": fragment_id,
            "page_id": page_id,
            "fragment_type": "abstract",
            "text_content": paper.abstract,
            "position": 0,
        },
        or_ignore=True,
    )

    return page_id


async def _create_citation_placeholder(
    paper: Any,
    task_id: str,
) -> str | None:
    """Create a placeholder page for a citation without abstract.

    Args:
        paper: Paper object (without abstract).
        task_id: Task ID.

    Returns:
        Page ID if created, None otherwise.
    """
    db = await get_database()

    # Build reference URL
    reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else "")
    if not reference_url:
        reference_url = f"https://paper/{paper.id}"

    # Check for existing page
    existing = await db.fetch_one(
        "SELECT id FROM pages WHERE url = ?",
        (reference_url,),
    )
    if existing:
        page_id_val = existing["id"] if isinstance(existing, dict) else existing[0]
        return str(page_id_val)

    # Create placeholder page
    page_id = str(uuid.uuid4())
    domain = _extract_domain(reference_url)

    paper_metadata = {
        "paper_id": paper.id,
        "doi": paper.doi,
        "arxiv_id": getattr(paper, "arxiv_id", None),
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "citation_count": paper.citation_count,
        "source_api": paper.source_api,
        "is_placeholder": True,
    }

    await db.insert(
        "pages",
        {
            "id": page_id,
            "url": reference_url,
            "domain": domain,
            "page_type": "academic_placeholder",
            "title": paper.title,
            "paper_metadata": json.dumps(paper_metadata),
        },
        or_ignore=True,
    )

    return page_id


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return "unknown"
