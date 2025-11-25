"""
Tests for URL fetcher module.

Covers:
- WARC file creation and validation (§3.1.2)
- Challenge page detection (§3.5)
- FetchResult cache fields for 304 support (§3.1.2, §4.3)
- URL normalization for cache keys (§5.1.2)
- Human-like behavior simulation (§4.3)
- Tor controller (§4.3)
- Fetch cache database operations (§5.1.2)
"""

import gzip
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from warcio.archiveiterator import ArchiveIterator


@pytest.mark.unit
class TestSaveWarc:
    """Tests for WARC saving functionality."""

    @pytest.fixture
    def warc_dir(self, temp_dir: Path) -> Path:
        """Create temporary WARC directory."""
        warc_path = temp_dir / "warc"
        warc_path.mkdir(parents=True, exist_ok=True)
        return warc_path

    @pytest.fixture
    def mock_warc_settings(self, mock_settings, warc_dir: Path):
        """Mock settings with temporary WARC directory."""
        mock_settings.storage.warc_dir = str(warc_dir)
        return mock_settings

    @pytest.mark.asyncio
    async def test_save_warc_creates_file(self, mock_warc_settings, warc_dir: Path):
        """Test that _save_warc creates a WARC file."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc
            
            url = "https://example.com/test"
            content = b"<html><body>Test content</body></html>"
            status_code = 200
            response_headers = {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(content)),
            }
            
            result = await _save_warc(url, content, status_code, response_headers)
            
            assert result is not None
            assert result.exists()
            assert result.suffix == ".gz"
            assert "warc" in result.name.lower()

    @pytest.mark.asyncio
    async def test_save_warc_contains_response_record(self, mock_warc_settings, warc_dir: Path):
        """Test that WARC file contains valid response record."""
        import gzip
        
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc
            
            url = "https://example.com/page"
            content = b"<html><body>Hello World</body></html>"
            status_code = 200
            response_headers = {
                "Content-Type": "text/html",
                "Server": "nginx",
            }
            
            warc_path = await _save_warc(url, content, status_code, response_headers)
            
            # Read raw gzipped WARC content to verify
            with gzip.open(warc_path, "rb") as f:
                raw_warc = f.read()
            
            # Verify WARC contains expected data
            assert b"WARC/1.0" in raw_warc
            assert b"WARC-Type: response" in raw_warc
            assert url.encode() in raw_warc
            assert content in raw_warc
            assert b"200 OK" in raw_warc

    @pytest.mark.asyncio
    async def test_save_warc_with_request_headers(self, mock_warc_settings, warc_dir: Path):
        """Test WARC file includes request record when headers provided."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc
            
            url = "https://example.com/api/data"
            content = b'{"status": "ok"}'
            status_code = 200
            response_headers = {"Content-Type": "application/json"}
            request_headers = {
                "Accept": "application/json",
                "User-Agent": "Lancet/1.0",
            }
            
            warc_path = await _save_warc(
                url, content, status_code, response_headers,
                request_headers=request_headers
            )
            
            # Count record types
            record_types = []
            with open(warc_path, "rb") as f:
                for record in ArchiveIterator(f):
                    record_types.append(record.rec_type)
            
            # Should have both request and response
            assert "request" in record_types
            assert "response" in record_types

    @pytest.mark.asyncio
    async def test_save_warc_different_status_codes(self, mock_warc_settings, warc_dir: Path):
        """Test WARC saves various HTTP status codes correctly."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc
            
            test_cases = [
                (200, "OK"),
                (404, "Not Found"),
                (500, "Internal Server Error"),
                (301, "Moved Permanently"),
            ]
            
            for status_code, expected_text in test_cases:
                url = f"https://example.com/test_{status_code}"
                content = b"Test content"
                response_headers = {"Content-Type": "text/plain"}
                
                warc_path = await _save_warc(url, content, status_code, response_headers)
                
                assert warc_path is not None
                assert warc_path.exists()

    @pytest.mark.asyncio
    async def test_save_warc_unicode_content(self, mock_warc_settings, warc_dir: Path):
        """Test WARC handles Unicode content correctly."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc
            
            url = "https://example.jp/日本語ページ"
            content = "<html><body>日本語コンテンツ🎉</body></html>".encode("utf-8")
            status_code = 200
            response_headers = {"Content-Type": "text/html; charset=utf-8"}
            
            warc_path = await _save_warc(url, content, status_code, response_headers)
            
            assert warc_path is not None
            
            # Verify content is preserved
            with open(warc_path, "rb") as f:
                for record in ArchiveIterator(f):
                    if record.rec_type == "response":
                        payload = record.content_stream().read()
                        assert "日本語コンテンツ".encode("utf-8") in payload


