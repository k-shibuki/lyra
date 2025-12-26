"""
Search execution engine for Lyra.

Executes Cursor AI-designed search queries through the search/fetch/extract pipeline.
Handles mechanical expansions (synonyms, mirror queries, operators) only.

See ADR-0002 and ADR-0010.

Note: This module uses "search" terminology (not "subquery").
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.research.state import ExplorationState
from src.storage.database import get_database

if TYPE_CHECKING:
    from src.storage.database import Database
from src.utils.config import get_settings
from src.utils.logging import LogContext, get_logger

logger = get_logger(__name__)

# Primary source domain patterns
PRIMARY_SOURCE_DOMAINS = {
    # Government
    "go.jp",
    "gov.uk",
    "gov",
    "gouv.fr",
    "bund.de",
    # Academic
    "edu",
    "ac.jp",
    "ac.uk",
    "edu.cn",
    # Standards
    "iso.org",
    "ietf.org",
    "w3.org",
    # Official organizations
    "who.int",
    "un.org",
    "oecd.org",
    # Academic publishers/repositories
    "arxiv.org",
    "pubmed.gov",
    "jstage.jst.go.jp",
    "doi.org",
}

# Mechanical refutation suffixes (ADR-0010)
REFUTATION_SUFFIXES = [
    "課題",
    "批判",
    "問題点",
    "limitations",
    "反論",
    "誤り",
    "criticism",
    "problems",
    "issues",
]


@dataclass
class SearchResult:
    """Result of search execution.

    Per ADR-0007: Includes authentication queue information.
    """

    search_id: str
    status: str
    pages_fetched: int = 0
    useful_fragments: int = 0
    harvest_rate: float = 0.0
    independent_sources: int = 0
    has_primary_source: bool = False
    satisfaction_score: float = 0.0
    novelty_score: float = 1.0
    new_claims: list[dict[str, Any]] = field(default_factory=list)
    budget_remaining: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # ADR-0007: Authentication queue tracking
    auth_blocked_urls: int = 0  # Count of URLs blocked by authentication
    auth_queued_count: int = 0  # Count of items queued for authentication this run
    # Error tracking for MCP
    error_code: str | None = None  # MCP error code if failed
    error_details: dict[str, Any] = field(default_factory=dict)  # Additional error info

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        # Determine ok based on error_code presence (error_code takes precedence)
        is_ok = self.error_code is None and len(self.errors) == 0

        result: dict[str, Any] = {
            "ok": is_ok,
            "search_id": self.search_id,
            "status": self.status,
            "pages_fetched": self.pages_fetched,
            "useful_fragments": self.useful_fragments,
            "harvest_rate": self.harvest_rate,
            "independent_sources": self.independent_sources,
            "has_primary_source": self.has_primary_source,
            "satisfaction_score": self.satisfaction_score,
            "novelty_score": self.novelty_score,
            "new_claims": self.new_claims,
            "budget_remaining": self.budget_remaining,
        }

        # Include error information if present
        if self.error_code:
            result["error_code"] = self.error_code
        if self.error_details:
            result["error_details"] = self.error_details
        if self.errors:
            result["errors"] = self.errors

        # ADR-0007: Include auth info only if there are blocked/queued items
        if self.auth_blocked_urls > 0 or self.auth_queued_count > 0:
            result["auth_blocked_urls"] = self.auth_blocked_urls
            result["auth_queued_count"] = self.auth_queued_count
        return result


# Terminology alias ("subquery" -> "search") kept for internal consistency.
SubqueryResult = SearchResult


class SearchExecutor:
    """
    Executes search queries designed by Cursor AI.

    Responsibilities (ADR-0002):
    - Mechanical expansion of queries (synonyms, mirror queries, operators)
    - Search → Fetch → Extract → Evaluate pipeline
    - Metrics calculation (harvest rate, novelty, satisfaction)

    Does NOT:
    - Design search queries (Cursor AI's responsibility)
    - Make strategic decisions about what to search next
    """

    def __init__(self, task_id: str, state: ExplorationState, worker_id: int = 0):
        """Initialize executor.

        Args:
            task_id: The task ID.
            state: The exploration state manager.
            worker_id: Worker ID for isolated browser context (ADR-0014 Phase 3).
        """
        self.task_id = task_id
        self.state = state
        self.worker_id = worker_id
        self._db: Database | None = None
        self._seen_fragment_hashes: set[str] = set()
        self._seen_domains: set[str] = set()
        # b: web citation detection budget (configurable)
        self._web_citation_pages_processed: int = 0

    def _should_run_web_citation_detection(
        self,
        *,
        enabled: bool,
        budget_pages_per_task: int,
        run_on_primary_sources_only: bool,
        require_useful_text: bool,
        is_primary: bool,
        is_useful: bool,
    ) -> bool:
        """Return whether b web citation detection should run for this page.

        This function centralizes policy decisions so they can be tested without I/O.
        """
        if not enabled:
            return False
        if (
            budget_pages_per_task > 0
            and self._web_citation_pages_processed >= budget_pages_per_task
        ):
            return False
        if run_on_primary_sources_only and not is_primary:
            return False
        if require_useful_text and not is_useful:
            return False
        return True

    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()

    async def execute(
        self,
        query: str,
        priority: str = "medium",
        budget_pages: int | None = None,
        budget_time_seconds: int | None = None,
        engines: list[str] | None = None,
        serp_max_pages: int = 1,
        search_job_id: str | None = None,
    ) -> SearchResult:
        """
        Execute a search query designed by Cursor AI.

        Args:
            query: The search query text (designed by Cursor AI).
            priority: Execution priority (high/medium/low).
            budget_pages: Optional page budget for this search.
            budget_time_seconds: Optional time budget for this search.
            serp_max_pages: Maximum SERP pages to fetch per query.
            search_job_id: Search job ID for CAPTCHA queue auto-requeue (ADR-0007).

        Returns:
            SearchResult with execution results.
        """
        # Store engines and job ID for use in _execute_search
        self._engines = engines
        self._search_job_id = search_job_id  # ADR-0007
        self._serp_max_pages = serp_max_pages

        await self._ensure_db()

        # Generate search ID
        search_id = f"s_{uuid.uuid4().hex[:8]}"

        with LogContext(task_id=self.task_id, search_id=search_id):
            logger.info("Executing search", query=query[:100], priority=priority)

            # Register and start search
            search_state = self.state.register_search(
                search_id=search_id,
                text=query,
                priority=priority,
                budget_pages=budget_pages,
                budget_time_seconds=budget_time_seconds,
            )
            self.state.start_search(search_id)

            result = SearchResult(search_id=search_id, status="running")

            try:
                # Step 1: Expand query mechanically
                expanded_queries = self._expand_query(query)

                # Step 2: Execute search for each expanded query
                all_serp_items = []
                search_errors = []  # Track errors from all queries

                for eq in expanded_queries:
                    serp_items, error_code, error_details = await self._execute_search(eq)
                    if error_code:
                        search_errors.append((eq, error_code, error_details))
                    all_serp_items.extend(serp_items)

                # If all searches failed, report the first error
                if not all_serp_items and search_errors:
                    first_error = search_errors[0]
                    result.status = "failed"
                    result.error_code = first_error[1]
                    result.error_details = first_error[2]
                    result.errors.append(f"All searches failed: {first_error[1]}")
                    logger.error(
                        "All searches failed",
                        error_code=first_error[1],
                        error_details=first_error[2],
                        query_count=len(expanded_queries),
                    )
                    return result

                # Deduplicate by URL
                seen_urls = set()
                unique_serp_items = []
                for item in all_serp_items:
                    url = item.get("url", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        unique_serp_items.append(item)

                logger.info(
                    "Search completed",
                    expanded_count=len(expanded_queries),
                    total_results=len(unique_serp_items),
                    errors_encountered=len(search_errors),
                )

                # Step 3: Fetch and extract from top results
                # Use dynamic budget from UCB allocator if available (ADR-0010)
                dynamic_budget = self.state.get_dynamic_budget(search_id)
                budget = budget_pages or dynamic_budget or 15

                logger.debug(
                    "Using budget for search",
                    search_id=search_id,
                    budget=budget,
                    dynamic_budget=dynamic_budget,
                )

                fetch_attempted = 0
                for item in unique_serp_items[:budget]:
                    # Check overall budget
                    within_budget, _ = self.state.check_budget()
                    if not within_budget:
                        result.errors.append("予算上限に達しました")
                        break

                    # Check novelty stop condition
                    if self.state.check_novelty_stop_condition(search_id):
                        logger.info("Novelty stop condition met", search_id=search_id)
                        break

                    fetch_attempted += 1
                    await self._fetch_and_extract(search_id, item, result)

                # Check for ALL_FETCHES_FAILED condition
                # If we attempted fetches but got no successful pages
                search_state_check = self.state.get_search(search_id)
                all_fetches_failed = (
                    fetch_attempted > 0
                    and search_state_check
                    and search_state_check.pages_fetched == 0
                )
                if all_fetches_failed:
                    result.status = "failed"
                    result.error_code = "ALL_FETCHES_FAILED"
                    result.error_details = {
                        "total_urls": fetch_attempted,
                        "auth_blocked_count": result.auth_blocked_urls,
                    }
                    result.errors.append(f"All {fetch_attempted} URL fetches failed")
                    logger.warning(
                        "All fetches failed",
                        attempted=fetch_attempted,
                        auth_blocked=result.auth_blocked_urls,
                    )

                # Update result from state (but preserve failed status if all fetches failed)
                if search_state:
                    search_state.update_status()
                    if not all_fetches_failed:
                        result.status = search_state.status.value
                    result.pages_fetched = search_state.pages_fetched
                    result.useful_fragments = search_state.useful_fragments
                    result.harvest_rate = search_state.harvest_rate
                    result.independent_sources = search_state.independent_sources
                    result.has_primary_source = search_state.has_primary_source
                    result.satisfaction_score = search_state.satisfaction_score
                    result.novelty_score = search_state.novelty_score

                # Calculate remaining budget
                overall_status = await self.state.get_status()
                result.budget_remaining = {
                    "pages": overall_status["budget"]["budget_pages_limit"]
                    - overall_status["budget"]["budget_pages_used"],
                    "time_seconds": overall_status["budget"]["time_limit_seconds"]
                    - overall_status["budget"]["time_used_seconds"],
                }

            except Exception as e:
                logger.error("Search execution failed", error=str(e), exc_info=True)
                result.status = "failed"
                result.errors.append(str(e))

            return result

    def _expand_query(self, query: str) -> list[str]:
        """
        Mechanically expand a query (ADR-0002).

        Only performs mechanical expansions:
        - Original query
        - With common operators
        - Mirror queries (if applicable)

        Does NOT generate new query ideas (that's Cursor AI's job).
        """
        expanded = [query]

        # Add site operators for known high-value domains
        if "site:" not in query.lower():
            # Academic
            if any(kw in query.lower() for kw in ["研究", "論文", "paper", "study"]):
                expanded.append(f"{query} site:arxiv.org OR site:jstage.jst.go.jp")

            # Government
            if any(kw in query.lower() for kw in ["政府", "省", "gov", "official"]):
                expanded.append(f"{query} site:go.jp")

        # Add filetype:pdf for document-heavy queries
        if "filetype:" not in query.lower():
            if any(
                kw in query.lower() for kw in ["仕様", "報告書", "白書", "specification", "report"]
            ):
                expanded.append(f"{query} filetype:pdf")

        return expanded

    async def _execute_search(
        self, query: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        """Execute search via search provider.

        Returns:
            Tuple of (results, error_code, error_details).
            error_code is None if successful.
        """
        from src.search import search_serp
        from src.search.search_api import (
            ParserNotAvailableSearchError,
            SearchError,
            SerpSearchError,
        )

        try:
            # Pass engines and job ID if specified (ADR-0007)
            results = await search_serp(
                query=query,
                limit=10,
                task_id=self.task_id,
                engines=getattr(self, "_engines", None),
                search_job_id=getattr(self, "_search_job_id", None),
                serp_max_pages=getattr(self, "_serp_max_pages", 1),
            )
            return results, None, {}
        except ParserNotAvailableSearchError as e:
            logger.error(
                "Search failed: parser not available",
                query=query[:50],
                engine=e.engine,
                available=e.available_engines,
            )
            return (
                [],
                "PARSER_NOT_AVAILABLE",
                {
                    "engine": e.engine,
                    "available_engines": e.available_engines,
                },
            )
        except SerpSearchError as e:
            logger.error(
                "Search failed: SERP error",
                query=query[:50],
                error=e.message,
            )
            return (
                [],
                "SERP_SEARCH_FAILED",
                {
                    "query": e.query,
                    "provider_error": e.provider_error,
                },
            )
        except SearchError as e:
            logger.error(
                "Search failed: generic error",
                query=query[:50],
                error=str(e),
            )
            return [], "SERP_SEARCH_FAILED", {"error": str(e)}
        except Exception as e:
            logger.error("Search failed: unexpected error", query=query[:50], error=str(e))
            return [], "INTERNAL_ERROR", {"error": str(e)}

    async def _fetch_and_extract(
        self,
        search_id: str,
        serp_item: dict[str, Any],
        result: SearchResult,
    ) -> None:
        """Fetch URL and extract content.

        Per ADR-0007: Tracks authentication blocks and queued items.
        """
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content

        url = serp_item.get("url", "")
        if not url:
            return

        # Extract domain
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Get TLD+1
            parts = domain.split(".")
            if len(parts) >= 2:
                domain_short = ".".join(parts[-2:])
            else:
                domain_short = domain
        except Exception:
            domain = url
            domain_short = url

        # Check if this is a primary source
        is_primary = any(primary in domain.lower() for primary in PRIMARY_SOURCE_DOMAINS)

        # Check if this is an independent source (new domain)
        is_independent = domain_short not in self._seen_domains
        if is_independent:
            self._seen_domains.add(domain_short)

        try:
            # Fetch (ADR-0014 Phase 3: pass worker_id for context isolation)
            fetch_result = await fetch_url(
                url=url,
                context={"referer": serp_item.get("engine", "")},
                task_id=self.task_id,
                worker_id=self.worker_id,
            )

            if not fetch_result.get("ok"):
                reason = fetch_result.get("reason", "")
                logger.debug("Fetch failed", url=url[:50], reason=reason)

                # ADR-0007: Track authentication blocks
                if fetch_result.get("auth_queued"):
                    result.auth_blocked_urls += 1
                    result.auth_queued_count += 1
                    logger.info(
                        "URL blocked by authentication, queued for later",
                        url=url[:80],
                        queue_id=fetch_result.get("queue_id"),
                    )
                elif reason in ("auth_required", "challenge_detected"):
                    result.auth_blocked_urls += 1

                return

            # Record page fetch
            self.state.record_page_fetch(
                search_id=search_id,
                domain=domain_short,
                is_primary_source=is_primary,
                is_independent=is_independent,
            )

            # Extract content
            html_path = fetch_result.get("html_path")
            if html_path:
                extract_result = await extract_content(
                    input_path=html_path,
                    content_type="html",
                )

                if extract_result.get("text"):
                    # Hash the content for novelty detection
                    content_hash = hashlib.sha256(
                        extract_result["text"][:1000].encode()
                    ).hexdigest()[:16]

                    is_novel = content_hash not in self._seen_fragment_hashes
                    self._seen_fragment_hashes.add(content_hash)

                    # Consider useful if we got substantial text
                    settings = get_settings()
                    wc = settings.search.web_citation_detection
                    min_text_chars = max(0, int(wc.min_text_chars))
                    is_useful = len(extract_result.get("text", "")) > min_text_chars

                    # b: General web citation detection (LLM, conservative gating)
                    # Behavior is settings-driven (search.web_citation_detection.*).
                    # Defaults preserve the original "useful + primary only" gating.
                    if wc.enabled and html_path and fetch_result.get("page_id"):
                        should_run = self._should_run_web_citation_detection(
                            enabled=wc.enabled,
                            budget_pages_per_task=int(wc.budget_pages_per_task),
                            run_on_primary_sources_only=wc.run_on_primary_sources_only,
                            require_useful_text=wc.require_useful_text,
                            is_primary=is_primary,
                            is_useful=is_useful,
                        )

                        if should_run:
                            try:
                                from src.extractor.citation_detector import CitationDetector
                                from src.filter.evidence_graph import add_citation

                                source_page_id = str(fetch_result["page_id"])
                                source_domain = (urlparse(url).netloc or domain).lower()

                                html = Path(html_path).read_text(encoding="utf-8", errors="ignore")

                                # 0 means "no limit" (practically: very large cap)
                                max_candidates = int(wc.max_candidates_per_page)
                                if max_candidates <= 0:
                                    max_candidates = 10_000

                                detector = CitationDetector(max_candidates=max_candidates)
                                detected = await detector.detect_citations(
                                    html=html,
                                    base_url=url,
                                    source_domain=source_domain,
                                )
                                self._web_citation_pages_processed += 1

                                citations = [d for d in detected if d.is_citation]
                                if wc.max_edges_per_page > 0:
                                    citations = citations[: int(wc.max_edges_per_page)]
                                if citations:
                                    db = await get_database()

                                    for c in citations:
                                        target_url = c.url
                                        target_domain = (
                                            urlparse(target_url).netloc or ""
                                        ).lower() or "unknown"

                                        # Use claim_resource for race-condition-safe dedup
                                        is_new, existing_page_id = await db.claim_resource(
                                            identifier_type="url",
                                            identifier_value=target_url,
                                            task_id=self.task_id,
                                            worker_id=self.worker_id,
                                        )

                                        if not is_new and existing_page_id:
                                            # Already processed by another worker
                                            target_page_id = existing_page_id
                                        elif not is_new:
                                            # Resource claimed but no page_id yet (being processed)
                                            # Check if page exists
                                            existing = await db.fetch_one(
                                                "SELECT id FROM pages WHERE url = ?",
                                                (target_url,),
                                            )
                                            if existing and existing.get("id"):
                                                target_page_id = str(existing["id"])
                                            else:
                                                continue  # Skip, being processed
                                        else:
                                            # We claimed it, create placeholder page
                                            if not wc.create_placeholder_pages:
                                                continue
                                            inserted_id = await db.insert(
                                                "pages",
                                                {
                                                    "url": target_url,
                                                    "domain": target_domain,
                                                },
                                                or_ignore=True,
                                            )
                                            if not inserted_id:
                                                continue
                                            target_page_id = str(inserted_id)

                                            # Mark resource as completed
                                            await db.complete_resource(
                                                identifier_type="url",
                                                identifier_value=target_url,
                                                page_id=target_page_id,
                                            )

                                        await add_citation(
                                            source_type="page",
                                            source_id=source_page_id,
                                            page_id=target_page_id,
                                            task_id=self.task_id,
                                            citation_source="extraction",
                                            citation_context=(c.context or "")[:500],
                                        )

                                    logger.debug(
                                        "Web citation detection completed",
                                        page_id=source_page_id,
                                        citations_total=len(detected),
                                        citations_added=len(citations),
                                    )
                            except Exception as e:
                                logger.debug(
                                    "Web citation detection failed",
                                    url=url[:80],
                                    error=str(e),
                                )

                    self.state.record_fragment(
                        search_id=search_id,
                        fragment_hash=content_hash,
                        is_useful=is_useful,
                        is_novel=is_novel,
                    )

                    # Persist fragment to DB for get_materials()
                    fragment_id = f"f_{uuid.uuid4().hex[:8]}"
                    page_id = fetch_result.get("page_id", f"p_{uuid.uuid4().hex[:8]}")
                    await self._persist_fragment(
                        fragment_id=fragment_id,
                        page_id=page_id,
                        text=extract_result.get("text", "")[:2000],
                        source_url=url,
                        title=serp_item.get("title", ""),
                        heading_context=extract_result.get("title", ""),
                        is_primary=is_primary,
                    )

                    # Extract claims using llm_extract for primary sources (ADR-0002, ADR-0005)
                    # LLM extraction is only applied to primary sources to control LLM time ratio
                    if is_useful:
                        extracted_claims = await self._extract_claims_from_text(
                            text=extract_result.get("text", ""),
                            source_url=url,
                            title=serp_item.get("title", ""),
                            is_primary=is_primary,
                        )

                        for claim in extracted_claims:
                            self.state.record_claim(search_id)
                            result.new_claims.append(claim)

                            # Persist claim to DB for get_materials()
                            claim_id = f"c_{uuid.uuid4().hex[:8]}"
                            await self._persist_claim(
                                claim_id=claim_id,
                                claim_text=claim.get("claim", ""),
                                confidence=claim.get("confidence", 0.5),
                                source_url=url,
                                source_fragment_id=fragment_id,
                            )

                        # If no claims extracted by LLM, record at least one potential claim
                        if not extracted_claims:
                            self.state.record_claim(search_id)
                            snippet = extract_result.get("text", "")[:200]
                            result.new_claims.append(
                                {
                                    "source_url": url,
                                    "title": serp_item.get("title", ""),
                                    "snippet": snippet,
                                }
                            )

                            # Persist snippet as claim for get_materials()
                            claim_id = f"c_{uuid.uuid4().hex[:8]}"
                            await self._persist_claim(
                                claim_id=claim_id,
                                claim_text=snippet,
                                confidence=0.3,  # Low confidence for non-LLM extracted
                                source_url=url,
                                source_fragment_id=fragment_id,
                            )

        except Exception as e:
            logger.debug("Fetch/extract failed", url=url[:50], error=str(e))

    async def _extract_claims_from_text(
        self,
        text: str,
        source_url: str,
        title: str,
        is_primary: bool,
    ) -> list[dict[str, Any]]:
        """
        Extract claims from text using LLM (ADR-0002, ADR-0005).

        LLM extraction is only applied to primary sources to control
        LLM processing time ratio (≤30% per ADR-0010).

        Args:
            text: The text to extract claims from.
            source_url: URL of the source.
            title: Title of the source.
            is_primary: Whether this is a primary source.

        Returns:
            List of extracted claims.
        """
        # Only use LLM for primary sources to control processing time
        if not is_primary:
            return []

        get_settings()

        try:
            from src.filter.llm import llm_extract

            # Prepare passage for LLM extraction
            passage = {
                "id": hashlib.sha256(source_url.encode()).hexdigest()[:16],
                "text": text[:4000],  # Limit text length for LLM
                "source_url": source_url,
            }

            # Extract claims using LLM
            result = await llm_extract(
                passages=[passage],
                task="extract_claims",
                context=self.state.original_query,
            )

            if result.get("ok") and result.get("claims"):
                claims = []
                for claim in result["claims"]:
                    if isinstance(claim, dict):
                        claims.append(
                            {
                                "source_url": source_url,
                                "title": title,
                                "claim": claim.get("claim", ""),
                                "claim_type": claim.get("type", "fact"),
                                "confidence": claim.get("confidence", 0.5),
                                "snippet": text[:200],
                            }
                        )
                return claims

        except Exception as e:
            logger.debug(
                "LLM claim extraction failed",
                source_url=source_url[:50],
                error=str(e),
            )

        return []

    async def _persist_fragment(
        self,
        fragment_id: str,
        page_id: str,
        text: str,
        source_url: str,
        title: str,
        heading_context: str,
        is_primary: bool,
    ) -> None:
        """
        Persist fragment to database for get_materials() retrieval.

        Fragments must be persisted to DB; memory-only tracking causes
        get_materials() to return empty results.

        Args:
            fragment_id: Unique fragment identifier.
            page_id: Associated page identifier.
            text: Fragment text content.
            source_url: Source URL.
            title: Page title.
            heading_context: Heading context for fragment.
            is_primary: Whether from primary source.
        """

        try:
            db = await get_database()

            # Hash text for deduplication
            text_hash = hashlib.sha256(text[:500].encode()).hexdigest()[:16]

            await db.execute(
                """
                INSERT OR IGNORE INTO fragments
                (id, page_id, fragment_type, text_content, heading_context, text_hash,
                 is_relevant, relevance_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    fragment_id,
                    page_id,
                    "paragraph",
                    text,
                    heading_context or title,
                    text_hash,
                    1,  # is_relevant
                    f"primary_source={is_primary}; url={source_url[:100]}",  # Store metadata in relevance_reason
                ),
            )
        except Exception as e:
            logger.debug(
                "Failed to persist fragment",
                fragment_id=fragment_id,
                error=str(e),
            )

    async def _persist_claim(
        self,
        claim_id: str,
        claim_text: str,
        confidence: float,
        source_url: str,
        source_fragment_id: str,
    ) -> None:
        """
        Persist claim to database for get_materials() retrieval.

        Claims must be persisted to DB; memory-only tracking causes
        get_materials() to return empty results.

        Args:
            claim_id: Unique claim identifier.
            claim_text: The claim text.
            confidence: Confidence score (0-1).
            source_url: Source URL.
            source_fragment_id: Associated fragment ID.
        """
        import json

        try:
            db = await get_database()

            # Insert claim (using schema-valid columns)
            await db.execute(
                """
                INSERT OR IGNORE INTO claims
                (id, task_id, claim_text, claim_type, claim_confidence,
                 source_fragment_ids, claim_adoption_status, verification_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    claim_id,
                    self.task_id,
                    claim_text[:500],  # Truncate to reasonable length
                    "fact",
                    confidence,
                    json.dumps([source_fragment_id]),  # JSON array
                    "adopted",  # Default changed from 'pending'
                    f"source_url={source_url[:200]}",  # Store URL in notes
                ),
            )

            # Run NLI for (fragment -> claim) and persist edge with nli_confidence.
            #
            # Note: We intentionally do NOT use LLM-extracted confidence as Bayesian input.
            # The evidence edge should carry NLI confidence (edges.nli_confidence).
            from urllib.parse import urlparse

            from src.filter.evidence_graph import add_claim_evidence
            from src.filter.nli import nli_judge
            from src.utils.domain_policy import get_domain_category

            # Determine domain category from source URL
            source_domain_category: str | None = None
            try:
                parsed = urlparse(source_url)
                domain = parsed.netloc.lower()
                source_domain_category = get_domain_category(domain).value if domain else None
            except Exception:
                source_domain_category = None

            # Target domain category is the same as source for claim origin (single-user mode)
            target_domain_category: str | None = source_domain_category

            # Fetch fragment text as premise (best-effort)
            premise = ""
            try:
                frag_row = await db.fetch_one(
                    "SELECT text_content FROM fragments WHERE id = ?",
                    (source_fragment_id,),
                )
                if frag_row:
                    premise = (frag_row.get("text_content") or "")[:800]
            except Exception:
                premise = ""

            # Fallback premise if fragment text is unavailable
            if not premise:
                premise = (claim_text or "")[:800]

            stance = "neutral"
            nli_conf = 0.0
            try:
                pairs = [
                    {
                        "pair_id": f"{source_fragment_id}:{claim_id}",
                        "premise": premise,
                        "hypothesis": (claim_text or "")[:300],
                    }
                ]
                nli_results = await nli_judge(pairs=pairs)
                if nli_results:
                    stance = str(nli_results[0].get("stance", "neutral") or "neutral")
                    nli_conf = float(nli_results[0].get("confidence", 0.0) or 0.0)
            except Exception:
                # Keep neutral/0.0 on failure (no fabrication)
                stance = "neutral"
                nli_conf = 0.0

            # Sanitize stance
            if stance not in ("supports", "refutes", "neutral"):
                stance = "neutral"

            # Persist edge (also updates in-memory EvidenceGraph)
            await add_claim_evidence(
                claim_id=claim_id,
                fragment_id=source_fragment_id,
                relation=stance,
                confidence=nli_conf,  # Keep confidence aligned with nli_confidence for legacy consumers
                nli_label=stance,
                nli_confidence=nli_conf,
                task_id=self.task_id,
                source_domain_category=source_domain_category,
                target_domain_category=target_domain_category,
            )
        except Exception as e:
            logger.debug(
                "Failed to persist claim",
                claim_id=claim_id,
                error=str(e),
            )

    def generate_refutation_queries(self, base_query: str) -> list[str]:
        """
        Generate refutation queries using mechanical patterns only.

        This applies predefined suffixes to the base query.
        Does NOT use LLM for query design (ADR-0002).

        Args:
            base_query: The base query to generate refutations for.

        Returns:
            List of refutation queries.
        """
        refutation_queries = []

        for suffix in REFUTATION_SUFFIXES:
            refutation_queries.append(f"{base_query} {suffix}")

        return refutation_queries


# Terminology alias ("subquery" -> "search") kept for internal consistency.
SubqueryExecutor = SearchExecutor
