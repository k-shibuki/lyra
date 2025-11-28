"""
Tests for Entity Knowledge Base.

Tests entity normalization, storage, and retrieval functionality.
Follows §7.1 test quality standards:
- Specific assertions with expected values
- No conditional assertions
- Realistic test data
- Clear AAA pattern

References:
- §3.1.2: Infrastructure/Registry Direct Access - Entity KB normalization
- §7.1: Test code quality standards
"""

import pytest

# All tests in this module are integration tests (use database)
pytestmark = pytest.mark.integration
import pytest_asyncio
import asyncio
from datetime import datetime, timezone

from src.storage.entity_kb import (
    EntityKB,
    EntityRecord,
    EntityType,
    IdentifierType,
    SourceType,
    NormalizedName,
    NormalizedAddress,
    NameNormalizer,
    AddressNormalizer,
    IdentifierNormalizer,
    get_entity_kb,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def name_normalizer():
    """Create NameNormalizer instance."""
    return NameNormalizer()


@pytest.fixture
def address_normalizer():
    """Create AddressNormalizer instance."""
    return AddressNormalizer()


@pytest.fixture
def identifier_normalizer():
    """Create IdentifierNormalizer instance."""
    return IdentifierNormalizer()


@pytest_asyncio.fixture
async def entity_kb(tmp_path):
    """Create EntityKB with in-memory database."""
    import aiosqlite
    
    # Create in-memory database
    db_path = tmp_path / "test_entities.db"
    
    class MockDatabase:
        """Mock database for testing."""
        
        def __init__(self, path):
            self._path = path
            self._conn = None
        
        async def connect(self):
            self._conn = await aiosqlite.connect(self._path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON")
        
        async def close(self):
            if self._conn:
                await self._conn.close()
        
        async def execute(self, sql, params=None):
            # Check if SQL contains multiple statements
            if params is None and ";" in sql.strip().rstrip(";"):
                # Use executescript for multiple statements
                await self._conn.executescript(sql)
                return None
            if params:
                return await self._conn.execute(sql, params)
            return await self._conn.execute(sql)
        
        async def fetch_one(self, sql, params=None):
            cursor = await self.execute(sql, params)
            row = await cursor.fetchone()
            return dict(row) if row else None
        
        async def fetch_all(self, sql, params=None):
            cursor = await self.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        
        async def insert(self, table, data, auto_id=True):
            import uuid
            if auto_id and "id" not in data:
                data = data.copy()
                data["id"] = str(uuid.uuid4())
            
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?" for _ in data])
            sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            await self.execute(sql, tuple(data.values()))
            return data.get("id")
        
        async def update(self, table, data, where, where_params=None):
            set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
            sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
            params = list(data.values())
            if where_params:
                params.extend(where_params)
            await self.execute(sql, tuple(params))
    
    db = MockDatabase(db_path)
    await db.connect()
    
    kb = EntityKB(db)
    await kb.initialize_schema()
    
    yield kb
    
    await db.close()


# =============================================================================
# Name Normalizer Tests
# =============================================================================

class TestNameNormalizer:
    """Tests for NameNormalizer class."""
    
    def test_normalize_basic_organization_name(self, name_normalizer):
        """Test basic organization name normalization.

        Verifies that simple organization names are properly normalized
        with lowercase canonical form and correct tokenization.
        """
        # Arrange
        name = "Example Corporation"

        # Act
        result = name_normalizer.normalize(name, EntityType.ORGANIZATION)

        # Assert
        assert result.original == "Example Corporation"
        assert result.suffix_type == "corp"
        # normalized contains the name part without suffix
        assert "example" in result.normalized.lower()
        # canonical includes the normalized suffix
        assert "corp" in result.canonical
        assert "example" in result.tokens
    
    def test_normalize_japanese_corporation(self, name_normalizer):
        """Test Japanese corporation name normalization.
        
        Verifies that Japanese corporate suffixes (株式会社) are
        properly extracted and normalized.
        """
        # Arrange
        name = "株式会社テスト"
        
        # Act
        result = name_normalizer.normalize(name, EntityType.ORGANIZATION)
        
        # Assert
        assert result.original == "株式会社テスト"
        assert result.suffix_type == "KK"
        assert "kk" in result.canonical.lower()
        assert result.language == "ja"
    
    def test_normalize_with_parenthetical_suffix(self, name_normalizer):
        """Test organization name with parenthetical suffix.
        
        Verifies that (株) and similar formats are handled.
        """
        # Arrange
        name = "(株)サンプル会社"
        
        # Act
        result = name_normalizer.normalize(name, EntityType.ORGANIZATION)
        
        # Assert
        assert result.suffix_type == "KK"
        assert result.language == "ja"
    
    def test_normalize_english_variations(self, name_normalizer):
        """Test various English corporate suffix variations.
        
        Verifies that Inc., Ltd., LLC etc. are all normalized consistently.
        """
        # Arrange
        names = [
            ("Acme Inc.", "inc"),
            ("Acme Incorporated", "inc"),
            ("Acme Limited", "ltd"),
            ("Acme Ltd.", "ltd"),
            ("Acme LLC", "llc"),
            ("Acme L.L.C.", "llc"),
        ]
        
        for name, expected_suffix in names:
            # Act
            result = name_normalizer.normalize(name, EntityType.ORGANIZATION)
            
            # Assert
            assert result.suffix_type == expected_suffix, f"Failed for {name}"
    
    def test_normalize_fullwidth_characters(self, name_normalizer):
        """Test full-width to half-width ASCII conversion.
        
        Verifies that full-width characters are converted to half-width.
        """
        # Arrange
        name = "ＡＢＣＤ　Ｃｏｒｐ"  # Full-width
        
        # Act
        result = name_normalizer.normalize(name, EntityType.ORGANIZATION)
        
        # Assert
        assert "abcd" in result.canonical.lower()
    
    def test_normalize_person_name(self, name_normalizer):
        """Test person name normalization (no suffix extraction).
        
        Verifies that person names don't have corporate suffixes extracted.
        """
        # Arrange
        name = "John Smith"
        
        # Act
        result = name_normalizer.normalize(name, EntityType.PERSON)
        
        # Assert
        assert result.original == "John Smith"
        assert result.suffix_type is None
        assert result.canonical == "john smith"
        assert result.tokens == ["john", "smith"]
    
    def test_compute_similarity_exact_match(self, name_normalizer):
        """Test similarity computation for exact canonical matches.

        Verifies that identical canonical names return similarity 1.0.
        """
        # Arrange - Same name with same suffix format
        name1 = name_normalizer.normalize("Example Corp", EntityType.ORGANIZATION)
        name2 = name_normalizer.normalize("Example Corp", EntityType.ORGANIZATION)

        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)

        # Assert
        assert similarity == 1.0
    
    def test_compute_similarity_same_name_different_suffix(self, name_normalizer):
        """Test similarity computation for same name with different suffix formats.

        Verifies that Example Corp and Example Corporation are recognized
        as highly similar due to matching suffix types.
        """
        # Arrange
        name1 = name_normalizer.normalize("Example Corp", EntityType.ORGANIZATION)
        name2 = name_normalizer.normalize("Example Corporation", EntityType.ORGANIZATION)

        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)

        # Assert
        # Both have suffix_type "corp", so similarity gets a boost
        assert similarity >= 0.6  # High similarity due to same suffix type
    
    def test_compute_similarity_partial_match(self, name_normalizer):
        """Test similarity computation for partial matches.
        
        Verifies that partially matching names have similarity < 1.0.
        """
        # Arrange
        name1 = name_normalizer.normalize("Acme Software Inc", EntityType.ORGANIZATION)
        name2 = name_normalizer.normalize("Acme Hardware Inc", EntityType.ORGANIZATION)
        
        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)
        
        # Assert
        assert 0.3 < similarity < 0.8  # Partial overlap
    
    def test_compute_similarity_no_match(self, name_normalizer):
        """Test similarity computation for completely different names.
        
        Verifies that unrelated names have low similarity.
        """
        # Arrange
        name1 = name_normalizer.normalize("Alpha Systems", EntityType.ORGANIZATION)
        name2 = name_normalizer.normalize("Beta Technologies", EntityType.ORGANIZATION)
        
        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)
        
        # Assert
        assert similarity < 0.3
    
    def test_detect_language_japanese(self, name_normalizer):
        """Test Japanese language detection."""
        # Arrange & Act
        result = name_normalizer.normalize("東京株式会社", EntityType.ORGANIZATION)
        
        # Assert
        assert result.language == "ja"
    
    def test_detect_language_english(self, name_normalizer):
        """Test English language detection."""
        # Arrange & Act
        result = name_normalizer.normalize("Tokyo Corporation", EntityType.ORGANIZATION)
        
        # Assert
        assert result.language == "en"
    
    def test_detect_language_korean(self, name_normalizer):
        """Test Korean language detection."""
        # Arrange & Act
        result = name_normalizer.normalize("삼성전자", EntityType.ORGANIZATION)
        
        # Assert
        assert result.language == "ko"