@pytest.mark.unit
class TestGetHttpStatusText:
    """Tests for HTTP status text helper."""

    def test_common_status_codes(self):
        """Test common HTTP status codes return correct text."""
        from src.crawler.fetcher import _get_http_status_text
        
        assert _get_http_status_text(200) == "OK"
        assert _get_http_status_text(404) == "Not Found"
        assert _get_http_status_text(500) == "Internal Server Error"
        assert _get_http_status_text(301) == "Moved Permanently"
        assert _get_http_status_text(403) == "Forbidden"

    def test_unknown_status_code(self):
        """Test unknown status code returns 'Unknown'."""
        from src.crawler.fetcher import _get_http_status_text
        
        assert _get_http_status_text(999) == "Unknown"
        assert _get_http_status_text(418) == "Unknown"  # I'm a teapot


@pytest.mark.unit
class TestFetchResult:
    """Tests for FetchResult class."""

    def test_fetch_result_to_dict_includes_warc_path(self):
        """Test FetchResult.to_dict() includes warc_path."""
        from src.crawler.fetcher import FetchResult
        
        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            status=200,
            html_path="/tmp/page.html",
            warc_path="/tmp/page.warc.gz",
            content_hash="abc123",
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["warc_path"] == "/tmp/page.warc.gz"
        assert result_dict["ok"] is True
        assert result_dict["status"] == 200


@pytest.mark.unit
class TestIsChallengePageFunction:
    """Tests for challenge page detection (§3.5 - CAPTCHA/challenge handling)."""

    def test_detect_cloudflare_challenge(self):
        """Test detection of Cloudflare challenge pages."""
        from src.crawler.fetcher import _is_challenge_page
        
        cf_content = """
        <html>
        <head><title>Just a moment...</title></head>
        <body>
        <div id="cf-browser-verification">Please wait...</div>
        </body>
        </html>
        """
        
        assert _is_challenge_page(cf_content, {}) is True

    def test_detect_recaptcha(self):
        """Test detection of reCAPTCHA."""
        from src.crawler.fetcher import _is_challenge_page
        
        captcha_content = """
        <html>
        <body>
        <div class="g-recaptcha" data-sitekey="xxx"></div>
        </body>
        </html>
        """
        
        assert _is_challenge_page(captcha_content, {}) is True

    def test_normal_page_not_detected(self):
        """Test normal page is not detected as challenge."""
        from src.crawler.fetcher import _is_challenge_page
        
        normal_content = """
        <html>
        <head><title>Welcome to Example.com</title></head>
        <body>
        <h1>Hello World</h1>
        <p>This is a normal web page with regular content.</p>
        </body>
        </html>
        """
        
        assert _is_challenge_page(normal_content, {}) is False


@pytest.mark.unit
class TestFetchResultCacheFields:
    """Tests for FetchResult cache-related fields (§3.1.2 - 304 support)."""

    def test_fetch_result_default_cache_fields(self):
        """Test FetchResult has correct defaults for cache fields."""
        from src.crawler.fetcher import FetchResult
        
        result = FetchResult(ok=True, url="https://example.com/page")
        
        assert result.from_cache is False
        assert result.etag is None
        assert result.last_modified is None

    def test_fetch_result_with_cache_fields(self):
        """Test FetchResult with cache fields populated."""
        from src.crawler.fetcher import FetchResult
        
        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            status=200,
            from_cache=True,
            etag='"abc123"',
            last_modified="Wed, 01 Jan 2024 00:00:00 GMT",
        )
        
        assert result.from_cache is True
        assert result.etag == '"abc123"'
        assert result.last_modified == "Wed, 01 Jan 2024 00:00:00 GMT"

    def test_fetch_result_to_dict_includes_cache_fields(self):
        """Test FetchResult.to_dict() includes cache-related fields."""
        from src.crawler.fetcher import FetchResult
        
        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            status=304,
            from_cache=True,
            etag='"xyz789"',
            last_modified="Thu, 15 Jan 2024 12:00:00 GMT",
        )
        
        result_dict = result.to_dict()
        
        assert "from_cache" in result_dict
        assert result_dict["from_cache"] is True
        assert result_dict["etag"] == '"xyz789"'
        assert result_dict["last_modified"] == "Thu, 15 Jan 2024 12:00:00 GMT"

    def test_fetch_result_304_response(self):
        """Test FetchResult for 304 Not Modified response.
        
        Per §4.3: 304活用率≥70% requires proper 304 handling.
        """
        from src.crawler.fetcher import FetchResult
        
        # Simulate 304 response - ok should be True, status 304
        result = FetchResult(
            ok=True,
            url="https://example.com/cached-page",
            status=304,
            from_cache=True,
            etag='"etag-unchanged"',
            method="http_client",
        )
        
        assert result.ok is True
        assert result.status == 304
        assert result.from_cache is True


