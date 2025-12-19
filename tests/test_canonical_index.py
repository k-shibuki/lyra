"""
Tests for canonical paper index (J2 Academic API Integration).

Tests for unified deduplication across Browser Search and Academic API results.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CI-N-01 | Register paper with DOI | Equivalence – normal | Paper registered with canonical_id | - |
| TC-CI-N-02 | Register duplicate paper (same DOI) | Equivalence – normal | Duplicate skipped, sources tracked | - |
| TC-CI-N-03 | Register SERP result | Equivalence – normal | SERP result registered | - |
| TC-CI-N-04 | Register SERP matching existing paper | Equivalence – normal | SERP linked to existing paper | - |
| TC-CI-N-05 | Title similarity matching | Equivalence – normal | Similar titles matched | - |
| TC-CI-B-01 | Empty index | Boundary – empty | Stats show zero counts | - |
| TC-CI-B-02 | Clear index | Boundary – empty | Index cleared | - |
| TC-CI-A-01 | Register paper without DOI or title | Abnormal – missing fields | Fallback canonical_id generated | - |
| TC-CI-N-06 | Get stats | Equivalence – normal | Correct counts returned | - |
| TC-CI-N-07 | Multiple sources for same paper | Equivalence – normal | Sources tracked correctly | - |
"""

import pytest

pytestmark = pytest.mark.unit

from src.search.canonical_index import CanonicalPaperIndex, PaperIdentityResolver
from src.search.provider import SearchResult
from src.utils.schemas import Author, Paper, PaperIdentifier


class TestPaperIdentityResolver:
    """Tests for PaperIdentityResolver."""

    def test_resolve_identity_with_doi(self):
        """Test resolving identity with DOI.

        // Given: Paper with DOI
        // When: Resolving identity
        // Then: Returns doi: prefix canonical_id
        """
        # Given: Paper with DOI
        resolver = PaperIdentityResolver()
        paper = Paper(
            id="test:123",
            title="Test Paper",
            doi="10.1234/example",
            source_api="test",
        )

        # When: Resolving identity
        canonical_id = resolver.resolve_identity(paper)

        # Then: Returns doi: prefix
        assert canonical_id.startswith("doi:")
        assert "10.1234/example" in canonical_id.lower()

    def test_resolve_identity_with_title_author_year(self):
        """Test resolving identity with title + author + year.

        // Given: Paper without DOI, with title/author/year
        // When: Resolving identity
        // Then: Returns meta: prefix canonical_id
        """
        # Given: Paper without DOI
        resolver = PaperIdentityResolver()
        paper = Paper(
            id="test:456",
            title="Test Paper Title",
            authors=[Author(name="John Smith")],
            year=2024,
            source_api="test",
        )

        # When: Resolving identity
        canonical_id = resolver.resolve_identity(paper)

        # Then: Returns meta: prefix
        assert canonical_id.startswith("meta:")

    def test_resolve_identity_from_identifier(self):
        """Test resolving identity from PaperIdentifier.

        // Given: PaperIdentifier with DOI
        // When: Resolving identity
        // Then: Returns canonical_id using identifier.get_canonical_id()
        """
        # Given: PaperIdentifier with DOI
        resolver = PaperIdentityResolver()
        identifier = PaperIdentifier(doi="10.1234/example")

        # When: Resolving identity
        canonical_id = resolver.resolve_identity_from_identifier(identifier)

        # Then: Returns canonical_id
        assert canonical_id.startswith("doi:")

    def test_normalize_title(self):
        """Test title normalization.

        // Given: Title with punctuation and articles
        // When: Normalizing title
        // Then: Punctuation removed, articles removed, lowercase
        """
        # Given: Title with punctuation
        resolver = PaperIdentityResolver()
        title = "The Test Paper: A Study"

        # When: Normalizing title
        normalized = resolver._normalize_title(title)

        # Then: Normalized
        assert "the" not in normalized
        assert ":" not in normalized
        assert normalized == normalized.lower()

    def test_extract_first_author_surname_first_last_format(self):
        """Test extracting surname from 'First Last' format.

        // Given: Author name in "First Last" format
        // When: Extracting surname
        // Then: Returns last name (lowercased)
        """
        # Given: Author name in "First Last" format
        resolver = PaperIdentityResolver()
        authors = [Author(name="John Smith")]

        # When: Extracting surname
        surname = resolver._extract_first_author_surname(authors)

        # Then: Returns "smith"
        assert surname == "smith"

    def test_extract_first_author_surname_last_first_format(self):
        """Test extracting surname from 'Last, First' format.

        // Given: Author name in "Last, First" format
        // When: Extracting surname
        // Then: Returns last name (lowercased)
        """
        # Given: Author name in "Last, First" format
        resolver = PaperIdentityResolver()
        authors = [Author(name="Smith, John")]

        # When: Extracting surname
        surname = resolver._extract_first_author_surname(authors)

        # Then: Returns "smith" (NOT "john")
        assert surname == "smith"

    def test_extract_first_author_surname_single_name(self):
        """Test extracting surname from single name.

        // Given: Single name author
        // When: Extracting surname
        // Then: Returns the name (lowercased)
        """
        # Given: Single name
        resolver = PaperIdentityResolver()
        authors = [Author(name="Madonna")]

        # When: Extracting surname
        surname = resolver._extract_first_author_surname(authors)

        # Then: Returns "madonna"
        assert surname == "madonna"

    def test_extract_first_author_surname_empty(self):
        """Test extracting surname from empty authors list.

        // Given: Empty authors list
        // When: Extracting surname
        // Then: Returns None
        """
        # Given: Empty authors list
        resolver = PaperIdentityResolver()
        authors = []

        # When: Extracting surname
        surname = resolver._extract_first_author_surname(authors)

        # Then: Returns None
        assert surname is None


