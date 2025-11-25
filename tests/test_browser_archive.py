"""
Tests for browser archive functionality (§4.3.2).

Tests CDXJ metadata generation and simplified HAR creation
for browser-fetched pages.
"""

import json
import pytest
import time
from pathlib import Path

from src.crawler.browser_archive import (
    ResourceInfo,
    CDXJEntry,
    NetworkEventCollector,
    HARGenerator,
    CDXJGenerator,
    BrowserArchiver,
    url_to_surt,
    get_browser_archiver,
)


# =============================================================================
# SURT Conversion Tests
# =============================================================================

class TestUrlToSurt:
    """Tests for SURT (Sort-friendly URI Reordering Transform) conversion."""
    
    def test_simple_url(self):
        """Test basic URL to SURT conversion."""
        url = "https://example.com/page"
        surt = url_to_surt(url)
        
        assert "com,example)" in surt
        assert "/page" in surt
    
    def test_subdomain_url(self):
        """Test URL with subdomain."""
        url = "https://www.example.com/path/to/page"
        surt = url_to_surt(url)
        
        # Domain parts should be reversed
        assert "com,example,www)" in surt
        assert "/path/to/page" in surt
    
    def test_url_with_query(self):
        """Test URL with query string."""
        url = "https://example.com/search?q=test&lang=en"
        surt = url_to_surt(url)
        
        assert "com,example)" in surt
        assert "?q=test&lang=en" in surt
    
    def test_deep_subdomain(self):
        """Test URL with multiple subdomain levels."""
        url = "https://api.v2.example.co.jp/endpoint"
        surt = url_to_surt(url)
        
        # All domain parts reversed
        assert "jp,co,example,v2,api)" in surt
    
    def test_root_path(self):
        """Test URL with root path."""
        url = "https://example.com/"
        surt = url_to_surt(url)
        
        assert "com,example)/" in surt


# =============================================================================
# ResourceInfo Tests
# =============================================================================

class TestResourceInfo:
    """Tests for ResourceInfo data class."""
    
    def test_resource_info_creation(self):
        """Test creating ResourceInfo with all fields."""
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
        
        assert resource.url == "https://example.com/page.html"
        assert resource.status == 200
        assert resource.size == 1024
        assert resource.is_main_frame is True
    
    def test_duration_calculation(self):
        """Test request duration calculation."""
        resource = ResourceInfo(
            url="https://example.com/",
            start_time=1000.0,
            end_time=1000.5,
        )
        
        duration = resource.duration_ms
        assert duration is not None
        assert abs(duration - 500.0) < 0.1  # 500ms
    
    def test_duration_none_when_incomplete(self):
        """Test that duration is None for incomplete requests."""
        resource = ResourceInfo(
            url="https://example.com/",
            start_time=1000.0,
            end_time=None,
        )
        
        assert resource.duration_ms is None
    
    def test_default_values(self):
        """Test default values for optional fields."""
        resource = ResourceInfo(url="https://example.com/")
        
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
    
    def test_cdxj_line_format(self):
        """Test CDXJ line format output."""
        entry = CDXJEntry(
            url="https://example.com/page",
            surt="com,example)/page",
            timestamp="20240101120000",
            digest="sha256:abc123",
            mime_type="text/html",
            status=200,
        )
        
        line = entry.to_cdxj_line()
        
        # Should contain SURT, timestamp, and JSON
        assert line.startswith("com,example)/page 20240101120000")
        
        # Parse JSON part
        json_str = line.split(" ", 2)[2]
        data = json.loads(json_str)
        
        assert data["url"] == "https://example.com/page"
        assert data["digest"] == "sha256:abc123"
        assert data["mime"] == "text/html"
        assert data["status"] == "200"
    
    def test_cdxj_with_extra_metadata(self):
        """Test CDXJ entry with extra metadata."""
        entry = CDXJEntry(
            url="https://example.com/",
            surt="com,example)/",
            timestamp="20240101120000",
            digest="sha256:xyz789",
            extra={"size": 2048, "is_main": True},
        )
        
        line = entry.to_cdxj_line()
        json_str = line.split(" ", 2)[2]
        data = json.loads(json_str)
        
        assert data["size"] == 2048
        assert data["is_main"] is True


# =============================================================================
# NetworkEventCollector Tests
# =============================================================================