# =============================================================================
# Address Normalizer Tests
# =============================================================================

class TestAddressNormalizer:
    """Tests for AddressNormalizer class."""
    
    def test_normalize_basic_address(self, address_normalizer):
        """Test basic address normalization."""
        # Arrange
        address = "123 Main Street, Tokyo, Japan"
        
        # Act
        result = address_normalizer.normalize(address)
        
        # Assert
        assert result.original == "123 Main Street, Tokyo, Japan"
        assert result.country_code == "jp"
    
    def test_normalize_japanese_postal_code(self, address_normalizer):
        """Test Japanese postal code extraction.
        
        Verifies that 〒123-4567 format is correctly extracted.
        """
        # Arrange
        address = "〒100-0001 東京都千代田区"
        
        # Act
        result = address_normalizer.normalize(address)
        
        # Assert
        assert result.postal_code == "100-0001"
    
    def test_normalize_us_postal_code(self, address_normalizer):
        """Test US postal code extraction.
        
        Verifies that 5-digit and 5+4 ZIP codes are extracted.
        """
        # Arrange
        address = "123 Main St, New York, NY 10001, USA"
        
        # Act
        result = address_normalizer.normalize(address)
        
        # Assert
        assert result.postal_code == "10001"
        assert result.country_code == "us"
    
    def test_normalize_country_code_from_hint(self, address_normalizer):
        """Test country code from explicit hint."""
        # Arrange
        address = "123 Main Street"
        
        # Act
        result = address_normalizer.normalize(address, country="Japan")
        
        # Assert
        assert result.country_code == "jp"
    
    def test_normalize_country_variations(self, address_normalizer):
        """Test various country name formats.
        
        Verifies that different country representations are normalized.
        """
        # Arrange
        test_cases = [
            ("Tokyo, Japan", "jp"),
            ("New York, USA", "us"),
            ("London, United Kingdom", "uk"),
            ("Berlin, Germany", "de"),
            ("東京, 日本", "jp"),
        ]
        
        for address, expected_code in test_cases:
            # Act
            result = address_normalizer.normalize(address)
            
            # Assert
            assert result.country_code == expected_code, f"Failed for {address}"
    
    def test_normalize_empty_address(self, address_normalizer):
        """Test handling of empty address."""
        # Arrange & Act
        result = address_normalizer.normalize("")
        
        # Assert
        assert result.original == ""
        assert result.normalized == ""
        assert result.country_code is None


