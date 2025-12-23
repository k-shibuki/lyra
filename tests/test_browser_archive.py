"""
Tests for browser archive functionality (ADR-0006).

Tests CDXJ metadata generation and simplified HAR creation
for browser-fetched pages.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-SURT-N-01 | Simple URL | Equivalence – normal | SURT formatted | Basic conversion |
| TC-SURT-N-02 | URL with subdomain | Equivalence – normal | Domain reversed | Subdomain handling |
| TC-SURT-N-03 | URL with query | Equivalence – normal | Query preserved | Query handling |
| TC-SURT-N-04 | Deep subdomain | Equivalence – normal | All parts reversed | Multi-level |
| TC-SURT-N-05 | Root path URL | Equivalence – normal | Trailing slash | Root handling |
| TC-RI-N-01 | All fields set | Equivalence – normal | ResourceInfo created | Construction |
| TC-RI-N-02 | Timing data present | Equivalence – normal | Duration calculated | Duration calc |
| TC-RI-B-01 | No end_time | Boundary – NULL | Duration is None | Incomplete |
| TC-RI-N-03 | Default values | Equivalence – normal | Defaults applied | Defaults |
| TC-CDXJ-N-01 | Complete entry | Equivalence – normal | CDXJ line format | Line format |
| TC-CDXJ-N-02 | Extra metadata | Equivalence – normal | Extra in JSON | Metadata |
| TC-NEC-N-01 | Start collection | Equivalence – normal | URL set, empty list | Init |
| TC-NEC-N-02 | Request event | Equivalence – normal | Resource recorded | Request |
| TC-NEC-N-03 | Response event | Equivalence – normal | Status/MIME set | Response |
| TC-NEC-N-04 | Request finished | Equivalence – normal | Size/end_time set | Finished |
| TC-NEC-N-05 | Add content hash | Equivalence – normal | Hash computed | Hashing |
| TC-NEC-N-06 | Filter main resources | Equivalence – normal | Images excluded | Filtering |
| TC-HAR-N-01 | Empty HAR | Equivalence – normal | Valid structure | Empty HAR |
| TC-HAR-N-02 | Add resource | Equivalence – normal | Entry added | Add resource |
| TC-HAR-N-03 | JSON output | Equivalence – normal | Valid JSON | Serialization |
| TC-HAR-N-04 | Multiple resources | Equivalence – normal | All entries | Multiple |
| TC-CDXJG-N-01 | Resource with content | Equivalence – normal | Hash in entry | Content hash |
| TC-CDXJG-N-02 | Pre-computed hash | Equivalence – normal | Hash preserved | Existing hash |
| TC-CDXJG-N-03 | Multiple resources | Equivalence – normal | Sorted by SURT | Sorting |
| TC-CDXJG-N-04 | String output | Equivalence – normal | Newline separated | String format |
| TC-BA-N-01 | Save creates CDXJ | Equivalence – normal | CDXJ file exists | CDXJ creation |
| TC-BA-N-02 | Save creates HAR | Equivalence – normal | HAR file exists | HAR creation |
| TC-BA-N-03 | Save with collector | Equivalence – normal | Multiple entries | Collector |
| TC-BA-N-04 | WARC reference | Equivalence – normal | Path in header | WARC ref |
| TC-BA-N-05 | Create collector | Equivalence – normal | Collector returned | Factory |
| TC-INT-N-01 | Get archiver | Equivalence – normal | BrowserArchiver | Singleton |
| TC-INT-N-02 | Full workflow | Equivalence – normal | All files created | Integration |
| TC-EC-N-01 | Invalid URL SURT | Equivalence – normal | No exception | Error handling |
| TC-EC-B-01 | Empty collector | Boundary – empty | Empty lists | Empty |
| TC-EC-N-02 | Response without request | Equivalence – normal | Resource created | Redirect case |
| TC-EC-B-02 | Empty content | Boundary – empty | Still succeeds | Empty content |
| TC-EC-N-03 | No timing data | Equivalence – normal | HAR generated | Missing timing |
"""

