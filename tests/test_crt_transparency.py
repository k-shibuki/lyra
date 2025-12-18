"""
Tests for Certificate Transparency client.

Tests §3.1.2: crt.sh integration via HTML scraping.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CI-01 | CertificateInfo serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-CI-02 | Current certificate validity | Equivalence – valid dates | is_valid=True | - |
| TC-CI-03 | Expired certificate | Boundary – past not_after | is_valid=False | - |
| TC-CI-04 | Future certificate | Boundary – future not_before | is_valid=False | - |
| TC-CI-05 | Wildcard detection | Equivalence – pattern | is_wildcard=True for *.domain | - |
| TC-CTP-01 | Parse HTML table | Equivalence – parsing | Certificates extracted | - |
| TC-CTP-02 | Parse empty HTML | Boundary – no data | Empty result list | - |
| TC-CTP-03 | Parse malformed HTML | Abnormal – bad format | Handles gracefully | - |
| TC-CTC-01 | Search by domain | Equivalence – search | CertSearchResult with certs | - |
| TC-CTC-02 | Search with cache hit | Equivalence – caching | Returns cached result | - |
| TC-CTC-03 | Search without fetcher | Boundary – no fetcher | Returns None | - |
| TC-CTC-04 | Search API error | Abnormal – fetch error | Returns None | - |
| TC-CSR-01 | CertSearchResult serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-CTL-01 | CertTimeline creation | Equivalence – timeline | Certs grouped by issuer | - |
| TC-CTL-02 | CertTimeline with single cert | Boundary – single | Valid timeline | - |
| TC-CTL-03 | CertTimeline overlapping certs | Equivalence – overlap | Correct overlap detection | - |
| TC-GF-01 | get_cert_transparency_client | Equivalence – factory | Returns client instance | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.crawler.crt_transparency import (
    CertTransparencyParser,
    CertTransparencyClient,
    CertificateInfo,
    CertSearchResult,
    CertTimeline,
    get_cert_transparency_client,
)


class TestCertificateInfo:
    """Tests for CertificateInfo data class."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        # Given: CertificateInfo with all fields
        cert = CertificateInfo(
            cert_id="123456",
            common_name="example.com",
            issuer_name="Let's Encrypt Authority X3",
            issuer_org="Let's Encrypt",
            not_before=datetime(2024, 1, 1, tzinfo=timezone.utc),
            not_after=datetime(2024, 4, 1, tzinfo=timezone.utc),
            san_dns=["example.com", "www.example.com"],
        )

        # When: Serializing to dict
        d = cert.to_dict()

        # Then: Dictionary with all fields
        assert d["cert_id"] == "123456"
        assert d["common_name"] == "example.com"
        assert d["issuer_org"] == "Let's Encrypt"
        assert len(d["san_dns"]) == 2
        assert "2024" in d["not_before"]

    def test_is_valid_current(self):
        """Test validity check for current certificate."""
        # Given: Certificate with current validity period
        now = datetime.now(timezone.utc)
        cert = CertificateInfo(
            cert_id="1",
            common_name="test.com",
            issuer_name="Test CA",
            not_before=now - timedelta(days=30),
            not_after=now + timedelta(days=30),
        )

        # When/Then: is_valid=True
        assert cert.is_valid

    def test_is_valid_expired(self):
        """Test validity check for expired certificate."""
        # Given: Certificate with past not_after
        now = datetime.now(timezone.utc)
        cert = CertificateInfo(
            cert_id="1",
            common_name="test.com",
            issuer_name="Test CA",
            not_before=now - timedelta(days=60),
            not_after=now - timedelta(days=30),
        )

        # When/Then: is_valid=False
        assert not cert.is_valid

    def test_is_valid_not_yet_valid(self):
        """Test validity check for future certificate."""
        # Given: Certificate with future not_before
        now = datetime.now(timezone.utc)
        cert = CertificateInfo(
            cert_id="1",
            common_name="test.com",
            issuer_name="Test CA",
            not_before=now + timedelta(days=30),
            not_after=now + timedelta(days=60),
        )

        # When/Then: is_valid=False
        assert not cert.is_valid

    def test_is_wildcard(self):
        """Test wildcard certificate detection."""
        # Given: Wildcard certificate
        cert = CertificateInfo(
            cert_id="1",
            common_name="*.example.com",
            issuer_name="Test CA",
        )
        # When/Then: is_wildcard=True
        assert cert.is_wildcard

        # Given: Non-wildcard certificate
        cert = CertificateInfo(
            cert_id="2",
            common_name="www.example.com",
            issuer_name="Test CA",
        )
        assert not cert.is_wildcard

    def test_get_all_domains(self):
        """Test getting all domains from cert."""
        cert = CertificateInfo(
            cert_id="1",
            common_name="example.com",
            issuer_name="Test CA",
            san_dns=["www.example.com", "api.example.com", "EXAMPLE.COM"],
        )

        domains = cert.get_all_domains()

        assert "example.com" in domains
        assert "www.example.com" in domains
        assert "api.example.com" in domains
        # Should be deduplicated
        assert len([d for d in domains if d == "example.com"]) == 1