# =============================================================================
# Identifier Normalizer Tests
# =============================================================================

class TestIdentifierNormalizer:
    """Tests for IdentifierNormalizer class."""
    
    def test_normalize_domain_basic(self, identifier_normalizer):
        """Test basic domain normalization."""
        # Arrange & Act
        result = identifier_normalizer.normalize_domain("Example.COM")
        
        # Assert
        assert result == "example.com"
    
    def test_normalize_domain_with_trailing_dot(self, identifier_normalizer):
        """Test domain with trailing dot."""
        # Arrange & Act
        result = identifier_normalizer.normalize_domain("example.com.")
        
        # Assert
        assert result == "example.com"
    
    def test_normalize_domain_from_url(self, identifier_normalizer):
        """Test domain extraction from URL."""
        # Arrange & Act
        result = identifier_normalizer.normalize_domain("https://www.example.com/path")
        
        # Assert
        assert result == "www.example.com"
    
    def test_normalize_domain_with_port(self, identifier_normalizer):
        """Test domain with port number."""
        # Arrange & Act
        result = identifier_normalizer.normalize_domain("example.com:8080")
        
        # Assert
        assert result == "example.com"
    
    def test_normalize_email_basic(self, identifier_normalizer):
        """Test basic email normalization."""
        # Arrange & Act
        result = identifier_normalizer.normalize_email("User@Example.COM")
        
        # Assert
        assert result == "user@example.com"
    
    def test_normalize_phone_japanese(self, identifier_normalizer):
        """Test Japanese phone number normalization."""
        # Arrange & Act
        result = identifier_normalizer.normalize_phone("03-1234-5678", country_code="jp")
        
        # Assert
        assert result == "+81312345678"
    
    def test_normalize_phone_with_plus(self, identifier_normalizer):
        """Test phone number with international prefix."""
        # Arrange & Act
        result = identifier_normalizer.normalize_phone("+1-555-123-4567")
        
        # Assert
        assert result == "+15551234567"
    
    def test_normalize_ip_v4(self, identifier_normalizer):
        """Test IPv4 address normalization."""
        # Arrange & Act
        result = identifier_normalizer.normalize_ip("192.168.001.001")
        
        # Assert
        assert result == "192.168.1.1"
    
    def test_normalize_ip_v6(self, identifier_normalizer):
        """Test IPv6 address normalization."""
        # Arrange & Act
        result = identifier_normalizer.normalize_ip("2001:DB8::1")
        
        # Assert
        assert result == "2001:db8::1"


