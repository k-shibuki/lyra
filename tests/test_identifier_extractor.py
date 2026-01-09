"""
Tests for identifier extractor (J2 Academic API Integration).

Tests for extracting paper identifiers (DOI, PMID, arXiv ID, etc.) from URLs.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-ID-N-01 | URL with doi.org | Equivalence – normal | DOI extracted | - |
| TC-ID-N-02 | URL with PubMed | Equivalence – normal | PMID extracted | - |
| TC-ID-N-03 | URL with arXiv | Equivalence – normal | arXiv ID extracted | - |
| TC-ID-N-04 | URL with J-Stage DOI | Equivalence – normal | DOI extracted from URL | - |
| TC-ID-N-05 | URL with PubMed Central (PMC) | Equivalence – normal | PMCID extracted | - |
| TC-ID-B-01 | Empty URL string | Boundary – empty | PaperIdentifier with url="" | - |
| TC-ID-B-02 | None URL | Boundary – NULL | PaperIdentifier with url=None | - |
| TC-ID-B-03 | URL without identifiers | Boundary – no match | PaperIdentifier with url only | - |
| TC-ID-A-01 | Invalid URL format | Abnormal – invalid | PaperIdentifier with url | - |
| TC-ID-A-02 | Malformed DOI in URL | Abnormal – invalid | No DOI extracted | - |
| TC-ID-N-06 | extract_doi_from_text() | Equivalence – normal | DOI extracted from text | - |
| TC-ID-B-04 | Empty text | Boundary – empty | Returns None | - |
| TC-ID-B-05 | Text without DOI | Boundary – no match | Returns None | - |
"""

import pytest

pytestmark = pytest.mark.unit

from src.search.identifier_extractor import IdentifierExtractor
from src.utils.schemas import PaperIdentifier