import json
import time
from pathlib import Path

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.crawler.browser_archive import (
    BrowserArchiver,
    CDXJEntry,
    CDXJGenerator,
    HARGenerator,
    NetworkEventCollector,
    ResourceInfo,
    get_browser_archiver,
    url_to_surt,
)

# =============================================================================
# SURT Conversion Tests
# =============================================================================


class TestUrlToSurt:
    """Tests for SURT (Sort-friendly URI Reordering Transform) conversion."""

    def test_simple_url(self) -> None:
        """Test basic URL to SURT conversion (TC-SURT-N-01)."""
        # Given: A simple URL
        url = "https://example.com/page"

        # When: Converting to SURT
        surt = url_to_surt(url)

        # Then: Domain should be reversed
        assert "com,example)" in surt
        assert "/page" in surt

    def test_subdomain_url(self) -> None:
        """Test URL with subdomain (TC-SURT-N-02)."""
        # Given: A URL with subdomain
        url = "https://www.example.com/path/to/page"

        # When: Converting to SURT
        surt = url_to_surt(url)

        # Then: Domain parts should be reversed
        assert "com,example,www)" in surt
        assert "/path/to/page" in surt

    def test_url_with_query(self) -> None:
        """Test URL with query string (TC-SURT-N-03)."""
        # Given: A URL with query parameters
        url = "https://example.com/search?q=test&lang=en"

        # When: Converting to SURT
        surt = url_to_surt(url)

        # Then: Query should be preserved
        assert "com,example)" in surt
        assert "?q=test&lang=en" in surt

    def test_deep_subdomain(self) -> None:
        """Test URL with multiple subdomain levels (TC-SURT-N-04)."""
        # Given: A URL with multiple subdomains
        url = "https://api.v2.example.co.jp/endpoint"

        # When: Converting to SURT
        surt = url_to_surt(url)

        # Then: All domain parts should be reversed
        assert "jp,co,example,v2,api)" in surt

    def test_root_path(self) -> None:
        """Test URL with root path (TC-SURT-N-05)."""
        # Given: A URL with root path only
        url = "https://example.com/"

        # When: Converting to SURT
        surt = url_to_surt(url)

        # Then: Should have trailing slash
        assert "com,example)/" in surt


# =============================================================================
# ResourceInfo Tests
# =============================================================================


class TestResourceInfo:
    """Tests for ResourceInfo data class."""

    def test_resource_info_creation(self) -> None:
        """Test creating ResourceInfo with all fields (TC-RI-N-01)."""
        # Given: All field values
        # When: Creating ResourceInfo
        resource = ResourceInfo(
            url="https://example.com/page.html",
            method="GET",
            status=200,
            mime_type="text/html",
            size=1024,
            content_hash="abc123",
            start_time=1000.0,
            end_time=1000.5,
            is_main_frame=True,
        )

        # Then: All fields should be set
        assert resource.url == "https://example.com/page.html"
        assert resource.status == 200
        assert resource.size == 1024
        assert resource.is_main_frame is True

    def test_duration_calculation(self) -> None:
        """Test request duration calculation (TC-RI-N-02)."""
        # Given: ResourceInfo with timing data
        resource = ResourceInfo(
            url="https://example.com/",
            start_time=1000.0,
            end_time=1000.5,
        )

        # When: Getting duration
        duration = resource.duration_ms

        # Then: Duration should be calculated correctly
        assert duration is not None
        assert abs(duration - 500.0) < 0.1

    def test_duration_none_when_incomplete(self) -> None:
        """Test that duration is None for incomplete requests (TC-RI-B-01)."""
        # Given: ResourceInfo without end_time
        resource = ResourceInfo(
            url="https://example.com/",
            start_time=1000.0,
            end_time=None,
        )

        # When: Getting duration
        # Then: Duration should be None (boundary case)
        assert resource.duration_ms is None

    def test_default_values(self) -> None:
        """Test default values for optional fields (TC-RI-N-03)."""
        # Given: Minimal ResourceInfo
        resource = ResourceInfo(url="https://example.com/")

        # When/Then: Defaults should be applied
        assert resource.method == "GET"
        assert resource.status is None
        assert resource.size == 0
        assert resource.is_main_frame is False
        assert resource.from_cache is False


