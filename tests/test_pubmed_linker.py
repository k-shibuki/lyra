"""
Tests for PubMed page linker.

Tests the PubMed page enrichment functionality that links browser-fetched
PubMed/PMC pages to normalized works via academic APIs.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-HEL-01 | `_is_pubmed_domain("pubmed.ncbi.nlm.nih.gov")` | Helper – normal | True | - |
| TC-HEL-02 | `_is_pubmed_domain("pmc.ncbi.nlm.nih.gov")` | Helper – normal | True | - |
| TC-HEL-03 | `_is_pubmed_domain("example.com")` | Helper – abnormal | False | - |
| TC-HEL-04 | `_is_pubmed_domain("")` empty string | Boundary – empty | False | - |
| TC-HEL-05 | `_is_pubmed_domain(None)` | Boundary – NULL | False | - |
| TC-HEL-06 | `_enabled()` returns True | Helper – enabled | True | - |
| TC-HEL-07 | `_enabled()` returns False | Helper – disabled | False | - |
| TC-HEL-08 | `_enrich_timeout_seconds()` normal | Helper – normal | Float from settings | - |
| TC-HEL-09 | `_enrich_timeout_seconds()` exception | Helper – error | 5.0 (default) | - |
| TC-N-01 | PubMed URL with PMID, feature enabled | Equivalence – normal | canonical_id returned | - |
| TC-N-02 | PMC URL with PMCID only (needs resolver) | Equivalence – normal | PMCID→PMID resolved | - |
| TC-N-03 | Page already has canonical_id | Equivalence – existing | Existing returned | - |
| TC-N-04 | PMCID resolver returns DOI | Equivalence – DOI path | Uses DOI for S2 lookup | - |
| TC-A-01 | Feature disabled | Abnormal – disabled | None returned | - |
| TC-A-02 | Non-PubMed domain | Abnormal – wrong domain | None returned | - |
| TC-A-03 | DB fetch_one fails | Abnormal – DB error | None returned | - |
| TC-A-04 | Semantic Scholar returns None | Abnormal – API no result | None returned | - |
| TC-A-05 | Semantic Scholar times out | Abnormal – timeout | None returned | - |
| TC-A-06 | No PMID or PMCID extractable | Abnormal – no identifier | None returned | - |
| TC-A-07 | PMCID resolver times out | Abnormal – resolver timeout | Falls back to None | - |
| TC-W-01 | Wiring: persist_work called | Wiring verification | Correct args passed | - |
| TC-W-02 | Wiring: db.update called | Wiring verification | Page updated correctly | - |
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestIsPubmedDomain:
    """Tests for _is_pubmed_domain() helper."""

    def test_pubmed_domain_returns_true(self) -> None:
        """TC-HEL-01: pubmed.ncbi.nlm.nih.gov returns True.

        // Given: PubMed domain string
        // When: Checking if it's a PubMed domain
        // Then: Returns True
        """
        # Given: PubMed domain string
        from src.crawler.pubmed_linker import _is_pubmed_domain

        # When: Checking if it's a PubMed domain
        result = _is_pubmed_domain("pubmed.ncbi.nlm.nih.gov")

        # Then: Returns True
        assert result is True

    def test_pmc_domain_returns_true(self) -> None:
        """TC-HEL-02: pmc.ncbi.nlm.nih.gov returns True.

        // Given: PMC domain string
        // When: Checking if it's a PubMed domain
        // Then: Returns True
        """
        # Given: PMC domain string
        from src.crawler.pubmed_linker import _is_pubmed_domain

        # When: Checking if it's a PubMed domain
        result = _is_pubmed_domain("pmc.ncbi.nlm.nih.gov")

        # Then: Returns True
        assert result is True

    def test_non_pubmed_domain_returns_false(self) -> None:
        """TC-HEL-03: Non-PubMed domain returns False.

        // Given: Non-PubMed domain string
        // When: Checking if it's a PubMed domain
        // Then: Returns False
        """
        # Given: Non-PubMed domain string
        from src.crawler.pubmed_linker import _is_pubmed_domain

        # When: Checking if it's a PubMed domain
        result = _is_pubmed_domain("example.com")

        # Then: Returns False
        assert result is False

    def test_empty_string_returns_false(self) -> None:
        """TC-HEL-04: Empty string returns False.

        // Given: Empty domain string
        // When: Checking if it's a PubMed domain
        // Then: Returns False
        """
        # Given: Empty domain string
        from src.crawler.pubmed_linker import _is_pubmed_domain

        # When: Checking if it's a PubMed domain
        result = _is_pubmed_domain("")

        # Then: Returns False
        assert result is False

    def test_none_returns_false(self) -> None:
        """TC-HEL-05: None returns False (handles gracefully).

        // Given: None as domain
        // When: Checking if it's a PubMed domain
        // Then: Returns False (no exception)
        """
        # Given: None as domain
        from src.crawler.pubmed_linker import _is_pubmed_domain

        # When: Checking if it's a PubMed domain
        result = _is_pubmed_domain(None)  # type: ignore[arg-type]

        # Then: Returns False (no exception)
        assert result is False


class TestEnabled:
    """Tests for _enabled() helper."""

    def test_enabled_returns_true_when_setting_is_true(self) -> None:
        """TC-HEL-06: Returns True when setting is enabled.

        // Given: pubmed_enrichment_enabled = True in settings
        // When: Checking if feature is enabled
        // Then: Returns True
        """
        # Given: pubmed_enrichment_enabled = True in settings
        from src.crawler.pubmed_linker import _enabled

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True

        # When: Checking if feature is enabled
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = _enabled()

        # Then: Returns True
        assert result is True

    def test_enabled_returns_false_when_setting_is_false(self) -> None:
        """TC-HEL-07: Returns False when setting is disabled.

        // Given: pubmed_enrichment_enabled = False in settings
        // When: Checking if feature is enabled
        // Then: Returns False
        """
        # Given: pubmed_enrichment_enabled = False in settings
        from src.crawler.pubmed_linker import _enabled

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = False

        # When: Checking if feature is enabled
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = _enabled()

        # Then: Returns False
        assert result is False


class TestEnrichTimeoutSeconds:
    """Tests for _enrich_timeout_seconds() helper."""

    def test_returns_configured_timeout(self) -> None:
        """TC-HEL-08: Returns timeout from settings.

        // Given: pubmed_enrichment_timeout_seconds = 10.0 in settings
        // When: Getting timeout value
        // Then: Returns 10.0
        """
        # Given: pubmed_enrichment_timeout_seconds = 10.0 in settings
        from src.crawler.pubmed_linker import _enrich_timeout_seconds

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 10.0

        # When: Getting timeout value
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = _enrich_timeout_seconds()

        # Then: Returns 10.0
        assert result == 10.0

    def test_returns_default_on_exception(self) -> None:
        """TC-HEL-09: Returns 5.0 on exception.

        // Given: Settings access raises exception
        // When: Getting timeout value
        // Then: Returns 5.0 (default)
        """
        # Given: Settings access raises exception
        from src.crawler.pubmed_linker import _enrich_timeout_seconds

        # When: Getting timeout value
        with patch("src.utils.config.get_settings", side_effect=RuntimeError("Config error")):
            result = _enrich_timeout_seconds()

        # Then: Returns 5.0 (default)
        assert result == 5.0


# =============================================================================
# Main Function Tests
# =============================================================================


class TestEnrichPubmedPageCanonicalId:
    """Tests for enrich_pubmed_page_canonical_id() main function."""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create mock database."""
        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value={"canonical_id": None})
        db.update = AsyncMock()
        return db

    @pytest.fixture
    def mock_paper(self) -> MagicMock:
        """Create mock Paper object."""
        paper = MagicMock()
        paper.title = "Test Paper Title"
        paper.doi = "10.1234/test.doi"
        paper.year = 2024
        paper.authors = [MagicMock(name="Author One", affiliation="Univ", orcid=None)]
        paper.source_api = "semantic_scholar"
        return paper

    @pytest.mark.asyncio
    async def test_feature_disabled_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-01: Returns None when feature is disabled.

        // Given: Feature is disabled in settings
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None immediately (no API calls)
        """
        # Given: Feature is disabled in settings
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = False

        # When: Calling enrich_pubmed_page_canonical_id
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns None immediately (no API calls)
        assert result is None
        mock_db.fetch_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_pubmed_domain_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-02: Returns None for non-PubMed domain.

        // Given: Domain is not PubMed/PMC
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None immediately
        """
        # Given: Domain is not PubMed/PMC
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True

        # When: Calling enrich_pubmed_page_canonical_id
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://example.com/paper",
                domain="example.com",
            )

        # Then: Returns None immediately
        assert result is None
        mock_db.fetch_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_canonical_id_returns_existing(self, mock_db: AsyncMock) -> None:
        """TC-N-03: Returns existing canonical_id without API call.

        // Given: Page already has canonical_id in DB
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns existing canonical_id (no S2 API call)
        """
        # Given: Page already has canonical_id in DB
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_db.fetch_one = AsyncMock(return_value={"canonical_id": "doi:10.1234/existing"})

        # When: Calling enrich_pubmed_page_canonical_id
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns existing canonical_id (no S2 API call)
        assert result == "doi:10.1234/existing"
        mock_db.update.assert_not_called()  # No update needed

    @pytest.mark.asyncio
    async def test_db_fetch_error_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-03: Returns None when DB fetch fails.

        // Given: DB fetch_one raises exception
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None gracefully (no crash)
        """
        # Given: DB fetch_one raises exception
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_db.fetch_one = AsyncMock(side_effect=RuntimeError("DB connection error"))

        # When: Calling enrich_pubmed_page_canonical_id
        with patch("src.utils.config.get_settings", return_value=mock_settings):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns None gracefully (no crash)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_pmid_or_pmcid_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-06: Returns None when no PMID/PMCID extractable.

        // Given: URL doesn't contain PMID or PMCID
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None (no identifier to look up)
        """
        # Given: URL doesn't contain PMID or PMCID
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True

        mock_identifier = MagicMock()
        mock_identifier.pmid = None
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/",  # No PMID
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns None (no identifier to look up)
        assert result is None

    @pytest.mark.asyncio
    async def test_semantic_scholar_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-04: Returns None when Semantic Scholar returns no paper.

        // Given: Semantic Scholar API returns None for paper
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None
        """
        # Given: Semantic Scholar API returns None for paper
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = "12345678"
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=None)
        mock_s2_client.close = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns None
        assert result is None
        mock_s2_client.get_paper.assert_called_once()
        mock_s2_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_scholar_timeout_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-05: Returns None when Semantic Scholar times out.

        // Given: Semantic Scholar API times out
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None (timeout handled gracefully)
        """
        # Given: Semantic Scholar API times out
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 0.001  # Very short timeout

        mock_identifier = MagicMock()
        mock_identifier.pmid = "12345678"
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        async def slow_get_paper(pid: str) -> None:
            await asyncio.sleep(10)  # Longer than timeout
            return None

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = slow_get_paper
        mock_s2_client.close = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Returns None (timeout handled gracefully)
        assert result is None
        mock_s2_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_with_pmid(self, mock_db: AsyncMock, mock_paper: MagicMock) -> None:
        """TC-N-01: Successfully enriches PubMed page with PMID.

        // Given: PubMed URL with PMID, S2 returns paper data
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: canonical_id returned, DB updated
        """
        # Given: PubMed URL with PMID, S2 returns paper data
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = "12345678"
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=mock_paper)
        mock_s2_client.close = AsyncMock()

        mock_index = MagicMock()
        mock_index.register_paper = MagicMock(return_value="doi:10.1234/test.doi")

        mock_persist_work = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.storage.works.persist_work", mock_persist_work),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: canonical_id returned, DB updated
        assert result == "doi:10.1234/test.doi"
        mock_s2_client.get_paper.assert_called_once_with("PMID:12345678")
        mock_db.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_with_pmcid_resolution(
        self, mock_db: AsyncMock, mock_paper: MagicMock
    ) -> None:
        """TC-N-02: Successfully enriches PMC page via PMCID→PMID resolution.

        // Given: PMC URL with PMCID only, resolver returns PMID
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: PMCID resolved to PMID, canonical_id returned
        """
        # Given: PMC URL with PMCID only, resolver returns PMID
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = None  # No PMID initially
        mock_identifier.pmcid = "PMC1234567"

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_resolver = AsyncMock()
        mock_resolver.resolve_pmcid = AsyncMock(return_value={"pmid": "87654321", "doi": None})
        mock_resolver.close = AsyncMock()

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=mock_paper)
        mock_s2_client.close = AsyncMock()

        mock_index = MagicMock()
        mock_index.register_paper = MagicMock(return_value="doi:10.1234/test.doi")

        mock_persist_work = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch("src.search.id_resolver.IDResolver", return_value=mock_resolver),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.storage.works.persist_work", mock_persist_work),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/",
                domain="pmc.ncbi.nlm.nih.gov",
            )

        # Then: PMCID resolved to PMID, canonical_id returned
        assert result == "doi:10.1234/test.doi"
        mock_resolver.resolve_pmcid.assert_called_once_with("PMC1234567")
        mock_s2_client.get_paper.assert_called_once_with("PMID:87654321")

    @pytest.mark.asyncio
    async def test_pmcid_resolver_returns_doi(
        self, mock_db: AsyncMock, mock_paper: MagicMock
    ) -> None:
        """TC-N-04: Uses DOI when PMCID resolver returns DOI.

        // Given: PMC URL with PMCID, resolver returns DOI
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Uses DOI for S2 lookup instead of PMID
        """
        # Given: PMC URL with PMCID, resolver returns DOI
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = None
        mock_identifier.pmcid = "PMC1234567"

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_resolver = AsyncMock()
        # Resolver returns DOI but no PMID
        mock_resolver.resolve_pmcid = AsyncMock(
            return_value={"pmid": None, "doi": "10.1234/resolved.doi"}
        )
        mock_resolver.close = AsyncMock()

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=mock_paper)
        mock_s2_client.close = AsyncMock()

        mock_index = MagicMock()
        mock_index.register_paper = MagicMock(return_value="doi:10.1234/resolved.doi")

        mock_persist_work = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch("src.search.id_resolver.IDResolver", return_value=mock_resolver),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.storage.works.persist_work", mock_persist_work),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/",
                domain="pmc.ncbi.nlm.nih.gov",
            )

        # Then: Uses DOI for S2 lookup instead of PMID
        assert result == "doi:10.1234/resolved.doi"
        mock_s2_client.get_paper.assert_called_once_with("DOI:10.1234/resolved.doi")

    @pytest.mark.asyncio
    async def test_pmcid_resolver_timeout_returns_none(self, mock_db: AsyncMock) -> None:
        """TC-A-07: Returns None when PMCID resolver times out.

        // Given: PMC URL with PMCID, resolver times out
        // When: Calling enrich_pubmed_page_canonical_id
        // Then: Returns None (timeout handled gracefully)
        """
        # Given: PMC URL with PMCID, resolver times out
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 0.001  # Very short

        mock_identifier = MagicMock()
        mock_identifier.pmid = None
        mock_identifier.pmcid = "PMC1234567"

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        async def slow_resolve(pmcid: str) -> dict[str, Any]:
            await asyncio.sleep(10)
            return {"pmid": "12345678"}

        mock_resolver = AsyncMock()
        mock_resolver.resolve_pmcid = slow_resolve
        mock_resolver.close = AsyncMock()

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=None)
        mock_s2_client.close = AsyncMock()

        # When: Calling enrich_pubmed_page_canonical_id
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch("src.search.id_resolver.IDResolver", return_value=mock_resolver),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
        ):
            result = await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/",
                domain="pmc.ncbi.nlm.nih.gov",
            )

        # Then: Returns None (timeout handled, no PMID available)
        assert result is None

    @pytest.mark.asyncio
    async def test_wiring_persist_work_called_correctly(
        self, mock_db: AsyncMock, mock_paper: MagicMock
    ) -> None:
        """TC-W-01: Verifies persist_work is called with correct arguments.

        // Given: Successful enrichment flow
        // When: persist_work is called
        // Then: Arguments are (db, paper, canonical_id)
        """
        # Given: Successful enrichment flow
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = "12345678"
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=mock_paper)
        mock_s2_client.close = AsyncMock()

        mock_index = MagicMock()
        mock_index.register_paper = MagicMock(return_value="doi:10.1234/test.doi")

        mock_persist_work = AsyncMock()

        # When: persist_work is called
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.storage.works.persist_work", mock_persist_work),
        ):
            await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Arguments are (db, paper, canonical_id)
        mock_persist_work.assert_called_once_with(mock_db, mock_paper, "doi:10.1234/test.doi")

    @pytest.mark.asyncio
    async def test_wiring_db_update_called_correctly(
        self, mock_db: AsyncMock, mock_paper: MagicMock
    ) -> None:
        """TC-W-02: Verifies db.update is called with correct page data.

        // Given: Successful enrichment flow
        // When: db.update is called
        // Then: Page is updated with canonical_id, title, page_type
        """
        # Given: Successful enrichment flow
        from src.crawler.pubmed_linker import enrich_pubmed_page_canonical_id

        mock_settings = MagicMock()
        mock_settings.crawler.pubmed_enrichment_enabled = True
        mock_settings.crawler.pubmed_enrichment_timeout_seconds = 5.0

        mock_identifier = MagicMock()
        mock_identifier.pmid = "12345678"
        mock_identifier.pmcid = None

        mock_extractor = MagicMock()
        mock_extractor.extract = MagicMock(return_value=mock_identifier)

        mock_s2_client = AsyncMock()
        mock_s2_client.get_paper = AsyncMock(return_value=mock_paper)
        mock_s2_client.close = AsyncMock()

        mock_index = MagicMock()
        mock_index.register_paper = MagicMock(return_value="doi:10.1234/test.doi")

        mock_persist_work = AsyncMock()

        # When: db.update is called
        with (
            patch("src.utils.config.get_settings", return_value=mock_settings),
            patch(
                "src.search.identifier_extractor.IdentifierExtractor", return_value=mock_extractor
            ),
            patch(
                "src.search.apis.semantic_scholar.SemanticScholarClient",
                return_value=mock_s2_client,
            ),
            patch("src.search.canonical_index.CanonicalPaperIndex", return_value=mock_index),
            patch("src.storage.works.persist_work", mock_persist_work),
        ):
            await enrich_pubmed_page_canonical_id(
                db=mock_db,
                page_id="page_123",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                domain="pubmed.ncbi.nlm.nih.gov",
            )

        # Then: Page is updated with canonical_id, title, page_type
        mock_db.update.assert_called_once_with(
            "pages",
            {
                "canonical_id": "doi:10.1234/test.doi",
                "title": "Test Paper Title",
                "page_type": "academic_paper",
            },
            "id = ?",
            ("page_123",),
        )
