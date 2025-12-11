"""
Reranker model service.
"""

import os
import structlog

logger = structlog.get_logger(__name__)


class RerankerService:
    """Reranker model service using cross-encoder."""

    def __init__(self):
        self._model = None
        self._model_name = os.environ.get(
            "LANCET_ML__RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
        )
        self._use_gpu = os.environ.get("LANCET_ML__USE_GPU", "true").lower() == "true"

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
            import os

            device = "cuda" if self._use_gpu else "cpu"
            # Use local_files_only when HF_HUB_OFFLINE is set
            local_only = os.environ.get("HF_HUB_OFFLINE", "0") == "1"

            try:
                self._model = CrossEncoder(
                    self._model_name,
                    device=device,
                    local_files_only=local_only,
                )
                logger.info(
                    "Reranker model loaded",
                    model=self._model_name,
                    device=device,
                )
            except Exception:
                self._model = CrossEncoder(self._model_name, device="cpu")
                logger.warning(
                    "Reranker loaded on CPU (GPU failed)",
                    model=self._model_name,
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
        await self.load()

        if not documents:
            return []

        # Prepare pairs
        pairs = [(query, doc) for doc in documents]

        # Get scores
        scores = self._model.predict(pairs, show_progress_bar=False)

        # Sort by score
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
