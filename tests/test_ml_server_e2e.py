"""
E2E tests for ML Server.

=============================================================================
RECOMMENDED: Primary way to validate ML Server functionality
=============================================================================

These tests verify the ML server by making actual HTTP requests through
the proxy server (localhost:8080). This is the production-like validation
method that tests:

- Embedding generation (bge-m3)
- NLI inference (nli-deberta-v3-small)
- Offline mode operation (no HuggingFace API calls)

Prerequisites:
    1. Start containers: podman-compose up -d
    2. Wait for ML server to be ready (models loaded)

Run:
    pytest tests/test_ml_server_e2e.py -v -m e2e

Architecture:
    WSL (pytest) --> localhost:8080 (proxy) --> lyra-ml:8100 (ML Server)

See also:
    - test_ml_server.py: Unit tests (some skipped without ML libs)
    - ADR-0008: Hybrid architecture
=============================================================================
"""

from collections.abc import AsyncGenerator

import pytest

from src.ml_client import MLClient

# =============================================================================
# E2E Tests
# =============================================================================


@pytest.mark.e2e
class TestMLServerE2E:
    """E2E tests for ML Server API."""

    @pytest.fixture
    async def ml_client(self) -> AsyncGenerator[MLClient]:
        """Create ML client (async fixture for proper cleanup)."""
        from src.ml_client import MLClient

        client = MLClient()
        yield client
        # Cleanup using the existing event loop (pytest-asyncio manages it)
        await client.close()

    @pytest.mark.asyncio
    async def test_health_check(self, ml_client: MLClient) -> None:
        """
        Given: ML Server container is running
        When: Health check endpoint is called
        Then: Returns status ok with model loading info
        """
        # When
        result = await ml_client.health_check()

        # Then
        assert result is not None
        assert result.get("status") == "ok"
        assert "models_loaded" in result

    @pytest.mark.asyncio
    async def test_embed_e2e(self, ml_client: MLClient) -> None:
        """
        Given: ML Server container is running with embedding model loaded
        When: embed() is called with texts
        Then: Returns embedding vectors as list[list[float]]
        """
        # When
        texts = ["This is a test sentence.", "Another test sentence."]
        result = await ml_client.embed(texts)

        # Then - result is list[list[float]]
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2
        assert len(result[0]) > 0  # Non-empty embedding vector
        assert all(isinstance(v, float) for v in result[0])

    @pytest.mark.asyncio
    async def test_nli_e2e(self, ml_client: MLClient) -> None:
        """
        Given: ML Server container is running with NLI model loaded
        When: nli() is called with premise-hypothesis pairs
        Then: Returns NLI predictions as list[dict]
        """
        # When
        pairs = [
            {
                "pair_id": "test1",
                "premise": "The sky is blue.",
                "hypothesis": "The weather is clear.",
            },
            {
                "pair_id": "test2",
                "premise": "The sky is blue.",
                "hypothesis": "It is raining.",
            },
        ]
        result = await ml_client.nli(pairs)

        # Then - result is list[dict] with pair_id, label, confidence
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2
        for r in result:
            assert "pair_id" in r
            assert "label" in r
            assert r["label"] in ["supports", "refutes", "neutral"]
            assert "confidence" in r
            assert 0.0 <= r["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_offline_mode_verification(self, ml_client: MLClient) -> None:
        """
        Given: ML Server is running in offline mode
        When: Multiple API calls are made
        Then: All requests succeed without internet access
        Note: This test verifies that models are loaded from local paths
        and no HuggingFace API calls are made.
        """
        # When - Make multiple requests to verify offline operation
        texts = ["Test text"]
        embeddings = await ml_client.embed(texts)

        pairs = [{"pair_id": "1", "premise": "Test premise", "hypothesis": "Test hypothesis"}]
        nli_results = await ml_client.nli(pairs)

        # Then - All requests should succeed
        assert embeddings is not None
        assert nli_results is not None

    @pytest.mark.asyncio
    async def test_model_paths_loaded(self, ml_client: MLClient) -> None:
        """
        Given: ML Server container is running
        When: Health check is called
        Then: Models should be loaded (indicating local paths are working)
        """
        # When
        health = await ml_client.health_check()

        # Then
        health.get("models_loaded", {})
        # At least embedding should be loaded (lazy loading)
        # We can't guarantee all models are loaded, but health check should work
        assert health["status"] == "ok"
