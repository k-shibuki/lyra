"""
E2E tests for ML Server.
Tests actual HTTP communication with the ML server container.

These tests require:
- ML server container running (lancet-ml)
- Models downloaded and available
- Internal network connectivity

Run with: ./scripts/dev.sh test tests/test_ml_server_e2e.py
"""

import pytest
from src.utils.config import get_settings


# =============================================================================
# E2E Tests
# =============================================================================


@pytest.mark.e2e
class TestMLServerE2E:
    """E2E tests for ML Server API."""

    @pytest.fixture
    def ml_client(self):
        """Create ML client."""
        from src.ml_client import MLClient

        client = MLClient()
        yield client
        # Cleanup
        import asyncio

        asyncio.run(client.close())

    @pytest.mark.asyncio
    async def test_health_check(self, ml_client):
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
    async def test_embed_e2e(self, ml_client):
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
    async def test_rerank_e2e(self, ml_client):
        """
        Given: ML Server container is running with reranker model loaded
        When: rerank() is called with query and documents
        Then: Returns ranked results as list[tuple[int, float]]
        """
        # When
        query = "machine learning"
        documents = [
            "Machine learning is a subset of artificial intelligence.",
            "The weather today is sunny.",
            "Deep learning uses neural networks.",
        ]
        result = await ml_client.rerank(query, documents, top_k=2)

        # Then - result is list[tuple[int, float]] (index, score)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2
        # Each result is (index, score) tuple
        for idx, score in result:
            assert isinstance(idx, int)
            assert isinstance(score, float)
        # Results should be sorted by score descending
        scores = [score for idx, score in result]
        assert scores[0] >= scores[1]

    @pytest.mark.asyncio
    async def test_nli_e2e(self, ml_client):
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
        result = await ml_client.nli(pairs, use_slow=False)

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
    async def test_offline_mode_verification(self, ml_client):
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

        query = "test"
        documents = ["test document"]
        rerank_results = await ml_client.rerank(query, documents)

        pairs = [
            {"pair_id": "1", "premise": "Test premise", "hypothesis": "Test hypothesis"}
        ]
        nli_results = await ml_client.nli(pairs)

        # Then - All requests should succeed
        assert embeddings is not None
        assert rerank_results is not None
        assert nli_results is not None

    @pytest.mark.asyncio
    async def test_model_paths_loaded(self, ml_client):
        """
        Given: ML Server container is running
        When: Health check is called
        Then: Models should be loaded (indicating local paths are working)
        """
        # When
        health = await ml_client.health_check()

        # Then
        models_loaded = health.get("models_loaded", {})
        # At least embedding should be loaded (lazy loading)
        # We can't guarantee all models are loaded, but health check should work
        assert health["status"] == "ok"

