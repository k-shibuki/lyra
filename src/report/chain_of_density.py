"""
Chain-of-Density compression for Lyra.

Implements iterative summarization that increases information density
while preserving all essential citations and evidence.

Compression and Citation Strictness
- Increase summary density using Chain-of-Density approach
- Require deep links, discovery timestamps, and excerpts for all claims
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.filter.llm import _get_client
from src.filter.llm_output import parse_and_validate
from src.filter.llm_schemas import DenseSummaryOutput, InitialSummaryOutput
from src.report.generator import generate_deep_link
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.prompt_manager import render_prompt

logger = get_logger(__name__)


@dataclass
class CitationInfo:
    """Citation information required for each claim.

    Require deep links, discovery timestamps, and excerpts for all claims.
    """

    url: str
    deep_link: str
    title: str
    heading_context: str | None
    excerpt: str
    discovered_at: str
    source_tag: str | None = None

    @property
    def is_primary(self) -> bool:
        """Check if this is a primary source based on source_tag.

        Per ADR-0005: Primary sources include government, academic, official,
        standard, registry.
        """
        return self.source_tag in ("government", "academic", "official", "standard", "registry")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "deep_link": self.deep_link,
            "title": self.title,
            "heading_context": self.heading_context,
            "excerpt": self.excerpt,
            "discovered_at": self.discovered_at,
            "source_tag": self.source_tag,
            "is_primary": self.is_primary,
        }

    @classmethod
    def from_fragment(cls, fragment: dict[str, Any]) -> "CitationInfo":
        """Create from a fragment record."""
        url = fragment.get("url", "")
        heading = fragment.get("heading_context")

        return cls(
            url=url,
            deep_link=generate_deep_link(url, heading),
            title=fragment.get("page_title", fragment.get("title", url)),
            heading_context=heading,
            excerpt=cls._extract_excerpt(fragment.get("text_content", "")),
            discovered_at=fragment.get("created_at", datetime.now().isoformat()),
            source_tag=fragment.get("source_tag"),
        )

    @staticmethod
    def _extract_excerpt(text: str, max_length: int = 200) -> str:
        """Extract a meaningful excerpt from text."""
        if not text:
            return ""

        # Clean whitespace
        text = re.sub(r"\s+", " ", text.strip())

        # If short enough, return as-is
        if len(text) <= max_length:
            return text

        # Try to find a sentence boundary
        sentences = re.split(r"(?<=[。.!?])\s*", text)
        if sentences:
            excerpt = ""
            for sentence in sentences:
                if len(excerpt) + len(sentence) <= max_length:
                    excerpt += sentence
                else:
                    break
            if excerpt:
                return excerpt

        # Fall back to truncation at word boundary
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            truncated = truncated[:last_space]

        return truncated + "..."


@dataclass
class DenseClaim:
    """A claim with mandatory citation information.

    Require deep links, discovery timestamps, and excerpts for all claims.
    """

    claim_id: str
    text: str
    llm_claim_confidence: float  # LLM's self-reported extraction quality
    citations: list[CitationInfo]
    claim_type: str = "fact"
    is_verified: bool = False
    refutation_status: str = "pending"  # pending, found, not_found

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "llm_claim_confidence": self.llm_claim_confidence,
            "citations": [c.to_dict() for c in self.citations],
            "claim_type": self.claim_type,
            "is_verified": self.is_verified,
            "refutation_status": self.refutation_status,
            "has_primary_source": any(c.is_primary for c in self.citations),
            "citation_count": len(self.citations),
        }

    def validate(self) -> tuple[bool, list[str]]:
        """Validate that claim has all required citation info.

        Returns:
            Tuple of (is_valid, list of missing items).
        """
        missing = []

        if not self.citations:
            missing.append("citations")
        else:
            for i, citation in enumerate(self.citations):
                if not citation.url:
                    missing.append(f"citation[{i}].url")
                if not citation.deep_link:
                    missing.append(f"citation[{i}].deep_link")
                if not citation.excerpt:
                    missing.append(f"citation[{i}].excerpt")
                if not citation.discovered_at:
                    missing.append(f"citation[{i}].discovered_at")

        return len(missing) == 0, missing


@dataclass
class DenseSummary:
    """A dense summary with increasing information density.

    Increase summary density using Chain-of-Density approach.
    """

    iteration: int
    text: str
    entity_count: int
    word_count: int
    density_score: float  # entities / words
    claims: list[DenseClaim]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "iteration": self.iteration,
            "text": self.text,
            "entity_count": self.entity_count,
            "word_count": self.word_count,
            "density_score": self.density_score,
            "claims": [c.to_dict() for c in self.claims],
        }


class ChainOfDensityCompressor:
    """
    Implements Chain-of-Density compression.

    Chain-of-Density is an iterative summarization technique that:
    1. Starts with an initial summary
    2. Iteratively adds missing entities while maintaining length
    3. Increases information density with each iteration

    Increase summary density using Chain-of-Density approach,
    requiring deep links, discovery timestamps, and excerpts for all claims.
    """

    def __init__(
        self,
        max_iterations: int = 5,
        target_density: float = 0.15,
        use_llm: bool = True,
    ):
        """
        Initialize compressor.

        Args:
            max_iterations: Maximum densification iterations.
            target_density: Target entity density (entities/words).
            use_llm: Whether to use LLM for compression.
        """
        self.max_iterations = max_iterations
        self.target_density = target_density
        self.use_llm = use_llm
        self._settings = get_settings()

    async def compress(
        self,
        claims: list[dict[str, Any]],
        fragments: list[dict[str, Any]],
        task_query: str,
    ) -> dict[str, Any]:
        """
        Compress claims and fragments into a dense summary.

        Args:
            claims: List of claim records.
            fragments: List of fragment records with citation info.
            task_query: Original research query.

        Returns:
            Compression result with dense summary and validated claims.
        """
        if not claims and not fragments:
            return {
                "ok": False,
                "error": "No claims or fragments provided",
            }

        # Build claim-to-fragment mapping
        claim_citations = self._build_citation_mapping(claims, fragments)

        # Create dense claims with mandatory citation info
        dense_claims = self._create_dense_claims(claims, claim_citations, fragments)

        # Validate all claims have required citation info
        validation_results = self._validate_claims(dense_claims)

        if self.use_llm:
            # Perform iterative densification
            summaries = await self._iterative_densify(dense_claims, fragments, task_query)
        else:
            # Rule-based compression
            summaries = self._rule_based_compress(dense_claims)

        # Get final summary
        final_summary = summaries[-1] if summaries else None

        return {
            "ok": True,
            "task_query": task_query,
            "dense_claims": [c.to_dict() for c in dense_claims],
            "summaries": [s.to_dict() for s in summaries],
            "final_summary": final_summary.to_dict() if final_summary else None,
            "validation": validation_results,
            "statistics": {
                "total_claims": len(dense_claims),
                "validated_claims": validation_results["valid_count"],
                "invalid_claims": validation_results["invalid_count"],
                "primary_source_ratio": self._calc_primary_ratio(dense_claims),
                "iterations": len(summaries),
                "final_density": final_summary.density_score if final_summary else 0,
            },
        }

    def _build_citation_mapping(
        self,
        claims: list[dict[str, Any]],
        fragments: list[dict[str, Any]],
    ) -> dict[str, list[CitationInfo]]:
        """Build mapping from claim IDs to citation info."""
        mapping: dict[str, list[CitationInfo]] = {}

        # Create fragment lookup by ID
        fragment_by_id = {f.get("id"): f for f in fragments if f.get("id")}

        # Create fragment lookup by URL
        fragment_by_url: dict[str, list[dict[str, Any]]] = {}
        for f in fragments:
            url = f.get("url")
            if url:
                if url not in fragment_by_url:
                    fragment_by_url[url] = []
                fragment_by_url[url].append(f)

        for claim in claims:
            claim_id = claim.get("id", str(uuid.uuid4()))
            citations = []

            # Try to find supporting fragments
            supporting_ids = claim.get("supporting_fragment_ids", [])
            source_url = claim.get("source_url")

            # From supporting fragment IDs
            for frag_id in supporting_ids:
                if frag_id in fragment_by_id:
                    citations.append(CitationInfo.from_fragment(fragment_by_id[frag_id]))

            # From source URL
            if source_url and source_url in fragment_by_url:
                for frag in fragment_by_url[source_url]:
                    citation = CitationInfo.from_fragment(frag)
                    # Avoid duplicates
                    if not any(c.url == citation.url for c in citations):
                        citations.append(citation)

            # If no citations found, try to match by text similarity
            if not citations and fragments:
                claim_text = claim.get("claim_text", claim.get("text", ""))
                best_match = self._find_best_matching_fragment(claim_text, fragments)
                if best_match:
                    citations.append(CitationInfo.from_fragment(best_match))

            mapping[claim_id] = citations

        return mapping

    def _find_best_matching_fragment(
        self,
        claim_text: str,
        fragments: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find the fragment that best matches a claim text."""
        if not claim_text:
            return None

        # Simple word overlap scoring
        claim_words = set(claim_text.lower().split())

        best_score: float = 0.0
        best_fragment: dict[str, Any] | None = None

        for frag in fragments:
            frag_text = frag.get("text_content", "")
            if not frag_text:
                continue

            frag_words = set(frag_text.lower().split())

            # Jaccard similarity
            intersection = len(claim_words & frag_words)
            union = len(claim_words | frag_words)

            if union > 0:
                score = intersection / union
                if score > best_score:
                    best_score = float(score)
                    best_fragment = frag

        # Only return if similarity is above threshold
        if best_score >= 0.1:
            return best_fragment

        return None

    def _create_dense_claims(
        self,
        claims: list[dict[str, Any]],
        claim_citations: dict[str, list[CitationInfo]],
        fragments: list[dict[str, Any]],
    ) -> list[DenseClaim]:
        """Create DenseClaim objects with citation info."""
        dense_claims = []

        for claim in claims:
            claim_id = claim.get("id", str(uuid.uuid4()))
            citations = claim_citations.get(claim_id, [])

            # If still no citations, create a placeholder with available info
            if not citations:
                source_url = claim.get("source_url", "")
                if source_url:
                    citations = [
                        CitationInfo(
                            url=source_url,
                            deep_link=source_url,
                            title=claim.get("source_title", source_url),
                            heading_context=None,
                            excerpt=claim.get("claim_text", "")[:200],
                            discovered_at=claim.get("created_at", datetime.now().isoformat()),
                            source_tag=claim.get("source_tag"),
                        )
                    ]

            dense_claim = DenseClaim(
                claim_id=claim_id,
                text=claim.get("claim_text", claim.get("text", "")),
                # LLM extraction quality only - no fallback to Bayesian (different semantics)
                llm_claim_confidence=claim.get("llm_claim_confidence", 0.5),
                citations=citations,
                claim_type=claim.get("claim_type", "fact"),
                is_verified=False,  # DB column removed
                refutation_status=claim.get("refutation_status", "pending"),
            )
            dense_claims.append(dense_claim)

        return dense_claims

    def _validate_claims(
        self,
        claims: list[DenseClaim],
    ) -> dict[str, Any]:
        """Validate all claims have required citation info."""
        valid_count = 0
        invalid_count = 0
        issues = []

        for claim in claims:
            is_valid, missing = claim.validate()
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                issues.append(
                    {
                        "claim_id": claim.claim_id,
                        "claim_text": claim.text[:100],
                        "missing": missing,
                    }
                )

        return {
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "issues": issues,
            "all_valid": invalid_count == 0,
        }

    def _calc_primary_ratio(self, claims: list[DenseClaim]) -> float:
        """Calculate ratio of claims with primary source citations."""
        if not claims:
            return 0.0

        with_primary = sum(1 for c in claims if any(cit.is_primary for cit in c.citations))

        return with_primary / len(claims)

    async def _iterative_densify(
        self,
        claims: list[DenseClaim],
        fragments: list[dict[str, Any]],
        task_query: str,
    ) -> list[DenseSummary]:
        """Perform iterative densification using LLM."""
        summaries = []

        # Prepare content for summarization
        content_items = []
        for i, claim in enumerate(claims):
            item = {
                "index": i,
                "text": claim.text,
                "llm_claim_confidence": claim.llm_claim_confidence,
                "sources": [c.title for c in claim.citations],
            }
            content_items.append(item)

        content_str = json.dumps(content_items, ensure_ascii=False, indent=2)

        # Initial summary
        try:
            initial = await self._generate_initial_summary(content_str, claims)
            summaries.append(initial)
        except Exception as e:
            logger.error("Initial summary generation failed", error=str(e))
            return self._rule_based_compress(claims)

        # Iterative densification
        current_summary = initial
        all_entities = self._extract_all_entities(claims, fragments)

        for iteration in range(1, self.max_iterations):
            # Check if target density reached
            if current_summary.density_score >= self.target_density:
                logger.info(
                    "Target density reached",
                    iteration=iteration,
                    density=current_summary.density_score,
                )
                break

            # Find missing entities
            current_entities = set(current_summary.text.lower().split())
            missing = [e for e in all_entities if e.lower() not in current_entities]

            if not missing:
                break

            try:
                densified = await self._densify_summary(
                    current_summary,
                    content_str,
                    missing[:10],  # Limit missing entities per iteration
                    claims,
                    iteration,
                )
                summaries.append(densified)
                current_summary = densified
            except Exception as e:
                logger.warning(
                    "Densification iteration failed",
                    iteration=iteration,
                    error=str(e),
                )
                break

        return summaries

    async def _generate_initial_summary(
        self,
        content: str,
        claims: list[DenseClaim],
    ) -> DenseSummary:
        """Generate initial summary using LLM."""
        client = _get_client()

        prompt = render_prompt("initial_summary", content=content[:8000])

        response = await client.generate(
            prompt=prompt,
            model=self._settings.llm.model,
            temperature=0.3,
            max_tokens=1000,
            response_format="json",
        )

        async def _retry_llm_call(retry_prompt: str) -> str:
            return await client.generate(
                prompt=retry_prompt,
                model=self._settings.llm.model,
                temperature=0.3,
                max_tokens=1000,
                response_format="json",
            )

        validated = await parse_and_validate(
            response=response,
            schema=InitialSummaryOutput,
            template_name="initial_summary",
            expect_array=False,
            llm_call=_retry_llm_call,
            max_retries=1,
            context={"phase": "initial_summary"},
        )

        if validated is None:
            summary_text = response.strip()
            entities: list[str] = []
        else:
            summary_text = validated.summary
            entities = validated.entities

        # Count words (handle Japanese)
        word_count = self._count_words(summary_text)

        return DenseSummary(
            iteration=0,
            text=summary_text,
            entity_count=len(entities),
            word_count=word_count,
            density_score=len(entities) / max(word_count, 1),
            claims=claims,
        )

    async def _densify_summary(
        self,
        current: DenseSummary,
        original_content: str,
        missing_entities: list[str],
        claims: list[DenseClaim],
        iteration: int,
    ) -> DenseSummary:
        """Densify summary by adding missing entities."""
        client = _get_client()

        prompt = render_prompt(
            "densify",
            current_summary=current.text,
            original_content=original_content[:6000],
            missing_entities=", ".join(missing_entities),
        )

        response = await client.generate(
            prompt=prompt,
            model=self._settings.llm.model,
            temperature=0.3,
            max_tokens=1000,
            response_format="json",
        )

        async def _retry_llm_call(retry_prompt: str) -> str:
            return await client.generate(
                prompt=retry_prompt,
                model=self._settings.llm.model,
                temperature=0.3,
                max_tokens=1000,
                response_format="json",
            )

        validated = await parse_and_validate(
            response=response,
            schema=DenseSummaryOutput,
            template_name="densify",
            expect_array=False,
            llm_call=_retry_llm_call,
            max_retries=1,
            context={"phase": "densify", "iteration": iteration},
        )

        if validated is None:
            summary_text = current.text
            entities: list[str] = []
        else:
            summary_text = validated.summary
            entities = validated.entities

        word_count = self._count_words(summary_text)

        return DenseSummary(
            iteration=iteration,
            text=summary_text,
            entity_count=len(entities),
            word_count=word_count,
            density_score=len(entities) / max(word_count, 1),
            claims=claims,
        )

    def _extract_all_entities(
        self,
        claims: list[DenseClaim],
        fragments: list[dict[str, Any]],
    ) -> list[str]:
        """Extract all important entities from claims and fragments."""
        entities = set()

        # From claims
        for claim in claims:
            # Extract entities from claim text using simple patterns
            text = claim.text

            # Numbers and dates
            entities.update(re.findall(r"\d{4}年", text))
            entities.update(re.findall(r"\d+%", text))
            entities.update(re.findall(r"\d+億", text))
            entities.update(re.findall(r"\d+万", text))

            # Quoted terms
            entities.update(re.findall(r"「([^」]+)」", text))
            entities.update(re.findall(r'"([^"]+)"', text))

            # From citations
            for cit in claim.citations:
                if cit.title:
                    entities.add(cit.title)

        # From fragments
        for frag in fragments:
            text = frag.get("text_content", "")
            # Extract capitalized terms (likely proper nouns)
            entities.update(re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", text))

        return list(entities)

    def _count_words(self, text: str) -> int:
        """Count words in text (handle Japanese)."""
        if not text:
            return 0

        # For Japanese, count characters as a rough approximation
        # (Japanese doesn't have word boundaries)
        japanese_chars = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]", text))

        # For non-Japanese, count words
        non_japanese = re.sub(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]", " ", text)
        english_words = len(non_japanese.split())

        # Approximate: 2 Japanese characters ≈ 1 word
        return english_words + (japanese_chars // 2)

    def _rule_based_compress(
        self,
        claims: list[DenseClaim],
    ) -> list[DenseSummary]:
        """Rule-based compression without LLM."""
        if not claims:
            return []

        # Sort claims by confidence
        sorted_claims = sorted(
            claims,
            key=lambda c: c.llm_claim_confidence,
            reverse=True,
        )

        # Take top claims
        top_claims = sorted_claims[:10]

        # Build summary text
        summary_parts = []
        for claim in top_claims:
            if claim.llm_claim_confidence >= 0.7:
                summary_parts.append(claim.text)

        summary_text = " ".join(summary_parts)

        # Extract entities
        entities = []
        for claim in top_claims:
            entities.extend(re.findall(r"「([^」]+)」", claim.text))
            entities.extend(re.findall(r"\d{4}年", claim.text))

        entities = list(set(entities))
        word_count = self._count_words(summary_text)

        return [
            DenseSummary(
                iteration=0,
                text=summary_text,
                entity_count=len(entities),
                word_count=word_count,
                density_score=len(entities) / max(word_count, 1),
                claims=claims,
            )
        ]


# Convenience function
async def compress_with_chain_of_density(
    claims: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    task_query: str,
    max_iterations: int = 5,
    use_llm: bool = True,
) -> dict[str, Any]:
    """
    Compress claims and fragments using Chain-of-Density.

    Compression and Citation Strictness
    - Increase summary density using Chain-of-Density approach
    - Require deep links, discovery timestamps, and excerpts for all claims

    Args:
        claims: List of claim records.
        fragments: List of fragment records.
        task_query: Original research query.
        max_iterations: Maximum densification iterations.
        use_llm: Whether to use LLM for compression.

    Returns:
        Compression result with dense summary and validated claims.
    """
    compressor = ChainOfDensityCompressor(
        max_iterations=max_iterations,
        use_llm=use_llm,
    )

    return await compressor.compress(claims, fragments, task_query)