class TestNetworkEventCollector:
    """Tests for network event collection."""
    
    def test_start_collection(self):
        """Test starting event collection."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        assert collector._main_frame_url == "https://example.com/"
        assert len(collector.resources) == 0
    
    def test_on_request(self):
        """Test recording a request event."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        collector.on_request(
            url="https://example.com/",
            method="GET",
            resource_type="document",
            is_main_frame=True,
        )
        
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].url == "https://example.com/"
        assert resources[0].is_main_frame is True
    
    def test_on_response(self):
        """Test recording a response event."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        collector.on_request(url="https://example.com/", method="GET")
        collector.on_response(
            url="https://example.com/",
            status=200,
            headers={"content-type": "text/html"},
            mime_type="text/html",
        )
        
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].status == 200
        assert resources[0].mime_type == "text/html"
    
    def test_on_request_finished(self):
        """Test recording request completion."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        collector.on_request(url="https://example.com/", method="GET")
        collector.on_request_finished(url="https://example.com/", size=1024)
        
        resources = collector.resources
        assert len(resources) == 1
        assert resources[0].size == 1024
        assert resources[0].end_time is not None
    
    def test_add_content_hash(self):
        """Test adding content hash to resource."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        collector.on_request(url="https://example.com/", method="GET")
        collector.add_content_hash("https://example.com/", b"test content")
        
        resources = collector.resources
        assert resources[0].content_hash is not None
    
    def test_main_resources_filtering(self):
        """Test filtering for main resources only."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        # Main document
        collector.on_request(
            url="https://example.com/",
            resource_type="document",
            is_main_frame=True,
        )
        collector.on_response(
            url="https://example.com/",
            status=200,
            headers={},
            mime_type="text/html",
        )
        
        # Script (should be included)
        collector.on_request(
            url="https://example.com/app.js",
            resource_type="script",
        )
        collector.on_response(
            url="https://example.com/app.js",
            status=200,
            headers={},
            mime_type="application/javascript",
        )
        
        # Image (should be filtered out)
        collector.on_request(
            url="https://example.com/image.png",
            resource_type="image",
        )
        collector.on_response(
            url="https://example.com/image.png",
            status=200,
            headers={},
            mime_type="image/png",
        )
        
        all_resources = collector.resources
        main_resources = collector.main_resources
        
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
    
    def test_empty_har_structure(self):
        """Test HAR structure with no entries."""
        har_gen = HARGenerator(
            page_url="https://example.com/",
            page_title="Example Page",
        )
        
        har = har_gen.generate()
        
        assert "log" in har
        assert har["log"]["version"] == "1.2"
        assert "creator" in har["log"]
        assert "pages" in har["log"]
        assert len(har["log"]["pages"]) == 1
        assert har["log"]["pages"][0]["title"] == "Example Page"
    
    def test_add_resource(self):
        """Test adding a resource to HAR."""
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
        har_gen.add_resource(resource)
        
        har = har_gen.generate()
        
        assert len(har["log"]["entries"]) == 1
        entry = har["log"]["entries"][0]
        
        assert entry["request"]["method"] == "GET"
        assert entry["request"]["url"] == "https://example.com/"
        assert entry["response"]["status"] == 200
        assert entry["response"]["content"]["mimeType"] == "text/html"
        assert entry["response"]["content"]["size"] == 1024
    
    def test_har_json_output(self):
        """Test HAR JSON string output."""
        har_gen = HARGenerator(page_url="https://example.com/")
        
        json_str = har_gen.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert "log" in parsed
    
    def test_multiple_resources(self):
        """Test adding multiple resources to HAR."""
        har_gen = HARGenerator(page_url="https://example.com/")
        
        resources = [
            ResourceInfo(url="https://example.com/", status=200),
            ResourceInfo(url="https://example.com/style.css", status=200),
            ResourceInfo(url="https://example.com/app.js", status=200),
        ]
        
        for resource in resources:
            har_gen.add_resource(resource)
        
        har = har_gen.generate()
        assert len(har["log"]["entries"]) == 3


# =============================================================================
# CDXJGenerator Tests
# =============================================================================