# =============================================================================
# CDXJEntry Tests
# =============================================================================


class TestCDXJEntry:
    """Tests for CDXJ entry creation and formatting."""

    def test_cdxj_line_format(self) -> None:
        """Test CDXJ line format output (TC-CDXJ-N-01)."""
        # Given: A complete CDXJEntry
        entry = CDXJEntry(
            url="https://example.com/page",
            surt="com,example)/page",
            timestamp="20240101120000",
            digest="sha256:abc123",
            mime_type="text/html",
            status=200,
        )

        # When: Converting to CDXJ line
        line = entry.to_cdxj_line()

        # Then: Line should have correct format
        assert line.startswith("com,example)/page 20240101120000")

        json_str = line.split(" ", 2)[2]
        data = json.loads(json_str)

        assert data["url"] == "https://example.com/page"
        assert data["digest"] == "sha256:abc123"
        assert data["mime"] == "text/html"
        assert data["status"] == "200"

    def test_cdxj_with_extra_metadata(self) -> None:
        """Test CDXJ entry with extra metadata (TC-CDXJ-N-02)."""
        # Given: CDXJEntry with extra metadata
        entry = CDXJEntry(
            url="https://example.com/",
            surt="com,example)/",
            timestamp="20240101120000",
            digest="sha256:xyz789",
            extra={"size": 2048, "is_main": True},
        )

        # When: Converting to CDXJ line
        line = entry.to_cdxj_line()
        json_str = line.split(" ", 2)[2]
        data = json.loads(json_str)

        # Then: Extra metadata should be included
        assert data["size"] == 2048
        assert data["is_main"] is True


# =============================================================================
# NetworkEventCollector Tests
# =============================================================================


class TestNetworkEventCollector:
    """Tests for network event collection."""

    def test_start_collection(self) -> None:
        """Test starting event collection (TC-NEC-N-01)."""
        # Given: A new collector
        collector = NetworkEventCollector()

        # When: Starting collection
        collector.start_collection("https://example.com/")

        # Then: State should be initialized
        assert collector._main_frame_url == "https://example.com/"
        assert len(collector.resources) == 0

    def test_on_request(self) -> None:
        """Test recording a request event (TC-NEC-N-02)."""
        # Given: An active collector
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")

        # When: Recording a request
        collector.on_request(
            url="https://example.com/",
            method="GET",
            resource_type="document",
            is_main_frame=True,
        )

        # Then: Resource should be recorded
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].url == "https://example.com/"
        assert resources[0].is_main_frame is True

    def test_on_response(self) -> None:
        """Test recording a response event (TC-NEC-N-03)."""
        # Given: Collector with a request
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        collector.on_request(url="https://example.com/", method="GET")

        # When: Recording a response
        collector.on_response(
            url="https://example.com/",
            status=200,
            headers={"content-type": "text/html"},
            mime_type="text/html",
        )

        # Then: Response data should be added
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].status == 200
        assert resources[0].mime_type == "text/html"

    def test_on_request_finished(self) -> None:
        """Test recording request completion (TC-NEC-N-04)."""
        # Given: Collector with a request
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        collector.on_request(url="https://example.com/", method="GET")

        # When: Recording request finish
        collector.on_request_finished(url="https://example.com/", size=1024)

        # Then: Finish data should be added
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].size == 1024
        assert resources[0].end_time is not None

    def test_add_content_hash(self) -> None:
        """Test adding content hash to resource (TC-NEC-N-05)."""
        # Given: Collector with a request
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        collector.on_request(url="https://example.com/", method="GET")

        # When: Adding content hash
        collector.add_content_hash("https://example.com/", b"test content")

        # Then: Hash should be computed and stored
        resources = collector.resources
        assert resources[0].content_hash is not None

    def test_main_resources_filtering(self) -> None:
        """Test filtering for main resources only (TC-NEC-N-06)."""
        # Given: Collector with various resource types
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")

        # Main document
        collector.on_request(
            url="https://example.com/", resource_type="document", is_main_frame=True
        )
        collector.on_response(
            url="https://example.com/", status=200, headers={}, mime_type="text/html"
        )

        # Script (should be included)
        collector.on_request(url="https://example.com/app.js", resource_type="script")
        collector.on_response(
            url="https://example.com/app.js",
            status=200,
            headers={},
            mime_type="application/javascript",
        )

        # Image (should be filtered out)
        collector.on_request(url="https://example.com/image.png", resource_type="image")
        collector.on_response(
            url="https://example.com/image.png", status=200, headers={}, mime_type="image/png"
        )

        # When: Getting main resources
        all_resources = collector.resources
        main_resources = collector.main_resources

        # Then: Images should be excluded from main resources
        assert len(all_resources) == 3
        assert len(main_resources) == 2

        main_urls = [r.url for r in main_resources]
        assert "https://example.com/" in main_urls
        assert "https://example.com/app.js" in main_urls
        assert "https://example.com/image.png" not in main_urls


