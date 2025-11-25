"""
Subquery execution engine for Lancet.

Executes Cursor AI-designed subqueries through the search/fetch/extract pipeline.
Handles mechanical expansions (synonyms, mirror queries, operators) only.

See requirements.md §2.1.3 and §3.1.7.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.research.state import ExplorationState, SubqueryStatus
from src.storage.database import get_database
from src.utils.logging import get_logger, LogContext
from src.utils.config import get_settings

logger = get_logger(__name__)

# Primary source domain patterns
PRIMARY_SOURCE_DOMAINS = {
    # Government
    "go.jp", "gov.uk", "gov", "gouv.fr", "bund.de",
    # Academic
    "edu", "ac.jp", "ac.uk", "edu.cn",
    # Standards
    "iso.org", "ietf.org", "w3.org",
    # Official organizations
    "who.int", "un.org", "oecd.org",
    # Academic publishers/repositories
    "arxiv.org", "pubmed.gov", "jstage.jst.go.jp", "doi.org",
}

# Mechanical refutation suffixes (§3.1.7.5)
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
class SubqueryResult:
    """Result of subquery execution."""
    
    subquery_id: str
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
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": len(self.errors) == 0,
            "subquery_id": self.subquery_id,
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
            "errors": self.errors if self.errors else None,
        }


class SubqueryExecutor:
    """
    Executes subqueries designed by Cursor AI.
    
    Responsibilities (§2.1.3):
    - Mechanical expansion of queries (synonyms, mirror queries, operators)
    - Search → Fetch → Extract → Evaluate pipeline
    - Metrics calculation (harvest rate, novelty, satisfaction)
    
    Does NOT:
    - Design subqueries (Cursor AI's responsibility)
    - Make strategic decisions about what to search next
    """
    
    def __init__(self, task_id: str, state: ExplorationState):
        """Initialize executor.
        
        Args:
            task_id: The task ID.
            state: The exploration state manager.
        """
        self.task_id = task_id
        self.state = state
        self._db = None
        self._seen_fragment_hashes: set[str] = set()
        self._seen_domains: set[str] = set()
    
    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()
    
    async def execute(
        self,
        subquery: str,
        priority: str = "medium",
        budget_pages: int | None = None,
        budget_time_seconds: int | None = None,
    ) -> SubqueryResult:
        """
        Execute a subquery designed by Cursor AI.
        
        Args:
            subquery: The subquery text (designed by Cursor AI).
            priority: Execution priority (high/medium/low).
            budget_pages: Optional page budget for this subquery.
            budget_time_seconds: Optional time budget for this subquery.
            
        Returns:
            SubqueryResult with execution results.
        """
        await self._ensure_db()
        
        # Generate subquery ID
        subquery_id = f"sq_{uuid.uuid4().hex[:8]}"
        
        with LogContext(task_id=self.task_id, subquery_id=subquery_id):
            logger.info("Executing subquery", subquery=subquery[:100], priority=priority)
            
            # Register and start subquery
            sq_state = self.state.register_subquery(
                subquery_id=subquery_id,
                text=subquery,
                priority=priority,
                budget_pages=budget_pages,
                budget_time_seconds=budget_time_seconds,
            )
            self.state.start_subquery(subquery_id)
            
            result = SubqueryResult(subquery_id=subquery_id, status="running")
            
            try:
                # Step 1: Expand query mechanically
                expanded_queries = self._expand_query(subquery)
                
                # Step 2: Execute search for each expanded query
                all_serp_items = []
                for eq in expanded_queries:
                    serp_items = await self._execute_search(eq)
                    all_serp_items.extend(serp_items)
                
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
                )
                
                # Step 3: Fetch and extract from top results
                budget = budget_pages or 15  # Default budget per subquery
                for item in unique_serp_items[:budget]:
                    # Check overall budget
                    within_budget, _ = self.state.check_budget()
                    if not within_budget:
                        result.errors.append("予算上限に達しました")
                        break
                    
                    # Check novelty stop condition
                    if self.state.check_novelty_stop_condition(subquery_id):
                        logger.info("Novelty stop condition met", subquery_id=subquery_id)
                        break
                    
                    await self._fetch_and_extract(subquery_id, item, result)
                
                # Update result from state
                sq_state = self.state.get_subquery(subquery_id)
                if sq_state:
                    sq_state.update_status()
                    result.status = sq_state.status.value
                    result.pages_fetched = sq_state.pages_fetched
                    result.useful_fragments = sq_state.useful_fragments
                    result.harvest_rate = sq_state.harvest_rate
                    result.independent_sources = sq_state.independent_sources
                    result.has_primary_source = sq_state.has_primary_source
                    result.satisfaction_score = sq_state.satisfaction_score
                    result.novelty_score = sq_state.novelty_score
                
                # Calculate remaining budget
                overall_status = self.state.get_status()
                result.budget_remaining = {
                    "pages": overall_status["budget"]["pages_limit"] - overall_status["budget"]["pages_used"],
                    "time_seconds": overall_status["budget"]["time_limit_seconds"] - overall_status["budget"]["time_used_seconds"],
                }
                
            except Exception as e:
                logger.error("Subquery execution failed", error=str(e), exc_info=True)
                result.status = "failed"
                result.errors.append(str(e))
            
            return result
    
    def _expand_query(self, query: str) -> list[str]:
        """
        Mechanically expand a query (§2.1.3).
        
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
                expanded.append(f'{query} site:arxiv.org OR site:jstage.jst.go.jp')
            
            # Government
            if any(kw in query.lower() for kw in ["政府", "省", "gov", "official"]):
                expanded.append(f'{query} site:go.jp')
        
        # Add filetype:pdf for document-heavy queries
        if "filetype:" not in query.lower():
            if any(kw in query.lower() for kw in ["仕様", "報告書", "白書", "specification", "report"]):
                expanded.append(f'{query} filetype:pdf')
        
        return expanded
    
    async def _execute_search(self, query: str) -> list[dict[str, Any]]:
        """Execute search via SearXNG."""
        from src.search.searxng import search_serp
        
        try:
            results = await search_serp(
                query=query,
                limit=10,
                task_id=self.task_id,
            )
            return results
        except Exception as e:
            logger.error("Search failed", query=query[:50], error=str(e))
            return []
    
    async def _fetch_and_extract(
        self,
        subquery_id: str,
        serp_item: dict[str, Any],
        result: SubqueryResult,
    ) -> None:
        """Fetch URL and extract content."""
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
        is_primary = any(
            primary in domain.lower()
            for primary in PRIMARY_SOURCE_DOMAINS
        )
        
        # Check if this is an independent source (new domain)
        is_independent = domain_short not in self._seen_domains
        if is_independent:
            self._seen_domains.add(domain_short)
        
        try:
            # Fetch
            fetch_result = await fetch_url(
                url=url,
                context={"referer": serp_item.get("engine", "")},
                task_id=self.task_id,
            )
            
            if not fetch_result.get("ok"):
                logger.debug("Fetch failed", url=url[:50], reason=fetch_result.get("reason"))
                return
            
            # Record page fetch
            self.state.record_page_fetch(
                subquery_id=subquery_id,
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
                    is_useful = len(extract_result.get("text", "")) > 200
                    
                    self.state.record_fragment(
                        subquery_id=subquery_id,
                        fragment_hash=content_hash,
                        is_useful=is_useful,
                        is_novel=is_novel,
                    )
                    
                    # Extract claims using llm_extract for primary sources (§2.1.4, §3.3)
                    # LLM extraction is only applied to primary sources to control LLM time ratio
                    if is_useful:
                        extracted_claims = await self._extract_claims_from_text(
                            text=extract_result.get("text", ""),
                            source_url=url,
                            title=serp_item.get("title", ""),
                            is_primary=is_primary,
                        )
                        
                        for claim in extracted_claims:
                            self.state.record_claim(subquery_id)
                            result.new_claims.append(claim)
                        
                        # If no claims extracted by LLM, record at least one potential claim
                        if not extracted_claims:
                            self.state.record_claim(subquery_id)
                            result.new_claims.append({
                                "source_url": url,
                                "title": serp_item.get("title", ""),
                                "snippet": extract_result.get("text", "")[:200],
                            })
        
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
        Extract claims from text using LLM (§2.1.4, §3.3).
        
        LLM extraction is only applied to primary sources to control
        LLM processing time ratio (≤30% per §3.1).
        
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
        
        settings = get_settings()
        
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
                use_slow_model=False,  # Use fast model to control time ratio
            )
            
            if result.get("ok") and result.get("claims"):
                claims = []
                for claim in result["claims"]:
                    if isinstance(claim, dict):
                        claims.append({
                            "source_url": source_url,
                            "title": title,
                            "claim": claim.get("claim", ""),
                            "claim_type": claim.get("type", "fact"),
                            "confidence": claim.get("confidence", 0.5),
                            "snippet": text[:200],
                        })
                return claims
            
        except Exception as e:
            logger.debug(
                "LLM claim extraction failed",
                source_url=source_url[:50],
                error=str(e),
            )
        
        return []
    
    def generate_refutation_queries(self, base_query: str) -> list[str]:
        """
        Generate refutation queries using mechanical patterns only.
        
        This applies predefined suffixes to the base query.
        Does NOT use LLM for query design (§2.1.4).
        
        Args:
            base_query: The base query to generate refutations for.
            
        Returns:
            List of refutation queries.
        """
        refutation_queries = []
        
        for suffix in REFUTATION_SUFFIXES:
            refutation_queries.append(f"{base_query} {suffix}")
        
        return refutation_queries