class TestCDXJGenerator:
    """Tests for CDXJ index generation."""
    
    def test_add_resource_with_content(self):
        """Test adding resource with content for hash calculation."""
        cdxj_gen = CDXJGenerator()
        
        resource = ResourceInfo(
            url="https://example.com/page.html",
            status=200,
            mime_type="text/html",
            size=1024,
        )
        cdxj_gen.add_resource(resource, b"<html>test content</html>")
        
        lines = cdxj_gen.generate()
        
        assert len(lines) == 1
        assert "sha256:" in lines[0]
        assert "com,example)/page.html" in lines[0]
    
    def test_add_resource_with_existing_hash(self):
        """Test adding resource with pre-computed hash."""
        cdxj_gen = CDXJGenerator()
        
        resource = ResourceInfo(
            url="https://example.com/",
            status=200,
            content_hash="abc123def456",
        )
        cdxj_gen.add_resource(resource)
        
        lines = cdxj_gen.generate()
        
        assert len(lines) == 1
        assert "sha256:abc123def456" in lines[0]
    
    def test_sorted_output(self):
        """Test that entries are sorted by SURT."""
        cdxj_gen = CDXJGenerator()
        
        # Add in unsorted order
        cdxj_gen.add_resource(ResourceInfo(url="https://zebra.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://apple.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://mango.com/"))
        
        lines = cdxj_gen.generate()
        
        # Should be sorted: apple, mango, zebra
        assert "com,apple)" in lines[0]
        assert "com,mango)" in lines[1]
        assert "com,zebra)" in lines[2]
    
    def test_to_string(self):
        """Test CDXJ string output."""
        cdxj_gen = CDXJGenerator()
        
        cdxj_gen.add_resource(ResourceInfo(url="https://example.com/"))
        cdxj_gen.add_resource(ResourceInfo(url="https://test.com/"))
        
        output = cdxj_gen.to_string()
        
        # Should have two lines
        lines = output.strip().split("\n")
        assert len(lines) == 2


# =============================================================================
# BrowserArchiver Tests
# =============================================================================

class TestBrowserArchiver:
    """Tests for browser archive saving."""
    
    @pytest.fixture
    def temp_archive_dir(self, tmp_path):
        """Create a temporary archive directory."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        return archive_dir
    
    @pytest.fixture
    def archiver(self, temp_archive_dir):
        """Create archiver with temp directory."""
        return BrowserArchiver(output_dir=temp_archive_dir)
    
    @pytest.mark.asyncio
    async def test_save_archive_creates_cdxj(self, archiver, temp_archive_dir):
        """Test that save_archive creates CDXJ file."""
        content = b"<html><head><title>Test</title></head><body>Hello</body></html>"
        
        result = await archiver.save_archive(
            url="https://example.com/test",
            content=content,
            title="Test Page",
        )
        
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None
        
        # Check file exists
        cdxj_path = Path(result["cdxj_path"])
        assert cdxj_path.exists()
        
        # Check content
        cdxj_content = cdxj_path.read_text()
        assert "com,example)/test" in cdxj_content
        assert "sha256:" in cdxj_content
    
    @pytest.mark.asyncio
    async def test_save_archive_creates_har(self, archiver, temp_archive_dir):
        """Test that save_archive creates HAR file."""
        content = b"<html><body>Test content</body></html>"
        
        result = await archiver.save_archive(
            url="https://example.com/page",
            content=content,
            title="Test",
        )
        
        assert result["status"] == "success"
        assert result["har_path"] is not None
        
        # Check file exists
        har_path = Path(result["har_path"])
        assert har_path.exists()
        
        # Check content is valid HAR JSON
        har_content = json.loads(har_path.read_text())
        assert "log" in har_content
        assert har_content["log"]["version"] == "1.2"
        assert len(har_content["log"]["entries"]) >= 1
    
    @pytest.mark.asyncio
    async def test_save_archive_with_collector(self, archiver, temp_archive_dir):
        """Test saving archive with network event collector."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        # Simulate some network events
        collector.on_request(
            url="https://example.com/",
            method="GET",
            resource_type="document",
            is_main_frame=True,
        )
        collector.on_response(
            url="https://example.com/",
            status=200,
            headers={"content-type": "text/html"},
            mime_type="text/html",
        )
        collector.on_request_finished(url="https://example.com/", size=512)
        
        collector.on_request(
            url="https://example.com/app.js",
            resource_type="script",
        )
        collector.on_response(
            url="https://example.com/app.js",
            status=200,
            headers={},
            mime_type="application/javascript",
        )
        
        content = b"<html><script src='app.js'></script></html>"
        
        result = await archiver.save_archive(
            url="https://example.com/",
            content=content,
            title="Test",
            collector=collector,
        )
        
        assert result["status"] == "success"
        
        # Check HAR contains multiple entries
        har_path = Path(result["har_path"])
        har_content = json.loads(har_path.read_text())
        
        # Should have main document + JS
        assert len(har_content["log"]["entries"]) >= 2
    
    @pytest.mark.asyncio
    async def test_save_archive_adds_warc_reference(self, archiver, temp_archive_dir):
        """Test that WARC path is added to CDXJ header."""
        content = b"<html></html>"
        warc_path = "/path/to/test.warc.gz"
        
        result = await archiver.save_archive(
            url="https://example.com/",
            content=content,
            warc_path=warc_path,
        )
        
        cdxj_path = Path(result["cdxj_path"])
        cdxj_content = cdxj_path.read_text()
        
        # Should have WARC reference in header
        assert warc_path in cdxj_content
    
    def test_create_collector(self, archiver):
        """Test creating network event collector."""
        collector = archiver.create_collector()
        
        assert isinstance(collector, NetworkEventCollector)


