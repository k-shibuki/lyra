"""
Passage ranking for Lancet.
Multi-stage ranking: BM25 → Embeddings → Reranker.
"""

import hashlib
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.storage.database import get_database

logger = get_logger(__name__)


class BM25Ranker:
    """BM25-based first-stage ranker."""
    
    def __init__(self):
        self._index = None
        self._corpus = []
        self._tokenizer = None
    
    def _get_tokenizer(self):
        """Get or create tokenizer."""
        if self._tokenizer is None:
            try:
                from sudachipy import tokenizer
                from sudachipy import dictionary
                
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
            tokens = [
                m.surface() 
                for m in tokenizer.tokenize(text, self._tokenize_mode)
            ]
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
        return scores.tolist()


class EmbeddingRanker:
    """Embedding-based semantic similarity ranker."""
    
    def __init__(self):
        self._model = None
        self._settings = get_settings()
        self._cache = {}
    
    async def _ensure_model(self) -> None:
        """Ensure embedding model is loaded."""
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
            
            model_name = self._settings.embedding.model_name
            
            # Try to load ONNX version if available
            self._model = SentenceTransformer(model_name)
            
            # Move to GPU if available
            if self._settings.embedding.use_gpu:
                try:
                    self._model = self._model.to("cuda")
                    logger.info("Embedding model loaded on GPU", model=model_name)
                except Exception:
                    logger.warning("GPU not available, using CPU for embeddings")
            else:
                logger.info("Embedding model loaded on CPU", model=model_name)
                
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
        await self._ensure_model()
        
        # Check cache
        uncached_texts = []
        uncached_indices = []
        results = [None] * len(texts)
        
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
            
            for idx, emb in zip(uncached_indices, embeddings):
                emb_list = emb.tolist()
                cache_key = self._get_cache_key(texts[idx])
                self._cache[cache_key] = emb_list
                results[idx] = emb_list
        
        return results
    
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
            score = sum(a * b for a, b in zip(query_emb, doc_emb))
            scores.append(score)
        
        return scores


class Reranker:
    """Cross-encoder reranker for final ranking."""
    
    def __init__(self):
        self._model = None
        self._settings = get_settings()
    
    async def _ensure_model(self) -> None:
        """Ensure reranker model is loaded."""
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import CrossEncoder
            
            model_name = self._settings.reranker.model_name
            
            device = "cuda" if self._settings.reranker.use_gpu else "cpu"
            
            try:
                self._model = CrossEncoder(model_name, device=device)
                logger.info("Reranker model loaded", model=model_name, device=device)
            except Exception:
                self._model = CrossEncoder(model_name, device="cpu")
                logger.warning("Reranker loaded on CPU (GPU failed)")
                
        except Exception as e:
            logger.error("Failed to load reranker model", error=str(e))
            raise
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.
        
        Args:
            query: Query text.
            documents: List of document texts.
            top_k: Number of top results to return.
            
        Returns:
            List of (index, score) tuples sorted by score descending.
        """
        await self._ensure_model()
        
        if top_k is None:
            top_k = self._settings.reranker.top_k
        
        # Prepare pairs
        pairs = [(query, doc) for doc in documents]
        
        # Get scores
        scores = self._model.predict(pairs, show_progress_bar=False)
        
        # Sort by score
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        
        return indexed_scores[:top_k]


# Global ranker instances
_bm25_ranker: BM25Ranker | None = None
_embedding_ranker: EmbeddingRanker | None = None
_reranker: Reranker | None = None


async def rank_candidates(
    query: str,
    passages: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Multi-stage ranking of passages.
    
    Stage 1: BM25 for fast filtering
    Stage 2: Embeddings for semantic similarity
    Stage 3: Reranker for precision
    
    Args:
        query: Search query.
        passages: List of passage dicts with 'id' and 'text'.
        top_k: Number of top results to return.
        
    Returns:
        List of passage dicts with scores added.
    """
    global _bm25_ranker, _embedding_ranker, _reranker
    
    if not passages:
        return []
    
    settings = get_settings()
    
    # Initialize rankers
    if _bm25_ranker is None:
        _bm25_ranker = BM25Ranker()
    if _embedding_ranker is None:
        _embedding_ranker = EmbeddingRanker()
    if _reranker is None:
        _reranker = Reranker()
    
    # Extract texts
    texts = [p["text"] for p in passages]
    
    # Stage 1: BM25
    _bm25_ranker.fit(texts)
    bm25_scores = _bm25_ranker.get_scores(query)
    
    # Get top candidates for embedding ranking
    bm25_top_k = min(len(passages), settings.reranker.max_top_k)
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
        combined_score = 0.3 * bm25_score + 0.7 * embed_score
        combined.append((orig_idx, bm25_score, embed_score, combined_score))
    
    # Sort by combined score and get top candidates for reranking
    combined.sort(key=lambda x: x[3], reverse=True)
    rerank_candidates = combined[:settings.reranker.top_k]
    
    # Stage 3: Reranker
    rerank_texts = [texts[idx] for idx, _, _, _ in rerank_candidates]
    reranked = await _reranker.rerank(query, rerank_texts, top_k=top_k)
    
    # Build final results
    results = []
    for rank_idx, (rerank_pos, rerank_score) in enumerate(reranked):
        orig_idx, bm25_score, embed_score, _ = rerank_candidates[rerank_pos]
        
        passage = passages[orig_idx].copy()
        passage["score_bm25"] = bm25_score
        passage["score_embed"] = embed_score
        passage["score_rerank"] = float(rerank_score)
        passage["final_rank"] = rank_idx + 1
        
        results.append(passage)
    
    logger.info(
        "Ranking completed",
        query=query[:50],
        input_count=len(passages),
        output_count=len(results),
    )
    
    return results