@pytest.mark.unit
class TestDatabaseUrlNormalization:
    """Tests for URL normalization used in fetch cache.
    
    Per §5.1.2: cache_fetch key should be normalized URL.
    """

    def test_normalize_url_lowercase_scheme_and_host(self):
        """Test URL scheme and host are lowercased."""
        from src.storage.database import Database
        
        url1 = "HTTPS://EXAMPLE.COM/Path"
        url2 = "https://example.com/Path"
        
        assert Database._normalize_url(url1) == Database._normalize_url(url2)
        assert "example.com" in Database._normalize_url(url1)

    def test_normalize_url_removes_fragment(self):
        """Test URL fragment is removed."""
        from src.storage.database import Database
        
        url1 = "https://example.com/page#section1"
        url2 = "https://example.com/page"
        
        assert Database._normalize_url(url1) == Database._normalize_url(url2)

    def test_normalize_url_sorts_query_params(self):
        """Test query parameters are sorted for consistent caching."""
        from src.storage.database import Database
        
        url1 = "https://example.com/search?b=2&a=1"
        url2 = "https://example.com/search?a=1&b=2"
        
        assert Database._normalize_url(url1) == Database._normalize_url(url2)

    def test_normalize_url_preserves_path(self):
        """Test URL path is preserved (case-sensitive)."""
        from src.storage.database import Database
        
        url = "https://example.com/CaseSensitive/Path"
        normalized = Database._normalize_url(url)
        
        assert "/CaseSensitive/Path" in normalized

    def test_normalize_url_empty_query_string(self):
        """Test URL with no query string."""
        from src.storage.database import Database
        
        url = "https://example.com/page"
        normalized = Database._normalize_url(url)
        
        assert normalized == "https://example.com/page"


@pytest.mark.unit
class TestHumanBehavior:
    """Tests for human-like behavior simulation (§4.3 - stealth requirements)."""

    def test_random_delay_within_bounds(self):
        """Test random delay stays within specified bounds."""
        from src.crawler.fetcher import HumanBehavior
        
        for _ in range(100):
            delay = HumanBehavior.random_delay(0.5, 3.0)
            assert 0.5 <= delay <= 3.0, f"Delay {delay} out of bounds"

    def test_random_delay_default_bounds(self):
        """Test random delay with default bounds."""
        from src.crawler.fetcher import HumanBehavior
        
        for _ in range(50):
            delay = HumanBehavior.random_delay()
            assert 0.5 <= delay <= 2.0, f"Delay {delay} out of default bounds"

    def test_scroll_pattern_generation(self):
        """Test scroll pattern generates reasonable positions.
        
        For page_height=3000 and viewport_height=1080, scrollable area is 1920px.
        With typical scroll steps of 200-400px, expect 5-10 scroll positions.
        """
        from src.crawler.fetcher import HumanBehavior
        
        positions = HumanBehavior.scroll_pattern(
            page_height=3000,
            viewport_height=1080,
        )
        
        # Scrollable area = 3000 - 1080 = 1920px
        # With typical 200-400px steps, expect 5-10 positions
        assert 3 <= len(positions) <= 15, (
            f"Expected 3-15 scroll positions for 1920px scrollable area, got {len(positions)}"
        )
        
        for idx, (scroll_y, delay) in enumerate(positions):
            assert 0 <= scroll_y <= 1920, (
                f"Position {idx}: scroll_y={scroll_y} out of range [0, 1920]"
            )
            assert 0.1 <= delay <= 3.0, (
                f"Position {idx}: delay={delay} out of expected range [0.1, 3.0]"
            )

    def test_scroll_pattern_short_page(self):
        """Test scroll pattern for page shorter than viewport."""
        from src.crawler.fetcher import HumanBehavior
        
        positions = HumanBehavior.scroll_pattern(
            page_height=500,
            viewport_height=1080,
        )
        
        # Short page should have no scrolling needed
        assert len(positions) == 0, "Short page should not need scrolling"

    def test_mouse_path_generation(self):
        """Test mouse path generates smooth bezier curve.
        
        Path should start near origin and end near destination,
        with small jitter applied to intermediate points.
        """
        from src.crawler.fetcher import HumanBehavior
        
        start_x, start_y = 100, 100
        end_x, end_y = 500, 400
        steps = 10
        
        path = HumanBehavior.mouse_path(
            start_x=start_x, start_y=start_y,
            end_x=end_x, end_y=end_y,
            steps=steps,
        )
        
        expected_points = steps + 1
        assert len(path) == expected_points, (
            f"Expected {expected_points} points (steps + 1), got {len(path)}"
        )
        
        # First point should be near start (within jitter tolerance)
        jitter_tolerance = 15
        assert abs(path[0][0] - start_x) < jitter_tolerance, (
            f"First point x={path[0][0]} too far from start_x={start_x}"
        )
        assert abs(path[0][1] - start_y) < jitter_tolerance, (
            f"First point y={path[0][1]} too far from start_y={start_y}"
        )
        
        # Last point should be near end
        assert abs(path[-1][0] - end_x) < jitter_tolerance, (
            f"Last point x={path[-1][0]} too far from end_x={end_x}"
        )
        assert abs(path[-1][1] - end_y) < jitter_tolerance, (
            f"Last point y={path[-1][1]} too far from end_y={end_y}"
        )

    def test_mouse_path_has_jitter(self):
        """Test mouse paths are not identical (random jitter)."""
        from src.crawler.fetcher import HumanBehavior
        
        path1 = HumanBehavior.mouse_path(0, 0, 100, 100, steps=5)
        path2 = HumanBehavior.mouse_path(0, 0, 100, 100, steps=5)
        
        # Paths should differ due to random control points and jitter
        assert path1 != path2, "Paths should differ due to randomness"