class TestCertSearchResult:
    """Tests for CertSearchResult data class."""

    def test_to_dict(self):
        """Test serialization."""
        result = CertSearchResult(
            query_domain="example.com",
            certificates=[
                CertificateInfo(
                    cert_id="1",
                    common_name="example.com",
                    issuer_name="Test CA",
                ),
            ],
            discovered_domains=["sub.example.net"],
            discovered_issuers=["Test CA"],
        )

        d = result.to_dict()

        assert d["query_domain"] == "example.com"
        assert len(d["certificates"]) == 1
        assert "sub.example.net" in d["discovered_domains"]


class TestCertTimeline:
    """Tests for CertTimeline data class."""

    def test_add_entry(self):
        """Test adding timeline entries."""
        timeline = CertTimeline(domain="example.com")

        timeline.add_entry(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            "issued",
            "Certificate issued by Let's Encrypt",
        )
        timeline.add_entry(
            datetime(2023, 6, 1, tzinfo=timezone.utc),
            "issued",
            "Previous certificate",
        )

        # Entries should be sorted chronologically
        assert len(timeline.entries) == 2
        assert timeline.entries[0][0].year == 2023  # Earlier first
        assert timeline.entries[1][0].year == 2024

    def test_to_dict(self):
        """Test serialization."""
        timeline = CertTimeline(domain="example.com")
        timeline.add_entry(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            "issued",
            "Test cert",
        )

        d = timeline.to_dict()

        assert d["domain"] == "example.com"
        assert len(d["entries"]) == 1
        assert d["entries"][0]["action"] == "issued"