# =============================================================================
# Integration Tests
# =============================================================================

class TestBrowserArchiverIntegration:
    """Integration tests for browser archiver."""
    
    def test_get_browser_archiver(self):
        """Test getting global archiver instance."""
        archiver = get_browser_archiver()
        
        assert isinstance(archiver, BrowserArchiver)
    
    @pytest.mark.asyncio
    async def test_full_workflow(self, tmp_path):
        """Test complete archive workflow."""
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
            url="https://example.org/style.css",
            status=200,
            headers={},
            mime_type="text/css",
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
            url="https://example.org/logo.png",
            status=200,
            headers={},
            mime_type="image/png",
        )
        
        # Page content
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
        
        # Save archive
        result = await archiver.save_archive(
            url="https://example.org/test",
            content=content,
            title="Test Page",
            collector=collector,
        )
        
        # Verify results
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None
        assert result["har_path"] is not None
        
        # Verify CDXJ content
        cdxj_content = Path(result["cdxj_path"]).read_text()
        lines = [l for l in cdxj_content.split("\n") if l and not l.startswith("#")]
        
        # Should have main document + CSS + JS (not image)
        assert len(lines) >= 3
        
        # Verify HAR content
        har_content = json.loads(Path(result["har_path"]).read_text())
        
        assert har_content["log"]["pages"][0]["title"] == "Test Page"
        
        # HAR should have all resources including image
        entry_urls = [e["request"]["url"] for e in har_content["log"]["entries"]]
        assert "https://example.org/test" in entry_urls


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_surt_invalid_url(self):
        """Test SURT conversion with invalid URL."""
        # Should not raise, returns something
        surt = url_to_surt("not-a-valid-url")
        assert surt is not None
    
    def test_empty_collector_resources(self):
        """Test collector with no resources."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        assert len(collector.resources) == 0
        assert len(collector.main_resources) == 0
    
    def test_response_without_request(self):
        """Test handling response without prior request."""
        collector = NetworkEventCollector()
        collector.start_collection("https://example.com/")
        
        # Response without request (can happen with redirects)
        collector.on_response(
            url="https://example.com/redirected",
            status=200,
            headers={},
            mime_type="text/html",
        )
        
        # Should create resource from response
        assert len(collector.resources) == 1
        assert collector.resources[0].status == 200
    
    @pytest.mark.asyncio
    async def test_save_archive_empty_content(self, tmp_path):
        """Test saving archive with empty content."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        
        archiver = BrowserArchiver(output_dir=archive_dir)
        
        result = await archiver.save_archive(
            url="https://example.com/",
            content=b"",
            title="Empty Page",
        )
        
        # Should still succeed
        assert result["status"] == "success"
        assert result["cdxj_path"] is not None
    
    def test_har_resource_without_timing(self):
        """Test HAR generation for resource without timing data."""
        har_gen = HARGenerator(page_url="https://example.com/")
        
        resource = ResourceInfo(
            url="https://example.com/",
            status=200,
            # No start_time/end_time
        )
        har_gen.add_resource(resource)
        
        har = har_gen.generate()
        
        # Should not raise
        assert len(har["log"]["entries"]) == 1

