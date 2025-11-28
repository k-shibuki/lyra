"""
Query A/B testing module for Lancet.

Implements §3.1.1: Query A/B Testing
- Small-scale A/B tests with notation/particle/word-order variants
- Cache and reuse high-yield queries

This module generates query variants, executes them in parallel,
and tracks which variants produce the highest harvest rates.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.storage.database import get_database
from src.utils.logging import get_logger, CausalTrace

logger = get_logger(__name__)


# ============================================================================
# Data Structures
# ============================================================================


class VariantType(str, Enum):
    """Type of query variant."""
    ORIGINAL = "original"
    NOTATION = "notation"  # Notation variation (e.g., kanji vs hiragana)
    PARTICLE = "particle"  # Particle substitution
    ORDER = "order"  # Word order change
    COMBINED = "combined"  # Combined changes


@dataclass
class QueryVariant:
    """A single query variant."""
    query_text: str
    variant_type: VariantType
    transformation: str = ""  # Description of transformation applied
    
    def __hash__(self):
        return hash((self.query_text, self.variant_type))
    
    def __eq__(self, other):
        if not isinstance(other, QueryVariant):
            return False
        return self.query_text == other.query_text


@dataclass
class ABTestResult:
    """Result of an A/B test for a single variant."""
    variant: QueryVariant
    query_id: str | None = None
    result_count: int = 0
    useful_fragments: int = 0
    harvest_rate: float = 0.0
    execution_time_ms: int = 0


@dataclass
class ABTestSession:
    """A complete A/B test session."""
    id: str
    task_id: str
    base_query: str
    variants: list[QueryVariant] = field(default_factory=list)
    results: list[ABTestResult] = field(default_factory=list)
    winner: ABTestResult | None = None
    status: str = "pending"  # pending, running, completed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HighYieldPattern:
    """A cached high-yield query pattern."""
    id: str
    pattern_type: str
    original_pattern: str
    improved_pattern: str
    improvement_ratio: float
    sample_count: int = 1
    confidence: float = 0.5


# ============================================================================
# Query Variant Generator
# ============================================================================


class QueryVariantGenerator:
    """
    Generate query variants for A/B testing.
    
    Implements three types of variations:
    1. Notation: Kanji↔Hiragana, long vowels, etc.
    2. Particle: Japanese particle substitutions
    3. Order: Reordering of query terms
    """
    
    def __init__(self):
        """Initialize the variant generator."""
        self._tokenizer = None
        self._initialized = False
        
        # Particle substitution rules (Japanese)
        self._particle_rules = [
            # の ↔ における (more formal)
            (r"(\w+)の(\w+)", r"\1における\2"),
            # は ↔ について
            (r"(\w+)は(\w+)", r"\1について\2"),
            # を ↔ に関する
            (r"(\w+)を(\w+)", r"\1に関する\2"),
            # と ↔ および
            (r"(\w+)と(\w+)", r"\1および\2"),
            # から ↔ より
            (r"から", r"より"),
            # まで ↔ に至る
            (r"まで", r"に至る"),
        ]
        
        # Notation substitution rules
        self._notation_rules = {
            # Long vowel variations
            "ー": ["−", "-", ""],  # Different dashes and omission
            # Common Kanji↔Hiragana pairs
            "問題": ["もんだい"],
            "方法": ["ほうほう"],
            "結果": ["けっか"],
            "影響": ["えいきょう"],
            "原因": ["げんいん"],
            "分析": ["ぶんせき"],
            "比較": ["ひかく"],
            "調査": ["ちょうさ"],
            # Tech term variations
            "AI": ["人工知能", "エーアイ"],
            "人工知能": ["AI", "エーアイ"],
            "セキュリティ": ["セキュリティー", "security"],
            "データ": ["data", "デェータ"],
            "サーバー": ["サーバ", "server"],
            "コンピューター": ["コンピュータ", "computer"],
            "ユーザー": ["ユーザ", "user"],
            # Business terms
            "企業": ["会社", "事業者"],
            "顧客": ["お客様", "クライアント"],
        }
    
    def _ensure_initialized(self) -> bool:
        """Ensure SudachiPy is initialized for tokenization."""
        if self._initialized:
            return self._tokenizer is not None
        
        self._initialized = True
        try:
            from sudachipy import dictionary, tokenizer
            
            self._tokenizer = dictionary.Dictionary().create()
            self._tokenize_mode = tokenizer.Tokenizer.SplitMode.B  # Use B mode for better segmentation
            
            logger.debug("SudachiPy initialized for query variant generation")
            return True
        except ImportError:
            logger.warning("SudachiPy not available for query variant generation")
            return False
    
    def _tokenize(self, text: str) -> list[dict[str, Any]]:
        """Tokenize text into morphemes."""
        if not self._ensure_initialized() or not self._tokenizer:
            # Fallback: simple space/punctuation-based tokenization
            words = re.findall(r'[\w]+', text, re.UNICODE)
            return [{"surface": w, "pos": "unknown"} for w in words]
        
        tokens = []
        for m in self._tokenizer.tokenize(text, self._tokenize_mode):
            tokens.append({
                "surface": m.surface(),
                "normalized": m.normalized_form(),
                "pos": m.part_of_speech()[0] if m.part_of_speech() else "unknown",
                "reading": m.reading_form(),
            })
        return tokens
    
    def generate_notation_variants(self, query: str, max_variants: int = 2) -> list[QueryVariant]:
        """
        Generate notation variants.
        
        Args:
            query: Original query.
            max_variants: Maximum number of variants to generate.
            
        Returns:
            List of notation variants.
        """
        variants = []
        
        # Check each notation rule
        for original, replacements in self._notation_rules.items():
            if original in query:
                for replacement in replacements[:1]:  # Limit to first replacement
                    variant_text = query.replace(original, replacement, 1)
                    if variant_text != query:
                        variants.append(QueryVariant(
                            query_text=variant_text,
                            variant_type=VariantType.NOTATION,
                            transformation=f"{original}→{replacement}",
                        ))
                        
                        if len(variants) >= max_variants:
                            return variants
        
        return variants
    
    def generate_particle_variants(self, query: str, max_variants: int = 2) -> list[QueryVariant]:
        """
        Generate particle variants.
        
        Args:
            query: Original query.
            max_variants: Maximum number of variants to generate.
            
        Returns:
            List of particle variants.
        """
        variants = []
        
        for pattern, replacement in self._particle_rules:
            if re.search(pattern, query):
                variant_text = re.sub(pattern, replacement, query, count=1)
                if variant_text != query:
                    variants.append(QueryVariant(
                        query_text=variant_text,
                        variant_type=VariantType.PARTICLE,
                        transformation=f"pattern:{pattern[:20]}",
                    ))
                    
                    if len(variants) >= max_variants:
                        return variants
        
        return variants
    
    def generate_order_variants(self, query: str, max_variants: int = 2) -> list[QueryVariant]:
        """
        Generate word order variants.
        
        Args:
            query: Original query.
            max_variants: Maximum number of variants to generate.
            
        Returns:
            List of order variants.
        """
        variants = []
        
        # Tokenize to get content words
        tokens = self._tokenize(query)
        
        # Extract content words (nouns, verbs)
        content_words = [
            t["surface"] for t in tokens
            if t["pos"] in ["名詞", "動詞", "形容詞", "unknown"] and len(t["surface"]) > 1
        ]
        
        # Only reorder if we have 2+ content words
        if len(content_words) >= 2:
            # Swap first two content words
            words_copy = content_words.copy()
            words_copy[0], words_copy[1] = words_copy[1], words_copy[0]
            
            # Reconstruct query with swapped order
            variant_text = query
            for orig, new in zip(content_words[:2], words_copy[:2]):
                if orig != new:
                    variant_text = variant_text.replace(orig, f"__TEMP_{new}__", 1)
            
            variant_text = variant_text.replace("__TEMP_", "").replace("__", "")
            
            if variant_text != query and len(variant_text) > 0:
                # More robust approach: just swap the order
                parts = query.split()
                if len(parts) >= 2:
                    swapped = parts.copy()
                    swapped[0], swapped[-1] = swapped[-1], swapped[0]
                    variant_text = " ".join(swapped)
                    
                    if variant_text != query:
                        variants.append(QueryVariant(
                            query_text=variant_text,
                            variant_type=VariantType.ORDER,
                            transformation=f"swap:{parts[0]}↔{parts[-1]}",
                        ))
        
        # Also try moving the last word to the front
        words = query.split()
        if len(words) >= 2 and len(variants) < max_variants:
            reordered = [words[-1]] + words[:-1]
            variant_text = " ".join(reordered)
            if variant_text != query:
                variants.append(QueryVariant(
                    query_text=variant_text,
                    variant_type=VariantType.ORDER,
                    transformation="rotate-last-to-front",
                ))
        
        return variants[:max_variants]
    
    def generate_all_variants(
        self,
        query: str,
        max_per_type: int = 2,
        max_total: int = 5,
    ) -> list[QueryVariant]:
        """
        Generate all types of variants.
        
        Args:
            query: Original query.
            max_per_type: Maximum variants per type.
            max_total: Maximum total variants (excluding original).
            
        Returns:
            List of all variants (including original).
        """
        all_variants = [
            QueryVariant(
                query_text=query,
                variant_type=VariantType.ORIGINAL,
                transformation="none",
            )
        ]
        
        # Generate each type
        notation_variants = self.generate_notation_variants(query, max_per_type)
        particle_variants = self.generate_particle_variants(query, max_per_type)
        order_variants = self.generate_order_variants(query, max_per_type)
        
        # Add in priority order (notation > particle > order)
        for v in notation_variants + particle_variants + order_variants:
            if v not in all_variants:
                all_variants.append(v)
                if len(all_variants) > max_total:
                    break
        
        logger.debug(
            "Generated query variants",
            original=query,
            variant_count=len(all_variants),
            types=[v.variant_type.value for v in all_variants],
        )
        
        return all_variants


# ============================================================================
# A/B Test Executor
# ============================================================================


class ABTestExecutor:
    """
    Execute A/B tests for query variants.
    
    Runs multiple query variants, measures harvest rates,
    and identifies the best-performing variant.
    """
    
    def __init__(self):
        """Initialize the A/B test executor."""
        self._generator = QueryVariantGenerator()
    
    async def run_ab_test(
        self,
        task_id: str,
        base_query: str,
        engines: list[str] | None = None,
        limit: int = 10,
        time_range: str = "all",
        max_variants: int = 3,
    ) -> ABTestSession:
        """
        Run an A/B test on query variants.
        
        Args:
            task_id: Task ID for tracking.
            base_query: Original query to test.
            engines: Search engines to use.
            limit: Results limit per query.
            time_range: Time range filter.
            max_variants: Maximum variants to test (including original).
            
        Returns:
            ABTestSession with results.
        """
        from src.search import search_serp
        
        session_id = self._generate_session_id(task_id, base_query)
        
        # Generate variants
        variants = self._generator.generate_all_variants(
            base_query,
            max_total=max_variants,
        )
        
        session = ABTestSession(
            id=session_id,
            task_id=task_id,
            base_query=base_query,
            variants=variants,
            status="running",
        )
        
        # Save session start
        await self._save_session(session)
        
        with CausalTrace() as trace:
            # Execute searches for each variant
            results = []
            
            for variant in variants:
                try:
                    start_time = datetime.now()
                    
                    # Execute search
                    serp_results = await search_serp(
                        query=variant.query_text,
                        engines=engines,
                        limit=limit,
                        time_range=time_range,
                        task_id=task_id,
                        use_cache=True,
                    )
                    
                    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
                    
                    # Calculate metrics (simplified: count results as proxy for usefulness)
                    result_count = len(serp_results)
                    # In a real scenario, we'd need to fetch and evaluate content
                    # For now, use result count as proxy
                    useful_estimate = min(result_count, limit)
                    harvest_rate = useful_estimate / limit if limit > 0 else 0
                    
                    result = ABTestResult(
                        variant=variant,
                        result_count=result_count,
                        useful_fragments=useful_estimate,
                        harvest_rate=harvest_rate,
                        execution_time_ms=execution_time,
                    )
                    results.append(result)
                    
                    logger.debug(
                        "A/B test variant executed",
                        variant_type=variant.variant_type.value,
                        query=variant.query_text[:50],
                        result_count=result_count,
                        harvest_rate=harvest_rate,
                    )
                    
                except Exception as e:
                    logger.error(
                        "A/B test variant failed",
                        variant=variant.query_text[:50],
                        error=str(e),
                    )
                    results.append(ABTestResult(
                        variant=variant,
                        harvest_rate=0.0,
                    ))
            
            # Find winner (highest harvest rate)
            if results:
                winner = max(results, key=lambda r: r.harvest_rate)
                session.winner = winner
            
            session.results = results
            session.status = "completed"
            
            # Save final session
            await self._save_session(session)
            
            # Cache high-yield pattern if improvement found
            if session.winner and session.winner.variant.variant_type != VariantType.ORIGINAL:
                await self._cache_high_yield_pattern(session)
            
            logger.info(
                "A/B test completed",
                session_id=session_id,
                base_query=base_query[:50],
                variant_count=len(variants),
                winner_type=session.winner.variant.variant_type.value if session.winner else None,
                winner_harvest_rate=session.winner.harvest_rate if session.winner else 0,
                cause_id=trace.id,
            )
        
        return session
    
    def _generate_session_id(self, task_id: str, query: str) -> str:
        """Generate a unique session ID."""
        content = f"{task_id}:{query}:{datetime.now(timezone.utc).isoformat()}"
        return f"ab_{hashlib.sha256(content.encode()).hexdigest()[:16]}"
    
    async def _save_session(self, session: ABTestSession) -> None:
        """Save A/B test session to database."""
        db = await get_database()
        
        # Save main session
        await db.execute(
            """
            INSERT OR REPLACE INTO query_ab_tests 
            (id, task_id, base_query, created_at, winner_variant_type, 
             winner_harvest_rate, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.task_id,
                session.base_query,
                session.created_at.isoformat(),
                session.winner.variant.variant_type.value if session.winner else None,
                session.winner.harvest_rate if session.winner else None,
                session.status,
            ),
        )
        
        # Save variants
        for result in session.results:
            await db.execute(
                """
                INSERT OR REPLACE INTO query_ab_variants
                (id, ab_test_id, variant_type, query_text, transformation,
                 result_count, useful_fragments, harvest_rate, execution_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{session.id}_{result.variant.variant_type.value}",
                    session.id,
                    result.variant.variant_type.value,
                    result.variant.query_text,
                    result.variant.transformation,
                    result.result_count,
                    result.useful_fragments,
                    result.harvest_rate,
                    result.execution_time_ms,
                ),
            )
    
    async def _cache_high_yield_pattern(self, session: ABTestSession) -> None:
        """Cache a high-yield pattern for reuse."""
        if not session.winner or session.winner.variant.variant_type == VariantType.ORIGINAL:
            return
        
        # Find original result
        original_result = next(
            (r for r in session.results if r.variant.variant_type == VariantType.ORIGINAL),
            None
        )
        
        if not original_result or original_result.harvest_rate <= 0:
            return
        
        improvement = (session.winner.harvest_rate - original_result.harvest_rate) / original_result.harvest_rate
        
        # Only cache if significant improvement (>10%)
        if improvement < 0.1:
            return
        
        db = await get_database()
        
        pattern_id = hashlib.sha256(
            f"{session.winner.variant.transformation}:{session.base_query}".encode()
        ).hexdigest()[:16]
        
        # Check if pattern exists
        existing = await db.fetch_one(
            "SELECT sample_count, improvement_ratio FROM high_yield_queries WHERE id = ?",
            (pattern_id,),
        )
        
        if existing:
            # Update with exponential moving average
            new_count = existing["sample_count"] + 1
            new_improvement = (
                existing["improvement_ratio"] * 0.7 + improvement * 0.3
            )
            confidence = min(0.95, 0.5 + 0.1 * new_count)
            
            await db.execute(
                """
                UPDATE high_yield_queries 
                SET sample_count = ?, improvement_ratio = ?, confidence = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_count, new_improvement, confidence, pattern_id),
            )
        else:
            await db.execute(
                """
                INSERT INTO high_yield_queries
                (id, pattern_type, original_pattern, improved_pattern, 
                 improvement_ratio, sample_count, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    session.winner.variant.variant_type.value,
                    session.base_query,
                    session.winner.variant.query_text,
                    improvement,
                    1,
                    0.5,
                ),
            )
        
        logger.info(
            "High-yield pattern cached",
            pattern_type=session.winner.variant.variant_type.value,
            improvement=f"{improvement:.1%}",
        )


# ============================================================================
# High-Yield Query Cache
# ============================================================================


class HighYieldQueryCache:
    """
    Cache and retrieve high-yield query patterns.
    
    Implements §3.1.1: Cache and reuse high-yield queries.
    """
    
    async def get_improved_query(
        self,
        query: str,
        min_confidence: float = 0.6,
    ) -> str | None:
        """
        Get an improved version of a query based on cached patterns.
        
        Args:
            query: Original query.
            min_confidence: Minimum confidence threshold.
            
        Returns:
            Improved query or None if no suitable pattern found.
        """
        db = await get_database()
        
        # Look for similar patterns
        patterns = await db.fetch_all(
            """
            SELECT pattern_type, original_pattern, improved_pattern, 
                   improvement_ratio, confidence
            FROM high_yield_queries
            WHERE confidence >= ?
            ORDER BY improvement_ratio DESC
            LIMIT 10
            """,
            (min_confidence,),
        )
        
        for pattern in patterns:
            original = pattern["original_pattern"]
            improved = pattern["improved_pattern"]
            
            # Check if query matches the pattern structure
            if self._matches_pattern(query, original, improved):
                applied = self._apply_pattern(query, original, improved)
                if applied and applied != query:
                    logger.debug(
                        "Applied cached high-yield pattern",
                        original=query[:50],
                        improved=applied[:50],
                        pattern_type=pattern["pattern_type"],
                        confidence=pattern["confidence"],
                    )
                    return applied
        
        return None
    
    def _matches_pattern(self, query: str, original: str, improved: str) -> bool:
        """Check if a query matches a cached pattern structure."""
        # Simple heuristic: check if they share common terms
        query_terms = set(query.lower().split())
        original_terms = set(original.lower().split())
        
        if not query_terms or not original_terms:
            return False
        
        overlap = len(query_terms & original_terms)
        similarity = overlap / max(len(query_terms), len(original_terms))
        
        return similarity >= 0.5
    
    def _apply_pattern(self, query: str, original: str, improved: str) -> str | None:
        """Apply a cached pattern to a new query."""
        # Find the transformation applied
        for orig_word, imp_word in zip(original.split(), improved.split()):
            if orig_word != imp_word and orig_word in query:
                return query.replace(orig_word, imp_word, 1)
        
        return None
    
    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about cached patterns."""
        db = await get_database()
        
        stats = await db.fetch_one(
            """
            SELECT 
                COUNT(*) as total_patterns,
                AVG(improvement_ratio) as avg_improvement,
                AVG(confidence) as avg_confidence,
                SUM(sample_count) as total_samples
            FROM high_yield_queries
            """
        )
        
        return {
            "total_patterns": stats["total_patterns"] if stats else 0,
            "avg_improvement": stats["avg_improvement"] if stats else 0,
            "avg_confidence": stats["avg_confidence"] if stats else 0,
            "total_samples": stats["total_samples"] if stats else 0,
        }


# ============================================================================
# Module-level Functions
# ============================================================================


# Global instances
_generator: QueryVariantGenerator | None = None
_executor: ABTestExecutor | None = None
_cache: HighYieldQueryCache | None = None


def get_variant_generator() -> QueryVariantGenerator:
    """Get or create the global variant generator."""
    global _generator
    if _generator is None:
        _generator = QueryVariantGenerator()
    return _generator


def get_ab_executor() -> ABTestExecutor:
    """Get or create the global A/B test executor."""
    global _executor
    if _executor is None:
        _executor = ABTestExecutor()
    return _executor


def get_high_yield_cache() -> HighYieldQueryCache:
    """Get or create the global high-yield cache."""
    global _cache
    if _cache is None:
        _cache = HighYieldQueryCache()
    return _cache


async def run_query_ab_test(
    task_id: str,
    query: str,
    engines: list[str] | None = None,
    limit: int = 10,
    max_variants: int = 3,
) -> ABTestSession:
    """
    Run an A/B test on a query.
    
    Convenience function for running A/B tests.
    
    Args:
        task_id: Task ID.
        query: Query to test.
        engines: Search engines.
        limit: Results limit.
        max_variants: Max variants.
        
    Returns:
        ABTestSession with results.
    """
    executor = get_ab_executor()
    return await executor.run_ab_test(
        task_id=task_id,
        base_query=query,
        engines=engines,
        limit=limit,
        max_variants=max_variants,
    )


async def get_optimized_query(query: str) -> str:
    """
    Get an optimized version of a query using cached patterns.
    
    Args:
        query: Original query.
        
    Returns:
        Optimized query (or original if no optimization found).
    """
    cache = get_high_yield_cache()
    improved = await cache.get_improved_query(query)
    return improved if improved else query


def generate_query_variants(query: str, max_variants: int = 5) -> list[QueryVariant]:
    """
    Generate query variants for testing.
    
    Args:
        query: Original query.
        max_variants: Maximum variants.
        
    Returns:
        List of variants.
    """
    generator = get_variant_generator()
    return generator.generate_all_variants(query, max_total=max_variants)

