"""
Reranker model service.
"""

import structlog

from src.ml_server.model_paths import get_reranker_path, is_using_local_paths

logger = structlog.get_logger(__name__)


class RerankerService:
    """Reranker model service using cross-encoder."""

    def __init__(self) -> None:
        self._model = None

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model is not None

    async def load(self) -> None:
        """Load reranker model."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import CrossEncoder

            model_path = get_reranker_path()
            use_local = is_using_local_paths()

            logger.info(
                "Loading reranker model",
                model_path=model_path,
                use_local=use_local,
            )

            self._model = CrossEncoder(
                model_path,
                device="cuda",
            )
            logger.info(
                "Reranker model loaded on GPU",
                model_path=model_path,
            )

        except Exception as e:
            logger.error("Failed to load reranker model", error=str(e))
            raise

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        Args:
            query: Query text.
            documents: List of document texts.
            top_k: Number of top results to return.

        Returns:
            List of (index, score) tuples sorted by score descending.
        """
        if not documents:
            return []

        await self.load()
        assert self._model is not None

        pairs = [(query, doc) for doc in documents]
        scores = self._model.predict(pairs, show_progress_bar=False)

        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        return [(idx, float(score)) for idx, score in indexed_scores[:top_k]]


# Global singleton
_reranker_service: RerankerService | None = None


def get_reranker_service() -> RerankerService:
    """Get or create reranker service singleton."""
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service