# =============================================================================
# EntityKB Integration Tests
# =============================================================================

@pytest.mark.asyncio
class TestEntityKB:
    """Integration tests for EntityKB class."""
    
    async def test_add_entity_basic(self, entity_kb):
        """Test adding a basic entity.
        
        Verifies that entities can be added and retrieved.
        """
        # Arrange
        name = "Test Corporation"
        
        # Act
        entity = await entity_kb.add_entity(
            name=name,
            entity_type=EntityType.ORGANIZATION,
            confidence=0.9,
        )
        
        # Assert
        assert entity.id is not None
        assert entity.display_name == name
        assert entity.entity_type == EntityType.ORGANIZATION
        assert entity.confidence == 0.9
    
    async def test_add_entity_with_address(self, entity_kb):
        """Test adding entity with address normalization."""
        # Arrange
        name = "Japan Corp"
        address = "〒100-0001 東京都千代田区"
        
        # Act
        entity = await entity_kb.add_entity(
            name=name,
            entity_type=EntityType.ORGANIZATION,
            address=address,
            country="Japan",
        )
        
        # Assert
        assert entity.normalized_address is not None
        assert entity.normalized_address.postal_code == "100-0001"
        assert entity.normalized_address.country_code == "jp"
    
    async def test_add_entity_with_identifiers(self, entity_kb):
        """Test adding entity with identifiers."""
        # Arrange
        name = "Example Inc"
        identifiers = [
            (IdentifierType.DOMAIN, "example.com"),
            (IdentifierType.EMAIL, "contact@example.com"),
        ]
        
        # Act
        entity = await entity_kb.add_entity(
            name=name,
            entity_type=EntityType.ORGANIZATION,
            identifiers=identifiers,
        )
        
        # Assert
        stored_ids = await entity_kb.get_entity_identifiers(entity.id)
        assert len(stored_ids) == 2
        
        domain_ids = [i for i in stored_ids if i.identifier_type == IdentifierType.DOMAIN]
        assert len(domain_ids) == 1
        assert domain_ids[0].identifier_normalized == "example.com"
    
    async def test_add_entity_with_aliases(self, entity_kb):
        """Test adding entity with aliases."""
        # Arrange
        name = "International Business Machines Corporation"
        aliases = ["IBM", "Big Blue"]
        
        # Act
        entity = await entity_kb.add_entity(
            name=name,
            entity_type=EntityType.ORGANIZATION,
            aliases=aliases,
        )
        
        # Assert
        stored_aliases = await entity_kb.get_entity_aliases(entity.id)
        assert len(stored_aliases) == 2
        
        alias_texts = [a.alias_text for a in stored_aliases]
        assert "IBM" in alias_texts
        assert "Big Blue" in alias_texts
    
    async def test_find_entity_by_canonical_name(self, entity_kb):
        """Test finding entity by canonical name match."""
        # Arrange
        await entity_kb.add_entity(
            name="Acme Corporation",
            entity_type=EntityType.ORGANIZATION,
        )
        
        # Act
        matches = await entity_kb.find_entity(
            name="Acme Corp",  # Different suffix format
            entity_type=EntityType.ORGANIZATION,
        )
        
        # Assert
        assert len(matches) >= 1
        assert matches[0].match_score == 1.0
        assert matches[0].match_type == "canonical"
    
    async def test_find_entity_by_alias(self, entity_kb):
        """Test finding entity by alias."""
        # Arrange
        await entity_kb.add_entity(
            name="International Business Machines Corporation",
            entity_type=EntityType.ORGANIZATION,
            aliases=["IBM"],
        )
        
        # Act
        matches = await entity_kb.find_entity(
            name="IBM",
            entity_type=EntityType.ORGANIZATION,
        )
        
        # Assert
        assert len(matches) >= 1
        assert matches[0].match_type == "alias"
    
    async def test_find_entity_by_identifier(self, entity_kb):
        """Test finding entity by identifier."""
        # Arrange
        await entity_kb.add_entity(
            name="Example Inc",
            entity_type=EntityType.ORGANIZATION,
            identifiers=[(IdentifierType.DOMAIN, "example.com")],
        )
        
        # Act
        matches = await entity_kb.find_entity(
            identifiers=[(IdentifierType.DOMAIN, "example.com")],
        )
        
        # Assert
        assert len(matches) >= 1
        assert matches[0].match_score == 1.0
        assert matches[0].match_type == "identifier"
    
    async def test_deduplication_by_name(self, entity_kb):
        """Test entity deduplication by name.
        
        Verifies that adding the same entity twice returns the existing one.
        """
        # Arrange
        entity1 = await entity_kb.add_entity(
            name="Acme Corporation",
            entity_type=EntityType.ORGANIZATION,
            confidence=0.8,
        )
        
        # Act - Add same entity with different suffix format
        entity2 = await entity_kb.add_entity(
            name="Acme Corp",
            entity_type=EntityType.ORGANIZATION,
            confidence=0.9,
            deduplicate=True,
        )
        
        # Assert
        assert entity2.id == entity1.id  # Same entity
    
    async def test_deduplication_by_identifier(self, entity_kb):
        """Test entity deduplication by identifier.
        
        Verifies that adding entity with same identifier returns existing one.
        """
        # Arrange
        entity1 = await entity_kb.add_entity(
            name="Example Inc",
            entity_type=EntityType.ORGANIZATION,
            identifiers=[(IdentifierType.DOMAIN, "example.com")],
        )
        
        # Act - Add different name but same domain
        entity2 = await entity_kb.add_entity(
            name="Example Corporation",
            entity_type=EntityType.ORGANIZATION,
            identifiers=[(IdentifierType.DOMAIN, "example.com")],
            deduplicate=True,
        )
        
        # Assert
        assert entity2.id == entity1.id
    
    async def test_add_relationship(self, entity_kb):
        """Test adding relationship between entities."""
        # Arrange
        org = await entity_kb.add_entity(
            name="Parent Corp",
            entity_type=EntityType.ORGANIZATION,
        )
        subsidiary = await entity_kb.add_entity(
            name="Subsidiary Inc",
            entity_type=EntityType.ORGANIZATION,
        )
        
        # Act
        rel_id = await entity_kb.add_relationship(
            org.id,
            subsidiary.id,
            "owns",
            confidence=0.9,
        )
        
        # Assert
        assert rel_id is not None
        
        related = await entity_kb.get_related_entities(org.id)
        assert len(related) == 1
        assert related[0][0].id == subsidiary.id
        assert related[0][1] == "owns"
        assert related[0][2] == 0.9
    
    async def test_get_related_entities_filtered(self, entity_kb):
        """Test getting related entities with type filter."""
        # Arrange
        org = await entity_kb.add_entity(
            name="Parent Corp",
            entity_type=EntityType.ORGANIZATION,
        )
        sub1 = await entity_kb.add_entity(
            name="Subsidiary 1",
            entity_type=EntityType.ORGANIZATION,
        )
        sub2 = await entity_kb.add_entity(
            name="Partner Corp",
            entity_type=EntityType.ORGANIZATION,
        )
        
        await entity_kb.add_relationship(org.id, sub1.id, "owns")
        await entity_kb.add_relationship(org.id, sub2.id, "partners_with")
        
        # Act
        owns_relations = await entity_kb.get_related_entities(org.id, "owns")
        
        # Assert
        assert len(owns_relations) == 1
        assert owns_relations[0][0].id == sub1.id
    
    async def test_domain_entity_with_identifiers(self, entity_kb):
        """Test domain entity with multiple identifiers."""
        # Arrange
        identifiers = [
            (IdentifierType.DOMAIN, "example.com"),
            (IdentifierType.NAMESERVER, "ns1.example.com"),
            (IdentifierType.NAMESERVER, "ns2.example.com"),
        ]
        
        # Act
        entity = await entity_kb.add_entity(
            name="example.com",
            entity_type=EntityType.DOMAIN,
            identifiers=identifiers,
        )
        
        # Assert
        stored_ids = await entity_kb.get_entity_identifiers(entity.id)
        assert len(stored_ids) == 3
        
        ns_ids = [i for i in stored_ids if i.identifier_type == IdentifierType.NAMESERVER]
        assert len(ns_ids) == 2


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_normalize_empty_name(self, name_normalizer):
        """Test handling of empty name."""
        # Arrange & Act
        result = name_normalizer.normalize("", EntityType.ORGANIZATION)
        
        # Assert
        assert result.original == ""
        assert result.normalized == ""
        assert result.canonical == ""
        assert result.tokens == []
    
    def test_normalize_whitespace_only_name(self, name_normalizer):
        """Test handling of whitespace-only name."""
        # Arrange & Act
        result = name_normalizer.normalize("   ", EntityType.ORGANIZATION)
        
        # Assert
        assert result.original == ""
        assert result.canonical == ""
    
    def test_normalize_name_with_special_characters(self, name_normalizer):
        """Test handling of names with special characters."""
        # Arrange
        name = "O'Reilly & Associates, Inc."
        
        # Act
        result = name_normalizer.normalize(name, EntityType.ORGANIZATION)
        
        # Assert
        assert result.suffix_type == "inc"
        assert "o'reilly" in result.canonical
    
    def test_normalize_domain_empty(self, identifier_normalizer):
        """Test handling of empty domain."""
        # Arrange & Act
        result = identifier_normalizer.normalize_domain("")
        
        # Assert
        assert result == ""
    
    def test_normalize_email_invalid(self, identifier_normalizer):
        """Test handling of invalid email (no @)."""
        # Arrange & Act
        result = identifier_normalizer.normalize_email("not-an-email")
        
        # Assert
        assert result == "not-an-email"  # Returns as-is
    
    def test_similarity_empty_tokens(self, name_normalizer):
        """Test similarity computation with empty tokens."""
        # Arrange
        name1 = NormalizedName(
            original="",
            normalized="",
            canonical="",
            tokens=[],
        )
        name2 = name_normalizer.normalize("Test", EntityType.ORGANIZATION)
        
        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)
        
        # Assert
        assert similarity == 0.0


