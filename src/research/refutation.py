"""
Refutation executor for Lyra.

Executes refutation searches using mechanical patterns only.
Cursor AI designs which claims/subqueries to refute;
Lyra applies mechanical suffix patterns.

See docs/REQUIREMENTS.md §2.1.4 and §3.1.7.5.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.research.executor import REFUTATION_SUFFIXES
from src.research.state import ExplorationState
from src.storage.database import get_database

if TYPE_CHECKING:
    from src.storage.database import Database
from src.utils.logging import LogContext, get_logger

logger = get_logger(__name__)

# Confidence reduction when no refutation is found
NO_REFUTATION_CONFIDENCE_DECAY = 0.05


@dataclass
class RefutationResult:
    """Result of refutation search."""

    target: str  # claim_id or subquery_id
    target_type: str  # "claim" or "subquery"
    reverse_queries_executed: int = 0
    refutations_found: int = 0
    refutation_details: list[dict[str, Any]] = field(default_factory=list)
    confidence_adjustment: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": len(self.errors) == 0,
            "target": self.target,
            "target_type": self.target_type,
            "reverse_queries_executed": self.reverse_queries_executed,
            "refutations_found": self.refutations_found,
            "refutation_details": self.refutation_details,
            "confidence_adjustment": self.confidence_adjustment,
            "errors": self.errors if self.errors else None,
        }


class RefutationExecutor:
    """
    Executes refutation searches for claims/subqueries.

    Responsibilities (§2.1.4, §3.1.7.5):
    - Apply mechanical suffix patterns to generate reverse queries
    - Execute reverse query searches
    - Detect refuting evidence using NLI
    - Update confidence scores

    Does NOT:
    - Design reverse queries (only applies mechanical patterns)
    - Use LLM to generate refutation hypotheses
    """

    def __init__(self, task_id: str, state: ExplorationState):
        """Initialize refutation executor.

        Args:
            task_id: The task ID.
            state: The exploration state manager.
        """
        self.task_id = task_id
        self.state = state
        self._db: Database | None = None

    async def _ensure_db(self) -> None:
        """Ensure database connection."""
        if self._db is None:
            self._db = await get_database()

    async def execute_for_claim(self, claim_id: str) -> RefutationResult:
        """
        Execute refutation search for a specific claim.

        Args:
            claim_id: The claim ID to search refutations for.

        Returns:
            RefutationResult with search results.
        """
        await self._ensure_db()
        assert self._db is not None  # Guaranteed by _ensure_db

        result = RefutationResult(target=claim_id, target_type="claim")

        with LogContext(task_id=self.task_id, claim_id=claim_id):
            # Get claim text from database
            claim = await self._db.fetch_one(
                "SELECT claim_text, confidence_score FROM claims WHERE id = ?",
                (claim_id,),
            )

            if not claim:
                result.errors.append(f"Claim not found: {claim_id}")
                return result

            claim_text = claim.get("claim_text", "")
            current_confidence = claim.get("confidence_score", 1.0)

            logger.info("Executing refutation for claim", claim_text=claim_text[:50])

            # Generate refutation queries using mechanical patterns only
            reverse_queries = self._generate_reverse_queries(claim_text)
            result.reverse_queries_executed = len(reverse_queries)

            # Execute each reverse query
            for rq in reverse_queries:
                refutations = await self._search_and_detect_refutation(rq, claim_text)
                result.refutation_details.extend(refutations)

            result.refutations_found = len(result.refutation_details)

            # Adjust confidence
            if result.refutations_found == 0:
                # No refutation found - decay confidence (§3.1.7.5)
                result.confidence_adjustment = -NO_REFUTATION_CONFIDENCE_DECAY
                new_confidence = max(0, current_confidence + result.confidence_adjustment)

                await self._db.execute(
                    "UPDATE claims SET confidence_score = ? WHERE id = ?",
                    (new_confidence, claim_id),
                )

                logger.info(
                    "No refutation found, confidence decayed",
                    claim_id=claim_id,
                    adjustment=result.confidence_adjustment,
                )
            else:
                # Refutation found - record in evidence graph
                for ref in result.refutation_details:
                    await self._record_refutation_edge(claim_id, ref)

            return result

    async def execute_for_subquery(self, subquery_id: str) -> RefutationResult:
        """
        Execute refutation search for all claims from a subquery.

        Args:
            subquery_id: The subquery ID.

        Returns:
            RefutationResult with search results.
        """
        await self._ensure_db()
        assert self._db is not None  # Guaranteed by _ensure_db

        result = RefutationResult(target=subquery_id, target_type="subquery")

        with LogContext(task_id=self.task_id, subquery_id=subquery_id):
            # Get subquery state
            sq_state = self.state.get_subquery(subquery_id)
            if not sq_state:
                result.errors.append(f"Subquery not found: {subquery_id}")
                return result

            logger.info("Executing refutation for subquery", subquery_text=sq_state.text[:50])

            # Use the subquery text as basis for refutation
            # (In production, would also get claims from this subquery)
            reverse_queries = self._generate_reverse_queries(sq_state.text)
            result.reverse_queries_executed = len(reverse_queries)

            for rq in reverse_queries:
                refutations = await self._search_and_detect_refutation(rq, sq_state.text)
                result.refutation_details.extend(refutations)

            result.refutations_found = len(result.refutation_details)

            # Update subquery refutation status
            if result.refutations_found > 0:
                sq_state.refutation_status = "found"
                sq_state.refutation_count = result.refutations_found
            else:
                sq_state.refutation_status = "not_found"
                result.confidence_adjustment = -NO_REFUTATION_CONFIDENCE_DECAY

            return result

    def _generate_reverse_queries(self, text: str) -> list[str]:
        """
        Generate reverse queries using mechanical patterns only.

        Applies predefined suffixes to the text.
        Does NOT use LLM to generate hypotheses (§2.1.4).

        Args:
            text: The claim or subquery text.

        Returns:
            List of reverse queries.
        """
        # Extract key terms (simple approach)
        # In production, could use more sophisticated term extraction
        key_terms = text[:100]  # Use first 100 chars as key

        reverse_queries = []
        for suffix in REFUTATION_SUFFIXES[:5]:  # Limit to avoid too many queries
            reverse_queries.append(f"{key_terms} {suffix}")

        return reverse_queries

    async def _search_and_detect_refutation(
        self,
        query: str,
        original_text: str,
    ) -> list[dict[str, Any]]:
        """
        Search for refuting evidence and detect refutations using NLI.

        Args:
            query: The reverse query.
            original_text: The original claim/subquery text.

        Returns:
            List of detected refutations.
        """
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content
        from src.search import search_serp

        refutations = []

        try:
            # Search
            results = await search_serp(
                query=query,
                limit=5,
                task_id=self.task_id,
            )

            for item in results[:3]:  # Check top 3 results
                url = item.get("url", "")
                if not url:
                    continue

                try:
                    # Fetch
                    fetch_result = await fetch_url(
                        url=url,
                        context={"referer": "refutation_search"},
                        task_id=self.task_id,
                    )

                    if not fetch_result.get("ok"):
                        continue

                    # Extract
                    html_path = fetch_result.get("html_path")
                    if not html_path:
                        continue

                    extract_result = await extract_content(
                        input_path=html_path,
                        content_type="html",
                    )

                    text = extract_result.get("text", "")
                    if not text:
                        continue

                    # Check for refutation using NLI
                    # Take a relevant passage
                    passage = text[:500]

                    refutation = await self._detect_refutation_nli(
                        original_text,
                        passage,
                        url,
                        item.get("title", ""),
                    )

                    if refutation:
                        refutations.append(refutation)

                except Exception as e:
                    logger.debug("Refutation fetch failed", url=url[:50], error=str(e))

        except Exception as e:
            logger.error("Refutation search failed", query=query[:50], error=str(e))

        return refutations

    async def _detect_refutation_nli(
        self,
        claim_text: str,
        passage: str,
        source_url: str,
        source_title: str,
    ) -> dict[str, Any] | None:
        """
        Detect if a passage refutes a claim using NLI.

        Args:
            claim_text: The claim text.
            passage: The passage to check.
            source_url: URL of the source.
            source_title: Title of the source.

        Returns:
            Refutation details if detected, None otherwise.
        """
        from src.filter.nli import nli_judge

        try:
            # Use NLI to check stance
            pairs = [
                {
                    "pair_id": "refutation_check",
                    "premise": passage,
                    "hypothesis": claim_text,
                }
            ]

            results = await nli_judge(pairs=pairs)

            if results and len(results) > 0:
                stance = results[0].get("stance", "neutral")
                confidence = results[0].get("confidence", 0)

                if stance == "refutes" and confidence > 0.6:
                    return {
                        "claim_text": claim_text[:100],
                        "refuting_passage": passage[:200],
                        "source_url": source_url,
                        "source_title": source_title,
                        "nli_confidence": confidence,
                    }

        except Exception as e:
            logger.debug("NLI detection failed", error=str(e))

        return None

    async def _record_refutation_edge(
        self,
        claim_id: str,
        refutation: dict[str, Any],
    ) -> None:
        """Record refutation edge in evidence graph."""
        import uuid
        from urllib.parse import urlparse

        from src.utils.domain_policy import get_domain_category

        await self._ensure_db()
        assert self._db is not None  # Guaranteed by _ensure_db

        edge_id = f"edge_{uuid.uuid4().hex[:8]}"

        # Derive domain category from source URL domain (for ranking adjustment)
        source_url = refutation.get("source_url", "")
        source_domain_category: str | None = None
        if source_url:
            try:
                parsed = urlparse(source_url)
                domain = parsed.netloc.lower()
                source_domain_category = get_domain_category(domain).value
            except Exception:
                pass

        # Derive target_domain_category from claim's origin domain
        # Claims store source_url in verification_notes as "source_url=..."
        target_domain_category: str | None = None
        try:
            claim_row = await self._db.fetch_one(
                "SELECT verification_notes FROM claims WHERE id = ?", (claim_id,)
            )
            if claim_row:
                verification_notes = claim_row.get("verification_notes", "") or ""
                if "source_url=" in verification_notes:
                    claim_source_url = (
                        verification_notes.split("source_url=")[1].split(";")[0].strip()
                    )
                    parsed = urlparse(claim_source_url)
                    domain = parsed.netloc.lower()
                    target_domain_category = get_domain_category(domain).value
        except Exception:
            pass

        await self._db.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id,
                             relation, confidence, nli_label, nli_confidence,
                             source_domain_category, target_domain_category)
            VALUES (?, 'fragment', ?, 'claim', ?, 'refutes', ?, 'refutes', ?, ?, ?)
            """,
            (
                edge_id,
                refutation.get("source_url", "unknown"),
                claim_id,
                refutation.get("nli_confidence", 0),
                refutation.get("nli_confidence", 0),
                source_domain_category,
                target_domain_category,
            ),
        )

        logger.info(
            "Recorded refutation edge",
            claim_id=claim_id,
            source_url=refutation.get("source_url", "")[:50],
            source_domain_category=source_domain_category,
            target_domain_category=target_domain_category,
        )
