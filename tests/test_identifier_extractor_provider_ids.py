"""
Tests for IdentifierExtractor provider-native IDs.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---|---|---|---|---|
| TC-ID-N-01 | OpenAlex URL `https://openalex.org/W2741809807` | Equivalence – normal | `openalex_work_id` extracted, canonical_id starts with `openalex:` | No API calls |
| TC-ID-N-02 | S2 URL `https://www.semanticscholar.org/paper/x/<paperId>` | Equivalence – normal | `s2_paper_id` extracted, canonical_id starts with `s2:` | paperId is 40-hex |
| TC-ID-B-01 | Empty url | Boundary – empty | All ids None, url preserved | - |
| TC-ID-B-02 | URL includes both DOI and OpenAlex patterns | Boundary – multi | DOI takes canonical_id precedence | Identifier can hold multiple IDs |
| TC-ID-A-01 | None url | Boundary – NULL | Returns PaperIdentifier with url=None, all ids None | - |
| TC-ID-A-02 | S2 URL with short hash (39 hex) | Boundary – min-1 | s2_paper_id not matched | paperId requires exactly 40 hex chars |
| TC-ID-A-03 | Generic URL (no provider pattern) | Abnormal – unrecognized | canonical_id fallback to url hash | - |
"""

from src.search.identifier_extractor import IdentifierExtractor


def test_extract_openalex_work_id() -> None:
    # Given: OpenAlex work URL
    url = "https://openalex.org/W2741809807"
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract(url)

    # Then: OpenAlex Work ID is extracted and canonical_id uses openalex prefix
    assert ident.openalex_work_id == "W2741809807"
    assert ident.get_canonical_id() == "openalex:W2741809807"


def test_extract_semantic_scholar_paper_id() -> None:
    # Given: Semantic Scholar paper URL with 40-hex paperId
    paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    url = f"https://www.semanticscholar.org/paper/example/{paper_id}"
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract(url)

    # Then: s2 paper id extracted and canonical_id uses s2 prefix
    assert ident.s2_paper_id == paper_id
    assert ident.get_canonical_id() == f"s2:{paper_id}"


def test_extract_empty_url_boundary() -> None:
    # Given: empty url
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract("")

    # Then: no ids, url preserved
    assert ident.url == ""
    assert ident.doi is None
    assert ident.pmid is None
    assert ident.pmcid is None
    assert ident.arxiv_id is None
    assert ident.openalex_work_id is None
    assert ident.s2_paper_id is None


def test_extract_doi_and_openalex_prefers_doi_for_canonical() -> None:
    # Given: URL that contains both DOI and OpenAlex patterns
    url = "https://doi.org/10.1234/example?ref=https://openalex.org/W123"
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract(url)

    # Then: DOI extracted and canonical_id prefers DOI
    assert ident.doi == "10.1234/example"
    assert ident.openalex_work_id == "W123"
    assert ident.get_canonical_id() == "doi:10.1234/example"


def test_extract_none_url_boundary() -> None:
    # Given: None as url input
    extractor = IdentifierExtractor()

    # When: extracting identifiers from None
    ident = extractor.extract(None)  # type: ignore[arg-type]

    # Then: no ids, url is None
    assert ident.url is None
    assert ident.doi is None
    assert ident.openalex_work_id is None
    assert ident.s2_paper_id is None


def test_extract_s2_url_with_short_hash_not_matched() -> None:
    # Given: S2 URL with 39-character hash (one less than required 40)
    short_hash = "204e3073870fae3d05bcbc2f6a8e263d9b72e77"  # 39 chars
    url = f"https://www.semanticscholar.org/paper/example/{short_hash}"
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract(url)

    # Then: s2_paper_id is NOT extracted (boundary: min-1)
    assert ident.s2_paper_id is None
    # Canonical ID falls back to url hash
    assert ident.get_canonical_id().startswith("url:")


def test_extract_generic_url_fallback() -> None:
    # Given: Generic URL with no recognized provider pattern
    url = "https://example.com/some-random-page"
    extractor = IdentifierExtractor()

    # When: extracting identifiers
    ident = extractor.extract(url)

    # Then: no structured ids, canonical_id is url-based hash
    assert ident.doi is None
    assert ident.openalex_work_id is None
    assert ident.s2_paper_id is None
    assert ident.get_canonical_id().startswith("url:")