# =============================================================================
# HARGenerator Tests
# =============================================================================


class TestHARGenerator:
    """Tests for HAR file generation."""

    def test_empty_har_structure(self) -> None:
        """Test HAR structure with no entries (TC-HAR-N-01)."""
        # Given: A new HAR generator
        har_gen = HARGenerator(
            page_url="https://example.com/",
            page_title="Example Page",
        )

        # When: Generating HAR
        har = har_gen.generate()

        # Then: Should have valid structure
        assert "log" in har
        assert har["log"]["version"] == "1.2"
        assert "creator" in har["log"]
        assert "pages" in har["log"]
        assert len(har["log"]["pages"]) == 1
        assert har["log"]["pages"][0]["title"] == "Example Page"

    def test_add_resource(self) -> None:
        """Test adding a resource to HAR (TC-HAR-N-02)."""
        # Given: A HAR generator
        har_gen = HARGenerator(page_url="https://example.com/")

        resource = ResourceInfo(
            url="https://example.com/",
            method="GET",
            status=200,
            mime_type="text/html",
            size=1024,
            start_time=time.time(),
            end_time=time.time() + 0.5,
        )

        # When: Adding a resource
        har_gen.add_resource(resource)
        har = har_gen.generate()

        # Then: Entry should be added correctly
        assert len(har["log"]["entries"]) == 1
        entry = har["log"]["entries"][0]

        assert entry["request"]["method"] == "GET"
        assert entry["request"]["url"] == "https://example.com/"
        assert entry["response"]["status"] == 200
        assert entry["response"]["content"]["mimeType"] == "text/html"
        assert entry["response"]["content"]["size"] == 1024

    def test_har_json_output(self) -> None:
        """Test HAR JSON string output (TC-HAR-N-03)."""
        # Given: A HAR generator
        har_gen = HARGenerator(page_url="https://example.com/")

        # When: Getting JSON string
        json_str = har_gen.to_json()

        # Then: Should be valid JSON
        parsed = json.loads(json_str)
        assert "log" in parsed

    def test_multiple_resources(self) -> None:
        """Test adding multiple resources to HAR (TC-HAR-N-04)."""
        # Given: A HAR generator
        har_gen = HARGenerator(page_url="https://example.com/")

        resources = [
            ResourceInfo(url="https://example.com/", status=200),
            ResourceInfo(url="https://example.com/style.css", status=200),
            ResourceInfo(url="https://example.com/app.js", status=200),
        ]

        # When: Adding multiple resources
        for resource in resources:
            har_gen.add_resource(resource)

        # Then: All entries should be present
        har = har_gen.generate()
        assert len(har["log"]["entries"]) == 3


