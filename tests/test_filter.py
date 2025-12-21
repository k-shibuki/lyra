"""
Tests for src/filter/ranking.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit


class TestBM25Ranker:
    """Tests for BM25Ranker class."""

    def test_bm25_ranker_init(self) -> None:
        """Test BM25Ranker initialization."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()

        assert ranker._index is None
        assert ranker._corpus == []

    def test_bm25_tokenize_simple(self) -> None:
        """Test simple tokenization fallback."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        ranker._tokenizer = "simple"

        tokens = ranker._tokenize("Hello World Test")

        assert tokens == ["hello", "world", "test"]

    def test_bm25_tokenize_handles_punctuation(self) -> None:
        """Test tokenization handles punctuation."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        ranker._tokenizer = "simple"

        tokens = ranker._tokenize("Hello, world! Test.")

        assert tokens == ["hello", "world", "test"]

    def test_bm25_fit_creates_index(self) -> None:
        """Test fit creates BM25 index."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        corpus = ["Document one about AI", "Document two about ML", "Document three about data"]

        ranker.fit(corpus)

        assert ranker._index is not None
        assert ranker._corpus == corpus

    def test_bm25_get_scores_requires_fit(self) -> None:
        """Test get_scores raises error before fit."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()

        with pytest.raises(ValueError, match="Index not fitted"):
            ranker.get_scores("test query")

    def test_bm25_get_scores_returns_scores(self) -> None:
        """Test get_scores returns list of scores."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        # Use simple English words that tokenize well with simple tokenizer
        corpus = [
            "python programming code development software",
            "weather forecast rain temperature climate",
            "python code programming tutorial learning",
        ]
        ranker.fit(corpus)

        scores = ranker.get_scores("python programming")

        assert len(scores) == 3
        # Python-related documents should score higher than weather
        assert scores[0] > scores[1]  # First doc > weather doc
        assert scores[2] > scores[1]  # Third doc > weather doc

    def test_bm25_scores_normalized_format(self) -> None:
        """Test scores are in expected format."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        corpus = ["Test document one", "Test document two"]
        ranker.fit(corpus)

        scores = ranker.get_scores("test")

        assert isinstance(scores, list)
        assert all(isinstance(s, float) for s in scores)


class TestEmbeddingRanker:
    """Tests for EmbeddingRanker class."""

    def test_embedding_ranker_init(self) -> None:
        """Test EmbeddingRanker initialization."""
        from src.filter.ranking import EmbeddingRanker

        ranker = EmbeddingRanker()

        assert ranker._model is None
        assert ranker._cache == {}

    def test_get_cache_key(self) -> None:
        """Test cache key generation."""
        from src.filter.ranking import EmbeddingRanker

        ranker = EmbeddingRanker()

        key1 = ranker._get_cache_key("test text")
        key2 = ranker._get_cache_key("test text")
        key3 = ranker._get_cache_key("different text")

        assert key1 == key2
        assert key1 != key3
        assert len(key1) == 32

    @pytest.mark.asyncio
    async def test_encode_caches_results(self) -> None:
        """Test that encode caches embedding results."""
        from unittest.mock import patch

        import numpy as np

        from src.filter.ranking import EmbeddingRanker

        ranker = EmbeddingRanker()

        # Mock the model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        mock_model.to = MagicMock(return_value=mock_model)
        ranker._model = mock_model

        # Ensure local mode (not remote)
        with patch.object(ranker._settings.ml, "use_remote", False):
            texts = ["text one", "text two"]

            # First call
            await ranker.encode(texts)

            # Both should be cached now
            assert ranker._get_cache_key("text one") in ranker._cache
            assert ranker._get_cache_key("text two") in ranker._cache

    @pytest.mark.asyncio
    async def test_encode_uses_cache(self) -> None:
        """Test that encode uses cached results."""
        from unittest.mock import patch

        import numpy as np

        from src.filter.ranking import EmbeddingRanker

        ranker = EmbeddingRanker()

        # Pre-populate cache
        ranker._cache[ranker._get_cache_key("cached text")] = [0.1, 0.2, 0.3]

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.7, 0.8, 0.9]])
        mock_model.to = MagicMock(return_value=mock_model)
        ranker._model = mock_model

        # Ensure local mode (not remote)
        with patch.object(ranker._settings.ml, "use_remote", False):
            results = await ranker.encode(["cached text", "new text"])

            # First result from cache, second from model
            assert results[0] == [0.1, 0.2, 0.3]
            # Model only called for "new text"
            mock_model.encode.assert_called_once_with(
                ["new text"],
                batch_size=8,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

    @pytest.mark.asyncio
    async def test_get_scores_returns_similarities(self) -> None:
        """Test get_scores returns similarity scores."""

        from src.filter.ranking import EmbeddingRanker

        ranker = EmbeddingRanker()

        # Mock encode to return normalized vectors
        async def mock_encode(texts: list[str]) -> list[list[float]]:
            # Return simple embeddings that produce predictable scores
            return [[1.0, 0.0, 0.0]] + [[0.9, 0.1, 0.0]] * (len(texts) - 1)

        with patch.object(ranker, "encode", mock_encode):
            scores = await ranker.get_scores("query", ["doc1", "doc2"])

            assert len(scores) == 2
            # Scores should be cosine similarities
            assert all(-1 <= s <= 1 for s in scores)


class TestReranker:
    """Tests for Reranker class."""

    def test_reranker_init(self) -> None:
        """Test Reranker initialization."""
        from src.filter.ranking import Reranker

        reranker = Reranker()

        assert reranker._model is None

    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(self) -> None:
        """Test rerank returns results sorted by score."""
        from unittest.mock import patch

        import numpy as np

        from src.filter.ranking import Reranker

        reranker = Reranker()

        # Mock model
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.5, 0.9, 0.3])
        setattr(reranker, "_model", mock_model)

        # Ensure local mode (not remote)
        with patch.object(reranker._settings.ml, "use_remote", False):
            results = await reranker.rerank(
                "test query",
                ["doc1", "doc2", "doc3"],
                top_k=3,
            )

            # Should be sorted by score descending
            assert results[0][0] == 1  # doc2 (score 0.9)
            assert results[1][0] == 0  # doc1 (score 0.5)
            assert results[2][0] == 2  # doc3 (score 0.3)

            assert results[0][1] == pytest.approx(0.9)
            assert results[1][1] == pytest.approx(0.5)
            assert results[2][1] == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_rerank_respects_top_k(self) -> None:
        """Test rerank respects top_k parameter."""
        from unittest.mock import patch

        import numpy as np

        from src.filter.ranking import Reranker

        reranker = Reranker()

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.5, 0.9, 0.3, 0.7, 0.1])
        setattr(reranker, "_model", mock_model)

        # Ensure local mode (not remote)
        with patch.object(reranker._settings.ml, "use_remote", False):
            results = await reranker.rerank(
                "query",
                ["d1", "d2", "d3", "d4", "d5"],
                top_k=2,
            )

            assert len(results) == 2
            # Top 2 by score
            assert results[0][0] == 1  # d2 (0.9)
            assert results[1][0] == 3  # d4 (0.7)


