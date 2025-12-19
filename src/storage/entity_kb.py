"""
Entity Knowledge Base for Lancet.

Normalizes and stores entities extracted from OSINT sources (RDAP/WHOIS, crt.sh, etc.).
Implements §3.1.2:
- Name normalization (alternate representations, identity estimation)
- Address normalization
- Identifier normalization
- Entity deduplication and linking

References:
- §3.1.2: Infrastructure/Registry Direct Access - Entity KB normalization
- §3.1.1: Pivot Exploration - Entity expansion
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Common corporate suffixes to normalize (English - at end of name)
CORPORATE_SUFFIXES = {
    # English
    "corporation": "corp",
    "corp.": "corp",
    "corp": "corp",
    "incorporated": "inc",
    "inc.": "inc",
    "inc": "inc",
    "limited": "ltd",
    "ltd.": "ltd",
    "ltd": "ltd",
    "company": "co",
    "co.": "co",
    "co": "co",
    "llc": "llc",
    "l.l.c.": "llc",
    "plc": "plc",
    "p.l.c.": "plc",
    "gmbh": "gmbh",
    "ag": "ag",
    "s.a.": "sa",
    "n.v.": "nv",
    "b.v.": "bv",
    "pty": "pty",
    "pty.": "pty",
    # Japanese (suffix position)
    "株式会社": "KK",
    "有限会社": "YK",
    "合同会社": "GK",
    "合資会社": "GS",
    "合名会社": "GM",
    "(株)": "KK",
    "（株）": "KK",
    "(有)": "YK",
    "（有）": "YK",
}

# Japanese prefixed suffixes (株式会社 at the beginning)
JAPANESE_PREFIX_SUFFIXES = {
    "株式会社": "KK",
    "有限会社": "YK",
    "合同会社": "GK",
    "合資会社": "GS",
    "合名会社": "GM",
}

# Country name variations
COUNTRY_ALIASES = {
    "jp": ["japan", "日本", "jpn"],
    "us": ["united states", "usa", "u.s.a.", "united states of america", "アメリカ", "米国"],
    "uk": ["united kingdom", "great britain", "england", "gb", "イギリス", "英国"],
    "cn": ["china", "中国", "prc", "people's republic of china", "中华人民共和国"],
    "kr": ["korea", "south korea", "韓国", "大韓民国", "rok", "republic of korea"],
    "de": ["germany", "deutschland", "ドイツ"],
    "fr": ["france", "フランス"],
    "au": ["australia", "オーストラリア"],
    "ca": ["canada", "カナダ"],
    "sg": ["singapore", "シンガポール"],
    "hk": ["hong kong", "香港"],
    "tw": ["taiwan", "台湾", "中華民国"],
}

# Japanese prefecture normalization
JP_PREFECTURES = {
    "東京都": "tokyo",
    "大阪府": "osaka",
    "京都府": "kyoto",
    "北海道": "hokkaido",
    # Add more as needed
}


# =============================================================================
# Enums
# =============================================================================


class EntityType(str, Enum):
    """Types of entities in the knowledge base."""

    ORGANIZATION = "organization"
    PERSON = "person"
    DOMAIN = "domain"
    IP_ADDRESS = "ip_address"
    EMAIL = "email"
    LOCATION = "location"
    CERTIFICATE = "certificate"


class IdentifierType(str, Enum):
    """Types of entity identifiers."""

    DOMAIN = "domain"
    EMAIL = "email"
    PHONE = "phone"
    IP_ADDRESS = "ip_address"
    AS_NUMBER = "as_number"
    REGISTRATION_NUMBER = "registration_number"
    TAX_ID = "tax_id"
    CERTIFICATE_ID = "certificate_id"
    NAMESERVER = "nameserver"


class SourceType(str, Enum):
    """Source types for entity information."""

    WHOIS = "whois"
    RDAP = "rdap"
    CERT_TRANSPARENCY = "cert_transparency"
    WEB_SCRAPE = "web_scrape"
    MANUAL = "manual"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NormalizedName:
    """Result of name normalization."""

    original: str
    normalized: str
    canonical: str  # Lowercase, no punctuation, standardized suffixes
    tokens: list[str]  # Tokenized form for matching
    suffix_type: str | None = None  # e.g., "KK", "inc"
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "original": self.original,
            "normalized": self.normalized,
            "canonical": self.canonical,
            "tokens": self.tokens,
            "suffix_type": self.suffix_type,
            "language": self.language,
        }


@dataclass
class NormalizedAddress:
    """Result of address normalization."""

    original: str
    normalized: str
    country_code: str | None = None
    country_name: str | None = None
    region: str | None = None  # Prefecture/State/Province
    city: str | None = None
    postal_code: str | None = None
    street: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "original": self.original,
            "normalized": self.normalized,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "region": self.region,
            "city": self.city,
            "postal_code": self.postal_code,
            "street": self.street,
        }


@dataclass
class EntityRecord:
    """An entity in the knowledge base."""

    id: str
    entity_type: EntityType
    canonical_name: str
    display_name: str

    # Normalized components
    normalized_name: NormalizedName | None = None
    normalized_address: NormalizedAddress | None = None

    # Metadata
    confidence: float = 0.5
    source_type: SourceType = SourceType.MANUAL
    source_url: str | None = None

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Additional data
    extra_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "entity_type": self.entity_type.value,
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "normalized_name": self.normalized_name.to_dict() if self.normalized_name else None,
            "normalized_address": self.normalized_address.to_dict()
            if self.normalized_address
            else None,
            "confidence": self.confidence,
            "source_type": self.source_type.value,
            "source_url": self.source_url,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "extra_data": self.extra_data,
        }


@dataclass
class EntityAlias:
    """An alias for an entity."""

    id: str
    entity_id: str
    alias_text: str
    alias_normalized: str
    alias_type: str  # "name", "abbreviation", "translation", etc.
    language: str | None = None
    confidence: float = 0.5
    source_type: SourceType = SourceType.MANUAL

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "alias_text": self.alias_text,
            "alias_normalized": self.alias_normalized,
            "alias_type": self.alias_type,
            "language": self.language,
            "confidence": self.confidence,
            "source_type": self.source_type.value,
        }


@dataclass
class EntityIdentifier:
    """An identifier associated with an entity."""

    id: str
    entity_id: str
    identifier_type: IdentifierType
    identifier_value: str
    identifier_normalized: str
    is_primary: bool = False
    confidence: float = 0.5
    source_type: SourceType = SourceType.MANUAL
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "identifier_type": self.identifier_type.value,
            "identifier_value": self.identifier_value,
            "identifier_normalized": self.identifier_normalized,
            "is_primary": self.is_primary,
            "confidence": self.confidence,
            "source_type": self.source_type.value,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


@dataclass
class EntityMatch:
    """Result of entity matching."""

    entity: EntityRecord
    match_score: float
    match_type: str  # "exact", "canonical", "alias", "identifier", "fuzzy"
    matched_value: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity": self.entity.to_dict(),
            "match_score": self.match_score,
            "match_type": self.match_type,
            "matched_value": self.matched_value,
        }


# =============================================================================
# Name Normalizer
# =============================================================================


class NameNormalizer:
    """Normalizes organization and person names."""

    def __init__(self) -> None:
        """Initialize normalizer."""
        # Build reverse lookup for suffixes (English: at end of string)
        self._suffix_patterns: list[tuple[re.Pattern, str, str]] = []
        for suffix, normalized in CORPORATE_SUFFIXES.items():
            # Create pattern that matches suffix at word boundary or end
            # Handle trailing punctuation (Inc., Ltd., etc.)
            pattern = re.compile(rf"(?:^|\s){re.escape(suffix)}\.?(?:\s|$)", re.IGNORECASE)
            self._suffix_patterns.append((pattern, normalized, suffix))

        # Japanese prefix patterns (株式会社テスト -> テスト KK)
        self._jp_prefix_patterns: list[tuple[re.Pattern, str]] = []
        for prefix, normalized in JAPANESE_PREFIX_SUFFIXES.items():
            pattern = re.compile(rf"^{re.escape(prefix)}(.+)$")
            self._jp_prefix_patterns.append((pattern, normalized))

        # Japanese parenthetical patterns (株) at beginning
        self._jp_paren_patterns: list[tuple[re.Pattern, str]] = [
            (re.compile(r"^\(株\)(.+)$"), "KK"),
            (re.compile(r"^（株）(.+)$"), "KK"),
            (re.compile(r"^\(有\)(.+)$"), "YK"),
            (re.compile(r"^（有）(.+)$"), "YK"),
        ]

    def normalize(
        self, name: str, entity_type: EntityType = EntityType.ORGANIZATION
    ) -> NormalizedName:
        """Normalize a name.

        Args:
            name: Original name string.
            entity_type: Type of entity (affects normalization rules).

        Returns:
            NormalizedName with various representations.
        """
        if not name:
            return NormalizedName(
                original="",
                normalized="",
                canonical="",
                tokens=[],
            )

        original = name.strip()

        # Step 1: Basic normalization
        normalized = self._basic_normalize(original)

        # Step 2: Extract and normalize corporate suffix
        suffix_type = None
        if entity_type == EntityType.ORGANIZATION:
            normalized, suffix_type = self._extract_suffix(normalized)

        # Step 3: Create canonical form (lowercase, no punctuation)
        canonical = self._canonicalize(normalized)
        if suffix_type:
            canonical = f"{canonical} {suffix_type}"

        # Step 4: Tokenize for matching
        tokens = self._tokenize(canonical)

        # Step 5: Detect language
        language = self._detect_language(original)

        return NormalizedName(
            original=original,
            normalized=normalized,
            canonical=canonical,
            tokens=tokens,
            suffix_type=suffix_type,
            language=language,
        )

    def _basic_normalize(self, name: str) -> str:
        """Apply basic normalization.

        Args:
            name: Input name.

        Returns:
            Normalized name.
        """
        # Normalize whitespace
        result = " ".join(name.split())

        # Normalize quotes
        result = result.replace('"', '"').replace('"', '"')
        result = result.replace("'", "'").replace("'", "'")

        # Normalize full-width to half-width for ASCII chars
        result = self._fullwidth_to_halfwidth(result)

        return result

    def _extract_suffix(self, name: str) -> tuple[str, str | None]:
        """Extract corporate suffix from name.

        Args:
            name: Input name.

        Returns:
            Tuple of (name without suffix, normalized suffix).
        """
        # Check Japanese parenthetical patterns first ((株)サンプル)
        for pattern, normalized_suffix in self._jp_paren_patterns:
            match = pattern.match(name)
            if match:
                company_name = match.group(1).strip()
                return (company_name, normalized_suffix)

        # Check Japanese prefix patterns (株式会社テスト)
        for pattern, normalized_suffix in self._jp_prefix_patterns:
            match = pattern.match(name)
            if match:
                # Extract the company name part after the prefix
                company_name = match.group(1).strip()
                return (company_name, normalized_suffix)

        # Check suffix patterns (テスト株式会社, Example Corp, Acme Inc.)
        for pattern, normalized_suffix, _original_suffix in self._suffix_patterns:
            if pattern.search(name):
                # Remove the suffix from name
                cleaned = pattern.sub(" ", name).strip()
                return (cleaned, normalized_suffix)

        return (name, None)

    def _canonicalize(self, name: str) -> str:
        """Create canonical form of name.

        Args:
            name: Input name.

        Returns:
            Canonical form (lowercase, minimal punctuation).
        """
        # Lowercase
        result = name.lower()

        # Remove most punctuation but keep hyphens and apostrophes in words
        result = re.sub(r"[^\w\s\-']", " ", result)

        # Normalize whitespace
        result = " ".join(result.split())

        return result

    def _tokenize(self, name: str) -> list[str]:
        """Tokenize name for matching.

        Args:
            name: Canonical name.

        Returns:
            List of tokens.
        """
        # Split on whitespace and hyphens
        tokens = re.split(r"[\s\-]+", name)

        # Filter empty tokens
        tokens = [t for t in tokens if t]

        return tokens

    def _detect_language(self, name: str) -> str | None:
        """Detect language of name.

        Args:
            name: Input name.

        Returns:
            Language code or None.
        """
        # Check for Japanese characters
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", name):
            return "ja"

        # Check for Chinese characters (without Japanese kana)
        if re.search(r"[\u4E00-\u9FFF]", name) and not re.search(
            r"[\u3040-\u309F\u30A0-\u30FF]", name
        ):
            return "zh"

        # Check for Korean characters
        if re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", name):
            return "ko"

        # Default to English for Latin alphabet
        if re.search(r"[a-zA-Z]", name):
            return "en"

        return None

    def _fullwidth_to_halfwidth(self, text: str) -> str:
        """Convert full-width ASCII to half-width.

        Args:
            text: Input text.

        Returns:
            Text with half-width ASCII.
        """
        result = []
        for char in text:
            code = ord(char)
            # Full-width ASCII range: 0xFF01-0xFF5E
            if 0xFF01 <= code <= 0xFF5E:
                result.append(chr(code - 0xFEE0))
            # Full-width space
            elif code == 0x3000:
                result.append(" ")
            else:
                result.append(char)
        return "".join(result)

    def compute_similarity(self, name1: NormalizedName, name2: NormalizedName) -> float:
        """Compute similarity between two normalized names.

        Args:
            name1: First normalized name.
            name2: Second normalized name.

        Returns:
            Similarity score between 0 and 1.
        """
        # Exact canonical match
        if name1.canonical == name2.canonical:
            return 1.0

        # Token-based Jaccard similarity
        tokens1 = set(name1.tokens)
        tokens2 = set(name2.tokens)

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        jaccard = intersection / union if union > 0 else 0.0

        # Boost if suffix types match
        if name1.suffix_type and name2.suffix_type:
            if name1.suffix_type == name2.suffix_type:
                jaccard = min(1.0, jaccard + 0.1)

        return jaccard


# =============================================================================
# Address Normalizer
# =============================================================================


class AddressNormalizer:
    """Normalizes addresses."""

    def __init__(self) -> None:
        """Initialize normalizer."""
        # Build country lookup
        self._country_lookup: dict[str, str] = {}
        for code, aliases in COUNTRY_ALIASES.items():
            self._country_lookup[code] = code
            for alias in aliases:
                self._country_lookup[alias.lower()] = code

    def normalize(self, address: str, country: str | None = None) -> NormalizedAddress:
        """Normalize an address.

        Args:
            address: Original address string.
            country: Optional country hint.

        Returns:
            NormalizedAddress with parsed components.
        """
        if not address:
            return NormalizedAddress(original="", normalized="")

        original = address.strip()

        # Normalize whitespace
        normalized = " ".join(original.split())

        # Try to parse components
        country_code = None
        country_name = None
        region = None
        city = None
        postal_code = None
        street = None

        # Extract country
        if country:
            country_code = self._normalize_country(country)
            country_name = country
        else:
            country_code, country_name = self._extract_country(normalized)

        # Extract postal code
        postal_code = self._extract_postal_code(normalized, country_code)

        # Extract region (prefecture/state)
        region = self._extract_region(normalized, country_code)

        # Build normalized string
        parts = []
        if street:
            parts.append(street)
        if city:
            parts.append(city)
        if region:
            parts.append(region)
        if postal_code:
            parts.append(postal_code)
        if country_code:
            parts.append(country_code.upper())

        normalized_str = ", ".join(parts) if parts else normalized

        return NormalizedAddress(
            original=original,
            normalized=normalized_str,
            country_code=country_code,
            country_name=country_name,
            region=region,
            city=city,
            postal_code=postal_code,
            street=street,
        )

    def _normalize_country(self, country: str) -> str | None:
        """Normalize country to ISO 3166-1 alpha-2 code.

        Args:
            country: Country name or code.

        Returns:
            ISO country code or None.
        """
        if not country:
            return None

        country_lower = country.lower().strip()

        # Direct lookup
        if country_lower in self._country_lookup:
            return self._country_lookup[country_lower]

        # Check if it's already a 2-letter code
        if len(country_lower) == 2 and country_lower.isalpha():
            return country_lower

        return None

    def _extract_country(self, address: str) -> tuple[str | None, str | None]:
        """Extract country from address string.

        Args:
            address: Address string.

        Returns:
            Tuple of (country_code, country_name).
        """
        address_lower = address.lower()

        for code, aliases in COUNTRY_ALIASES.items():
            for alias in aliases:
                if alias in address_lower:
                    return (code, alias)

        return (None, None)

    def _extract_postal_code(self, address: str, country_code: str | None) -> str | None:
        """Extract postal code from address.

        Args:
            address: Address string.
            country_code: Country code for format hints.

        Returns:
            Postal code or None.
        """
        patterns = [
            # Japanese: 〒123-4567 or 123-4567
            r"〒?(\d{3}-?\d{4})",
            # US: 12345 or 12345-6789
            r"\b(\d{5}(?:-\d{4})?)\b",
            # UK: SW1A 1AA
            r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
            # Generic numeric
            r"\b(\d{4,6})\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, address, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_region(self, address: str, country_code: str | None) -> str | None:
        """Extract region (state/prefecture) from address.

        Args:
            address: Address string.
            country_code: Country code.

        Returns:
            Region name or None.
        """
        if country_code == "jp":
            # Check for Japanese prefectures
            for jp_name, en_name in JP_PREFECTURES.items():
                if jp_name in address:
                    return en_name

        return None


# =============================================================================
# Identifier Normalizer
# =============================================================================


class IdentifierNormalizer:
    """Normalizes various identifiers."""

    def normalize_domain(self, domain: str) -> str:
        """Normalize a domain name.

        Args:
            domain: Domain name.

        Returns:
            Normalized domain (lowercase, no trailing dot).
        """
        if not domain:
            return ""

        result = domain.lower().strip()
        result = result.rstrip(".")

        # Remove protocol if present
        if "://" in result:
            result = result.split("://", 1)[1]

        # Remove path if present
        result = result.split("/")[0]

        # Remove port if present
        result = result.split(":")[0]

        return result

    def normalize_email(self, email: str) -> str:
        """Normalize an email address.

        Args:
            email: Email address.

        Returns:
            Normalized email (lowercase).
        """
        if not email:
            return ""

        result = email.lower().strip()

        # Basic validation
        if "@" not in result:
            return result

        local, domain = result.rsplit("@", 1)
        domain = self.normalize_domain(domain)

        return f"{local}@{domain}"

    def normalize_phone(self, phone: str, country_code: str | None = None) -> str:
        """Normalize a phone number.

        Args:
            phone: Phone number.
            country_code: Country code for formatting.

        Returns:
            Normalized phone number (digits only with country code).
        """
        if not phone:
            return ""

        # Extract digits only
        digits = re.sub(r"[^\d+]", "", phone)

        # Handle leading +
        if digits.startswith("+"):
            return digits

        # Add country code if known
        if country_code == "jp" and not digits.startswith("81"):
            if digits.startswith("0"):
                digits = "81" + digits[1:]
            else:
                digits = "81" + digits
            return "+" + digits

        return digits

    def normalize_ip(self, ip: str) -> str:
        """Normalize an IP address.

        Args:
            ip: IP address.

        Returns:
            Normalized IP address.
        """
        if not ip:
            return ""

        result = ip.strip()

        # For IPv4, remove leading zeros
        if "." in result and ":" not in result:
            parts = result.split(".")
            try:
                parts = [str(int(p)) for p in parts]
                return ".".join(parts)
            except ValueError:
                pass

        # For IPv6, lowercase
        return result.lower()


# =============================================================================
# Entity Knowledge Base
# =============================================================================


class EntityKB:
    """Entity Knowledge Base manager.

    Stores and retrieves normalized entities with deduplication
    and identity estimation.
    """

    def __init__(self, db: Any = None):
        """Initialize Entity KB.

        Args:
            db: Database instance (from src.storage.database).
        """
        self._db = db
        self._name_normalizer = NameNormalizer()
        self._address_normalizer = AddressNormalizer()
        self._identifier_normalizer = IdentifierNormalizer()

        # In-memory cache for frequent lookups
        self._entity_cache: dict[str, EntityRecord] = {}
        self._alias_index: dict[str, list[str]] = {}  # normalized_alias -> [entity_ids]
        self._identifier_index: dict[str, list[str]] = {}  # normalized_id -> [entity_ids]

    async def initialize_schema(self) -> None:
        """Initialize database schema for entity KB."""
        if self._db is None:
            logger.warning("No database connection for EntityKB")
            return

        # Execute each SQL statement individually to support both
        # standard Database class and aiosqlite's single-statement limitation
        statements = [
            # Entities: Core entity records
            """CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                normalized_name_json TEXT,
                normalized_address_json TEXT,
                confidence REAL DEFAULT 0.5,
                source_type TEXT,
                source_url TEXT,
                extra_data_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)",
            "CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_name)",
            # Entity aliases
            """CREATE TABLE IF NOT EXISTS entity_aliases (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                alias_text TEXT NOT NULL,
                alias_normalized TEXT NOT NULL,
                alias_type TEXT NOT NULL,
                language TEXT,
                confidence REAL DEFAULT 0.5,
                source_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_aliases_entity ON entity_aliases(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_aliases_normalized ON entity_aliases(alias_normalized)",
            # Entity identifiers
            """CREATE TABLE IF NOT EXISTS entity_identifiers (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL,
                identifier_normalized TEXT NOT NULL,
                is_primary BOOLEAN DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                source_type TEXT,
                valid_from DATETIME,
                valid_until DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_identifiers_entity ON entity_identifiers(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_identifiers_normalized ON entity_identifiers(identifier_normalized)",
            "CREATE INDEX IF NOT EXISTS idx_identifiers_type ON entity_identifiers(identifier_type)",
            # Entity relationships
            """CREATE TABLE IF NOT EXISTS entity_relationships (
                id TEXT PRIMARY KEY,
                source_entity_id TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                source_type TEXT,
                evidence_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_entity_id) REFERENCES entities(id),
                FOREIGN KEY (target_entity_id) REFERENCES entities(id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_relationships_source ON entity_relationships(source_entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_relationships_target ON entity_relationships(target_entity_id)",
            # FTS for entity search
            """CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                canonical_name,
                display_name,
                content='entities',
                content_rowid='rowid'
            )""",
        ]

        for sql in statements:
            await self._db.execute(sql)

        logger.info("EntityKB schema initialized")

    async def add_entity(
        self,
        name: str,
        entity_type: EntityType,
        *,
        address: str | None = None,
        country: str | None = None,
        source_type: SourceType = SourceType.MANUAL,
        source_url: str | None = None,
        confidence: float = 0.5,
        identifiers: list[tuple[IdentifierType, str]] | None = None,
        aliases: list[str] | None = None,
        extra_data: dict[str, Any] | None = None,
        deduplicate: bool = True,
    ) -> EntityRecord:
        """Add or update an entity in the KB.

        Args:
            name: Entity name.
            entity_type: Type of entity.
            address: Optional address.
            country: Optional country.
            source_type: Source of information.
            source_url: URL where entity was found.
            confidence: Confidence score.
            identifiers: List of (type, value) identifier tuples.
            aliases: List of alias names.
            extra_data: Additional data to store.
            deduplicate: Whether to check for existing entity.

        Returns:
            EntityRecord (new or existing).
        """
        # Normalize name
        normalized_name = self._name_normalizer.normalize(name, entity_type)

        # Normalize address if provided
        normalized_address = None
        if address:
            normalized_address = self._address_normalizer.normalize(address, country)

        # Check for existing entity if deduplication enabled
        if deduplicate:
            matches = await self.find_entity(
                name=name,
                entity_type=entity_type,
                identifiers=identifiers,
                threshold=0.9,
            )

            if matches:
                # Update existing entity if new info has higher confidence
                existing = matches[0].entity
                if confidence > existing.confidence:
                    await self._update_entity(
                        existing, normalized_name, normalized_address, confidence
                    )

                # Add new identifiers/aliases
                if identifiers:
                    for id_type, id_value in identifiers:
                        await self._add_identifier(existing.id, id_type, id_value, source_type)

                if aliases:
                    for alias in aliases:
                        await self._add_alias(existing.id, alias, source_type)

                return existing

        # Create new entity
        entity_id = str(uuid.uuid4())
        entity = EntityRecord(
            id=entity_id,
            entity_type=entity_type,
            canonical_name=normalized_name.canonical,
            display_name=normalized_name.original,
            normalized_name=normalized_name,
            normalized_address=normalized_address,
            confidence=confidence,
            source_type=source_type,
            source_url=source_url,
            extra_data=extra_data or {},
        )

        # Save to database
        if self._db:
            await self._db.insert(
                "entities",
                {
                    "id": entity_id,
                    "entity_type": entity_type.value,
                    "canonical_name": normalized_name.canonical,
                    "display_name": normalized_name.original,
                    "normalized_name_json": json.dumps(normalized_name.to_dict()),
                    "normalized_address_json": json.dumps(normalized_address.to_dict())
                    if normalized_address
                    else None,
                    "confidence": confidence,
                    "source_type": source_type.value,
                    "source_url": source_url,
                    "extra_data_json": json.dumps(extra_data) if extra_data else None,
                },
                auto_id=False,
            )

        # Cache
        self._entity_cache[entity_id] = entity

        # Add identifiers
        if identifiers:
            for id_type, id_value in identifiers:
                await self._add_identifier(entity_id, id_type, id_value, source_type)

        # Add aliases
        if aliases:
            for alias in aliases:
                await self._add_alias(entity_id, alias, source_type)

        logger.info(f"Added entity: {entity.display_name} ({entity_type.value})")
        return entity

    async def find_entity(
        self,
        name: str | None = None,
        entity_type: EntityType | None = None,
        identifiers: list[tuple[IdentifierType, str]] | None = None,
        threshold: float = 0.7,
        limit: int = 10,
    ) -> list[EntityMatch]:
        """Find entities matching the given criteria.

        Args:
            name: Name to search for.
            entity_type: Type filter.
            identifiers: Identifiers to match.
            threshold: Minimum similarity threshold.
            limit: Maximum results.

        Returns:
            List of EntityMatch results.
        """
        matches: list[EntityMatch] = []

        # Search by identifiers first (most reliable)
        if identifiers:
            for id_type, id_value in identifiers:
                normalized_id = self._normalize_identifier(id_type, id_value)

                if self._db:
                    rows = await self._db.fetch_all(
                        """
                        SELECT entity_id FROM entity_identifiers
                        WHERE identifier_normalized = ? AND identifier_type = ?
                        """,
                        (normalized_id, id_type.value),
                    )

                    for row in rows:
                        entity = await self._get_entity(row["entity_id"])
                        if entity:
                            matches.append(
                                EntityMatch(
                                    entity=entity,
                                    match_score=1.0,
                                    match_type="identifier",
                                    matched_value=id_value,
                                )
                            )

        # Search by name
        if name:
            normalized_name = self._name_normalizer.normalize(
                name,
                entity_type or EntityType.ORGANIZATION,
            )

            # Exact canonical match
            if self._db:
                type_filter = f"AND entity_type = '{entity_type.value}'" if entity_type else ""
                rows = await self._db.fetch_all(
                    f"""
                    SELECT * FROM entities
                    WHERE canonical_name = ? {type_filter}
                    LIMIT ?
                    """,
                    (normalized_name.canonical, limit),
                )

                for row in rows:
                    entity = self._row_to_entity(row)
                    if entity and not any(m.entity.id == entity.id for m in matches):
                        matches.append(
                            EntityMatch(
                                entity=entity,
                                match_score=1.0,
                                match_type="canonical",
                                matched_value=name,
                            )
                        )

            # Alias search
            if self._db:
                rows = await self._db.fetch_all(
                    """
                    SELECT entity_id, alias_text FROM entity_aliases
                    WHERE alias_normalized = ?
                    LIMIT ?
                    """,
                    (normalized_name.canonical, limit),
                )

                for row in rows:
                    entity = await self._get_entity(row["entity_id"])
                    if entity and not any(m.entity.id == entity.id for m in matches):
                        if entity_type is None or entity.entity_type == entity_type:
                            matches.append(
                                EntityMatch(
                                    entity=entity,
                                    match_score=0.95,
                                    match_type="alias",
                                    matched_value=row["alias_text"],
                                )
                            )

            # Fuzzy match on remaining candidates
            if len(matches) < limit and self._db:
                type_filter = f"AND entity_type = '{entity_type.value}'" if entity_type else ""
                rows = await self._db.fetch_all(
                    f"""
                    SELECT * FROM entities
                    WHERE canonical_name LIKE ? {type_filter}
                    LIMIT ?
                    """,
                    (f"%{normalized_name.tokens[0] if normalized_name.tokens else ''}%", limit * 2),
                )

                for row in rows:
                    entity = self._row_to_entity(row)
                    if entity and not any(m.entity.id == entity.id for m in matches):
                        if entity.normalized_name:
                            similarity = self._name_normalizer.compute_similarity(
                                normalized_name,
                                entity.normalized_name,
                            )
                            if similarity >= threshold:
                                matches.append(
                                    EntityMatch(
                                        entity=entity,
                                        match_score=similarity,
                                        match_type="fuzzy",
                                        matched_value=name,
                                    )
                                )

        # Sort by score and limit
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:limit]

    async def get_entity(self, entity_id: str) -> EntityRecord | None:
        """Get entity by ID.

        Args:
            entity_id: Entity ID.

        Returns:
            EntityRecord or None.
        """
        return await self._get_entity(entity_id)

    async def get_entity_identifiers(self, entity_id: str) -> list[EntityIdentifier]:
        """Get all identifiers for an entity.

        Args:
            entity_id: Entity ID.

        Returns:
            List of EntityIdentifier.
        """
        if not self._db:
            return []

        rows = await self._db.fetch_all(
            "SELECT * FROM entity_identifiers WHERE entity_id = ?",
            (entity_id,),
        )

        return [self._row_to_identifier(row) for row in rows]

    async def get_entity_aliases(self, entity_id: str) -> list[EntityAlias]:
        """Get all aliases for an entity.

        Args:
            entity_id: Entity ID.

        Returns:
            List of EntityAlias.
        """
        if not self._db:
            return []

        rows = await self._db.fetch_all(
            "SELECT * FROM entity_aliases WHERE entity_id = ?",
            (entity_id,),
        )

        return [self._row_to_alias(row) for row in rows]

    async def add_relationship(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: str,
        confidence: float = 0.5,
        source_type: SourceType = SourceType.MANUAL,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        """Add a relationship between entities.

        Args:
            source_entity_id: Source entity ID.
            target_entity_id: Target entity ID.
            relationship_type: Type of relationship.
            confidence: Confidence score.
            source_type: Source of information.
            evidence: Evidence for the relationship.

        Returns:
            Relationship ID.
        """
        rel_id = str(uuid.uuid4())

        if self._db:
            await self._db.insert(
                "entity_relationships",
                {
                    "id": rel_id,
                    "source_entity_id": source_entity_id,
                    "target_entity_id": target_entity_id,
                    "relationship_type": relationship_type,
                    "confidence": confidence,
                    "source_type": source_type.value,
                    "evidence_json": json.dumps(evidence) if evidence else None,
                },
                auto_id=False,
            )

        return rel_id

    async def get_related_entities(
        self,
        entity_id: str,
        relationship_type: str | None = None,
    ) -> list[tuple[EntityRecord, str, float]]:
        """Get entities related to the given entity.

        Args:
            entity_id: Entity ID.
            relationship_type: Optional filter by relationship type.

        Returns:
            List of (entity, relationship_type, confidence) tuples.
        """
        if not self._db:
            return []

        type_filter = "AND relationship_type = ?" if relationship_type else ""
        params = [entity_id]
        if relationship_type:
            params.append(relationship_type)

        rows = await self._db.fetch_all(
            f"""
            SELECT target_entity_id, relationship_type, confidence
            FROM entity_relationships
            WHERE source_entity_id = ? {type_filter}
            """,
            tuple(params),
        )

        results = []
        for row in rows:
            entity = await self._get_entity(row["target_entity_id"])
            if entity:
                results.append((entity, row["relationship_type"], row["confidence"]))

        return results

    # =========================================================================
    # Private Methods
    # =========================================================================

    async def _get_entity(self, entity_id: str) -> EntityRecord | None:
        """Get entity by ID from cache or database."""
        # Check cache
        if entity_id in self._entity_cache:
            return self._entity_cache[entity_id]

        if not self._db:
            return None

        row = await self._db.fetch_one(
            "SELECT * FROM entities WHERE id = ?",
            (entity_id,),
        )

        if row:
            entity = self._row_to_entity(row)
            if entity:
                self._entity_cache[entity_id] = entity
            return entity

        return None

    def _row_to_entity(self, row: dict[str, Any]) -> EntityRecord | None:
        """Convert database row to EntityRecord."""
        try:
            normalized_name = None
            if row.get("normalized_name_json"):
                name_data = json.loads(row["normalized_name_json"])
                normalized_name = NormalizedName(**name_data)

            normalized_address = None
            if row.get("normalized_address_json"):
                addr_data = json.loads(row["normalized_address_json"])
                normalized_address = NormalizedAddress(**addr_data)

            extra_data = {}
            if row.get("extra_data_json"):
                extra_data = json.loads(row["extra_data_json"])

            return EntityRecord(
                id=row["id"],
                entity_type=EntityType(row["entity_type"]),
                canonical_name=row["canonical_name"],
                display_name=row["display_name"],
                normalized_name=normalized_name,
                normalized_address=normalized_address,
                confidence=row.get("confidence", 0.5),
                source_type=SourceType(row["source_type"])
                if row.get("source_type")
                else SourceType.MANUAL,
                source_url=row.get("source_url"),
                extra_data=extra_data,
            )
        except Exception as e:
            logger.warning(f"Failed to parse entity row: {e}")
            return None

    def _row_to_identifier(self, row: dict[str, Any]) -> EntityIdentifier:
        """Convert database row to EntityIdentifier."""
        return EntityIdentifier(
            id=row["id"],
            entity_id=row["entity_id"],
            identifier_type=IdentifierType(row["identifier_type"]),
            identifier_value=row["identifier_value"],
            identifier_normalized=row["identifier_normalized"],
            is_primary=bool(row.get("is_primary", False)),
            confidence=row.get("confidence", 0.5),
            source_type=SourceType(row["source_type"])
            if row.get("source_type")
            else SourceType.MANUAL,
        )

    def _row_to_alias(self, row: dict[str, Any]) -> EntityAlias:
        """Convert database row to EntityAlias."""
        return EntityAlias(
            id=row["id"],
            entity_id=row["entity_id"],
            alias_text=row["alias_text"],
            alias_normalized=row["alias_normalized"],
            alias_type=row["alias_type"],
            language=row.get("language"),
            confidence=row.get("confidence", 0.5),
            source_type=SourceType(row["source_type"])
            if row.get("source_type")
            else SourceType.MANUAL,
        )

    async def _add_identifier(
        self,
        entity_id: str,
        id_type: IdentifierType,
        id_value: str,
        source_type: SourceType,
    ) -> str:
        """Add an identifier to an entity."""
        normalized = self._normalize_identifier(id_type, id_value)

        # Check if already exists
        if self._db:
            existing = await self._db.fetch_one(
                """
                SELECT id FROM entity_identifiers
                WHERE entity_id = ? AND identifier_normalized = ?
                """,
                (entity_id, normalized),
            )

            if existing:
                return existing["id"]

        identifier_id = str(uuid.uuid4())

        if self._db:
            await self._db.insert(
                "entity_identifiers",
                {
                    "id": identifier_id,
                    "entity_id": entity_id,
                    "identifier_type": id_type.value,
                    "identifier_value": id_value,
                    "identifier_normalized": normalized,
                    "source_type": source_type.value,
                },
                auto_id=False,
            )

        # Update index
        if normalized not in self._identifier_index:
            self._identifier_index[normalized] = []
        if entity_id not in self._identifier_index[normalized]:
            self._identifier_index[normalized].append(entity_id)

        return identifier_id

    async def _add_alias(
        self,
        entity_id: str,
        alias: str,
        source_type: SourceType,
    ) -> str:
        """Add an alias to an entity."""
        normalized = self._name_normalizer.normalize(alias).canonical

        # Check if already exists
        if self._db:
            existing = await self._db.fetch_one(
                """
                SELECT id FROM entity_aliases
                WHERE entity_id = ? AND alias_normalized = ?
                """,
                (entity_id, normalized),
            )

            if existing:
                return existing["id"]

        alias_id = str(uuid.uuid4())

        if self._db:
            await self._db.insert(
                "entity_aliases",
                {
                    "id": alias_id,
                    "entity_id": entity_id,
                    "alias_text": alias,
                    "alias_normalized": normalized,
                    "alias_type": "name",
                    "source_type": source_type.value,
                },
                auto_id=False,
            )

        # Update index
        if normalized not in self._alias_index:
            self._alias_index[normalized] = []
        if entity_id not in self._alias_index[normalized]:
            self._alias_index[normalized].append(entity_id)

        return alias_id

    async def _update_entity(
        self,
        entity: EntityRecord,
        normalized_name: NormalizedName,
        normalized_address: NormalizedAddress | None,
        confidence: float,
    ) -> None:
        """Update an existing entity with new information."""
        if self._db:
            update_data = {
                "confidence": confidence,
                "updated_at": datetime.now(UTC).isoformat(),
            }

            if normalized_address and not entity.normalized_address:
                update_data["normalized_address_json"] = json.dumps(normalized_address.to_dict())

            await self._db.update(
                "entities",
                update_data,
                "id = ?",
                (entity.id,),
            )

        # Update cache
        entity.confidence = confidence
        if normalized_address and not entity.normalized_address:
            entity.normalized_address = normalized_address

    def _normalize_identifier(self, id_type: IdentifierType, value: str) -> str:
        """Normalize an identifier value."""
        if id_type == IdentifierType.DOMAIN:
            return self._identifier_normalizer.normalize_domain(value)
        elif id_type == IdentifierType.EMAIL:
            return self._identifier_normalizer.normalize_email(value)
        elif id_type == IdentifierType.PHONE:
            return self._identifier_normalizer.normalize_phone(value)
        elif id_type == IdentifierType.IP_ADDRESS:
            return self._identifier_normalizer.normalize_ip(value)
        else:
            return value.lower().strip()


# =============================================================================
# Factory Function
# =============================================================================


async def get_entity_kb(db: Any = None) -> EntityKB:
    """Get EntityKB instance.

    Args:
        db: Database instance.

    Returns:
        Initialized EntityKB.
    """
    kb = EntityKB(db)
    if db:
        await kb.initialize_schema()
    return kb
