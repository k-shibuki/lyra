"""
Tests for CanonicalPaperIndex merging SERP entries into DOI-based canonical entries.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---|---|---|---|---|
| TC-MERGE-N-01 | SERP canonical=openalex:W..., API paper has DOI | Equivalence – normal | SERP entry merged into doi:... entry, single entry remains | Prevents redundant web fetch |
| TC-MERGE-B-01 | SERP canonical exists, API paper has no DOI | Boundary – no DOI | Still merges by meta/title identity, single entry remains | Depends on PaperIdentityResolver |
| TC-MERGE-A-01 | attach_paper_to_entry with non-existent serp_canonical_id | Abnormal – not found | Paper registered independently, returns paper canonical_id | Safe no-op merge |
"""

from src.search.canonical_index import CanonicalPaperIndex
from src.search.provider import SERPResult
from src.utils.schemas import Paper, PaperIdentifier


def test_merge_openalex_serp_into_doi_entry() -> None:
    # Given: SERP entry identified by OpenAlex work id
    index = CanonicalPaperIndex()
    ident = PaperIdentifier(openalex_work_id="W2741809807", url="https://openalex.org/W2741809807")
    serp = SERPResult(
        title="OpenAlex Work Page",
        url="https://openalex.org/W2741809807",
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    serp_cid = index.register_serp_result(serp, ident)
    assert serp_cid == "openalex:W2741809807"

    # When: attaching a paper with DOI
    paper = Paper(
        id="openalex:W2741809807",
        title="Example",
        abstract="Abstract",
        authors=[],
        year=2020,
        published_date=None,
        doi="10.7717/peerj.4375",
        arxiv_id=None,
        venue=None,
        citation_count=0,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )
    merged_id = index.attach_paper_to_entry(serp_cid, paper, source_api="openalex")

    # Then: single entry remains under DOI canonical id, with serp evidence kept
    assert merged_id == "doi:10.7717/peerj.4375"
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].canonical_id == "doi:10.7717/peerj.4375"
    assert entries[0].paper is not None
    assert entries[0].source == "both"
    assert entries[0].best_url == "https://doi.org/10.7717/peerj.4375"


def test_merge_openalex_serp_into_non_doi_identity() -> None:
    # Given: SERP entry identified by OpenAlex work id
    index = CanonicalPaperIndex()
    ident = PaperIdentifier(openalex_work_id="W1", url="https://openalex.org/W1")
    serp = SERPResult(
        title="Some Title",
        url="https://openalex.org/W1",
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    serp_cid = index.register_serp_result(serp, ident)

    # When: attaching a paper without DOI but with title/year to compute meta identity
    paper = Paper(
        id="openalex:W1",
        title="Some Title",
        abstract="Abstract",
        authors=[],
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
        source_api="openalex",
    )
    merged_id = index.attach_paper_to_entry(serp_cid, paper, source_api="openalex")

    # Then: merged into a non-openalex canonical id (meta/title/unknown), single entry remains
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].paper is not None
    assert entries[0].source in ("api", "both")
    assert merged_id == entries[0].canonical_id


def test_attach_paper_to_nonexistent_serp_entry() -> None:
    # Given: empty index (no SERP entry registered)
    index = CanonicalPaperIndex()

    # When: attaching a paper with a non-existent serp_canonical_id
    paper = Paper(
        id="openalex:W999",
        title="Orphan Paper",
        abstract="Abstract",
        authors=[],
        year=2021,
        published_date=None,
        doi="10.9999/orphan",
        arxiv_id=None,
        venue=None,
        citation_count=0,
        reference_count=0,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )
    merged_id = index.attach_paper_to_entry("openalex:W999", paper, source_api="openalex")

    # Then: paper registered independently, canonical_id based on DOI
    assert merged_id == "doi:10.9999/orphan"
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].paper is not None
    assert entries[0].canonical_id == "doi:10.9999/orphan"