# =============================================================================
# Boundary Condition Tests
# =============================================================================

class TestBoundaryConditions:
    """Tests for boundary conditions per §7.1.2."""
    
    def test_similarity_single_token(self, name_normalizer):
        """Test similarity with single-token names."""
        # Arrange
        name1 = name_normalizer.normalize("IBM", EntityType.ORGANIZATION)
        name2 = name_normalizer.normalize("IBM", EntityType.ORGANIZATION)
        
        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)
        
        # Assert
        assert similarity == 1.0
    
    def test_similarity_many_tokens(self, name_normalizer):
        """Test similarity with many-token names.
        
        Long names with the same core content but different suffixes
        should have high similarity but not necessarily 1.0 due to
        token-based Jaccard calculation.
        """
        # Arrange
        name1 = name_normalizer.normalize(
            "The Very Long Company Name With Many Words Inc",
            EntityType.ORGANIZATION,
        )
        name2 = name_normalizer.normalize(
            "The Very Long Company Name With Many Words Corporation",
            EntityType.ORGANIZATION,
        )
        
        # Act
        similarity = name_normalizer.compute_similarity(name1, name2)
        
        # Assert
        # High similarity due to many shared tokens, but suffix adds to union
        assert similarity >= 0.6  # Significant overlap expected
    
    @pytest.mark.asyncio
    async def test_find_entity_no_matches(self, entity_kb):
        """Test find_entity when no matches exist."""
        # Arrange - Empty KB
        
        # Act
        matches = await entity_kb.find_entity(
            name="Nonexistent Corp",
            entity_type=EntityType.ORGANIZATION,
        )
        
        # Assert
        assert matches == []
    
    @pytest.mark.asyncio
    async def test_get_entity_nonexistent(self, entity_kb):
        """Test get_entity with nonexistent ID."""
        # Arrange & Act
        entity = await entity_kb.get_entity("nonexistent-id")
        
        # Assert
        assert entity is None
    
    @pytest.mark.asyncio
    async def test_get_identifiers_no_entity(self, entity_kb):
        """Test get_entity_identifiers with nonexistent entity."""
        # Arrange & Act
        identifiers = await entity_kb.get_entity_identifiers("nonexistent-id")
        
        # Assert
        assert identifiers == []
    
    @pytest.mark.asyncio
    async def test_get_aliases_no_entity(self, entity_kb):
        """Test get_entity_aliases with nonexistent entity."""
        # Arrange & Act
        aliases = await entity_kb.get_entity_aliases("nonexistent-id")
        
        # Assert
        assert aliases == []

