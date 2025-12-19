"""
ML Server Client.
HTTP client for communicating with the ML server (lancet-ml container).
ML models run in a separate container on internal network for security isolation.
"""

import asyncio
from typing import Any

import httpx

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MLClientError(Exception):
    """Base exception for ML client errors."""

    def __init__(self, message: str, operation: str | None = None):
        self.operation = operation
        super().__init__(message)


class EmbeddingError(MLClientError):
    """Raised when embedding operation fails."""

    def __init__(self, message: str):
        super().__init__(message, operation="embedding")


class RerankingError(MLClientError):
    """Raised when reranking operation fails."""

    def __init__(self, message: str):
        super().__init__(message, operation="reranking")


class NLIError(MLClientError):
    """Raised when NLI operation fails."""

    def __init__(self, message: str):
        super().__init__(message, operation="nli")


class MLClient:
    """HTTP client for ML Server."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._base_url: str | None = None

    def _get_base_url(self) -> str:
        """Get base URL for ML server (always via proxy in hybrid mode)."""
        if self._base_url is not None:
            return self._base_url

        # Hybrid mode: always use proxy URL
        self._base_url = f"{self._settings.general.proxy_url}/ml"
        logger.debug("Using proxy for ML Server", proxy_url=self._base_url)

        return self._base_url

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._get_base_url(),
                timeout=httpx.Timeout(self._settings.ml.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        json: dict | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST).
            endpoint: API endpoint.
            json: Request body (for POST).

        Returns:
            Response JSON.

        Raises:
            Exception: If all retries fail.
        """
        client = await self._get_client()
        last_error = None

        for attempt in range(self._settings.ml.max_retries):
            try:
                if method == "GET":
                    response = await client.get(endpoint)
                else:
                    response = await client.post(endpoint, json=json)

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    "ML Server HTTP error",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    "ML Server request error",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt + 1,
                )

            if attempt < self._settings.ml.max_retries - 1:
                delay = self._settings.ml.retry_delay * (2**attempt)
                await asyncio.sleep(delay)

        logger.error(
            "ML Server request failed after retries",
            endpoint=endpoint,
            max_retries=self._settings.ml.max_retries,
        )
        raise last_error or Exception("ML Server request failed")

    async def health_check(self) -> dict[str, Any]:
        """Check ML server health.

        Returns:
            Health status including loaded models.
        """
        return await self._request_with_retry("GET", "/health")

    async def embed(
        self,
        texts: list[str],
        batch_size: int = 8,
    ) -> list[list[float]]:
        """Generate embeddings for texts.

        Args:
            texts: Texts to embed.
            batch_size: Batch size for encoding.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        response = await self._request_with_retry(
            "POST",
            "/embed",
            json={"texts": texts, "batch_size": batch_size},
        )

        if not response.get("ok"):
            error = response.get("error", "Unknown error")
            logger.error("Embedding failed", error=error)
            raise EmbeddingError(f"Embedding failed: {error}")

        return response.get("embeddings", [])

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        Args:
            query: Query text.
            documents: Documents to rerank.
            top_k: Number of top results.

        Returns:
            List of (index, score) tuples sorted by score descending.
        """
        if not documents:
            return []

        response = await self._request_with_retry(
            "POST",
            "/rerank",
            json={"query": query, "documents": documents, "top_k": top_k},
        )

        if not response.get("ok"):
            error = response.get("error", "Unknown error")
            logger.error("Reranking failed", error=error)
            raise RerankingError(f"Reranking failed: {error}")

        results = response.get("results", [])
        return [(r["index"], r["score"]) for r in results]

    async def nli(
        self,
        pairs: list[dict[str, str]],
        use_slow: bool = False,
    ) -> list[dict[str, Any]]:
        """Judge stance relationships for claim pairs.

        Args:
            pairs: List of dicts with 'pair_id', 'premise', 'hypothesis'.
            use_slow: Whether to use slow (GPU) model.

        Returns:
            List of result dicts with 'pair_id', 'label', 'confidence'.
        """
        if not pairs:
            return []

        response = await self._request_with_retry(
            "POST",
            "/nli",
            json={"pairs": pairs, "use_slow": use_slow},
        )

        if not response.get("ok"):
            error = response.get("error", "Unknown error")
            logger.error("NLI failed", error=error)
            raise NLIError(f"NLI failed: {error}")

        return response.get("results", [])

    async def warmup(self) -> None:
        """Warmup ML server by preloading models."""
        try:
            await self._request_with_retry("POST", "/warmup")
            logger.info("ML Server warmup completed")
        except Exception as e:
            logger.warning("ML Server warmup failed", error=str(e))


# Global singleton
_ml_client: MLClient | None = None


def get_ml_client() -> MLClient:
    """Get or create ML client singleton."""
    global _ml_client
    if _ml_client is None:
        _ml_client = MLClient()
    return _ml_client


async def close_ml_client() -> None:
    """Close ML client."""
    global _ml_client
    if _ml_client is not None:
        await _ml_client.close()
        _ml_client = None
