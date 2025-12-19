"""
Tests for Entity Integration module.

Tests integration between RDAP/WHOIS, Certificate Transparency, and Entity KB.
Follows §7.1 test quality standards.

Note: This tests the "EntityIntegration" module, not integration tests as a test type.
All external dependencies are mocked.

References:
- §3.1.2: Infrastructure/Registry Direct Access - Entity KB normalization
- §7.1: Test code quality standards

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-EE-01 | Extract from WHOIS with registrant | Equivalence – normal | Organization entity extracted | - |
| TC-EE-02 | Extract from WHOIS with tech contact | Equivalence – normal | Person entity extracted | - |
| TC-EE-03 | Extract from WHOIS with nameservers | Equivalence – normal | Domain entities extracted | - |
| TC-EE-04 | Extract from empty WHOIS | Boundary – empty | Empty result | - |
| TC-EE-05 | Extract from CertSearchResult | Equivalence – normal | Issuer org entities extracted | - |
| TC-EE-06 | Extract from cert with SAN | Equivalence – SAN | Domain entities extracted | - |
| TC-REI-01 | Integrate domain data | Equivalence – integration | Entities added to KB | - |
| TC-REI-02 | Integrate with mocked fetcher | Integration – mocked | Entities from all sources | - |
| TC-REI-03 | Integrate with failed fetcher | Abnormal – error | Handles gracefully | - |
| TC-EER-01 | EntityExtractionResult serialization | Equivalence – to_dict | Dictionary with all fields | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.crawler.crt_transparency import CertificateInfo, CertSearchResult
from src.crawler.entity_integration import (
    EntityExtractionResult,
    EntityExtractor,
    RegistryEntityIntegration,
)
from src.crawler.rdap_whois import NameserverInfo, RegistrantInfo, WHOISRecord
from src.storage.entity_kb import (
    EntityKB,
    EntityType,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_entity_kb():
    """Create mock EntityKB for testing."""
    kb = MagicMock(spec=EntityKB)

    # Track added entities
    kb._entities = {}
    kb._entity_counter = 0

    async def mock_add_entity(**kwargs):
        kb._entity_counter += 1
        entity_id = f"entity_{kb._entity_counter}"

        entity = MagicMock()
        entity.id = entity_id
        entity.display_name = kwargs.get("name", "")
        entity.entity_type = kwargs.get("entity_type")
        entity.confidence = kwargs.get("confidence", 0.5)
        entity.to_dict = lambda: {"id": entity_id, "name": kwargs.get("name")}

        kb._entities[entity_id] = entity
        return entity

    async def mock_add_relationship(*args, **kwargs):
        return f"rel_{kb._entity_counter}"

    async def mock_find_entity(**kwargs):
        return []  # No duplicates by default

    kb.add_entity = AsyncMock(side_effect=mock_add_entity)
    kb.add_relationship = AsyncMock(side_effect=mock_add_relationship)
    kb.find_entity = AsyncMock(side_effect=mock_find_entity)

    return kb


@pytest.fixture
def sample_whois_record():
    """Create sample WHOISRecord for testing."""
    return WHOISRecord(
        domain="example.com",
        registrar="Example Registrar Inc.",
        registrant=RegistrantInfo(
            name="John Doe",
            organization="Example Corporation",
            email="admin@example.com",
            phone="+1-555-123-4567",
            address="123 Main Street",
            city="San Francisco",
            state="CA",
            country="US",
        ),
        created_date=datetime(2020, 1, 15, tzinfo=UTC),
        updated_date=datetime(2024, 1, 15, tzinfo=UTC),
        expiry_date=datetime(2025, 1, 15, tzinfo=UTC),
        nameservers=[
            NameserverInfo(hostname="ns1.example.com"),
            NameserverInfo(hostname="ns2.example.com"),
        ],
        status=["clientTransferProhibited"],
        dnssec=True,
        source_url="https://whois.example.com/example.com",
        source_type="whois-html",
    )


@pytest.fixture
def sample_cert_result():
    """Create sample CertSearchResult for testing."""
    return CertSearchResult(
        query_domain="example.com",
        certificates=[
            CertificateInfo(
                cert_id="12345",
                common_name="example.com",
                issuer_name="Let's Encrypt Authority X3",
                issuer_org="Let's Encrypt",
                not_before=datetime(2024, 1, 1, tzinfo=UTC),
                not_after=datetime(2024, 4, 1, tzinfo=UTC),
                san_dns=["example.com", "www.example.com", "api.example.com"],
            ),
            CertificateInfo(
                cert_id="12346",
                common_name="*.example.com",
                issuer_name="DigiCert SHA2 Extended Validation Server CA",
                issuer_org="DigiCert Inc",
                not_before=datetime(2023, 6, 1, tzinfo=UTC),
                not_after=datetime(2024, 6, 1, tzinfo=UTC),
                san_dns=["*.example.com", "example.com"],
            ),
        ],
        discovered_domains=["related.example.org", "partner.example.net"],
        discovered_issuers=["Let's Encrypt", "DigiCert Inc"],
        earliest_cert=datetime(2020, 1, 1, tzinfo=UTC),
        latest_cert=datetime(2024, 6, 1, tzinfo=UTC),
        source_url="https://crt.sh/?q=example.com",
    )


# =============================================================================
# EntityExtractor Tests
# =============================================================================

@pytest.mark.asyncio
class TestEntityExtractor:
    """Tests for EntityExtractor class."""

    async def test_extract_from_whois_creates_domain_entity(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test that WHOIS extraction creates domain entity.

        Verifies that the domain itself is registered as an entity.
        """
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(sample_whois_record)

        # Assert
        assert len(result.domains) >= 1

        # Check domain entity was created with correct type
        domain_calls = [
            call for call in mock_entity_kb.add_entity.call_args_list
            if call.kwargs.get("entity_type") == EntityType.DOMAIN
        ]
        assert len(domain_calls) >= 1

    async def test_extract_from_whois_creates_registrant_entity(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test that WHOIS extraction creates registrant organization entity."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(sample_whois_record)

        # Assert
        assert len(result.organizations) >= 1

        # Check organization entity was created
        org_calls = [
            call for call in mock_entity_kb.add_entity.call_args_list
            if call.kwargs.get("entity_type") == EntityType.ORGANIZATION
        ]
        assert len(org_calls) >= 1

    async def test_extract_from_whois_creates_nameserver_entities(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test that WHOIS extraction creates nameserver domain entities."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(sample_whois_record)

        # Assert
        # Should have main domain + 2 nameservers = 3 domain entities
        assert len(result.domains) >= 3

    async def test_extract_from_whois_creates_relationships(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test that WHOIS extraction creates entity relationships."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(sample_whois_record)

        # Assert
        assert result.relationships_created >= 3  # registered_by + 2 nameservers

        # Check relationship types
        rel_types = [r[2] for r in result.relationships]
        assert "registered_by" in rel_types
        assert "uses_nameserver" in rel_types

    async def test_extract_from_whois_without_registrant(self, mock_entity_kb):
        """Test WHOIS extraction when registrant info is missing."""
        # Arrange
        record = WHOISRecord(
            domain="example.com",
            registrar="Example Registrar",
            registrant=None,  # No registrant
            nameservers=[],
            source_url="https://whois.example.com",
        )
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(record)

        # Assert
        assert len(result.domains) == 1  # Only the main domain
        assert len(result.organizations) == 0  # No registrant

    async def test_extract_from_cert_creates_domain_entity(
        self,
        mock_entity_kb,
        sample_cert_result,
    ):
        """Test that CT extraction creates main domain entity."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(sample_cert_result)

        # Assert
        assert len(result.domains) >= 1
        assert result.entities_created >= 1

    async def test_extract_from_cert_creates_issuer_entities(
        self,
        mock_entity_kb,
        sample_cert_result,
    ):
        """Test that CT extraction creates certificate issuer entities."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(sample_cert_result)

        # Assert
        assert len(result.organizations) >= 2  # Let's Encrypt + DigiCert

    async def test_extract_from_cert_creates_related_domain_entities(
        self,
        mock_entity_kb,
        sample_cert_result,
    ):
        """Test that CT extraction creates related domain entities from SANs."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(sample_cert_result)

        # Assert
        # Main domain + discovered domains
        assert len(result.domains) >= 3

    async def test_extract_from_cert_creates_relationships(
        self,
        mock_entity_kb,
        sample_cert_result,
    ):
        """Test that CT extraction creates entity relationships."""
        # Arrange
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(sample_cert_result)

        # Assert
        rel_types = [r[2] for r in result.relationships]
        assert "certificate_issued_by" in rel_types
        assert "shares_certificate" in rel_types


# =============================================================================
# RegistryEntityIntegration Tests
# =============================================================================

@pytest.mark.asyncio
class TestRegistryEntityIntegration:
    """Tests for RegistryEntityIntegration class."""

    async def test_process_domain_with_whois_only(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test processing domain with only WHOIS data."""
        # Arrange
        mock_rdap = MagicMock()
        mock_rdap.lookup = AsyncMock(return_value=sample_whois_record)

        integration = RegistryEntityIntegration(
            entity_kb=mock_entity_kb,
            rdap_client=mock_rdap,
            ct_client=None,
        )

        # Act
        result = await integration.process_domain(
            "example.com",
            include_whois=True,
            include_ct=False,
        )

        # Assert
        assert result.entities_created >= 1
        mock_rdap.lookup.assert_called_once()

    async def test_process_domain_with_ct_only(
        self,
        mock_entity_kb,
        sample_cert_result,
    ):
        """Test processing domain with only CT data."""
        # Arrange
        mock_ct = MagicMock()
        mock_ct.search = AsyncMock(return_value=sample_cert_result)

        integration = RegistryEntityIntegration(
            entity_kb=mock_entity_kb,
            rdap_client=None,
            ct_client=mock_ct,
        )

        # Act
        result = await integration.process_domain(
            "example.com",
            include_whois=False,
            include_ct=True,
        )

        # Assert
        assert result.entities_created >= 1
        mock_ct.search.assert_called_once()

    async def test_process_domain_with_both_sources(
        self,
        mock_entity_kb,
        sample_whois_record,
        sample_cert_result,
    ):
        """Test processing domain with both WHOIS and CT data."""
        # Arrange
        mock_rdap = MagicMock()
        mock_rdap.lookup = AsyncMock(return_value=sample_whois_record)

        mock_ct = MagicMock()
        mock_ct.search = AsyncMock(return_value=sample_cert_result)

        integration = RegistryEntityIntegration(
            entity_kb=mock_entity_kb,
            rdap_client=mock_rdap,
            ct_client=mock_ct,
        )

        # Act
        result = await integration.process_domain(
            "example.com",
            include_whois=True,
            include_ct=True,
        )

        # Assert
        assert result.entities_created >= 2  # At least domain from each source
        mock_rdap.lookup.assert_called_once()
        mock_ct.search.assert_called_once()

    async def test_process_domain_with_failed_whois(self, mock_entity_kb):
        """Test processing domain when WHOIS lookup fails."""
        # Arrange
        mock_rdap = MagicMock()
        mock_rdap.lookup = AsyncMock(return_value=None)  # Failed lookup

        integration = RegistryEntityIntegration(
            entity_kb=mock_entity_kb,
            rdap_client=mock_rdap,
            ct_client=None,
        )

        # Act
        result = await integration.process_domain(
            "example.com",
            include_whois=True,
            include_ct=False,
        )

        # Assert
        assert result.entities_created == 0

    async def test_process_domains_batch(
        self,
        mock_entity_kb,
        sample_whois_record,
    ):
        """Test batch processing of multiple domains."""
        # Arrange
        mock_rdap = MagicMock()
        mock_rdap.lookup = AsyncMock(return_value=sample_whois_record)

        integration = RegistryEntityIntegration(
            entity_kb=mock_entity_kb,
            rdap_client=mock_rdap,
            ct_client=None,
        )

        domains = ["example.com", "test.com", "sample.org"]

        # Act
        results = await integration.process_domains_batch(
            domains,
            include_whois=True,
            include_ct=False,
            max_concurrent=2,
        )

        # Assert
        assert len(results) == 3
        assert all(d in results for d in domains)
        assert mock_rdap.lookup.call_count == 3


# =============================================================================
# EntityExtractionResult Tests
# =============================================================================

class TestEntityExtractionResult:
    """Tests for EntityExtractionResult data class."""

    def test_to_dict_empty(self):
        """Test to_dict with empty result."""
        # Arrange
        result = EntityExtractionResult()

        # Act
        data = result.to_dict()

        # Assert
        assert data["organizations"] == []
        assert data["domains"] == []
        assert data["persons"] == []
        assert data["relationships"] == []
        assert data["entities_created"] == 0

    def test_to_dict_with_data(self):
        """Test to_dict with populated result."""
        # Arrange
        result = EntityExtractionResult(
            source_type="whois",
            source_url="https://example.com",
            entities_created=5,
            relationships_created=3,
        )
        result.relationships = [
            ("id1", "id2", "owns"),
            ("id1", "id3", "partners_with"),
        ]

        # Act
        data = result.to_dict()

        # Assert
        assert data["source_type"] == "whois"
        assert data["source_url"] == "https://example.com"
        assert data["entities_created"] == 5
        assert data["relationships_created"] == 3
        assert len(data["relationships"]) == 2
        assert data["relationships"][0]["type"] == "owns"


# =============================================================================
# Edge Cases
# =============================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Tests for edge cases in entity integration."""

    async def test_extract_whois_empty_registrant_name(self, mock_entity_kb):
        """Test extraction when registrant has no name or organization."""
        # Arrange
        record = WHOISRecord(
            domain="example.com",
            registrar="Example Registrar",
            registrant=RegistrantInfo(
                name=None,
                organization=None,
            ),
            nameservers=[],
            source_url="https://whois.example.com",
        )
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_whois(record)

        # Assert
        assert len(result.organizations) == 0  # No valid registrant
        assert len(result.domains) == 1  # Only main domain

    async def test_extract_cert_empty_issuers(self, mock_entity_kb):
        """Test extraction when no issuers are discovered."""
        # Arrange
        cert_result = CertSearchResult(
            query_domain="example.com",
            certificates=[],
            discovered_domains=[],
            discovered_issuers=[],
        )
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(cert_result)

        # Assert
        assert len(result.organizations) == 0
        assert len(result.domains) == 1  # Only main domain

    async def test_extract_cert_limits_discovered_domains(self, mock_entity_kb):
        """Test that discovered domains are limited to prevent explosion."""
        # Arrange
        cert_result = CertSearchResult(
            query_domain="example.com",
            certificates=[],
            discovered_domains=[f"domain{i}.com" for i in range(100)],  # Many domains
            discovered_issuers=[],
        )
        extractor = EntityExtractor(mock_entity_kb)

        # Act
        result = await extractor.extract_from_cert(cert_result)

        # Assert
        # Should be limited (main domain + up to 20 discovered)
        assert len(result.domains) <= 21

