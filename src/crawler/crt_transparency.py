"""
Certificate Transparency client for Lyra.

Retrieves certificate information from crt.sh via HTML scraping (no API).
Implements §3.1.2:
- SAN (Subject Alternative Names) extraction
- Issuer information
- Issue date timeline
- Related domain discovery

References:
- §3.1.2: Infrastructure/Registry Direct Access (HTML only)
- §3.1.1: Pivot Exploration (domain → certificate → organization)
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import tldextract
from bs4 import BeautifulSoup

from src.utils.config import get_settings
from src.utils.logging import CausalTrace, get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# crt.sh HTML endpoint (no API per §4.1)
CRT_SH_BASE = "https://crt.sh"
CRT_SH_SEARCH = f"{CRT_SH_BASE}/?q={{domain}}"
CRT_SH_CERT = f"{CRT_SH_BASE}/?id={{cert_id}}"

# Budget: limit cert lookups per task
MAX_CERTS_PER_DOMAIN = 20
MAX_DOMAINS_DISCOVERED = 50


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CertificateInfo:
    """Information about a single certificate."""

    cert_id: str
    common_name: str
    issuer_name: str
    issuer_org: str | None = None

    # Validity
    not_before: datetime | None = None
    not_after: datetime | None = None

    # Subject Alternative Names
    san_dns: list[str] = field(default_factory=list)
    san_ip: list[str] = field(default_factory=list)

    # Source tracking
    source_url: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cert_id": self.cert_id,
            "common_name": self.common_name,
            "issuer_name": self.issuer_name,
            "issuer_org": self.issuer_org,
            "not_before": self.not_before.isoformat() if self.not_before else None,
            "not_after": self.not_after.isoformat() if self.not_after else None,
            "san_dns": self.san_dns,
            "san_ip": self.san_ip,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
        }

    @property
    def is_valid(self) -> bool:
        """Check if certificate is currently valid."""
        now = datetime.now(UTC)
        if self.not_before and now < self.not_before:
            return False
        if self.not_after and now > self.not_after:
            return False
        return True

    @property
    def is_wildcard(self) -> bool:
        """Check if certificate is a wildcard certificate."""
        return self.common_name.startswith("*.")

    def get_all_domains(self) -> list[str]:
        """Get all domains from CN and SANs.

        Returns:
            Deduplicated list of all domains.
        """
        domains = set()

        # Add common name (if it's a domain)
        if self.common_name and "." in self.common_name:
            domains.add(self.common_name.lower())

        # Add SANs
        for san in self.san_dns:
            domains.add(san.lower())

        return sorted(domains)


@dataclass
class CertSearchResult:
    """Result of certificate transparency search."""

    query_domain: str
    certificates: list[CertificateInfo] = field(default_factory=list)

    # Discovered entities
    discovered_domains: list[str] = field(default_factory=list)
    discovered_orgs: list[str] = field(default_factory=list)
    discovered_issuers: list[str] = field(default_factory=list)

    # Timeline
    earliest_cert: datetime | None = None
    latest_cert: datetime | None = None

    # Source tracking
    source_url: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_domain": self.query_domain,
            "certificates": [c.to_dict() for c in self.certificates],
            "discovered_domains": self.discovered_domains,
            "discovered_orgs": self.discovered_orgs,
            "discovered_issuers": self.discovered_issuers,
            "earliest_cert": self.earliest_cert.isoformat() if self.earliest_cert else None,
            "latest_cert": self.latest_cert.isoformat() if self.latest_cert else None,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass
class CertTimeline:
    """Timeline of certificate issuance for a domain."""

    domain: str
    entries: list[tuple[datetime, str, str]] = field(default_factory=list)
    # (date, action, description)

    def add_entry(
        self,
        date: datetime,
        action: str,
        description: str,
    ) -> None:
        """Add a timeline entry.

        Args:
            date: Event date.
            action: Action type (issued, expired, renewed).
            description: Event description.
        """
        self.entries.append((date, action, description))
        self.entries.sort(key=lambda x: x[0])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "entries": [
                {
                    "date": e[0].isoformat(),
                    "action": e[1],
                    "description": e[2],
                }
                for e in self.entries
            ],
        }


# =============================================================================
# Certificate Transparency Parser
# =============================================================================


class CertTransparencyParser:
    """Parser for crt.sh HTML responses."""

    # Date patterns
    DATE_PATTERNS = [
        r"(\d{4}-\d{2}-\d{2})",  # ISO format
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",  # ISO with time
    ]

    def parse_search_results(
        self,
        domain: str,
        html: str,
        source_url: str = "",
    ) -> CertSearchResult:
        """Parse crt.sh search results page.

        Args:
            domain: Domain being searched.
            html: HTML response from crt.sh.
            source_url: Source URL.

        Returns:
            CertSearchResult with parsed certificates.
        """
        result = CertSearchResult(
            query_domain=domain,
            source_url=source_url,
        )

        soup = BeautifulSoup(html, "html.parser")

        # Find the results table
        table = soup.find("table")
        if not table:
            logger.debug(f"No certificate table found for {domain}")
            return result

        # Skip header row
        rows = table.find_all("tr")[1:]

        seen_certs = set()

        for row in rows[:MAX_CERTS_PER_DOMAIN]:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            try:
                # Parse row data
                # Columns: crt.sh ID, Logged At, Not Before, Not After, Common Name, Matching Identities, Issuer Name
                cert_id = cells[0].get_text(strip=True)

                # Skip duplicates
                if cert_id in seen_certs:
                    continue
                seen_certs.add(cert_id)

                # Parse dates
                not_before = self._parse_date(cells[2].get_text(strip=True))
                not_after = self._parse_date(cells[3].get_text(strip=True))

                # Get common name
                common_name = cells[4].get_text(strip=True)

                # Get matching identities (SANs)
                san_text = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                san_dns = self._parse_sans(san_text)

                # Get issuer name
                issuer_name = cells[6].get_text(strip=True) if len(cells) > 6 else ""
                issuer_org = self._extract_org_from_issuer(issuer_name)

                cert = CertificateInfo(
                    cert_id=cert_id,
                    common_name=common_name,
                    issuer_name=issuer_name,
                    issuer_org=issuer_org,
                    not_before=not_before,
                    not_after=not_after,
                    san_dns=san_dns,
                    source_url=f"{CRT_SH_BASE}/?id={cert_id}",
                )

                result.certificates.append(cert)

            except Exception as e:
                logger.debug(f"Failed to parse certificate row: {e}")
                continue

        # Aggregate discovered entities
        self._aggregate_discoveries(result)

        return result

    def parse_cert_detail(
        self,
        html: str,
        cert_id: str,
    ) -> CertificateInfo | None:
        """Parse certificate detail page.

        Args:
            html: HTML response from crt.sh certificate page.
            cert_id: Certificate ID.

        Returns:
            CertificateInfo or None if parsing fails.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Find certificate text display
        cert_text = soup.find("pre")
        if not cert_text:
            return None

        text = cert_text.get_text()

        # Extract fields from certificate text
        cert = CertificateInfo(
            cert_id=cert_id,
            common_name="",
            issuer_name="",
            source_url=f"{CRT_SH_BASE}/?id={cert_id}",
        )

        # Extract Common Name
        cn_match = re.search(r"Subject:.*?CN\s*=\s*([^,\n]+)", text)
        if cn_match:
            cert.common_name = cn_match.group(1).strip()

        # Extract Issuer
        issuer_match = re.search(r"Issuer:.*?CN\s*=\s*([^,\n]+)", text)
        if issuer_match:
            cert.issuer_name = issuer_match.group(1).strip()

        # Extract Issuer Org
        issuer_org_match = re.search(r"Issuer:.*?O\s*=\s*([^,\n]+)", text)
        if issuer_org_match:
            cert.issuer_org = issuer_org_match.group(1).strip()

        # Extract validity dates
        not_before_match = re.search(r"Not Before:\s*([^\n]+)", text)
        if not_before_match:
            cert.not_before = self._parse_cert_date(not_before_match.group(1).strip())

        not_after_match = re.search(r"Not After\s*:\s*([^\n]+)", text)
        if not_after_match:
            cert.not_after = self._parse_cert_date(not_after_match.group(1).strip())

        # Extract SANs
        san_match = re.search(
            r"X509v3 Subject Alternative Name:.*?\n\s*(.+?)(?:\n\s*\n|\Z)",
            text,
            re.DOTALL,
        )
        if san_match:
            san_text = san_match.group(1)
            cert.san_dns = self._parse_sans(san_text)

        return cert

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse date string from crt.sh.

        Args:
            date_str: Date string.

        Returns:
            Parsed datetime or None.
        """
        if not date_str:
            return None

        # Try common formats
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%b %d %Y",
            "%b %d %H:%M:%S %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.replace(tzinfo=UTC)
            except ValueError:
                continue

        return None

    def _parse_cert_date(self, date_str: str) -> datetime | None:
        """Parse certificate date format.

        Args:
            date_str: Certificate date string (e.g., "Jan 15 00:00:00 2024 GMT").

        Returns:
            Parsed datetime or None.
        """
        if not date_str:
            return None

        # Remove timezone suffix
        date_str = date_str.replace(" GMT", "").replace(" UTC", "")

        formats = [
            "%b %d %H:%M:%S %Y",
            "%b  %d %H:%M:%S %Y",  # Double space for single-digit day
            "%Y-%m-%d %H:%M:%S",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.replace(tzinfo=UTC)
            except ValueError:
                continue

        return None

    def _parse_sans(self, san_text: str) -> list[str]:
        """Parse Subject Alternative Names from text.

        Args:
            san_text: SAN text field.

        Returns:
            List of DNS names.
        """
        dns_names = []

        # Split by comma or newline
        parts = re.split(r"[,\n]", san_text)

        for part in parts:
            part = part.strip()

            # Extract DNS: prefix
            if part.startswith("DNS:"):
                name = part[4:].strip()
                if name and "." in name:
                    dns_names.append(name.lower())
            # Plain domain
            elif "." in part and not part.startswith("IP:"):
                # Validate it looks like a domain
                if re.match(r"^[\*a-z0-9][\*a-z0-9\.\-]*$", part.lower()):
                    dns_names.append(part.lower())

        return dns_names

    def _extract_org_from_issuer(self, issuer: str) -> str | None:
        """Extract organization from issuer string.

        Args:
            issuer: Issuer string.

        Returns:
            Organization name or None.
        """
        # Try O= pattern
        match = re.search(r"O\s*=\s*([^,]+)", issuer)
        if match:
            return match.group(1).strip()

        # Common issuers
        known_issuers = {
            "Let's Encrypt": "Let's Encrypt",
            "DigiCert": "DigiCert Inc",
            "Comodo": "Comodo CA Limited",
            "GlobalSign": "GlobalSign nv-sa",
            "Sectigo": "Sectigo Limited",
            "GeoTrust": "GeoTrust Inc.",
            "RapidSSL": "RapidSSL",
        }

        for key, org in known_issuers.items():
            if key.lower() in issuer.lower():
                return org

        return None

    def _aggregate_discoveries(self, result: CertSearchResult) -> None:
        """Aggregate discovered entities from certificates.

        Args:
            result: CertSearchResult to update.
        """
        domains: set[str] = set()
        orgs: set[str] = set()
        issuers: set[str] = set()
        earliest = None
        latest = None

        base_ext = tldextract.extract(result.query_domain)
        base_domain = f"{base_ext.domain}.{base_ext.suffix}".lower()

        for cert in result.certificates:
            # Track issuers
            if cert.issuer_org:
                issuers.add(cert.issuer_org)

            # Track timeline
            if cert.not_before:
                if earliest is None or cert.not_before < earliest:
                    earliest = cert.not_before
            if cert.not_after:
                if latest is None or cert.not_after > latest:
                    latest = cert.not_after

            # Discover related domains
            for domain in cert.get_all_domains():
                # Skip the query domain itself
                if domain == result.query_domain:
                    continue

                # Skip wildcards
                if domain.startswith("*."):
                    # Add the base domain instead
                    domain = domain[2:]

                # Check if it's a different base domain
                ext = tldextract.extract(domain)
                this_base = f"{ext.domain}.{ext.suffix}".lower()

                if this_base != base_domain:
                    domains.add(domain)

        # Limit discovered domains
        result.discovered_domains = sorted(domains)[:MAX_DOMAINS_DISCOVERED]
        result.discovered_orgs = sorted(orgs)
        result.discovered_issuers = sorted(issuers)
        result.earliest_cert = earliest
        result.latest_cert = latest


# =============================================================================
# Certificate Transparency Client
# =============================================================================


class CertTransparencyClient:
    """Client for certificate transparency log queries via crt.sh.

    Implements HTML scraping only (no API per §4.1).
    """

    def __init__(
        self,
        fetcher: Any = None,  # HTTPFetcher or BrowserFetcher
        parser: CertTransparencyParser | None = None,
    ):
        """Initialize certificate transparency client.

        Args:
            fetcher: URL fetcher to use.
            parser: Parser instance.
        """
        self._fetcher = fetcher
        self._parser = parser or CertTransparencyParser()
        self._settings = get_settings()

        # Cache to avoid repeated lookups
        self._cache: dict[str, CertSearchResult] = {}
        self._cache_ttl = 86400  # 24 hours

    async def search(
        self,
        domain: str,
        trace: CausalTrace | None = None,
        use_cache: bool = True,
        include_wildcards: bool = True,
    ) -> CertSearchResult | None:
        """Search for certificates for a domain.

        Args:
            domain: Domain to search.
            trace: Causal trace for logging.
            use_cache: Whether to use cached results.
            include_wildcards: Whether to include wildcard matches.

        Returns:
            CertSearchResult or None if search fails.
        """
        # Normalize domain
        ext = tldextract.extract(domain)
        base_domain = f"{ext.domain}.{ext.suffix}".lower()

        # Prepare search query
        if include_wildcards:
            search_query = f"%.{base_domain}"
        else:
            search_query = base_domain

        # Check cache
        cache_key = f"{search_query}:{include_wildcards}"
        if use_cache and cache_key in self._cache:
            logger.debug(f"CT cache hit for {domain}")
            return self._cache[cache_key]

        trace = trace or CausalTrace()

        url = CRT_SH_SEARCH.format(domain=quote(search_query, safe=""))

        logger.info(f"Searching crt.sh for {domain}: {url}")

        try:
            result = await self._fetch_and_parse(base_domain, url, trace)
            if result:
                self._cache[cache_key] = result
                return result
        except Exception as e:
            logger.warning(f"CT search failed for {domain}: {e}")

        return None

    async def get_certificate(
        self,
        cert_id: str,
        trace: CausalTrace | None = None,
    ) -> CertificateInfo | None:
        """Get detailed certificate information.

        Args:
            cert_id: Certificate ID from crt.sh.
            trace: Causal trace.

        Returns:
            CertificateInfo or None.
        """
        trace = trace or CausalTrace()

        url = CRT_SH_CERT.format(cert_id=cert_id)

        if self._fetcher is None:
            logger.error("No fetcher available for CT lookup")
            return None

        result = await self._fetcher.fetch(url, trace=trace)

        if not result.ok:
            logger.warning(f"Failed to fetch certificate {cert_id}")
            return None

        content = ""
        if result.html_path:
            try:
                with open(result.html_path, encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read CT response: {e}")
                return None

        if not content:
            return None

        return self._parser.parse_cert_detail(content, cert_id)

    async def _fetch_and_parse(
        self,
        domain: str,
        url: str,
        trace: CausalTrace,
    ) -> CertSearchResult | None:
        """Fetch URL and parse CT response.

        Args:
            domain: Domain being searched.
            url: crt.sh search URL.
            trace: Causal trace.

        Returns:
            Parsed CertSearchResult or None.
        """
        if self._fetcher is None:
            logger.error("No fetcher available for CT lookup")
            return None

        result = await self._fetcher.fetch(url, trace=trace)

        if not result.ok:
            logger.warning(f"Failed to fetch CT page: {result.reason}")
            return None

        content = ""
        if result.html_path:
            try:
                with open(result.html_path, encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read CT response: {e}")
                return None

        if not content:
            return None

        return self._parser.parse_search_results(domain, content, url)

    async def discover_related_domains(
        self,
        domain: str,
        trace: CausalTrace | None = None,
    ) -> list[str]:
        """Discover domains related via certificate sharing.

        This is useful for Academic Research pivot exploration per §3.1.1.

        Args:
            domain: Domain to start from.
            trace: Causal trace.

        Returns:
            List of related domains.
        """
        result = await self.search(domain, trace=trace, include_wildcards=True)

        if result:
            return result.discovered_domains

        return []

    async def build_timeline(
        self,
        domain: str,
        trace: CausalTrace | None = None,
    ) -> CertTimeline:
        """Build certificate timeline for a domain.

        Args:
            domain: Domain to analyze.
            trace: Causal trace.

        Returns:
            CertTimeline with issuance history.
        """
        timeline = CertTimeline(domain=domain)

        result = await self.search(domain, trace=trace)

        if not result:
            return timeline

        for cert in result.certificates:
            # Add issue event
            if cert.not_before:
                description = f"Certificate issued by {cert.issuer_name}"
                if cert.is_wildcard:
                    description += " (wildcard)"
                timeline.add_entry(cert.not_before, "issued", description)

            # Add expiry event (if past)
            if cert.not_after and cert.not_after < datetime.now(UTC):
                timeline.add_entry(
                    cert.not_after,
                    "expired",
                    f"Certificate expired (issued by {cert.issuer_name})",
                )

        return timeline

    async def search_batch(
        self,
        domains: list[str],
        max_concurrent: int = 2,
        trace: CausalTrace | None = None,
    ) -> dict[str, CertSearchResult | None]:
        """Search certificates for multiple domains.

        Args:
            domains: List of domains to search.
            max_concurrent: Maximum concurrent searches.
            trace: Causal trace.

        Returns:
            Dictionary mapping domain to CertSearchResult or None.
        """
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def search_one(domain: str) -> tuple[str, CertSearchResult | None]:
            async with semaphore:
                result = await self.search(domain, trace)
                # Rate limit between requests
                await asyncio.sleep(2.0)  # crt.sh can be slow
                return (domain, result)

        tasks = [search_one(d) for d in domains]
        for future in asyncio.as_completed(tasks):
            domain, result = await future
            results[domain] = result

        return results


# =============================================================================
# Helper Functions
# =============================================================================


def get_cert_transparency_client(fetcher: Any = None) -> CertTransparencyClient:
    """Get certificate transparency client instance.

    Args:
        fetcher: URL fetcher to use.

    Returns:
        CertTransparencyClient instance.
    """
    return CertTransparencyClient(fetcher=fetcher)
