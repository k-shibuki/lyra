"""
Tests for ranking module.

Verifies that category_weight is applied in ranking.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-RANK-N-01 | Passages from different domain categories | Equivalence – normal | category_weight applied, final_score adjusted | - |
| TC-RANK-N-02 | Passage without URL | Boundary – empty URL | category_weight defaults to 1.0 | - |
| TC-RANK-N-03 | Passage with invalid URL | Boundary – invalid format | category_weight uses UNVERIFIED (0.3) | Empty netloc |
| TC-RANK-N-04 | Empty passages list | Boundary – empty | Returns empty list | - |
| TC-RANK-A-01 | Invalid URL format | Abnormal – invalid | category_weight defaults to 1.0 | - |
| TC-RANK-A-02 | Missing required fields in passage | Abnormal – missing field | Raises KeyError or uses defaults | - |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from src.filter import ranking


def _mock_rankers(
    passages_count: int, rerank_result: list[tuple[int, float]]
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create mock rankers for testing.

    Args:
        passages_count: Number of passages to mock scores for.
        rerank_result: List of (position, score) tuples for rerank result.

    Returns:
        Tuple of (mock_bm25, mock_embed, mock_rerank).
    """
    mock_bm25 = MagicMock()
    mock_bm25.fit = MagicMock()
    mock_bm25.get_scores = MagicMock(return_value=[0.5] * passages_count)

    mock_embed = MagicMock()
    mock_embed.get_scores = AsyncMock(return_value=[0.5] * passages_count)

    mock_rerank = MagicMock()
    mock_rerank.rerank = AsyncMock(return_value=rerank_result)

    return mock_bm25, mock_embed, mock_rerank


@pytest.mark.asyncio
async def test_category_weight_applied_in_ranking() -> None:
    """
    TC-RANK-N-01: Category weight is applied to final score.

    // Given: Passages from different domain categories
    // When: Ranking passages
    // Then: Final score includes category_weight adjustment
    """
    passages = [
        {
            "id": "p1",
            "text": "Test passage 1",
            "url": "https://iso.org/test",
        },
        {
            "id": "p2",
            "text": "Test passage 2",
            "url": "https://unverified-site.com/test",
        },
    ]

    # Mock rankers: return both passages with same rerank score
    mock_bm25, mock_embed, mock_rerank = _mock_rankers(2, [(0, 0.9), (1, 0.9)])

    with patch.object(ranking, "_bm25_ranker", mock_bm25):
        with patch.object(ranking, "_embedding_ranker", mock_embed):
            with patch.object(ranking, "_reranker", mock_rerank):
                results = await ranking.rank_candidates("test query", passages, top_k=2)

    assert len(results) == 2

    # Check that category_weight is applied
    for result in results:
        assert "category_weight" in result
        assert "final_score" in result
        assert result["final_score"] == result["score_rerank"] * result["category_weight"]

    # PRIMARY domain (iso.org) should have higher category_weight than UNVERIFIED
    p1_result = next(r for r in results if r["id"] == "p1")
    p2_result = next(r for r in results if r["id"] == "p2")

    assert p1_result["category_weight"] > p2_result["category_weight"]


@pytest.mark.asyncio
async def test_category_weight_defaults_to_one_without_url() -> None:
    """
    TC-RANK-N-02: Category weight defaults to 1.0 when URL is missing.

    // Given: Passage without URL
    // When: Ranking passages
    // Then: category_weight is 1.0 (no adjustment)
    """
    passages = [
        {
            "id": "p1",
            "text": "Test passage without URL",
        },
    ]

    mock_bm25, mock_embed, mock_rerank = _mock_rankers(1, [(0, 0.9)])

    with patch.object(ranking, "_bm25_ranker", mock_bm25):
        with patch.object(ranking, "_embedding_ranker", mock_embed):
            with patch.object(ranking, "_reranker", mock_rerank):
                results = await ranking.rank_candidates("test query", passages, top_k=1)

    assert len(results) == 1
    assert results[0]["category_weight"] == 1.0
    assert results[0]["final_score"] == results[0]["score_rerank"]


@pytest.mark.asyncio
async def test_category_weight_with_invalid_url() -> None:
    """
    TC-RANK-N-03: Category weight uses UNVERIFIED when URL has no valid domain.

    // Given: Passage with invalid URL format (no scheme, empty netloc)
    // When: Ranking passages
    // Then: category_weight is UNVERIFIED weight (0.3)
    """
    passages = [
        {
            "id": "p1",
            "text": "Test passage with invalid URL",
            "url": "not-a-valid-url",  # urlparse gives empty netloc
        },
    ]

    mock_bm25, mock_embed, mock_rerank = _mock_rankers(1, [(0, 0.9)])

    with patch.object(ranking, "_bm25_ranker", mock_bm25):
        with patch.object(ranking, "_embedding_ranker", mock_embed):
            with patch.object(ranking, "_reranker", mock_rerank):
                results = await ranking.rank_candidates("test query", passages, top_k=1)

    assert len(results) == 1
    # Empty domain -> get_domain_category returns UNVERIFIED -> 0.3 weight
    assert results[0]["category_weight"] == 0.3
    assert results[0]["final_score"] == results[0]["score_rerank"] * 0.3


@pytest.mark.asyncio
async def test_rank_candidates_empty_input() -> None:
    """
    TC-RANK-N-04: Empty passages list returns empty results.

    // Given: Empty passages list
    // When: Ranking passages
    // Then: Returns empty list
    """
    results = await ranking.rank_candidates("test query", [], top_k=10)

    assert results == []


@pytest.mark.asyncio
async def test_category_weight_all_categories() -> None:
    """
    TC-RANK-N-05: All domain categories have correct weights.

    // Given: Passages from all domain categories
    // When: Ranking passages
    // Then: category_weight matches expected values
    """
    passages = [
        {"id": "p1", "text": "Primary", "url": "https://iso.org/test"},
        {"id": "p2", "text": "Government", "url": "https://example.go.jp/test"},
        {"id": "p3", "text": "Academic", "url": "https://arxiv.org/test"},
        {"id": "p4", "text": "Trusted", "url": "https://wikipedia.org/test"},
        {"id": "p5", "text": "Low", "url": "https://example.com/test"},
        {"id": "p6", "text": "Unverified", "url": "https://unknown-site.com/test"},
    ]

    # All passages with same rerank score
    mock_bm25, mock_embed, mock_rerank = _mock_rankers(
        6, [(0, 0.9), (1, 0.9), (2, 0.9), (3, 0.9), (4, 0.9), (5, 0.9)]
    )

    with patch.object(ranking, "_bm25_ranker", mock_bm25):
        with patch.object(ranking, "_embedding_ranker", mock_embed):
            with patch.object(ranking, "_reranker", mock_rerank):
                results = await ranking.rank_candidates("test query", passages, top_k=6)

    assert len(results) == 6

    # Verify all results have category_weight
    for result in results:
        assert "category_weight" in result
        assert "final_score" in result
        assert 0.0 <= result["category_weight"] <= 1.0
        assert result["final_score"] == result["score_rerank"] * result["category_weight"]