class TestRankCandidates:
    """Tests for rank_candidates function."""

    @pytest.mark.asyncio
    async def test_rank_candidates_empty_input(self) -> None:
        """Test rank_candidates with empty passages."""
        from src.filter.ranking import rank_candidates

        results = await rank_candidates("query", [])

        assert results == []

    @pytest.mark.asyncio
    async def test_rank_candidates_full_pipeline(self, sample_passages: list[dict[str, str]]) -> None:
        """Test rank_candidates runs full ranking pipeline."""

        from src.filter import ranking

        # Mock all rankers
        mock_bm25 = MagicMock()
        mock_bm25.fit = MagicMock()
        mock_bm25.get_scores = MagicMock(return_value=[0.8, 0.1, 0.7, 0.3, 0.6])

        mock_embed = MagicMock()
        mock_embed.get_scores = AsyncMock(return_value=[0.9, 0.2, 0.8, 0.4, 0.7])

        mock_rerank = MagicMock()
        mock_rerank.rerank = AsyncMock(return_value=[(0, 0.95), (2, 0.85)])

        with patch.object(ranking, "_bm25_ranker", mock_bm25):
            with patch.object(ranking, "_embedding_ranker", mock_embed):
                with patch.object(ranking, "_reranker", mock_rerank):
                    results = await ranking.rank_candidates(
                        "AI in healthcare",
                        sample_passages,
                        top_k=2,
                    )

        # Should return top_k results
        assert len(results) == 2

        # Results should have all score fields
        assert "score_bm25" in results[0]
        assert "score_embed" in results[0]
        assert "score_rerank" in results[0]
        assert "final_rank" in results[0]

    @pytest.mark.asyncio
    async def test_rank_candidates_preserves_passage_data(self, sample_passages: list[dict[str, str]]) -> None:
        """Test rank_candidates preserves original passage data."""

        from src.filter import ranking

        mock_bm25 = MagicMock()
        mock_bm25.fit = MagicMock()
        mock_bm25.get_scores = MagicMock(return_value=[0.5] * 5)

        mock_embed = MagicMock()
        mock_embed.get_scores = AsyncMock(return_value=[0.5] * 5)

        mock_rerank = MagicMock()
        mock_rerank.rerank = AsyncMock(return_value=[(0, 0.9)])

        with patch.object(ranking, "_bm25_ranker", mock_bm25):
            with patch.object(ranking, "_embedding_ranker", mock_embed):
                with patch.object(ranking, "_reranker", mock_rerank):
                    results = await ranking.rank_candidates(
                        "query",
                        sample_passages,
                        top_k=1,
                    )

        # Original passage data should be preserved
        assert "id" in results[0]
        assert "text" in results[0]


class TestBM25Integration:
    """Integration tests for BM25 ranking (using real rank-bm25)."""

    def test_bm25_ranks_relevant_docs_higher(self) -> None:
        """Test BM25 ranks relevant documents higher."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()

        corpus = [
            "Python programming language basics",
            "Machine learning with Python",
            "JavaScript web development",
            "Python data science tutorial",
        ]

        ranker.fit(corpus)
        scores = ranker.get_scores("Python programming")

        # Python-related docs should score higher
        python_docs_scores = [scores[0], scores[1], scores[3]]
        js_doc_score = scores[2]

        assert all(s > js_doc_score for s in python_docs_scores)

    def test_bm25_handles_empty_query(self) -> None:
        """Test BM25 handles empty query gracefully."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()
        corpus = ["Doc one", "Doc two"]
        ranker.fit(corpus)

        scores = ranker.get_scores("")

        assert len(scores) == 2
        assert all(s == 0.0 for s in scores)

    def test_bm25_handles_unicode(self) -> None:
        """Test BM25 handles Unicode text."""
        from src.filter.ranking import BM25Ranker

        ranker = BM25Ranker()

        corpus = [
            "日本語のテキスト",
            "English text here",
            "混合 mixed テキスト",
        ]

        ranker.fit(corpus)
        scores = ranker.get_scores("日本語")

        assert len(scores) == 3
        # Japanese doc should score highest
        assert scores[0] > scores[1]
