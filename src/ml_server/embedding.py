"""
Embedding model service.
"""

import os

import structlog

from src.ml_server.model_paths import get_embedding_path, is_using_local_paths

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Embedding model service using sentence-transformers.

    Provides text embedding functionality using a sentence-transformer model.
    The model is lazy-loaded on first encode() call.
    """

    def __init__(self) -> None:
        """Initialize embedding service."""
        from typing import Any

        self._model: Any = None

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

            model_path = get_embedding_path()
            use_local = is_using_local_paths()

            logger.info(
                "Loading embedding model",
                model_path=model_path,
                use_local=use_local,
            )

            local_only = use_local or os.environ.get("HF_HUB_OFFLINE", "0") == "1"

            self._model = SentenceTransformer(
                model_path,
                local_files_only=local_only,
            )
            assert self._model is not None

            self._model = self._model.to("cuda")
            logger.info(
                "Embedding model loaded on GPU",
                model_path=model_path,
            )

        except Exception as e:
            logger.error("Failed to load embedding model", error=str(e))
            raise

    async def encode(self, texts: list[str], batch_size: int = 8) -> list[list[float]]:
        """Encode texts to embeddings.

        Args:
            texts: List of texts to encode.
            batch_size: Batch size for encoding.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        await self.load()
        assert self._model is not None

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