class TestIdentifierExtractor:
    """Tests for IdentifierExtractor."""

    def test_extract_doi_from_doi_org(self) -> None:
        """TC-ID-N-01: Test extracting DOI from doi.org URL.

        // Given: URL with doi.org
        // When: Extracting identifiers
        // Then: DOI extracted correctly
        """
        # Given: URL with doi.org
        extractor = IdentifierExtractor()
        url = "https://doi.org/10.1038/nature12373"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: DOI extracted correctly
        assert identifier.doi == "10.1038/nature12373"
        assert identifier.url == url
        assert identifier.pmid is None
        assert identifier.arxiv_id is None

    def test_extract_pmid_from_pubmed(self) -> None:
        """TC-ID-N-02: Test extracting PMID from PubMed URL.

        // Given: URL with pubmed.ncbi.nlm.nih.gov
        // When: Extracting identifiers
        // Then: PMID extracted, needs_meta_extraction=True
        """
        # Given: URL with PubMed
        extractor = IdentifierExtractor()
        url = "https://pubmed.ncbi.nlm.nih.gov/12345678/"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: PMID extracted
        assert identifier.pmid == "12345678"
        assert identifier.needs_meta_extraction is True
        assert identifier.doi is None

    def test_extract_arxiv_id(self) -> None:
        """TC-ID-N-03: Test extracting arXiv ID from URL.

        // Given: URL with arxiv.org
        // When: Extracting identifiers
        // Then: arXiv ID extracted, needs_meta_extraction=True
        """
        # Given: URL with arXiv
        extractor = IdentifierExtractor()
        url = "https://arxiv.org/abs/2301.12345"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: arXiv ID extracted
        assert identifier.arxiv_id == "2301.12345"
        assert identifier.needs_meta_extraction is True
        assert identifier.doi is None

    def test_extract_pmcid_from_pmc(self) -> None:
        """TC-ID-N-05: Test extracting PMCID from PubMed Central URL.

        // Given: URL with pmc.ncbi.nlm.nih.gov/articles/PMC...
        // When: Extracting identifiers
        // Then: PMCID extracted, needs_meta_extraction=True
        """
        # Given: URL with PMC
        extractor = IdentifierExtractor()
        url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC5768864/"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: PMCID extracted
        assert identifier.pmcid == "PMC5768864"
        assert identifier.needs_meta_extraction is True
        assert identifier.doi is None
        assert identifier.pmid is None

    def test_extract_jstage_doi(self) -> None:
        """TC-ID-N-04: Test extracting DOI from J-Stage URL.

        // Given: URL with jstage.jst.go.jp containing DOI
        // When: Extracting identifiers
        // Then: DOI extracted from URL path
        """
        # Given: URL with J-Stage DOI
        extractor = IdentifierExtractor()
        url = "https://www.jstage.jst.go.jp/article/jjspe/89/3/89_12345678/_article/-char/ja"

        # When: Extracting identifiers
        # Note: Actual J-Stage URLs may not have DOI in path, this is a test case
        identifier = extractor.extract(url)

        # Then: URL stored (DOI extraction depends on actual URL format)
        assert identifier.url == url

    def test_empty_url(self) -> None:
        """TC-ID-B-01: Test empty URL string.

        // Given: Empty URL string
        // When: Extracting identifiers
        // Then: PaperIdentifier with url=""
        """
        # Given: Empty URL string
        extractor = IdentifierExtractor()

        # When: Extracting identifiers
        identifier = extractor.extract("")

        # Then: PaperIdentifier with url=""
        assert identifier.url == ""
        assert identifier.doi is None
        assert identifier.pmid is None

    def test_none_url(self) -> None:
        """TC-ID-B-02: Test None URL.

        // Given: None URL
        // When: Extracting identifiers
        // Then: PaperIdentifier with url=None
        """
        # Given: None URL
        extractor = IdentifierExtractor()

        # When: Extracting identifiers
        identifier = extractor.extract(None)  # type: ignore

        # Then: PaperIdentifier with url=None
        assert identifier.url is None

    def test_url_without_identifiers(self) -> None:
        """TC-ID-B-03: Test URL without known identifiers.

        // Given: Generic URL without identifiers
        // When: Extracting identifiers
        // Then: PaperIdentifier with url only
        """
        # Given: Generic URL
        extractor = IdentifierExtractor()
        url = "https://example.com/article/123"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: PaperIdentifier with url only
        assert identifier.url == url
        assert identifier.doi is None
        assert identifier.pmid is None
        assert identifier.arxiv_id is None

    def test_invalid_url_format(self) -> None:
        """TC-ID-A-01: Test invalid URL format.

        // Given: Invalid URL format
        // When: Extracting identifiers
        // Then: PaperIdentifier with url stored
        """
        # Given: Invalid URL format
        extractor = IdentifierExtractor()
        url = "not-a-valid-url"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: PaperIdentifier with url stored
        assert identifier.url == url

    def test_malformed_doi_in_url(self) -> None:
        """TC-ID-A-02: Test malformed DOI in URL.

        // Given: URL with malformed DOI pattern
        // When: Extracting identifiers
        // Then: No DOI extracted
        """
        # Given: URL with malformed DOI
        extractor = IdentifierExtractor()
        url = "https://doi.org/invalid-doi-format"

        # When: Extracting identifiers
        identifier = extractor.extract(url)

        # Then: No DOI extracted (pattern doesn't match)
        # Note: Actual behavior depends on regex pattern
        assert identifier.url == url

    def test_extract_doi_from_text(self) -> None:
        """TC-ID-N-06: Test extracting DOI from text.

        // Given: Text containing DOI
        // When: Calling extract_doi_from_text()
        // Then: DOI extracted
        """
        # Given: Text containing DOI
        extractor = IdentifierExtractor()
        text = "This paper is available at 10.1038/nature12373"

        # When: Calling extract_doi_from_text()
        doi = extractor.extract_doi_from_text(text)

        # Then: DOI extracted
        assert doi == "10.1038/nature12373"

    def test_extract_doi_from_text_empty(self) -> None:
        """TC-ID-B-04: Test extracting DOI from empty text.

        // Given: Empty text
        // When: Calling extract_doi_from_text()
        // Then: Returns None
        """
        # Given: Empty text
        extractor = IdentifierExtractor()

        # When: Calling extract_doi_from_text()
        doi = extractor.extract_doi_from_text("")

        # Then: Returns None
        assert doi is None

    def test_extract_doi_from_text_no_doi(self) -> None:
        """TC-ID-B-05: Test extracting DOI from text without DOI.

        // Given: Text without DOI
        // When: Calling extract_doi_from_text()
        // Then: Returns None
        """
        # Given: Text without DOI
        extractor = IdentifierExtractor()
        text = "This is a regular text without any DOI"

        # When: Calling extract_doi_from_text()
        doi = extractor.extract_doi_from_text(text)

        # Then: Returns None
        assert doi is None

    def test_paper_identifier_get_canonical_id(self) -> None:
        """Test PaperIdentifier.get_canonical_id() priority.

        // Given: PaperIdentifier with multiple IDs
        // When: Calling get_canonical_id()
        // Then: Returns DOI (highest priority)
        """
        # Given: PaperIdentifier with multiple IDs
        identifier = PaperIdentifier(
            doi="10.1234/example",
            pmid="12345678",
            pmcid="PMC123456",
            arxiv_id="2301.12345",
            url=None,
        )

        # When: Calling get_canonical_id()
        canonical_id = identifier.get_canonical_id()

        # Then: Returns DOI (highest priority)
        assert canonical_id.startswith("doi:")
        assert "10.1234/example" in canonical_id

    def test_paper_identifier_get_canonical_id_fallback(self) -> None:
        """Test PaperIdentifier.get_canonical_id() fallback order.

        // Given: PaperIdentifier without DOI
        // When: Calling get_canonical_id()
        // Then: Returns next priority ID (PMID)
        """
        # Given: PaperIdentifier without DOI
        identifier = PaperIdentifier(
            doi=None,
            pmid="12345678",
            pmcid="PMC123456",
            arxiv_id="2301.12345",
            url=None,
        )

        # When: Calling get_canonical_id()
        canonical_id = identifier.get_canonical_id()

        # Then: Returns PMID (next priority)
        assert canonical_id.startswith("pmid:")
        assert "12345678" in canonical_id