@pytest.mark.unit
class TestTorController:
    """Tests for Tor circuit controller (§4.3 - network layer)."""

    def test_tor_controller_initialization(self):
        """Test TorController initializes correctly."""
        from src.crawler.fetcher import TorController
        
        controller = TorController()
        
        assert controller._controller is None  # Not connected yet
        assert len(controller._last_renewal) == 0

    @pytest.mark.asyncio
    async def test_tor_controller_disabled(self, mock_settings):
        """Test TorController when Tor is disabled."""
        mock_settings.tor.enabled = False
        
        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            from src.crawler.fetcher import TorController
            
            controller = TorController()
            result = await controller.connect()
            
            assert result is False, "Should return False when Tor disabled"


@pytest.mark.integration
class TestDatabaseFetchCache:
    """Tests for fetch cache database operations (§5.1.2 - cache_fetch).
    
    Tests cache storage and retrieval for conditional request support.
    Uses in-memory SQLite database for isolation.
    """

    @pytest.mark.asyncio
    async def test_set_and_get_fetch_cache(self, memory_database):
        """Test storing and retrieving fetch cache entry."""
        db = memory_database
        url = "https://example.com/page"
        expected_etag = '"abc123"'
        expected_last_modified = "Wed, 01 Jan 2024 00:00:00 GMT"
        expected_hash = "sha256-hash"
        expected_path = "/tmp/cache/page.html"
        
        await db.set_fetch_cache(
            url,
            etag=expected_etag,
            last_modified=expected_last_modified,
            content_hash=expected_hash,
            content_path=expected_path,
        )
        
        cached = await db.get_fetch_cache(url)
        
        assert cached is not None, f"Cache entry should exist for {url}"
        assert cached["etag"] == expected_etag, (
            f"ETag mismatch: expected {expected_etag}, got {cached['etag']}"
        )
        assert cached["last_modified"] == expected_last_modified, (
            f"Last-Modified mismatch: expected {expected_last_modified}, got {cached['last_modified']}"
        )
        assert cached["content_hash"] == expected_hash, (
            f"Content hash mismatch: expected {expected_hash}, got {cached['content_hash']}"
        )
        assert cached["content_path"] == expected_path, (
            f"Content path mismatch: expected {expected_path}, got {cached['content_path']}"
        )

    @pytest.mark.asyncio
    async def test_get_fetch_cache_missing_url(self, memory_database):
        """Test cache miss returns None."""
        db = memory_database
        
        cached = await db.get_fetch_cache("https://nonexistent.com/page")
        
        assert cached is None

    @pytest.mark.asyncio
    async def test_fetch_cache_url_normalization(self, memory_database):
        """Test cache lookup uses normalized URLs.
        
        URLs differing only in query param order or fragment should match.
        """
        db = memory_database
        store_url = "https://example.com/page?b=2&a=1#section"
        lookup_url = "https://example.com/page?a=1&b=2"  # Different order, no fragment
        expected_etag = '"etag1"'
        
        await db.set_fetch_cache(store_url, etag=expected_etag)
        
        cached = await db.get_fetch_cache(lookup_url)
        
        assert cached is not None, (
            f"Cache miss for normalized URL: stored={store_url}, lookup={lookup_url}"
        )
        assert cached["etag"] == expected_etag, (
            f"ETag mismatch after normalization: expected {expected_etag}, got {cached['etag']}"
        )

    @pytest.mark.asyncio
    async def test_update_fetch_cache_validation(self, memory_database):
        """Test updating cache validation timestamp."""
        db = memory_database
        url = "https://example.com/page"
        
        # Initial store
        await db.set_fetch_cache(url, etag='"old-etag"')
        
        # Update validation with new ETag
        await db.update_fetch_cache_validation(url, etag='"new-etag"')
        
        cached = await db.get_fetch_cache(url)
        assert cached["etag"] == '"new-etag"'

    @pytest.mark.asyncio
    async def test_invalidate_fetch_cache(self, memory_database):
        """Test cache invalidation."""
        db = memory_database
        url = "https://example.com/page"
        
        await db.set_fetch_cache(url, etag='"etag"')
        assert await db.get_fetch_cache(url) is not None
        
        await db.invalidate_fetch_cache(url)
        assert await db.get_fetch_cache(url) is None

    @pytest.mark.asyncio
    async def test_fetch_cache_with_only_etag(self, memory_database):
        """Test cache entry with only ETag (no Last-Modified)."""
        db = memory_database
        
        await db.set_fetch_cache(
            "https://example.com/page",
            etag='"etag-only"',
        )
        
        cached = await db.get_fetch_cache("https://example.com/page")
        
        assert cached["etag"] == '"etag-only"'
        assert cached["last_modified"] is None

    @pytest.mark.asyncio
    async def test_fetch_cache_with_only_last_modified(self, memory_database):
        """Test cache entry with only Last-Modified (no ETag)."""
        db = memory_database
        
        await db.set_fetch_cache(
            "https://example.com/page",
            last_modified="Wed, 01 Jan 2024 00:00:00 GMT",
        )
        
        cached = await db.get_fetch_cache("https://example.com/page")
        
        assert cached["etag"] is None
        assert cached["last_modified"] == "Wed, 01 Jan 2024 00:00:00 GMT"

    @pytest.mark.asyncio
    async def test_fetch_cache_stats(self, memory_database):
        """Test fetch cache statistics.
        
        Setup:
        - a.com: etag only
        - b.com: last_modified only  
        - c.com: both etag and last_modified
        """
        db = memory_database
        
        await db.set_fetch_cache("https://a.com/1", etag='"e1"')
        await db.set_fetch_cache("https://b.com/2", last_modified="Mon, 01 Jan 2024 00:00:00 GMT")
        await db.set_fetch_cache("https://c.com/3", etag='"e3"', last_modified="Tue, 02 Jan 2024 00:00:00 GMT")
        
        stats = await db.get_fetch_cache_stats()
        
        assert stats["total_entries"] == 3, (
            f"Expected 3 total entries, got {stats['total_entries']}"
        )
        assert stats["with_etag"] == 2, (
            f"Expected 2 entries with ETag (a.com, c.com), got {stats['with_etag']}"
        )
        assert stats["with_last_modified"] == 2, (
            f"Expected 2 entries with Last-Modified (b.com, c.com), got {stats['with_last_modified']}"
        )

    @pytest.mark.asyncio
    async def test_fetch_cache_replace_existing(self, memory_database):
        """Test that setting cache replaces existing entry (upsert behavior)."""
        db = memory_database
        url = "https://example.com/page"
        
        # First set
        await db.set_fetch_cache(url, etag='"old"', content_path="/old/path")
        
        # Second set should replace
        new_etag = '"new"'
        new_path = "/new/path"
        await db.set_fetch_cache(url, etag=new_etag, content_path=new_path)
        
        cached = await db.get_fetch_cache(url)
        
        assert cached["etag"] == new_etag, (
            f"ETag should be replaced: expected {new_etag}, got {cached['etag']}"
        )
        assert cached["content_path"] == new_path, (
            f"Content path should be replaced: expected {new_path}, got {cached['content_path']}"
        )

