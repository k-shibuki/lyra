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

