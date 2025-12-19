"""
RDAP and WHOIS client for Lancet.

Retrieves domain registration information via HTML scraping (no API).
Implements §3.1.2, §3.1.3:
- RDAP/WHOIS public web interfaces (IANA, regional NICs)
- Registrant, nameserver, registration/update history extraction
- Entity normalization for KB integration

References:
- §3.1.2: Infrastructure/Registry Direct Access (HTML only)
- §3.1.3: OSINT Vertical Templates
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import tldextract
from bs4 import BeautifulSoup

from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# RDAP web interfaces (no API, HTML scraping)
RDAP_WEB_ENDPOINTS = {
    # Regional Internet Registries (RIRs)
    "arin": "https://rdap.arin.net/registry/domain/{domain}",  # North America
    "ripe": "https://rdap.db.ripe.net/domain/{domain}",  # Europe, Middle East
    "apnic": "https://rdap.apnic.net/domain/{domain}",  # Asia Pacific
    "lacnic": "https://rdap.lacnic.net/rdap/domain/{domain}",  # Latin America
    "afrinic": "https://rdap.afrinic.net/rdap/domain/{domain}",  # Africa
    # IANA
    "iana": "https://www.iana.org/whois?q={domain}",
}

# WHOIS web interfaces (fallback)
WHOIS_WEB_ENDPOINTS = {
    "jp": "https://whois.jprs.jp/en/whois?key={domain}",  # .jp domains
    "com": "https://lookup.icann.org/en/lookup?name={domain}",  # ICANN lookup
    "generic": "https://www.whois.com/whois/{domain}",  # Generic fallback
}

# TLD to RIR mapping (simplified)
TLD_TO_RIR = {
    "jp": "jprs",
    "cn": "cnnic",
    "kr": "krnic",
    "au": "apnic",
    "eu": "ripe",
    "uk": "ripe",
    "de": "ripe",
    "fr": "ripe",
    "us": "arin",
    "ca": "arin",
    "br": "lacnic",
    "za": "afrinic",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class RegistrantInfo:
    """Domain registrant information."""

    name: str | None = None
    organization: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "organization": self.organization,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "country": self.country,
            "state": self.state,
            "city": self.city,
        }

    def is_empty(self) -> bool:
        """Check if all fields are empty."""
        return all(v is None for v in [
            self.name, self.organization, self.email,
            self.phone, self.address, self.country,
        ])


@dataclass
class NameserverInfo:
    """Nameserver information."""

    hostname: str
    ip_addresses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hostname": self.hostname,
            "ip_addresses": self.ip_addresses,
        }


@dataclass
class WHOISRecord:
    """Complete WHOIS/RDAP record for a domain."""

    domain: str
    registrar: str | None = None
    registrant: RegistrantInfo | None = None

    # Dates
    created_date: datetime | None = None
    updated_date: datetime | None = None
    expiry_date: datetime | None = None

    # Technical info
    nameservers: list[NameserverInfo] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    dnssec: bool = False

    # Source tracking
    source_url: str | None = None
    source_type: str = "unknown"  # rdap, whois-web, whois-cli
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Raw data for debugging
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "registrar": self.registrar,
            "registrant": self.registrant.to_dict() if self.registrant else None,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "updated_date": self.updated_date.isoformat() if self.updated_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "nameservers": [ns.to_dict() for ns in self.nameservers],
            "status": self.status,
            "dnssec": self.dnssec,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "fetched_at": self.fetched_at.isoformat(),
        }

    def get_registrant_org(self) -> str | None:
        """Get registrant organization or name."""
        if self.registrant:
            return self.registrant.organization or self.registrant.name
        return None


# =============================================================================
# WHOIS Parser
# =============================================================================

class WHOISParser:
    """Parser for WHOIS/RDAP HTML and text responses."""

    # Common date patterns
    DATE_PATTERNS = [
        r"(\d{4}-\d{2}-\d{2})",  # ISO format: 2024-01-15
        r"(\d{2}-[A-Za-z]{3}-\d{4})",  # 15-Jan-2024
        r"(\d{4}/\d{2}/\d{2})",  # 2024/01/15
        r"(\d{2}/\d{2}/\d{4})",  # 01/15/2024
        r"(\d{4}\.\d{2}\.\d{2})",  # 2024.01.15
    ]

    # Field name patterns (case-insensitive)
    FIELD_PATTERNS = {
        "registrar": [
            r"registrar[:\s]+(.+)",
            r"sponsoring\s+registrar[:\s]+(.+)",
            r"reg(?:istered)?\s+by[:\s]+(.+)",
        ],
        "registrant_name": [
            r"registrant\s+name[:\s]+(.+)",
            r"registrant[:\s]+(.+)",
            r"holder[:\s]+(.+)",
        ],
        "registrant_org": [
            r"registrant\s+organi[sz]ation[:\s]+(.+)",
            r"registrant\s+org[:\s]+(.+)",
            r"organi[sz]ation[:\s]+(.+)",
            r"org(?:anization)?\s+name[:\s]+(.+)",
        ],
        "registrant_email": [
            r"registrant\s+email[:\s]+(.+)",
            r"registrant\s+contact\s+email[:\s]+(.+)",
        ],
        "registrant_country": [
            r"registrant\s+country[:\s]+(.+)",
            r"registrant\s+country\s+code[:\s]+(.+)",
        ],
        "created": [
            r"creat(?:ed?|ion)\s+date[:\s]+(.+)",
            r"registered\s+(?:on|date)[:\s]+(.+)",
            r"registration\s+date[:\s]+(.+)",
            r"\[登録年月日\][:\s]*(.+)",  # Japanese
            r"\[Created on\][:\s]*(.+)",
        ],
        "updated": [
            r"updated?\s+date[:\s]+(.+)",
            r"last\s+(?:updated?|modified)[:\s]+(.+)",
            r"modification\s+date[:\s]+(.+)",
            r"\[最終更新\][:\s]*(.+)",  # Japanese
        ],
        "expiry": [
            r"expir(?:y|ation|es)\s+date[:\s]+(.+)",
            r"expires\s+on[:\s]+(.+)",
            r"registry\s+expiry\s+date[:\s]+(.+)",
            r"paid-till[:\s]+(.+)",
            r"\[有効期限\][:\s]*(.+)",  # Japanese
        ],
        "nameserver": [
            r"name\s*server[:\s]+(.+)",
            r"ns\d*[:\s]+(.+)",
            r"nserver[:\s]+(.+)",
            r"\[ネームサーバ\][:\s]*(\S+)",  # Japanese JPRS format
        ],
        "status": [
            r"domain\s+status[:\s]+(.+)",
            r"status[:\s]+(.+)",
            r"state[:\s]+(.+)",
        ],
        "dnssec": [
            r"dnssec[:\s]+(.+)",
            r"ds\s+records?[:\s]+(.+)",
        ],
    }

    def __init__(self):
        """Initialize parser."""
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns."""
        for field, patterns in self.FIELD_PATTERNS.items():
            self._compiled_patterns[field] = [
                re.compile(p, re.IGNORECASE | re.MULTILINE)
                for p in patterns
            ]

    def parse_text(self, domain: str, text: str, source_url: str = "") -> WHOISRecord:
        """Parse WHOIS text response.
        
        Args:
            domain: Domain name being queried.
            text: Raw WHOIS text response.
            source_url: URL where data was fetched.
            
        Returns:
            Parsed WHOISRecord.
        """
        record = WHOISRecord(
            domain=domain,
            source_url=source_url,
            source_type="whois-text",
            raw_text=text[:5000],  # Limit stored raw text
        )

        # Parse each field
        record.registrar = self._extract_field(text, "registrar")

        # Registrant info
        registrant = RegistrantInfo()
        registrant.name = self._extract_field(text, "registrant_name")
        registrant.organization = self._extract_field(text, "registrant_org")
        registrant.email = self._extract_field(text, "registrant_email")
        registrant.country = self._extract_field(text, "registrant_country")

        if not registrant.is_empty():
            record.registrant = registrant

        # Dates
        record.created_date = self._parse_date(self._extract_field(text, "created"))
        record.updated_date = self._parse_date(self._extract_field(text, "updated"))
        record.expiry_date = self._parse_date(self._extract_field(text, "expiry"))

        # Nameservers - multiple patterns for different formats
        ns_patterns = [
            r"name\s*server[:\s]+(\S+)",
            r"\[ネームサーバ\][:\s]*(\S+)",  # Japanese JPRS format
            r"nserver[:\s]+(\S+)",
        ]
        for pattern in ns_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ns = match.group(1).strip().rstrip(".")
                if ns and "." in ns:
                    # Avoid duplicates
                    if not any(existing.hostname == ns.lower() for existing in record.nameservers):
                        record.nameservers.append(NameserverInfo(hostname=ns.lower()))

        # Status
        for match in re.finditer(r"(?:domain\s+)?status[:\s]+(\S+)", text, re.IGNORECASE):
            status = match.group(1).strip()
            if status and status not in record.status:
                record.status.append(status)

        # DNSSEC
        dnssec_value = self._extract_field(text, "dnssec")
        if dnssec_value:
            record.dnssec = dnssec_value.lower() in ("signed", "yes", "true", "active")

        return record

    def parse_html(self, domain: str, html: str, source_url: str = "") -> WHOISRecord:
        """Parse WHOIS/RDAP HTML response.
        
        Args:
            domain: Domain name being queried.
            html: HTML response.
            source_url: URL where data was fetched.
            
        Returns:
            Parsed WHOISRecord.
        """
        soup = BeautifulSoup(html, "html.parser")

        # First, try to extract text from common WHOIS containers
        whois_text = ""

        # Common container selectors
        containers = [
            soup.select_one(".whois-data"),
            soup.select_one("#whois-data"),
            soup.select_one(".whois-result"),
            soup.select_one("#whois-result"),
            soup.select_one("pre"),  # Many WHOIS displays use <pre>
            soup.select_one(".domain-info"),
            soup.select_one("#domain-info"),
        ]

        for container in containers:
            if container:
                whois_text = container.get_text(separator="\n", strip=True)
                break

        if not whois_text:
            # Fallback: get all text
            whois_text = soup.get_text(separator="\n", strip=True)

        # Parse extracted text
        record = self.parse_text(domain, whois_text, source_url)
        record.source_type = "whois-html"

        # Try to extract structured data from tables
        self._parse_tables(soup, record)

        # Parse RDAP-specific JSON-LD if present
        self._parse_rdap_json(soup, record)

        return record

    def _parse_tables(self, soup: BeautifulSoup, record: WHOISRecord) -> None:
        """Extract data from HTML tables.
        
        Args:
            soup: BeautifulSoup object.
            record: WHOISRecord to update.
        """
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)

                    # Map common table fields
                    if "registrar" in key and not record.registrar:
                        record.registrar = value
                    elif "registrant" in key and "org" in key:
                        if not record.registrant:
                            record.registrant = RegistrantInfo()
                        record.registrant.organization = value
                    elif "name server" in key or "nameserver" in key:
                        if value and "." in value:
                            record.nameservers.append(
                                NameserverInfo(hostname=value.lower())
                            )

    def _parse_rdap_json(self, soup: BeautifulSoup, record: WHOISRecord) -> None:
        """Parse RDAP JSON-LD data if present.
        
        Args:
            soup: BeautifulSoup object.
            record: WHOISRecord to update.
        """
        import json

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Extract RDAP fields
                    if "ldhName" in data:
                        record.domain = data["ldhName"]
                    if "events" in data:
                        for event in data["events"]:
                            action = event.get("eventAction", "")
                            date_str = event.get("eventDate", "")
                            dt = self._parse_date(date_str)
                            if dt:
                                if action == "registration":
                                    record.created_date = dt
                                elif action == "last changed":
                                    record.updated_date = dt
                                elif action == "expiration":
                                    record.expiry_date = dt
            except (json.JSONDecodeError, AttributeError):
                continue

    def _extract_field(self, text: str, field: str) -> str | None:
        """Extract a field value from text.
        
        Args:
            text: Text to search.
            field: Field name to extract.
            
        Returns:
            Extracted value or None.
        """
        patterns = self._compiled_patterns.get(field, [])
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                # Clean common artifacts
                value = re.sub(r"\s+", " ", value)
                value = value.rstrip(".")
                if value and value.lower() not in ("not disclosed", "redacted", "n/a", "none"):
                    return value
        return None

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Parse date string to datetime.
        
        Args:
            date_str: Date string to parse.
            
        Returns:
            Parsed datetime or None.
        """
        if not date_str:
            return None

        # Try ISO format first
        try:
            # Handle ISO 8601 with timezone
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            pass

        # Try common patterns
        formats = [
            "%Y-%m-%d",
            "%d-%b-%Y",
            "%Y/%m/%d",
            "%m/%d/%Y",
            "%Y.%m.%d",
            "%d %b %Y",
            "%B %d, %Y",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y年%m月%d日",  # Japanese
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:20], fmt)
                return dt.replace(tzinfo=UTC)
            except ValueError:
                continue

        return None


# =============================================================================
# RDAP/WHOIS Client
# =============================================================================

class RDAPClient:
    """Client for fetching domain registration via RDAP/WHOIS web interfaces.
    
    Implements HTML scraping only (no API per §4.1).
    Follows rate limiting and domain policies per §4.3.
    """

    def __init__(
        self,
        fetcher: Any = None,  # HTTPFetcher or BrowserFetcher
        parser: WHOISParser | None = None,
    ):
        """Initialize RDAP client.
        
        Args:
            fetcher: URL fetcher to use.
            parser: WHOIS parser instance.
        """
        self._fetcher = fetcher
        self._parser = parser or WHOISParser()
        self._settings = get_settings()

        # Cache to avoid repeated lookups
        self._cache: dict[str, WHOISRecord] = {}
        self._cache_ttl = 86400  # 24 hours

    async def lookup(
        self,
        domain: str,
        trace: CausalTrace | None = None,
        use_cache: bool = True,
    ) -> WHOISRecord | None:
        """Look up WHOIS/RDAP record for a domain.
        
        Tries multiple sources in order:
        1. TLD-specific endpoint (e.g., JPRS for .jp)
        2. ICANN lookup
        3. Generic WHOIS web interface
        
        Args:
            domain: Domain name to look up.
            trace: Causal trace for logging.
            use_cache: Whether to use cached results.
            
        Returns:
            WHOISRecord or None if lookup fails.
        """
        # Normalize domain
        ext = tldextract.extract(domain)
        domain = f"{ext.domain}.{ext.suffix}".lower()

        # Check cache
        if use_cache and domain in self._cache:
            logger.debug(f"WHOIS cache hit for {domain}")
            return self._cache[domain]

        trace = trace or CausalTrace()

        # Determine endpoints to try
        endpoints = self._get_endpoints_for_domain(domain, ext.suffix)

        for endpoint_name, url_template in endpoints:
            url = url_template.format(domain=quote(domain, safe=""))

            logger.info(f"Trying WHOIS lookup via {endpoint_name}: {url}")

            try:
                result = await self._fetch_and_parse(domain, url, trace)
                if result:
                    self._cache[domain] = result
                    return result
            except Exception as e:
                logger.warning(f"WHOIS lookup failed via {endpoint_name}: {e}")
                continue

        logger.warning(f"All WHOIS lookups failed for {domain}")
        return None

    def _get_endpoints_for_domain(
        self,
        domain: str,
        tld: str,
    ) -> list[tuple[str, str]]:
        """Get ordered list of endpoints to try for a domain.
        
        Args:
            domain: Domain name.
            tld: Top-level domain.
            
        Returns:
            List of (endpoint_name, url_template) tuples.
        """
        endpoints = []

        # TLD-specific endpoint
        if tld in WHOIS_WEB_ENDPOINTS:
            endpoints.append((f"whois-{tld}", WHOIS_WEB_ENDPOINTS[tld]))

        # RIR mapping
        rir = TLD_TO_RIR.get(tld)
        if rir and rir in RDAP_WEB_ENDPOINTS:
            endpoints.append((f"rdap-{rir}", RDAP_WEB_ENDPOINTS[rir]))

        # ICANN lookup (generic)
        endpoints.append(("icann", WHOIS_WEB_ENDPOINTS["com"]))

        # Generic fallback
        endpoints.append(("whois-generic", WHOIS_WEB_ENDPOINTS["generic"]))

        return endpoints

    async def _fetch_and_parse(
        self,
        domain: str,
        url: str,
        trace: CausalTrace,
    ) -> WHOISRecord | None:
        """Fetch URL and parse WHOIS response.
        
        Args:
            domain: Domain being looked up.
            url: WHOIS lookup URL.
            trace: Causal trace.
            
        Returns:
            Parsed WHOISRecord or None.
        """
        if self._fetcher is None:
            logger.error("No fetcher available for RDAP lookup")
            return None

        # Fetch the page
        result = await self._fetcher.fetch(url, trace=trace)

        if not result.ok:
            logger.warning(f"Failed to fetch WHOIS page: {result.reason}")
            return None

        # Read content
        content = ""
        if result.html_path:
            try:
                with open(result.html_path, encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read WHOIS response: {e}")
                return None

        if not content:
            return None

        # Parse response
        record = self._parser.parse_html(domain, content, url)

        # Validate: at least some data should be extracted
        if not record.registrar and not record.registrant and not record.nameservers:
            logger.debug(f"WHOIS parsing yielded no data from {url}")
            return None

        return record

    async def lookup_batch(
        self,
        domains: list[str],
        max_concurrent: int = 2,
        trace: CausalTrace | None = None,
    ) -> dict[str, WHOISRecord | None]:
        """Look up WHOIS records for multiple domains.
        
        Args:
            domains: List of domains to look up.
            max_concurrent: Maximum concurrent lookups.
            trace: Causal trace.
            
        Returns:
            Dictionary mapping domain to WHOISRecord or None.
        """
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def lookup_one(domain: str) -> tuple[str, WHOISRecord | None]:
            async with semaphore:
                result = await self.lookup(domain, trace)
                # Rate limit between requests
                await asyncio.sleep(1.0)
                return (domain, result)

        tasks = [lookup_one(d) for d in domains]
        for future in asyncio.as_completed(tasks):
            domain, record = await future
            results[domain] = record

        return results


# =============================================================================
# Helper Functions
# =============================================================================

def normalize_domain(url_or_domain: str) -> str:
    """Normalize URL or domain string to base domain.
    
    Args:
        url_or_domain: URL or domain string.
        
    Returns:
        Normalized base domain (e.g., example.com).
    """
    # Handle URLs
    if "://" in url_or_domain:
        parsed = urlparse(url_or_domain)
        url_or_domain = parsed.netloc or parsed.path

    # Remove port
    url_or_domain = url_or_domain.split(":")[0]

    # Extract domain
    ext = tldextract.extract(url_or_domain)
    return f"{ext.domain}.{ext.suffix}".lower()


def get_rdap_client(fetcher: Any = None) -> RDAPClient:
    """Get RDAP client instance.
    
    Args:
        fetcher: URL fetcher to use.
        
    Returns:
        RDAPClient instance.
    """
    return RDAPClient(fetcher=fetcher)

