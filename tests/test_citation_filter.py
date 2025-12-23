"""
Tests for citation relevance filtering .

## Test Perspectives Table - Stage 0 citation_count threshold

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-S0-N-01 | min_citation_count=0 (default) | Equivalence – normal | All papers pass Stage 0 filter | Default behavior |
| TC-S0-N-02 | min_citation_count=5, papers with count 0,4,5,100 | Equivalence – normal | Papers with count 0,4 filtered out; 5,100 pass | Normal filtering |
| TC-S0-B-01 | min_citation_count=5, paper with count=5 | Boundary – threshold | Paper passes (>= check) | Boundary value |
| TC-S0-B-02 | min_citation_count=5, paper with count=4 | Boundary – threshold-1 | Paper filtered out | Boundary value |
| TC-S0-B-03 | min_citation_count=0 | Boundary – zero | No filtering applied | Zero threshold |
| TC-S0-B-04 | citation_count=0 | Boundary – zero | Treated as 0, filtered if min>0 | Zero handling (implementation uses `or 0` for safety) |
| TC-S0-B-05 | All papers below threshold | Boundary – empty result | Empty list returned | All filtered |
| TC-S0-A-01 | min_citation_count=-1 (invalid) | Abnormal – negative | Pydantic validation error at config load | Config validation (out of scope for filter_relevant_citations test) |
| TC-S0-A-02 | citation_count is negative | Abnormal – negative | Pydantic validation error at Paper creation | Paper schema validation (out of scope for filter_relevant_citations test) |

"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
def test_local_impact_scores_percentile_rank() -> None:
    from src.search.citation_filter import _local_impact_scores
    from src.utils.schemas import Author, Paper

    papers = [
        Paper(
            id="p1",
            title="p1",
            abstract="a",
            authors=[Author(name="a", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        ),
        Paper(
            id="p2",
            title="p2",
            abstract="a",
            authors=[Author(name="a", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=10,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        ),
        Paper(
            id="p3",
            title="p3",
            abstract="a",
            authors=[Author(name="a", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=1000,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        ),
    ]

    scores = _local_impact_scores(papers)
    assert 0.0 <= scores["p1"] <= 1.0
    assert 0.0 <= scores["p2"] <= 1.0
    assert 0.0 <= scores["p3"] <= 1.0
    assert scores["p1"] < scores["p2"] < scores["p3"]


@pytest.mark.unit
def test_local_impact_scores_singleton() -> None:
    from src.search.citation_filter import _local_impact_scores
    from src.utils.schemas import Author, Paper

    p = Paper(
        id="p1",
        title="p1",
        abstract="a",
        authors=[Author(name="a", affiliation=None, orcid=None)],
        year=2020,
        published_date=None,
        doi=None,
        arxiv_id=None,
        venue=None,
        citation_count=42,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )
    scores = _local_impact_scores([p])
    assert scores["p1"] == 0.5


# =============================================================================
# Stage 0: citation_count threshold filter tests
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stage0_min_citation_count_default() -> None:
    """TC-S0-N-01: Default min_citation_count=0 allows all papers.

    Given: min_citation_count is 0 (default)
    When: filter_relevant_citations() is called with papers having various citation counts
    Then: All papers pass Stage 0 filter
    """
    from src.search.citation_filter import filter_relevant_citations
    from src.utils.config import CitationFilterConfig
    from src.utils.schemas import Author, Paper

    source_paper = Paper(
        id="source",
        title="Source",
        abstract="Source abstract",
        authors=[Author(name="Author", affiliation=None, orcid=None)],
        year=2020,
        published_date=None,
        doi=None,
        arxiv_id=None,
        venue=None,
        citation_count=10,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )

    candidates = [
        Paper(
            id=f"p{i}",
            title=f"Paper {i}",
            abstract=f"Abstract {i}",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=count,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        for i, count in enumerate([0, 5, 100])
    ]

    mock_settings = MagicMock()
    mock_settings.search.citation_filter = CitationFilterConfig(min_citation_count=0)
    mock_settings.embedding.batch_size = 10

    with (
        patch("src.search.citation_filter.get_settings", return_value=mock_settings),
        patch("src.search.citation_filter.get_ml_client") as mock_ml_client,
        patch("src.search.citation_filter.create_ollama_provider") as mock_ollama,
    ):
        mock_ml = MagicMock()
        mock_ml.embed = AsyncMock(
            return_value=[
                [0.1] * 384,  # source embedding
                [0.2] * 384,  # p0 embedding
                [0.3] * 384,  # p1 embedding
                [0.4] * 384,  # p2 embedding
            ]
        )
        mock_ml_client.return_value = mock_ml

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=MagicMock(ok=True, text="5"))
        mock_provider.close = AsyncMock()
        mock_ollama.return_value = mock_provider

        result = await filter_relevant_citations(
            query="test query",
            source_paper=source_paper,
            candidate_papers=candidates,
        )

        # All 3 papers should pass Stage 0 (min=0 means no filtering)
        assert len(result) > 0
        # Verify all candidates were considered (check via embedding calls)
        assert mock_ml.embed.call_count == 1
        call_args = mock_ml.embed.call_args[0][0]
        assert len(call_args) == 4  # 1 source + 3 candidates


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stage0_min_citation_count_filters_low_count() -> None:
    """TC-S0-N-02, TC-S0-B-01, TC-S0-B-02: Threshold filters papers below min_citation_count.

    Given: min_citation_count=5
    When: filter_relevant_citations() is called with papers having counts 0, 4, 5, 100
    Then: Papers with count 0, 4 are filtered out; papers with count 5, 100 pass
    """
    from src.search.citation_filter import filter_relevant_citations
    from src.utils.config import CitationFilterConfig
    from src.utils.schemas import Author, Paper

    source_paper = Paper(
        id="source",
        title="Source",
        abstract="Source abstract",
        authors=[Author(name="Author", affiliation=None, orcid=None)],
        year=2020,
        published_date=None,
        doi=None,
        arxiv_id=None,
        venue=None,
        citation_count=10,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )

    candidates = [
        Paper(
            id=f"p{i}",
            title=f"Paper {i}",
            abstract=f"Abstract {i}",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=count,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        for i, count in enumerate([0, 4, 5, 100])
    ]

    mock_settings = MagicMock()
    mock_settings.search.citation_filter = CitationFilterConfig(min_citation_count=5)
    mock_settings.embedding.batch_size = 10

    with (
        patch("src.search.citation_filter.get_settings", return_value=mock_settings),
        patch("src.search.citation_filter.get_ml_client") as mock_ml_client,
        patch("src.search.citation_filter.create_ollama_provider") as mock_ollama,
    ):
        mock_ml = MagicMock()
        # Only 2 candidates should pass Stage 0 (count >= 5): p2 (5) and p3 (100)
        mock_ml.embed = AsyncMock(
            return_value=[
                [0.1] * 384,  # source embedding
                [0.3] * 384,  # p2 embedding (count=5)
                [0.4] * 384,  # p3 embedding (count=100)
            ]
        )
        mock_ml_client.return_value = mock_ml

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=MagicMock(ok=True, text="5"))
        mock_provider.close = AsyncMock()
        mock_ollama.return_value = mock_provider

        result = await filter_relevant_citations(
            query="test query",
            source_paper=source_paper,
            candidate_papers=candidates,
        )

        # Only papers with count >= 5 should pass Stage 0
        assert len(result) > 0
        # Verify only 2 candidates passed Stage 0 (check via embedding calls)
        call_args = mock_ml.embed.call_args[0][0]
        assert len(call_args) == 3  # 1 source + 2 candidates (p2, p3)
        # Verify the correct papers passed
        paper_ids_in_result = {score.paper.id for score in result}
        assert "p2" in paper_ids_in_result or "p3" in paper_ids_in_result
        assert "p0" not in paper_ids_in_result
        assert "p1" not in paper_ids_in_result


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stage0_min_citation_count_zero_treated_as_zero() -> None:
    """TC-S0-B-04: citation_count=0 is filtered out when threshold > 0.

    Given: min_citation_count=5 and paper with citation_count=0
    When: filter_relevant_citations() is called
    Then: Paper is filtered out (0 < 5)
    Note: Paper schema ensures citation_count is always int (never None).
          Implementation uses (p.citation_count or 0) for safety.
    """
    from src.search.citation_filter import filter_relevant_citations
    from src.utils.config import CitationFilterConfig
    from src.utils.schemas import Author, Paper

    source_paper = Paper(
        id="source",
        title="Source",
        abstract="Source abstract",
        authors=[Author(name="Author", affiliation=None, orcid=None)],
        year=2020,
        published_date=None,
        doi=None,
        arxiv_id=None,
        venue=None,
        citation_count=10,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )

    candidates = [
        Paper(
            id="p0",
            title="Paper 0",
            abstract="Abstract 0",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=0,  # 0 should be filtered out (0 < 5)
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        ),
        Paper(
            id="p1",
            title="Paper 1",
            abstract="Abstract 1",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=10,  # This should pass
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        ),
    ]

    mock_settings = MagicMock()
    mock_settings.search.citation_filter = CitationFilterConfig(min_citation_count=5)
    mock_settings.embedding.batch_size = 10

    with (
        patch("src.search.citation_filter.get_settings", return_value=mock_settings),
        patch("src.search.citation_filter.get_ml_client") as mock_ml_client,
        patch("src.search.citation_filter.create_ollama_provider") as mock_ollama,
    ):
        mock_ml = MagicMock()
        # Only p1 should pass Stage 0 (p0 has 0 which is < 5)
        mock_ml.embed = AsyncMock(
            return_value=[
                [0.1] * 384,  # source embedding
                [0.3] * 384,  # p1 embedding
            ]
        )
        mock_ml_client.return_value = mock_ml

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=MagicMock(ok=True, text="5"))
        mock_provider.close = AsyncMock()
        mock_ollama.return_value = mock_provider

        result = await filter_relevant_citations(
            query="test query",
            source_paper=source_paper,
            candidate_papers=candidates,
        )

        # Only p1 should pass Stage 0
        assert len(result) > 0
        call_args = mock_ml.embed.call_args[0][0]
        assert len(call_args) == 2  # 1 source + 1 candidate (p1 only)
        paper_ids_in_result = {score.paper.id for score in result}
        assert "p1" in paper_ids_in_result
        assert "p0" not in paper_ids_in_result


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stage0_all_below_threshold_returns_empty() -> None:
    """TC-S0-B-05: All papers below threshold returns empty list.

    Given: min_citation_count=100 and all papers have count < 100
    When: filter_relevant_citations() is called
    Then: Empty list is returned early (no Stage 1/2 processing)
    """
    from src.search.citation_filter import filter_relevant_citations
    from src.utils.config import CitationFilterConfig
    from src.utils.schemas import Author, Paper

    source_paper = Paper(
        id="source",
        title="Source",
        abstract="Source abstract",
        authors=[Author(name="Author", affiliation=None, orcid=None)],
        year=2020,
        published_date=None,
        doi=None,
        arxiv_id=None,
        venue=None,
        citation_count=10,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="semantic_scholar",
    )

    candidates = [
        Paper(
            id=f"p{i}",
            title=f"Paper {i}",
            abstract=f"Abstract {i}",
            authors=[Author(name="Author", affiliation=None, orcid=None)],
            year=2020,
            published_date=None,
            doi=None,
            arxiv_id=None,
            venue=None,
            citation_count=count,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
        for i, count in enumerate([0, 10, 50])  # All below threshold 100
    ]

    mock_settings = MagicMock()
    mock_settings.search.citation_filter = CitationFilterConfig(min_citation_count=100)
    mock_settings.embedding.batch_size = 10

    with (
        patch("src.search.citation_filter.get_settings", return_value=mock_settings),
        patch("src.search.citation_filter.get_ml_client") as mock_ml_client,
    ):
        result = await filter_relevant_citations(
            query="test query",
            source_paper=source_paper,
            candidate_papers=candidates,
        )

        # Should return empty list early (all papers filtered at Stage 0)
        assert result == []
        # ML client should not be called since all papers are filtered out at Stage 0
        mock_ml_client.assert_not_called()