# =============================================================================
# CDXJGenerator Tests
# =============================================================================


class TestCDXJGenerator:
    """Tests for CDXJ index generation."""

    def test_add_resource_with_content(self) -> None:
        """Test adding resource with content for hash calculation (TC-CDXJG-N-01)."""
        # Given: A CDXJ generator
        cdxj_gen = CDXJGenerator()

        resource = ResourceInfo(
            url="https://example.com/page.html",
            status=200,
            mime_type="text/html",
            size=1024,
        )

        # When: Adding resource with content
        cdxj_gen.add_resource(resource, b"<html>test content</html>")
        lines = cdxj_gen.generate()

        # Then: Hash should be computed
        assert len(lines) == 1
        assert "sha256:" in lines[0]
        assert "com,example)/page.html" in lines[0]

    def test_add_resource_with_existing_hash(self) -> None:
        """Test adding resource with pre-computed hash (TC-CDXJG-N-02)."""
        # Given: A CDXJ generator
        cdxj_gen = CDXJGenerator()

        resource = ResourceInfo(
            url="https://example.com/",
            status=200,
            content_hash="abc123def456",
        )

        # When: Adding resource with existing hash
        cdxj_gen.add_resource(resource)
        lines = cdxj_gen.generate()

        # Then: Existing hash should be used
        assert len(lines) == 1
        assert "sha256:abc123def456" in lines[0]

    def test_sorted_output(self) -> None:
        """Test that entries are sorted by SURT (TC-CDXJG-N-03)."""
        # Given: A CDXJ generator
        cdxj_gen = CDXJGenerator()

        # When: Adding resources in unsorted order
        cdxj_gen.add_resource(ResourceInfo(url="https://zebra.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://apple.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://mango.com/"))

        lines = cdxj_gen.generate()

        # Then: Should be sorted by SURT
        assert "com,apple)" in lines[0]
        assert "com,mango)" in lines[1]
        assert "com,zebra)" in lines[2]

    def test_to_string(self) -> None:
        """Test CDXJ string output (TC-CDXJG-N-04)."""
        # Given: A CDXJ generator with entries
        cdxj_gen = CDXJGenerator()
        cdxj_gen.add_resource(ResourceInfo(url="https://example.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://test.com/"))

        # When: Getting string output
        output = cdxj_gen.to_string()

        # Then: Should have two lines
        lines = output.strip().split("\n")
        assert len(lines) == 2


# =============================================================================
# BrowserArchiver Tests
# =============================================================================