class TestCertTransparencyParser:
    """Tests for crt.sh HTML parser."""

    def test_parse_search_results(self):
        """Test parsing crt.sh search results table."""
        parser = CertTransparencyParser()

        html = """
        <html>
        <body>
        <table>
            <tr><th>crt.sh ID</th><th>Logged At</th><th>Not Before</th><th>Not After</th><th>Common Name</th><th>Matching Identities</th><th>Issuer Name</th></tr>
            <tr>
                <td>123456</td>
                <td>2024-01-15</td>
                <td>2024-01-01</td>
                <td>2024-04-01</td>
                <td>example.com</td>
                <td>example.com, www.example.com</td>
                <td>C=US, O=Let's Encrypt, CN=R3</td>
            </tr>
            <tr>
                <td>123457</td>
                <td>2023-10-01</td>
                <td>2023-10-01</td>
                <td>2024-01-01</td>
                <td>*.example.com</td>
                <td>*.example.com</td>
                <td>C=US, O=DigiCert Inc, CN=DigiCert</td>
            </tr>
        </table>
        </body>
        </html>
        """

        result = parser.parse_search_results("example.com", html)

        assert result.query_domain == "example.com"
        assert len(result.certificates) == 2

        cert1 = result.certificates[0]
        assert cert1.cert_id == "123456"
        assert cert1.common_name == "example.com"
        assert "www.example.com" in cert1.san_dns

    def test_parse_search_results_empty(self):
        """Test parsing empty results."""
        parser = CertTransparencyParser()

        html = """
        <html>
        <body>
        <p>No certificates found</p>
        </body>
        </html>
        """

        result = parser.parse_search_results("nonexistent.com", html)

        assert result.query_domain == "nonexistent.com"
        assert len(result.certificates) == 0

    def test_parse_cert_detail(self):
        """Test parsing certificate detail page."""
        parser = CertTransparencyParser()

        html = """
        <html>
        <body>
        <pre>
Certificate:
    Data:
        Subject: CN = example.com
        Issuer: C = US, O = Let's Encrypt, CN = R3
        Validity
            Not Before: Jan  1 00:00:00 2024 GMT
            Not After : Apr  1 00:00:00 2024 GMT
        X509v3 extensions:
            X509v3 Subject Alternative Name:
                DNS:example.com, DNS:www.example.com, DNS:api.example.com
        </pre>
        </body>
        </html>
        """

        cert = parser.parse_cert_detail(html, "123456")

        assert cert is not None
        assert cert.cert_id == "123456"
        assert cert.common_name == "example.com"
        assert len(cert.san_dns) == 3
        assert "api.example.com" in cert.san_dns

    def test_parse_sans(self):
        """Test parsing Subject Alternative Names."""
        parser = CertTransparencyParser()

        # Standard format
        sans = parser._parse_sans("DNS:example.com, DNS:www.example.com")
        assert "example.com" in sans
        assert "www.example.com" in sans

        # Plain domains
        sans = parser._parse_sans("example.com\nwww.example.com")
        assert "example.com" in sans

        # Ignore IP addresses
        sans = parser._parse_sans("DNS:example.com, IP:192.168.1.1")
        assert "example.com" in sans
        assert "192.168.1.1" not in sans

    def test_extract_org_from_issuer(self):
        """Test extracting organization from issuer string."""
        parser = CertTransparencyParser()

        assert parser._extract_org_from_issuer(
            "C=US, O=Let's Encrypt, CN=R3"
        ) == "Let's Encrypt"

        assert parser._extract_org_from_issuer(
            "DigiCert SHA2 Secure Server CA"
        ) == "DigiCert Inc"

        assert parser._extract_org_from_issuer(
            "Unknown Issuer"
        ) is None

    def test_aggregate_discoveries(self):
        """Test aggregating discovered entities from certs."""
        parser = CertTransparencyParser()

        result = CertSearchResult(
            query_domain="example.com",
            certificates=[
                CertificateInfo(
                    cert_id="1",
                    common_name="example.com",
                    issuer_name="Let's Encrypt R3",
                    issuer_org="Let's Encrypt",
                    san_dns=["example.com", "other-domain.net"],
                    not_before=datetime(2024, 1, 1, tzinfo=timezone.utc),
                ),
                CertificateInfo(
                    cert_id="2",
                    common_name="*.example.com",
                    issuer_name="DigiCert",
                    issuer_org="DigiCert Inc",
                    san_dns=["*.example.com", "third-party.org"],
                    not_before=datetime(2023, 6, 1, tzinfo=timezone.utc),
                    not_after=datetime(2024, 6, 1, tzinfo=timezone.utc),
                ),
            ],
        )

        parser._aggregate_discoveries(result)

        # Discovered domains should not include query domain
        assert "example.com" not in result.discovered_domains
        # But should include other domains
        assert "other-domain.net" in result.discovered_domains
        assert "third-party.org" in result.discovered_domains

        # Issuers should be tracked (from fixture data)
        assert "Let's Encrypt" in result.discovered_issuers, (
            f"Expected 'Let\\'s Encrypt' in issuers: {result.discovered_issuers}"
        )

        # Timeline
        assert result.earliest_cert is not None
        assert result.earliest_cert.year == 2023


