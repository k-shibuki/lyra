"""
Passage ranking for Lyra.
Multi-stage ranking: BM25 → Embeddings → Dynamic Cutoff (Kneedle).

When ml.use_remote=True, embedding is performed
via HTTP calls to the lyra-ml container on internal network.
"""

import hashlib
from typing import Any, cast
from urllib.parse import urlparse

from src.utils.config import get_settings
from src.utils.domain_policy import CATEGORY_WEIGHTS, get_domain_category
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BM25Ranker:
    """BM25-based first-stage ranker."""

    def __init__(self) -> None:
        self._index: Any = None
        self._corpus: list[str] = []
        self._tokenizer: Any = None

    def _get_tokenizer(self) -> Any:
        """Get or create tokenizer."""
        if self._tokenizer is None:
            try:
                from sudachipy import dictionary, tokenizer

                self._tokenizer = dictionary.Dictionary().create()
                self._tokenize_mode = tokenizer.Tokenizer.SplitMode.A
            except ImportError:
                # Fallback to simple whitespace tokenization
                self._tokenizer = "simple"
        return self._tokenizer

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text.

        Args:
            text: Text to tokenize.

        Returns:
            List of tokens.
        """
        tokenizer = self._get_tokenizer()

        if tokenizer == "simple":
            # Simple tokenization for fallback
            import re

            tokens = re.findall(r"\w+", text.lower())
            return tokens
        else:
            # SudachiPy tokenization
            tokens = [m.surface() for m in tokenizer.tokenize(text, self._tokenize_mode)]
            return tokens

    def fit(self, corpus: list[str]) -> None:
        """Fit BM25 index on corpus.

        Args:
            corpus: List of documents.
        """
        from rank_bm25 import BM25Okapi

        self._corpus = corpus
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        self._index = BM25Okapi(tokenized_corpus)

        logger.debug("BM25 index fitted", corpus_size=len(corpus))

    def get_scores(self, query: str) -> list[float]:
        """Get BM25 scores for query.

        Args:
            query: Search query.

        Returns:
            List of scores corresponding to corpus documents.
        """
        if self._index is None:
            raise ValueError("Index not fitted. Call fit() first.")

        tokenized_query = self._tokenize(query)
        scores = self._index.get_scores(tokenized_query)
        return cast(list[float], scores.tolist())


class EmbeddingRanker:
    """Embedding-based semantic similarity ranker.

    Supports both local and remote (ML server) execution based on ml.use_remote setting.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._settings = get_settings()
        self._cache: dict[str, Any] = {}

    async def _ensure_model(self) -> None:
        """Ensure embedding model is loaded (local mode only)."""
        if self._settings.ml.use_remote:
            return  # No local model needed

        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer

            model_name = self._settings.embedding.model_name

            self._model = SentenceTransformer(model_name)
            assert self._model is not None

            self._model = self._model.to("cuda")
            logger.info("Embedding model loaded on GPU", model=model_name)

        except Exception as e:
            logger.error("Failed to load embedding model", error=str(e))
            raise

    def _get_cache_key(self, text: str) -> str:
        """Get cache key for text."""
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts to embeddings.

        Args:
            texts: List of texts.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        # Use remote ML server if configured
        if self._settings.ml.use_remote:
            return await self._encode_remote(texts)

        return await self._encode_local(texts)

    async def _encode_remote(self, texts: list[str]) -> list[list[float]]:
        """Encode texts via ML server."""
        from src.ml_client import get_ml_client

        client = get_ml_client()
        batch_size = self._settings.embedding.batch_size

        return await client.embed(texts, batch_size=batch_size)

    async def _encode_local(self, texts: list[str]) -> list[list[float]]:
        """Encode texts using local model."""
        await self._ensure_model()
        assert self._model is not None  # Guaranteed by _ensure_model

        # Check cache
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []
        results: list[list[float] | None] = [None] * len(texts)

        for idx, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                results[idx] = self._cache[cache_key]
            else:
                uncached_texts.append(text)
                uncached_indices.append(idx)

        # Encode uncached texts
        if uncached_texts:
            batch_size = self._settings.embedding.batch_size
            embeddings = self._model.encode(
                uncached_texts,
                batch_size=batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

            for idx, emb in zip(uncached_indices, embeddings, strict=False):
                emb_list = emb.tolist()
                cache_key = self._get_cache_key(texts[idx])
                self._cache[cache_key] = emb_list
                results[idx] = emb_list

        return cast(list[list[float]], results)

    async def get_scores(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        """Get similarity scores between query and documents.

        Args:
            query: Query text.
            documents: List of document texts.

        Returns:
            List of similarity scores.
        """
        # Encode query and documents together
        all_texts = [query] + documents
        embeddings = await self.encode(all_texts)

        query_emb = embeddings[0]
        doc_embs = embeddings[1:]

        # Calculate cosine similarity
        scores = []
        for doc_emb in doc_embs:
            score = sum(a * b for a, b in zip(query_emb, doc_emb, strict=False))
            scores.append(score)

        return scores


def kneedle_cutoff(
    ranked: list[dict[str, Any]],
    min_results: int = 3,
    max_results: int = 50,
    sensitivity: float = 1.0,
) -> list[dict[str, Any]]:
    """Kneedle algorithm for adaptive cutoff.

    Detects the "knee" (point of maximum curvature) in the score curve
    and cuts off results after that point.

    Args:
        ranked: List of dicts with 'final_score' key, sorted by score descending.
        min_results: Minimum number of results to return.
        max_results: Maximum number of results to consider.
        sensitivity: Kneedle sensitivity parameter (default 1.0).

    Returns:
        Cutoff list of ranked results.
    """
    if len(ranked) <= min_results:
        return ranked

    try:
        from kneed import KneeLocator

        # Extract scores up to max_results
        scores = [p["final_score"] for p in ranked[:max_results]]
        x = list(range(len(scores)))

        if len(scores) < 2:
            return ranked[:min_results]

        # Find knee point
        kneedle = KneeLocator(
            x,
            scores,
            curve="convex",
            direction="decreasing",
            S=sensitivity,
        )

        cutoff = kneedle.knee if kneedle.knee else len(scores)
        cutoff = max(cutoff, min_results)

        return ranked[:cutoff]

    except ImportError:
        # Fallback: return top min_results if kneed not available
        logger.warning("kneed library not available, using min_results cutoff")
        return ranked[:min_results]
    except Exception as e:
        logger.warning("Kneedle cutoff failed, using min_results", error=str(e))
        return ranked[:min_results]


# Global ranker instances
_bm25_ranker: BM25Ranker | None = None
_embedding_ranker: EmbeddingRanker | None = None


async def rank_candidates(
    query: str,
    passages: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Multi-stage ranking of passages.

    Stage 1: BM25 for fast filtering
    Stage 2: Embeddings for semantic similarity
    Stage 3: Dynamic cutoff (Kneedle algorithm)

    Args:
        query: Search query.
        passages: List of passage dicts with 'id' and 'text'.
        top_k: Number of top results to return (deprecated, kept for compatibility).

    Returns:
        List of passage dicts with scores added.
    """
    global _bm25_ranker, _embedding_ranker

    if not passages:
        return []

    settings = get_settings()
    ranking_config = settings.ranking

    # Initialize rankers
    if _bm25_ranker is None:
        _bm25_ranker = BM25Ranker()
    if _embedding_ranker is None:
        _embedding_ranker = EmbeddingRanker()

    # Extract texts
    texts = [p["text"] for p in passages]

    # Stage 1: BM25
    _bm25_ranker.fit(texts)
    bm25_scores = _bm25_ranker.get_scores(query)

    # Get top candidates for embedding ranking
    bm25_top_k = min(len(passages), ranking_config.bm25_top_k)
    bm25_ranked = sorted(
        enumerate(bm25_scores),
        key=lambda x: x[1],
        reverse=True,
    )[:bm25_top_k]

    # Stage 2: Embedding similarity
    candidate_indices = [idx for idx, _ in bm25_ranked]
    candidate_texts = [texts[idx] for idx in candidate_indices]

    embed_scores = await _embedding_ranker.get_scores(query, candidate_texts)

    # Combine BM25 and embedding scores
    combined = []
    for i, (orig_idx, bm25_score) in enumerate(bm25_ranked):
        embed_score = embed_scores[i]
        # Weighted combination
        combined_score = (
            ranking_config.bm25_weight * bm25_score + ranking_config.embedding_weight * embed_score
        )
        combined.append((orig_idx, bm25_score, embed_score, combined_score))

    # Sort by combined score
    combined.sort(key=lambda x: x[3], reverse=True)

    # Build results with category weight adjustment
    results = []
    for orig_idx, bm25_score, embed_score, combined_score in combined:
        passage = passages[orig_idx].copy()
        passage["score_bm25"] = bm25_score
        passage["score_embed"] = embed_score

        # Apply category weight adjustment
        url = passage.get("url") or passage.get("page_url") or ""
        category_weight = 1.0  # Default weight
        if url:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                category = get_domain_category(domain)
                category_weight = CATEGORY_WEIGHTS.get(category, 0.3)
            except Exception:
                pass

        passage["category_weight"] = category_weight
        passage["final_score"] = combined_score * category_weight

        results.append(passage)

    # Stage 3: Dynamic cutoff (Kneedle algorithm)
    if ranking_config.kneedle_cutoff.enabled:
        results = kneedle_cutoff(
            results,
            min_results=ranking_config.kneedle_cutoff.min_results,
            max_results=ranking_config.kneedle_cutoff.max_results,
            sensitivity=ranking_config.kneedle_cutoff.sensitivity,
        )
    else:
        # Fallback: use top_k if Kneedle disabled
        results = results[:top_k]

    # Set final ranks
    for rank_idx, passage in enumerate(results):
        passage["final_rank"] = rank_idx + 1

    logger.info(
        "Ranking completed",
        query=query[:50],
        input_count=len(passages),
        output_count=len(results),
    )

    return results


def get_embedding_ranker() -> EmbeddingRanker:
    """Get or create the global EmbeddingRanker instance.

    Returns:
        EmbeddingRanker instance.
    """
    global _embedding_ranker
    if _embedding_ranker is None:
        _embedding_ranker = EmbeddingRanker()
    return _embedding_ranker