class TestBrowserArchiver:
    """Tests for browser archive saving."""

    @pytest.fixture
    def temp_archive_dir(self, tmp_path: Path) -> Path:
        """Create a temporary archive directory."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        return archive_dir

    @pytest.fixture
    def archiver(self, temp_archive_dir: Path) -> BrowserArchiver:
        """Create archiver with temp directory."""
        return BrowserArchiver(output_dir=temp_archive_dir)

    @pytest.mark.asyncio
    async def test_save_archive_creates_cdxj(
        self, archiver: BrowserArchiver, temp_archive_dir: Path
    ) -> None:
        """Test that save_archive creates CDXJ file (TC-BA-N-01)."""
        # Given: An archiver and content
        content = b"<html><head><title>Test</title></head><body>Hello</body></html>"

        # When: Saving archive
        result = await archiver.save_archive(
            url="https://example.com/test",
            content=content,
            title="Test Page",
        )

        # Then: CDXJ file should be created
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None

        cdxj_path = Path(result["cdxj_path"])
        assert cdxj_path.exists()

        cdxj_content = cdxj_path.read_text()
        assert "com,example)/test" in cdxj_content
        assert "sha256:" in cdxj_content

    @pytest.mark.asyncio
    async def test_save_archive_creates_har(
        self, archiver: BrowserArchiver, temp_archive_dir: Path
    ) -> None:
        """Test that save_archive creates HAR file (TC-BA-N-02)."""
        # Given: An archiver and content
        content = b"<html><body>Test content</body></html>"

        # When: Saving archive
        result = await archiver.save_archive(
            url="https://example.com/page",
            content=content,
            title="Test",
        )

        # Then: HAR file should be created with valid JSON
        assert result["status"] == "success"
        assert result["har_path"] is not None

        har_path = Path(result["har_path"])
        assert har_path.exists()

        har_content = json.loads(har_path.read_text())
        assert "log" in har_content
        assert har_content["log"]["version"] == "1.2"
        assert len(har_content["log"]["entries"]) >= 1

    @pytest.mark.asyncio
    async def test_save_archive_with_collector(
        self, archiver: BrowserArchiver, temp_archive_dir: Path
    ) -> None:
        """Test saving archive with network event collector (TC-BA-N-03)."""
        # Given: A collector with events
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")

        collector.on_request(
            url="https://example.com/", method="GET", resource_type="document", is_main_frame=True
        )
        collector.on_response(
            url="https://example.com/",
            status=200,
            headers={"content-type": "text/html"},
            mime_type="text/html",
        )
        collector.on_request_finished(url="https://example.com/", size=512)

        collector.on_request(url="https://example.com/app.js", resource_type="script")
        collector.on_response(
            url="https://example.com/app.js",
            status=200,
            headers={},
            mime_type="application/javascript",
        )

        content = b"<html><script src='app.js'></script></html>"

        # When: Saving archive with collector
        result = await archiver.save_archive(
            url="https://example.com/",
            content=content,
            title="Test",
            collector=collector,
        )

        # Then: HAR should contain multiple entries
        assert result["status"] == "success"
        assert result["har_path"] is not None

        har_path = Path(result["har_path"])
        har_content = json.loads(har_path.read_text())
        assert len(har_content["log"]["entries"]) >= 2

    @pytest.mark.asyncio
    async def test_save_archive_adds_warc_reference(
        self, archiver: BrowserArchiver, temp_archive_dir: Path
    ) -> None:
        """Test that WARC path is added to CDXJ header (TC-BA-N-04)."""
        # Given: Content and WARC path
        content = b"<html></html>"
        warc_path = "/path/to/test.warc.gz"

        # When: Saving archive with WARC reference
        result = await archiver.save_archive(
            url="https://example.com/",
            content=content,
            warc_path=warc_path,
        )

        # Then: WARC path should be in CDXJ
        assert result["cdxj_path"] is not None
        cdxj_path = Path(result["cdxj_path"])
        cdxj_content = cdxj_path.read_text()
        assert warc_path in cdxj_content

    def test_create_collector(self, archiver: BrowserArchiver) -> None:
        """Test creating network event collector (TC-BA-N-05)."""
        # Given: An archiver
        # When: Creating collector
        collector = archiver.create_collector()

        # Then: Should return NetworkEventCollector
        assert isinstance(collector, NetworkEventCollector)


# =============================================================================
# Integration Tests
# =============================================================================


class TestBrowserArchiverIntegration:
    """Integration tests for browser archiver."""

    def test_get_browser_archiver(self) -> None:
        """Test getting global archiver instance (TC-INT-N-01)."""
        # Given: No preconditions
        # When: Getting archiver
        archiver = get_browser_archiver()

        # Then: Should return BrowserArchiver
        assert isinstance(archiver, BrowserArchiver)

    @pytest.mark.asyncio
    async def test_full_workflow(self, tmp_path: Path) -> None:
        """Test complete archive workflow (TC-INT-N-02)."""
        # Given: Archive directory and archiver
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archiver = BrowserArchiver(output_dir=archive_dir)

        # Create collector and simulate page load
        collector = archiver.create_collector()
        collector.start_collection("https://example.org/test")

        # Main document
        collector.on_request(
            url="https://example.org/test",
            method="GET",
            resource_type="document",
            is_main_frame=True,
        )
        collector.on_response(
            url="https://example.org/test",
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            mime_type="text/html",
        )
        collector.on_request_finished(url="https://example.org/test", size=2048)

        # CSS file
        collector.on_request(url="https://example.org/style.css", resource_type="stylesheet")
        collector.on_response(
            url="https://example.org/style.css", status=200, headers={}, mime_type="text/css"
        )

        # JS file
        collector.on_request(url="https://example.org/main.js", resource_type="script")
        collector.on_response(
            url="https://example.org/main.js",
            status=200,
            headers={},
            mime_type="application/javascript",
        )

        # Image (should be filtered from main_resources)
        collector.on_request(url="https://example.org/logo.png", resource_type="image")
        collector.on_response(
            url="https://example.org/logo.png", status=200, headers={}, mime_type="image/png"
        )

        content = b"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Page</title>
            <link rel="stylesheet" href="style.css">
            <script src="main.js"></script>
        </head>
        <body>
            <img src="logo.png">
            <h1>Hello World</h1>
        </body>
        </html>
        """

        # When: Saving archive
        result = await archiver.save_archive(
            url="https://example.org/test",
            content=content,
            title="Test Page",
            collector=collector,
        )

        # Then: All files should be created correctly
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None
        assert result["har_path"] is not None

        cdxj_content = Path(result["cdxj_path"]).read_text()
        lines = [line for line in cdxj_content.split("\n") if line and not line.startswith("#")]
        assert len(lines) >= 3

        har_content = json.loads(Path(result["har_path"]).read_text())
        assert har_content["log"]["pages"][0]["title"] == "Test Page"

        entry_urls = [e["request"]["url"] for e in har_content["log"]["entries"]]
        assert "https://example.org/test" in entry_urls


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_surt_invalid_url(self) -> None:
        """Test SURT conversion with invalid URL (TC-EC-N-01)."""
        # Given: An invalid URL
        # When: Converting to SURT
        surt = url_to_surt("not-a-valid-url")

        # Then: Should not raise, returns something
        assert surt is not None

    def test_empty_collector_resources(self) -> None:
        """Test collector with no resources (TC-EC-B-01)."""
        # Given: A new collector
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")

        # When/Then: Should have empty lists
        assert len(collector.resources) == 0
        assert len(collector.main_resources) == 0

    def test_response_without_request(self) -> None:
        """Test handling response without prior request (TC-EC-N-02)."""
        # Given: A collector
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")

        # When: Recording response without prior request (redirect case)
        collector.on_response(
            url="https://example.com/redirected",
            status=200,
            headers={},
            mime_type="text/html",
        )

        # Then: Resource should be created from response
        assert len(collector.resources) == 1
        assert collector.resources[0].status == 200

    @pytest.mark.asyncio
    async def test_save_archive_empty_content(self, tmp_path: Path) -> None:
        """Test saving archive with empty content (TC-EC-B-02)."""
        # Given: Archive directory and archiver
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archiver = BrowserArchiver(output_dir=archive_dir)

        # When: Saving archive with empty content
        result = await archiver.save_archive(
            url="https://example.com/",
            content=b"",
            title="Empty Page",
        )

        # Then: Should still succeed
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None

    def test_har_resource_without_timing(self) -> None:
        """Test HAR generation for resource without timing data (TC-EC-N-03)."""
        # Given: A HAR generator
        har_gen = HARGenerator(page_url="https://example.com/")

        resource = ResourceInfo(
            url="https://example.com/",
            status=200,
            # No start_time/end_time
        )

        # When: Adding resource without timing
        har_gen.add_resource(resource)
        har = har_gen.generate()

        # Then: Should not raise
        assert len(har["log"]["entries"]) == 1
