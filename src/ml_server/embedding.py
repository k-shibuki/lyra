"""
Embedding model service.
"""

import os
import structlog

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Embedding model service using sentence-transformers."""

    def __init__(self):
        self._model = None
        self._model_name = os.environ.get(
            "LANCET_ML__EMBEDDING_MODEL", "BAAI/bge-m3"
        )
        self._use_gpu = os.environ.get("LANCET_ML__USE_GPU", "true").lower() == "true"

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model is not None

    async def load(self) -> None:
        """Load embedding model."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
            import os

            # Use local_files_only when HF_HUB_OFFLINE is set
            local_only = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
            
            self._model = SentenceTransformer(
                self._model_name,
                local_files_only=local_only,
            )

            # Move to GPU if available
            if self._use_gpu:
                try:
                    self._model = self._model.to("cuda")
                    logger.info(
                        "Embedding model loaded on GPU", model=self._model_name
                    )
                except Exception:
                    logger.warning(
                        "GPU not available, using CPU for embeddings",
                        model=self._model_name,
                    )
            else:
                logger.info("Embedding model loaded on CPU", model=self._model_name)

        except Exception as e:
            logger.error("Failed to load embedding model", error=str(e))
            raise

    async def encode(
        self, texts: list[str], batch_size: int = 8
    ) -> list[list[float]]:
        """Encode texts to embeddings.

        Args:
            texts: List of texts to encode.
            batch_size: Batch size for encoding.

        Returns:
            List of embedding vectors.
        """
        await self.load()

        if not texts:
            return []

        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        return [emb.tolist() for emb in embeddings]


# Global singleton
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