class TestCertTransparencyClient:
    """Tests for CertTransparencyClient."""

    @pytest.fixture
    def mock_fetcher(self):
        """Create mock fetcher."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_search_success(self, mock_fetcher, tmp_path):
        """Test successful certificate search."""
        html_path = tmp_path / "crt.html"
        html_path.write_text("""
        <table>
            <tr><th>ID</th><th>Logged</th><th>Not Before</th><th>Not After</th><th>CN</th><th>SANs</th><th>Issuer</th></tr>
            <tr>
                <td>12345</td>
                <td>2024-01-01</td>
                <td>2024-01-01</td>
                <td>2024-04-01</td>
                <td>example.com</td>
                <td>example.com</td>
                <td>R3</td>
            </tr>
        </table>
        """)

        result = MagicMock()
        result.ok = True
        result.html_path = str(html_path)
        mock_fetcher.fetch = AsyncMock(return_value=result)

        client = CertTransparencyClient(fetcher=mock_fetcher)
        search_result = await client.search("example.com")

        assert search_result is not None
        assert search_result.query_domain == "example.com"
        assert len(search_result.certificates) == 1

    @pytest.mark.asyncio
    async def test_search_cache(self, mock_fetcher, tmp_path):
        """Test that results are cached."""
        html_path = tmp_path / "crt.html"
        html_path.write_text("""
        <table>
            <tr><th>ID</th><th>Logged</th><th>Not Before</th><th>Not After</th><th>CN</th><th>SANs</th><th>Issuer</th></tr>
            <tr><td>1</td><td>2024-01-01</td><td>2024-01-01</td><td>2024-04-01</td><td>cached.com</td><td>cached.com</td><td>CA</td></tr>
        </table>
        """)

        result = MagicMock()
        result.ok = True
        result.html_path = str(html_path)
        mock_fetcher.fetch = AsyncMock(return_value=result)

        client = CertTransparencyClient(fetcher=mock_fetcher)

        result1 = await client.search("cached.com")
        result2 = await client.search("cached.com")

        assert result1 is result2
        assert mock_fetcher.fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_search_no_fetcher(self):
        """Test search without fetcher returns None."""
        client = CertTransparencyClient(fetcher=None)
        result = await client.search("example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_discover_related_domains(self, mock_fetcher, tmp_path):
        """Test discovering related domains."""
        html_path = tmp_path / "crt.html"
        html_path.write_text("""
        <table>
            <tr><th>ID</th><th>Logged</th><th>Not Before</th><th>Not After</th><th>CN</th><th>SANs</th><th>Issuer</th></tr>
            <tr>
                <td>1</td>
                <td>2024-01-01</td>
                <td>2024-01-01</td>
                <td>2024-04-01</td>
                <td>example.com</td>
                <td>example.com, related.net, another.org</td>
                <td>CA</td>
            </tr>
        </table>
        """)

        result = MagicMock()
        result.ok = True
        result.html_path = str(html_path)
        mock_fetcher.fetch = AsyncMock(return_value=result)

        client = CertTransparencyClient(fetcher=mock_fetcher)
        domains = await client.discover_related_domains("example.com")

        assert "related.net" in domains
        assert "another.org" in domains
        assert "example.com" not in domains  # Should not include query domain

    @pytest.mark.asyncio
    async def test_build_timeline(self, mock_fetcher, tmp_path):
        """Test building certificate timeline."""
        html_path = tmp_path / "crt.html"
        html_path.write_text("""
        <table>
            <tr><th>ID</th><th>Logged</th><th>Not Before</th><th>Not After</th><th>CN</th><th>SANs</th><th>Issuer</th></tr>
            <tr>
                <td>2</td>
                <td>2024-01-01</td>
                <td>2024-01-01</td>
                <td>2024-04-01</td>
                <td>example.com</td>
                <td>example.com</td>
                <td>Let's Encrypt</td>
            </tr>
            <tr>
                <td>1</td>
                <td>2023-06-01</td>
                <td>2023-06-01</td>
                <td>2023-09-01</td>
                <td>example.com</td>
                <td>example.com</td>
                <td>DigiCert</td>
            </tr>
        </table>
        """)

        result = MagicMock()
        result.ok = True
        result.html_path = str(html_path)
        mock_fetcher.fetch = AsyncMock(return_value=result)

        client = CertTransparencyClient(fetcher=mock_fetcher)
        timeline = await client.build_timeline("example.com")

        assert timeline.domain == "example.com"
        assert len(timeline.entries) >= 2  # At least issued events


class TestGetCertTransparencyClient:
    """Tests for client factory function."""

    def test_get_client_with_fetcher(self):
        """Test getting client with fetcher."""
        mock_fetcher = MagicMock()
        client = get_cert_transparency_client(mock_fetcher)

        assert client is not None
        assert client._fetcher is mock_fetcher

    def test_get_client_without_fetcher(self):
        """Test getting client without fetcher."""
        client = get_cert_transparency_client()

        assert client is not None
        assert client._fetcher is None