class TestCanonicalPaperIndex:
    """Tests for CanonicalPaperIndex."""

    def test_register_paper(self):
        """TC-CI-N-01: Test registering a paper.

        // Given: Paper with DOI
        // When: Registering paper
        // Then: Paper registered with canonical_id
        """
        # Given: Paper with DOI
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="Test Paper",
            doi="10.1234/example",
            source_api="semantic_scholar",
        )

        # When: Registering paper
        canonical_id = index.register_paper(paper, source_api="semantic_scholar")

        # Then: Paper registered
        assert canonical_id.startswith("doi:")
        entries = index.get_all_entries()
        assert len(entries) == 1
        assert entries[0].paper == paper
        assert entries[0].source == "api"

    def test_register_duplicate_paper(self):
        """TC-CI-N-02: Test registering duplicate paper (same DOI).

        // Given: Paper already registered
        // When: Registering same paper again
        // Then: Duplicate skipped, sources tracked
        """
        # Given: Paper already registered
        index = CanonicalPaperIndex()
        paper1 = Paper(
            id="test:123",
            title="Test Paper",
            doi="10.1234/example",
            source_api="semantic_scholar",
        )
        paper2 = Paper(
            id="test:456",
            title="Test Paper",
            doi="10.1234/example",
            source_api="openalex",
        )

        # When: Registering same paper again
        id1 = index.register_paper(paper1, source_api="semantic_scholar")
        id2 = index.register_paper(paper2, source_api="openalex")

        # Then: Duplicate skipped, sources tracked
        assert id1 == id2  # Same canonical_id
        entries = index.get_all_entries()
        assert len(entries) == 1  # Only one entry
        # Higher priority source (semantic_scholar) is kept
        assert entries[0].paper.source_api == "semantic_scholar"

    def test_register_serp_result(self):
        """TC-CI-N-03: Test registering SERP result.

        // Given: SERP SearchResult
        // When: Registering SERP result
        // Then: SERP result registered
        """
        # Given: SERP SearchResult
        index = CanonicalPaperIndex()
        serp_result = SearchResult(
            title="Test Result",
            url="https://example.com/paper",
            snippet="Snippet",
            engine="google",
            rank=1,
        )
        identifier = PaperIdentifier(url=serp_result.url)

        # When: Registering SERP result
        canonical_id = index.register_serp_result(serp_result, identifier)

        # Then: SERP result registered
        assert canonical_id.startswith("url:")
        entries = index.get_all_entries()
        assert len(entries) == 1
        assert entries[0].source == "serp"
        assert len(entries[0].serp_results) == 1

    def test_register_serp_matching_existing_paper(self):
        """TC-CI-N-04: Test registering SERP matching existing paper.

        // Given: Paper already registered, SERP result with same DOI
        // When: Registering SERP result
        // Then: SERP linked to existing paper, source="both"
        """
        # Given: Paper already registered
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="Test Paper",
            doi="10.1234/example",
            source_api="semantic_scholar",
        )
        index.register_paper(paper, source_api="semantic_scholar")

        serp_result = SearchResult(
            title="Test Paper",
            url="https://doi.org/10.1234/example",
            snippet="Snippet",
            engine="google",
            rank=1,
        )
        identifier = PaperIdentifier(doi="10.1234/example")

        # When: Registering SERP result
        index.register_serp_result(serp_result, identifier)

        # Then: SERP linked to existing paper
        entries = index.get_all_entries()
        assert len(entries) == 1
        assert entries[0].source == "both"
        assert len(entries[0].serp_results) == 1

    def test_find_by_title_similarity(self):
        """TC-CI-N-05: Test finding by title similarity.

        // Given: Paper registered, similar title
        // When: Finding by title similarity
        // Then: Matching entry found
        """
        # Given: Paper registered
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="Machine Learning Research Paper",
            source_api="test",
        )
        index.register_paper(paper, source_api="test")

        # When: Finding by title similarity
        normalized_title = "machine learning research paper"
        match = index.find_by_title_similarity(normalized_title, threshold=0.9)

        # Then: Matching entry found
        assert match is not None
        assert match.paper == paper

    def test_empty_index(self):
        """TC-CI-B-01: Test empty index stats.

        // Given: Empty index
        // When: Getting stats
        // Then: Stats show zero counts
        """
        # Given: Empty index
        index = CanonicalPaperIndex()

        # When: Getting stats
        stats = index.get_stats()

        # Then: Stats show zero counts
        assert stats["total"] == 0
        assert stats["api_only"] == 0
        assert stats["serp_only"] == 0
        assert stats["both"] == 0

    def test_clear_index(self):
        """TC-CI-B-02: Test clearing index.

        // Given: Index with entries
        // When: Clearing index
        // Then: Index cleared
        """
        # Given: Index with entries
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="Test",
            doi="10.1234/example",
            source_api="test",
        )
        index.register_paper(paper, source_api="test")

        # When: Clearing index
        index.clear()

        # Then: Index cleared
        assert len(index.get_all_entries()) == 0
        assert index.get_stats()["total"] == 0

    def test_register_paper_without_doi_or_title(self):
        """TC-CI-A-01: Test registering paper without DOI or title.

        // Given: Paper without DOI or title
        // When: Registering paper
        // Then: Fallback canonical_id generated
        """
        # Given: Paper without DOI or title
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="",  # Empty title
            source_api="test",
        )

        # When: Registering paper
        canonical_id = index.register_paper(paper, source_api="test")

        # Then: Fallback canonical_id generated
        assert canonical_id.startswith("unknown:") or canonical_id.startswith("title:")

    def test_get_stats(self):
        """TC-CI-N-06: Test getting stats.

        // Given: Index with mixed entries
        // When: Getting stats
        // Then: Correct counts returned
        """
        # Given: Index with mixed entries
        index = CanonicalPaperIndex()

        # API-only entry
        paper1 = Paper(id="test:1", title="Paper 1", doi="10.1/1", source_api="test")
        index.register_paper(paper1, source_api="test")

        # SERP-only entry
        serp = SearchResult(
            title="Paper 2",
            url="https://example.com/2",
            snippet="Snippet",
            engine="google",
            rank=1,
        )
        index.register_serp_result(serp, PaperIdentifier(url=serp.url))

        # Both entry
        paper3 = Paper(id="test:3", title="Paper 3", doi="10.3/3", source_api="test")
        index.register_paper(paper3, source_api="test")
        serp3 = SearchResult(
            title="Paper 3",
            url="https://doi.org/10.3/3",
            snippet="Snippet",
            engine="google",
            rank=1,
        )
        index.register_serp_result(serp3, PaperIdentifier(doi="10.3/3"))

        # When: Getting stats
        stats = index.get_stats()

        # Then: Correct counts returned
        assert stats["total"] == 3
        assert stats["api_only"] == 1
        assert stats["serp_only"] == 1
        assert stats["both"] == 1

    def test_multiple_sources_tracking(self):
        """TC-CI-N-07: Test multiple sources tracking.

        // Given: Same paper from multiple APIs
        // When: Registering from different sources
        // Then: Sources tracked correctly
        """
        # Given: Same paper from multiple APIs
        index = CanonicalPaperIndex()
        paper = Paper(
            id="test:123",
            title="Test Paper",
            doi="10.1234/example",
            source_api="semantic_scholar",
        )

        # When: Registering from different sources
        id1 = index.register_paper(paper, source_api="semantic_scholar")
        # Same paper from different API (should be deduplicated)
        paper2 = Paper(
            id="test:456",
            title="Test Paper",
            doi="10.1234/example",
            source_api="openalex",
        )
        id2 = index.register_paper(paper2, source_api="openalex")

        # Then: Same canonical_id, higher priority kept
        assert id1 == id2
        entries = index.get_all_entries()
        assert len(entries) == 1
        # Higher priority (semantic_scholar=1) kept over openalex=2
        assert entries[0].paper.source_api == "semantic_scholar"

