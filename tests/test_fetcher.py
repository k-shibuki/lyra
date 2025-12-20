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
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from warcio.archiveiterator import ArchiveIterator

if TYPE_CHECKING:
    from src.storage.database import Database
    from src.utils.config import Settings


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
    def mock_warc_settings(self, mock_settings: "Settings", warc_dir: Path) -> "Settings":
        """Mock settings with temporary WARC directory."""
        mock_settings.storage.warc_dir = str(warc_dir)
        return mock_settings

    @pytest.mark.asyncio
    async def test_save_warc_creates_file(self, mock_warc_settings: "Settings", warc_dir: Path) -> None:
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
    async def test_save_warc_contains_response_record(self, mock_warc_settings: "Settings", warc_dir: Path) -> None:
        """Test that WARC file contains valid response record."""

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
    async def test_save_warc_with_request_headers(self, mock_warc_settings: "Settings", warc_dir: Path) -> None:
        """Test WARC file includes request record when headers provided."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc

            url = "https://example.com/api/data"
            content = b'{"status": "ok"}'
            status_code = 200
            response_headers = {"Content-Type": "application/json"}
            request_headers = {
                "Accept": "application/json",
                "User-Agent": "Lyra/1.0",
            }

            warc_path = await _save_warc(
                url, content, status_code, response_headers, request_headers=request_headers
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
    async def test_save_warc_different_status_codes(self, mock_warc_settings: "Settings", warc_dir: Path) -> None:
        """Test WARC saves various HTTP status codes correctly."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc

            test_cases = [
                (200, "OK"),
                (404, "Not Found"),
                (500, "Internal Server Error"),
                (301, "Moved Permanently"),
            ]

            for status_code, _expected_text in test_cases:
                url = f"https://example.com/test_{status_code}"
                content = b"Test content"
                response_headers = {"Content-Type": "text/plain"}

                warc_path = await _save_warc(url, content, status_code, response_headers)

                assert warc_path is not None
                assert warc_path.exists()

    @pytest.mark.asyncio
    async def test_save_warc_unicode_content(self, mock_warc_settings: "Settings", warc_dir: Path) -> None:
        """Test WARC handles Unicode content correctly."""
        with patch("src.crawler.fetcher.get_settings", return_value=mock_warc_settings):
            from src.crawler.fetcher import _save_warc

            url = "https://example.jp/日本語ページ"
            content = "<html><body>日本語コンテンツ🎉</body></html>".encode()
            status_code = 200
            response_headers = {"Content-Type": "text/html; charset=utf-8"}

            warc_path = await _save_warc(url, content, status_code, response_headers)

            assert warc_path is not None

            # Verify content is preserved
            with open(warc_path, "rb") as f:
                for record in ArchiveIterator(f):
                    if record.rec_type == "response":
                        payload = record.content_stream().read()
                        assert "日本語コンテンツ".encode() in payload


@pytest.mark.unit
class TestGetHttpStatusText:
    """Tests for HTTP status text helper."""

    def test_common_status_codes(self) -> None:
        """Test common HTTP status codes return correct text."""
        from src.crawler.fetcher import _get_http_status_text

        assert _get_http_status_text(200) == "OK"
        assert _get_http_status_text(404) == "Not Found"
        assert _get_http_status_text(500) == "Internal Server Error"
        assert _get_http_status_text(301) == "Moved Permanently"
        assert _get_http_status_text(403) == "Forbidden"

    def test_unknown_status_code(self) -> None:
        """Test unknown status code returns 'Unknown'."""
        from src.crawler.fetcher import _get_http_status_text

        assert _get_http_status_text(999) == "Unknown"
        assert _get_http_status_text(418) == "Unknown"  # I'm a teapot


@pytest.mark.unit
class TestFetchResult:
    """Tests for FetchResult class."""

    def test_fetch_result_to_dict_includes_warc_path(self) -> None:
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

    def test_detect_cloudflare_challenge(self) -> None:
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

    def test_detect_recaptcha(self) -> None:
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

    def test_normal_page_not_detected(self) -> None:
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

    def test_fetch_result_default_cache_fields(self) -> None:
        """Test FetchResult has correct defaults for cache fields."""
        from src.crawler.fetcher import FetchResult

        result = FetchResult(ok=True, url="https://example.com/page")

        assert result.from_cache is False
        assert result.etag is None
        assert result.last_modified is None

    def test_fetch_result_with_cache_fields(self) -> None:
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

    def test_fetch_result_to_dict_includes_cache_fields(self) -> None:
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

    def test_fetch_result_304_response(self) -> None:
        """Test FetchResult for 304 Not Modified response.

        Per §4.3: 304 utilization rate ≥70% requires proper 304 handling.
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
class TestFetchResultAuthFields:
    """Tests for FetchResult authentication-related fields (§16.7.4)."""

    def test_fetch_result_default_auth_fields(self) -> None:
        """Test FetchResult has correct defaults for auth fields."""
        from src.crawler.fetcher import FetchResult

        result = FetchResult(
            ok=False,
            url="https://example.com/protected",
            reason="challenge_detected",
        )

        assert result.auth_queued is False
        assert result.queue_id is None
        assert result.auth_type is None
        assert result.estimated_effort is None

    def test_fetch_result_with_auth_fields(self) -> None:
        """Test FetchResult with auth fields populated.

        Per §16.7.4: auth_type and estimated_effort should be included.
        """
        from src.crawler.fetcher import FetchResult

        result = FetchResult(
            ok=False,
            url="https://protected.example.com/page",
            status=403,
            reason="auth_required",
            method="browser_headful",
            auth_queued=True,
            queue_id="iq_abc123456789",
            auth_type="cloudflare",
            estimated_effort="low",
        )

        assert result.auth_queued is True
        assert result.queue_id == "iq_abc123456789"
        assert result.auth_type == "cloudflare"
        assert result.estimated_effort == "low"

    def test_fetch_result_to_dict_includes_auth_type_when_set(self) -> None:
        """Test FetchResult.to_dict() includes auth_type when set.

        Per §16.7.4: Include auth details only when relevant.
        """
        from src.crawler.fetcher import FetchResult

        result = FetchResult(
            ok=False,
            url="https://captcha.example.com/page",
            status=403,
            reason="auth_required",
            auth_type="captcha",
            estimated_effort="high",
        )

        result_dict = result.to_dict()

        assert result_dict["auth_type"] == "captcha"
        assert result_dict["estimated_effort"] == "high"

    def test_fetch_result_to_dict_omits_auth_type_when_none(self) -> None:
        """Test FetchResult.to_dict() omits auth fields when None.

        Per §16.7.4: Include auth details only when relevant.
        """
        from src.crawler.fetcher import FetchResult

        result = FetchResult(
            ok=True,
            url="https://example.com/page",
            status=200,
        )

        result_dict = result.to_dict()

        # auth_type and estimated_effort should not be in dict when None
        assert "auth_type" not in result_dict
        assert "estimated_effort" not in result_dict


@pytest.mark.unit
class TestEstimateAuthEffort:
    """Tests for _estimate_auth_effort function (§16.7.4)."""

    def test_cloudflare_is_low_effort(self) -> None:
        """Test Cloudflare challenge is estimated as low effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("cloudflare")
        assert effort == "low", f"cloudflare should be 'low' effort, got '{effort}'"

    def test_js_challenge_is_low_effort(self) -> None:
        """Test JS challenge is estimated as low effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("js_challenge")
        assert effort == "low", f"js_challenge should be 'low' effort, got '{effort}'"

    def test_turnstile_is_medium_effort(self) -> None:
        """Test Turnstile is estimated as medium effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("turnstile")
        assert effort == "medium", f"turnstile should be 'medium' effort, got '{effort}'"

    def test_captcha_is_high_effort(self) -> None:
        """Test generic CAPTCHA is estimated as high effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("captcha")
        assert effort == "high", f"captcha should be 'high' effort, got '{effort}'"

    def test_recaptcha_is_high_effort(self) -> None:
        """Test reCAPTCHA is estimated as high effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("recaptcha")
        assert effort == "high", f"recaptcha should be 'high' effort, got '{effort}'"

    def test_hcaptcha_is_high_effort(self) -> None:
        """Test hCaptcha is estimated as high effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("hcaptcha")
        assert effort == "high", f"hcaptcha should be 'high' effort, got '{effort}'"

    def test_login_is_high_effort(self) -> None:
        """Test login requirement is estimated as high effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("login")
        assert effort == "high", f"login should be 'high' effort, got '{effort}'"

    def test_unknown_type_defaults_to_medium(self) -> None:
        """Test unknown challenge type defaults to medium effort."""
        from src.crawler.fetcher import _estimate_auth_effort

        effort = _estimate_auth_effort("unknown_challenge")
        assert effort == "medium", f"unknown type should default to 'medium' effort, got '{effort}'"


@pytest.mark.unit
class TestDatabaseUrlNormalization:
    """Tests for URL normalization used in fetch cache.

    Per §5.1.2: cache_fetch key should be normalized URL.
    """

    def test_normalize_url_lowercase_scheme_and_host(self) -> None:
        """Test URL scheme and host are lowercased."""
        from src.storage.database import Database

        url1 = "HTTPS://EXAMPLE.COM/Path"
        url2 = "https://example.com/Path"

        assert Database._normalize_url(url1) == Database._normalize_url(url2)
        assert "example.com" in Database._normalize_url(url1)

    def test_normalize_url_removes_fragment(self) -> None:
        """Test URL fragment is removed."""
        from src.storage.database import Database

        url1 = "https://example.com/page#section1"
        url2 = "https://example.com/page"

        assert Database._normalize_url(url1) == Database._normalize_url(url2)

    def test_normalize_url_sorts_query_params(self) -> None:
        """Test query parameters are sorted for consistent caching."""
        from src.storage.database import Database

        url1 = "https://example.com/search?b=2&a=1"
        url2 = "https://example.com/search?a=1&b=2"

        assert Database._normalize_url(url1) == Database._normalize_url(url2)

    def test_normalize_url_preserves_path(self) -> None:
        """Test URL path is preserved (case-sensitive)."""
        from src.storage.database import Database

        url = "https://example.com/CaseSensitive/Path"
        normalized = Database._normalize_url(url)

        assert "/CaseSensitive/Path" in normalized

    def test_normalize_url_empty_query_string(self) -> None:
        """Test URL with no query string."""
        from src.storage.database import Database

        url = "https://example.com/page"
        normalized = Database._normalize_url(url)

        assert normalized == "https://example.com/page"


@pytest.mark.unit
class TestHumanBehavior:
    """Tests for human-like behavior simulation (§4.3 - stealth requirements)."""

    def test_random_delay_within_bounds(self) -> None:
        """Test random delay stays within specified bounds."""
        from src.crawler.fetcher import HumanBehavior

        for _ in range(100):
            delay = HumanBehavior.random_delay(0.5, 3.0)
            assert 0.5 <= delay <= 3.0, f"Delay {delay} out of bounds"

    def test_random_delay_default_bounds(self) -> None:
        """Test random delay with default bounds."""
        from src.crawler.fetcher import HumanBehavior

        for _ in range(50):
            delay = HumanBehavior.random_delay()
            assert 0.5 <= delay <= 2.0, f"Delay {delay} out of default bounds"

    def test_scroll_pattern_generation(self) -> None:
        """Test scroll pattern generates reasonable positions.

        For page_height=3000 and viewport_height=1080, scrollable area is 1920px.

        Note: New implementation returns fine-grained inertial animation steps,
        so we get more positions with shorter delays (in seconds, not ms).
        Per §7.1.3.3: Random seed is fixed for determinism.
        """
        import random

        from src.crawler.fetcher import HumanBehavior

        # Fix seed for determinism per §7.1.3.3
        random.seed(42)

        positions = HumanBehavior.scroll_pattern(
            page_height=3000,
            viewport_height=1080,
        )

        # Scrollable area = 3000 - 1080 = 1920px
        # New implementation returns inertial animation steps (more positions)
        assert len(positions) >= 1, f"Expected at least 1 scroll position, got {len(positions)}"

        # Verify positions are within scrollable range and have valid delays
        for idx, (scroll_y, delay) in enumerate(positions):
            assert 0 <= scroll_y <= 1920, (
                f"Position {idx}: scroll_y={scroll_y} out of range [0, 1920]"
            )
            # Delays are now in seconds (converted from ms)
            assert delay >= 0, f"Position {idx}: delay={delay} should be non-negative"

    def test_scroll_pattern_short_page(self) -> None:
        """Test scroll pattern for page shorter than viewport."""
        from src.crawler.fetcher import HumanBehavior

        positions = HumanBehavior.scroll_pattern(
            page_height=500,
            viewport_height=1080,
        )

        # Short page should have no scrolling needed
        assert len(positions) == 0, "Short page should not need scrolling"

    def test_mouse_path_generation(self) -> None:
        """Test mouse path generates smooth bezier curve.

        Path should start near origin and end near destination,
        with small jitter applied to intermediate points.

        Note: The path length is now determined dynamically based on distance,
        not the `steps` parameter (which is ignored by the new implementation).
        """
        from src.crawler.fetcher import HumanBehavior

        start_x, start_y = 100, 100
        end_x, end_y = 500, 400
        steps = 10  # Note: This parameter is now ignored by new implementation

        path = HumanBehavior.mouse_path(
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            steps=steps,
        )

        # Path should have multiple points (dynamically calculated)
        assert len(path) >= 10, f"Path should have at least 10 points, got {len(path)}"
        assert len(path) <= 100, f"Path should have at most 100 points, got {len(path)}"

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

    def test_mouse_path_has_jitter(self) -> None:
        """Test mouse paths are not identical (random jitter)."""
        from src.crawler.fetcher import HumanBehavior

        # Note: steps parameter is ignored by new implementation
        path1 = HumanBehavior.mouse_path(0, 0, 100, 100, steps=5)
        path2 = HumanBehavior.mouse_path(0, 0, 100, 100, steps=5)

        # Paths should differ due to random control points and jitter
        # Note: Paths may have different lengths due to dynamic calculation
        assert path1 != path2, "Paths should differ due to randomness"


@pytest.mark.unit
class TestTorController:
    """Tests for Tor circuit controller (§4.3 - network layer)."""

    def test_tor_controller_initialization(self) -> None:
        """Test TorController initializes correctly."""
        from src.crawler.fetcher import TorController

        controller = TorController()

        assert controller._controller is None  # Not connected yet
        assert len(controller._last_renewal) == 0

    @pytest.mark.asyncio
    async def test_tor_controller_disabled(self, mock_settings: Settings) -> None:
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
    async def test_set_and_get_fetch_cache(self, memory_database: Database) -> None:
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
    async def test_get_fetch_cache_missing_url(self, memory_database: Database) -> None:
        """Test cache miss returns None."""
        db = memory_database

        cached = await db.get_fetch_cache("https://nonexistent.com/page")

        assert cached is None

    @pytest.mark.asyncio
    async def test_fetch_cache_url_normalization(self, memory_database: Database) -> None:
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
    async def test_update_fetch_cache_validation(self, memory_database: Database) -> None:
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
    async def test_invalidate_fetch_cache(self, memory_database: Database) -> None:
        """Test cache invalidation."""
        db = memory_database
        url = "https://example.com/page"

        await db.set_fetch_cache(url, etag='"etag"')
        assert await db.get_fetch_cache(url) is not None

        await db.invalidate_fetch_cache(url)
        assert await db.get_fetch_cache(url) is None

    @pytest.mark.asyncio
    async def test_fetch_cache_with_only_etag(self, memory_database: Database) -> None:
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
    async def test_fetch_cache_with_only_last_modified(self, memory_database: Database) -> None:
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
    async def test_fetch_cache_stats(self, memory_database: Database) -> None:
        """Test fetch cache statistics.

        Setup:
        - a.com: etag only
        - b.com: last_modified only
        - c.com: both etag and last_modified
        """
        db = memory_database

        await db.set_fetch_cache("https://a.com/1", etag='"e1"')
        await db.set_fetch_cache("https://b.com/2", last_modified="Mon, 01 Jan 2024 00:00:00 GMT")
        await db.set_fetch_cache(
            "https://c.com/3", etag='"e3"', last_modified="Tue, 02 Jan 2024 00:00:00 GMT"
        )

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
    async def test_fetch_cache_replace_existing(self, memory_database: Database) -> None:
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


@pytest.mark.unit
class TestHTTPFetcherConditionalHeaders:
    """Tests for HTTPFetcher conditional request headers handling.

    Per fix: URL-specific cached_etag/cached_last_modified should take precedence
    over session-level conditional headers to prevent incorrect ETag usage.
    """

    @pytest.mark.asyncio
    async def test_url_specific_etag_takes_precedence(self, mock_settings: "Settings") -> None:
        """Test that URL-specific cached_etag is not overwritten by session headers.

        TC-CH-01: When cached_etag is provided, session transfer headers should
        not include If-None-Match to prevent overwriting URL-specific value.
        """
        from unittest.mock import patch

        from src.crawler.fetcher import HTTPFetcher

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            # Mock curl_cffi requests (sync function, use MagicMock)
            mock_response = MagicMock()
            mock_response.status_code = 304
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""

            mock_get = MagicMock(return_value=mock_response)

            with patch("src.crawler.session_transfer.get_transfer_headers") as mock_get_transfer:
                # Mock session transfer to return conditional headers only when include_conditional=True
                def mock_get_transfer_side_effect(url: str, include_conditional: bool = True) -> MagicMock:
                    mock_transfer_result = MagicMock()
                    mock_transfer_result.ok = True
                    mock_transfer_result.session_id = "session_123"
                    if include_conditional:
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                            "If-None-Match": '"session-etag"',  # Session-level ETag
                            "If-Modified-Since": "Wed, 01 Jan 2024",
                        }
                    else:
                        # When include_conditional=False, don't include conditional headers
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                        }
                    return mock_transfer_result

                mock_get_transfer.side_effect = mock_get_transfer_side_effect

                with patch("curl_cffi.requests.get", mock_get):
                    fetcher = HTTPFetcher()

                    # Fetch with URL-specific ETag
                    url_specific_etag = '"url-specific-etag"'
                    await fetcher.fetch(
                        "https://example.com/page",
                        cached_etag=url_specific_etag,
                    )

                    # Verify get_transfer_headers was called with include_conditional=False
                    # when cached_etag is provided
                    mock_get_transfer.assert_called_once()
                    call_args = mock_get_transfer.call_args
                    assert call_args[0][0] == "https://example.com/page"
                    assert call_args[1]["include_conditional"] is False, (
                        "include_conditional should be False when cached_etag is provided"
                    )

                    # Verify the actual request used URL-specific ETag
                    # (check mock_get call arguments)
                    assert mock_get.called
                    call_kwargs = mock_get.call_args[1]
                    request_headers = call_kwargs.get("headers", {})
                    assert request_headers.get("If-None-Match") == url_specific_etag, (
                        f"Request should use URL-specific ETag '{url_specific_etag}', "
                        f"got '{request_headers.get('If-None-Match')}'"
                    )

    @pytest.mark.asyncio
    async def test_url_specific_last_modified_takes_precedence(self, mock_settings: "Settings") -> None:
        """Test that URL-specific cached_last_modified is not overwritten.

        TC-CH-02: When cached_last_modified is provided, session transfer headers
        should not include If-Modified-Since.
        """
        from unittest.mock import patch

        from src.crawler.fetcher import HTTPFetcher

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            mock_response = MagicMock()
            mock_response.status_code = 304
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""

            mock_get = MagicMock(return_value=mock_response)

            with patch("src.crawler.session_transfer.get_transfer_headers") as mock_get_transfer:

                def mock_get_transfer_side_effect(url: str, include_conditional: bool = True) -> MagicMock:
                    mock_transfer_result = MagicMock()
                    mock_transfer_result.ok = True
                    mock_transfer_result.session_id = "session_123"
                    if include_conditional:
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                            "If-Modified-Since": "Wed, 01 Jan 2024",  # Session-level
                        }
                    else:
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                        }
                    return mock_transfer_result

                mock_get_transfer.side_effect = mock_get_transfer_side_effect

                with patch("curl_cffi.requests.get", mock_get):
                    fetcher = HTTPFetcher()

                    url_specific_lm = "Thu, 15 Jan 2024 12:00:00 GMT"
                    await fetcher.fetch(
                        "https://example.com/page",
                        cached_last_modified=url_specific_lm,
                    )

                    # Verify include_conditional=False when cached_last_modified is provided
                    call_args = mock_get_transfer.call_args
                    assert call_args[1]["include_conditional"] is False, (
                        "include_conditional should be False when cached_last_modified is provided"
                    )

                    # Verify request uses URL-specific Last-Modified
                    call_kwargs = mock_get.call_args[1]
                    request_headers = call_kwargs.get("headers", {})
                    assert request_headers.get("If-Modified-Since") == url_specific_lm, (
                        f"Request should use URL-specific Last-Modified '{url_specific_lm}', "
                        f"got '{request_headers.get('If-Modified-Since')}'"
                    )

    @pytest.mark.asyncio
    async def test_both_cached_values_exclude_session_conditionals(self, mock_settings: "Settings") -> None:
        """Test that both cached_etag and cached_last_modified exclude session conditionals.

        TC-CH-03: When both are provided, session should not include either conditional header.
        """
        from unittest.mock import patch

        from src.crawler.fetcher import HTTPFetcher

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            mock_response = MagicMock()
            mock_response.status_code = 304
            mock_response.headers = {}
            mock_response.content = b""
            mock_response.text = ""

            mock_get = MagicMock(return_value=mock_response)

            with patch("src.crawler.session_transfer.get_transfer_headers") as mock_get_transfer:

                def mock_get_transfer_side_effect(url: str, include_conditional: bool = True) -> MagicMock:
                    mock_transfer_result = MagicMock()
                    mock_transfer_result.ok = True
                    mock_transfer_result.session_id = "session_123"
                    if include_conditional:
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                            "If-None-Match": '"session-etag"',
                            "If-Modified-Since": "Wed, 01 Jan 2024",
                        }
                    else:
                        mock_transfer_result.headers = {
                            "Cookie": "session=abc123",
                        }
                    return mock_transfer_result

                mock_get_transfer.side_effect = mock_get_transfer_side_effect

                with patch("curl_cffi.requests.get", mock_get):
                    fetcher = HTTPFetcher()

                    await fetcher.fetch(
                        "https://example.com/page",
                        cached_etag='"url-etag"',
                        cached_last_modified="Thu, 15 Jan 2024",
                    )

                    # Verify include_conditional=False
                    call_args = mock_get_transfer.call_args
                    assert call_args[1]["include_conditional"] is False, (
                        "include_conditional should be False when both cached values are provided"
                    )

    @pytest.mark.asyncio
    async def test_no_cached_values_includes_session_conditionals(self, mock_settings: Settings) -> None:
        """Test that session conditional headers are included when no cached values provided.

        TC-CH-04: When cached_etag and cached_last_modified are None, session should
        include conditional headers (backward compatibility).
        """
        from unittest.mock import patch

        from src.crawler.fetcher import HTTPFetcher

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.content = b"<html>content</html>"
            mock_response.text = "<html>content</html>"

            mock_get = MagicMock(return_value=mock_response)

            with patch("src.crawler.session_transfer.get_transfer_headers") as mock_get_transfer:
                mock_transfer_result = MagicMock()
                mock_transfer_result.ok = True
                mock_transfer_result.headers = {
                    "Cookie": "session=abc123",
                    "If-None-Match": '"session-etag"',
                }
                mock_transfer_result.session_id = "session_123"
                mock_get_transfer.return_value = mock_transfer_result

                with patch("curl_cffi.requests.get", mock_get):
                    fetcher = HTTPFetcher()

                    await fetcher.fetch(
                        "https://example.com/page",
                        # No cached_etag or cached_last_modified
                    )

                    # Verify include_conditional=True (default)
                    call_args = mock_get_transfer.call_args
                    assert call_args[1]["include_conditional"] is True, (
                        "include_conditional should be True when no cached values are provided"
                    )


@pytest.mark.unit
class TestBrowserFetcherHumanBehavior:
    """Tests for human-like behavior integration in BrowserFetcher.fetch() (§4.3.4)."""

    @pytest.mark.asyncio
    async def test_fetch_with_human_behavior_enabled(self) -> None:
        """Test BrowserFetcher.fetch() applies human behavior when simulate_human=True.

        Given: simulate_human=True, page has interactive elements
        When: fetch() is called
        Then: simulate_reading() and move_mouse_to_element() are called
        """
        from unittest.mock import patch

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        # Mock page with elements
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.content = AsyncMock(return_value="<html><body><a href='#'>Link</a></body></html>")
        mock_page.query_selector_all = AsyncMock(
            return_value=[MagicMock(evaluate=AsyncMock(return_value="a"))]
        )

        # Mock context
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.add_cookies = AsyncMock()

        # Mock browser
        mock_browser = MagicMock()

        with patch.object(
            fetcher, "_ensure_browser", AsyncMock(return_value=(mock_browser, mock_context))
        ):
            with patch.object(
                fetcher._human_behavior, "simulate_reading", AsyncMock()
            ) as mock_simulate:
                with patch.object(
                    fetcher._human_behavior, "move_mouse_to_element", AsyncMock()
                ) as mock_mouse:
                    with patch(
                        "src.crawler.fetcher._save_content",
                        AsyncMock(return_value="/tmp/page.html"),
                    ):
                        with patch(
                            "src.crawler.fetcher._save_warc",
                            AsyncMock(return_value="/tmp/page.warc.gz"),
                        ):
                            with patch(
                                "src.crawler.fetcher._save_screenshot", AsyncMock(return_value=None)
                            ):
                                with patch(
                                    "src.crawler.fetcher._is_challenge_page", return_value=False
                                ):
                                    from src.crawler.http3_policy import ProtocolVersion

                                    with patch(
                                        "src.crawler.fetcher.detect_protocol_from_playwright_response",
                                        AsyncMock(return_value=ProtocolVersion.HTTP_2),
                                    ):
                                        mock_http3_manager = MagicMock()
                                        mock_http3_manager.get_adjusted_browser_ratio = AsyncMock(
                                            return_value=0.1
                                        )
                                        mock_http3_manager.record_request = AsyncMock()
                                        with patch(
                                            "src.crawler.fetcher.get_http3_policy_manager",
                                            return_value=mock_http3_manager,
                                        ):
                                            with patch(
                                                "src.utils.notification.get_intervention_queue",
                                                return_value=MagicMock(
                                                    get_session_for_domain=AsyncMock(
                                                        return_value=None
                                                    )
                                                ),
                                            ):
                                                with patch(
                                                    "src.crawler.session_transfer.capture_browser_session",
                                                    AsyncMock(return_value=None),
                                                ):
                                                    result = await fetcher.fetch(
                                                        "https://example.com",
                                                        simulate_human=True,
                                                        take_screenshot=False,
                                                    )

                                                    # Verify human behavior was applied
                                                    mock_simulate.assert_called_once()
                                                    mock_mouse.assert_called_once()
                                                    assert result.ok is True

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_with_human_behavior_disabled(self) -> None:
        """Test BrowserFetcher.fetch() skips human behavior when simulate_human=False.

        Given: simulate_human=False
        When: fetch() is called
        Then: simulate_reading() and move_mouse_to_element() are not called
        """
        from unittest.mock import patch

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.content = AsyncMock(return_value="<html><body>Content</body></html>")

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.add_cookies = AsyncMock()

        mock_browser = MagicMock()

        with patch.object(
            fetcher, "_ensure_browser", AsyncMock(return_value=(mock_browser, mock_context))
        ):
            with patch.object(
                fetcher._human_behavior, "simulate_reading", AsyncMock()
            ) as mock_simulate:
                with patch.object(
                    fetcher._human_behavior, "move_mouse_to_element", AsyncMock()
                ) as mock_mouse:
                    with patch(
                        "src.crawler.fetcher._save_content",
                        AsyncMock(return_value="/tmp/page.html"),
                    ):
                        with patch(
                            "src.crawler.fetcher._save_warc",
                            AsyncMock(return_value="/tmp/page.warc.gz"),
                        ):
                            with patch(
                                "src.crawler.fetcher._save_screenshot", AsyncMock(return_value=None)
                            ):
                                with patch(
                                    "src.crawler.fetcher._is_challenge_page", return_value=False
                                ):
                                    from src.crawler.http3_policy import ProtocolVersion

                                    with patch(
                                        "src.crawler.fetcher.detect_protocol_from_playwright_response",
                                        AsyncMock(return_value=ProtocolVersion.HTTP_2),
                                    ):
                                        mock_http3_manager = MagicMock()
                                        mock_http3_manager.get_adjusted_browser_ratio = AsyncMock(
                                            return_value=0.1
                                        )
                                        mock_http3_manager.record_request = AsyncMock()
                                        with patch(
                                            "src.crawler.fetcher.get_http3_policy_manager",
                                            return_value=mock_http3_manager,
                                        ):
                                            with patch(
                                                "src.utils.notification.get_intervention_queue",
                                                return_value=MagicMock(
                                                    get_session_for_domain=AsyncMock(
                                                        return_value=None
                                                    )
                                                ),
                                            ):
                                                with patch(
                                                    "src.crawler.session_transfer.capture_browser_session",
                                                    AsyncMock(return_value=None),
                                                ):
                                                    result = await fetcher.fetch(
                                                        "https://example.com",
                                                        simulate_human=False,
                                                        take_screenshot=False,
                                                    )

                                                    # Verify human behavior was not applied
                                                    mock_simulate.assert_not_called()
                                                    mock_mouse.assert_not_called()
                                                    assert result.ok is True

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_with_no_elements(self) -> None:
        """Test BrowserFetcher.fetch() handles pages with no interactive elements.

        Given: simulate_human=True, page has no interactive elements
        When: fetch() is called
        Then: simulate_reading() is called but move_mouse_to_element() is skipped
        """
        from unittest.mock import patch

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.content = AsyncMock(return_value="<html><body>No links</body></html>")
        mock_page.query_selector_all = AsyncMock(return_value=[])  # No elements

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.add_cookies = AsyncMock()

        mock_browser = MagicMock()

        with patch.object(
            fetcher, "_ensure_browser", AsyncMock(return_value=(mock_browser, mock_context))
        ):
            with patch.object(
                fetcher._human_behavior, "simulate_reading", AsyncMock()
            ) as mock_simulate:
                with patch.object(
                    fetcher._human_behavior, "move_mouse_to_element", AsyncMock()
                ) as mock_mouse:
                    with patch(
                        "src.crawler.fetcher._save_content",
                        AsyncMock(return_value="/tmp/page.html"),
                    ):
                        with patch(
                            "src.crawler.fetcher._save_warc",
                            AsyncMock(return_value="/tmp/page.warc.gz"),
                        ):
                            with patch(
                                "src.crawler.fetcher._save_screenshot", AsyncMock(return_value=None)
                            ):
                                with patch(
                                    "src.crawler.fetcher._is_challenge_page", return_value=False
                                ):
                                    from src.crawler.http3_policy import ProtocolVersion

                                    with patch(
                                        "src.crawler.fetcher.detect_protocol_from_playwright_response",
                                        AsyncMock(return_value=ProtocolVersion.HTTP_2),
                                    ):
                                        mock_http3_manager = MagicMock()
                                        mock_http3_manager.get_adjusted_browser_ratio = AsyncMock(
                                            return_value=0.1
                                        )
                                        mock_http3_manager.record_request = AsyncMock()
                                        with patch(
                                            "src.crawler.fetcher.get_http3_policy_manager",
                                            return_value=mock_http3_manager,
                                        ):
                                            with patch(
                                                "src.utils.notification.get_intervention_queue",
                                                return_value=MagicMock(
                                                    get_session_for_domain=AsyncMock(
                                                        return_value=None
                                                    )
                                                ),
                                            ):
                                                with patch(
                                                    "src.crawler.session_transfer.capture_browser_session",
                                                    AsyncMock(return_value=None),
                                                ):
                                                    result = await fetcher.fetch(
                                                        "https://example.com",
                                                        simulate_human=True,
                                                        take_screenshot=False,
                                                    )

                                                    # Verify simulate_reading was called but mouse movement was skipped
                                                    mock_simulate.assert_called_once()
                                                    mock_mouse.assert_not_called()
                                                    assert result.ok is True

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_with_element_search_exception(self) -> None:
        """Test BrowserFetcher.fetch() handles exceptions during element search gracefully.

        Given: simulate_human=True, query_selector_all raises exception
        When: fetch() is called
        Then: Exception is caught, logged, and normal flow continues
        """
        from unittest.mock import patch

        from src.crawler.fetcher import BrowserFetcher

        fetcher = BrowserFetcher()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
        mock_page.content = AsyncMock(return_value="<html><body>Content</body></html>")
        mock_page.query_selector_all = AsyncMock(side_effect=Exception("Search failed"))

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.add_cookies = AsyncMock()

        mock_browser = MagicMock()

        with patch.object(
            fetcher, "_ensure_browser", AsyncMock(return_value=(mock_browser, mock_context))
        ):
            with patch.object(
                fetcher._human_behavior, "simulate_reading", AsyncMock()
            ) as mock_simulate:
                with patch.object(
                    fetcher._human_behavior, "move_mouse_to_element", AsyncMock()
                ) as mock_mouse:
                    with patch(
                        "src.crawler.fetcher._save_content",
                        AsyncMock(return_value="/tmp/page.html"),
                    ):
                        with patch(
                            "src.crawler.fetcher._save_warc",
                            AsyncMock(return_value="/tmp/page.warc.gz"),
                        ):
                            with patch(
                                "src.crawler.fetcher._save_screenshot", AsyncMock(return_value=None)
                            ):
                                with patch(
                                    "src.crawler.fetcher._is_challenge_page", return_value=False
                                ):
                                    from src.crawler.http3_policy import ProtocolVersion

                                    with patch(
                                        "src.crawler.fetcher.detect_protocol_from_playwright_response",
                                        AsyncMock(return_value=ProtocolVersion.HTTP_2),
                                    ):
                                        mock_http3_manager = MagicMock()
                                        mock_http3_manager.get_adjusted_browser_ratio = AsyncMock(
                                            return_value=0.1
                                        )
                                        mock_http3_manager.record_request = AsyncMock()
                                        with patch(
                                            "src.crawler.fetcher.get_http3_policy_manager",
                                            return_value=mock_http3_manager,
                                        ):
                                            with patch(
                                                "src.utils.notification.get_intervention_queue",
                                                return_value=MagicMock(
                                                    get_session_for_domain=AsyncMock(
                                                        return_value=None
                                                    )
                                                ),
                                            ):
                                                with patch(
                                                    "src.crawler.session_transfer.capture_browser_session",
                                                    AsyncMock(return_value=None),
                                                ):
                                                    result = await fetcher.fetch(
                                                        "https://example.com",
                                                        simulate_human=True,
                                                        take_screenshot=False,
                                                    )

                                                    # Verify simulate_reading was called but mouse movement failed gracefully
                                                    mock_simulate.assert_called_once()
                                                    mock_mouse.assert_not_called()  # Exception prevented call
                                                    assert (
                                                        result.ok is True
                                                    )  # Normal flow continues

        await fetcher.close()


@pytest.mark.unit
class TestFetchUrlCumulativeTimeout:
    """Tests for fetch_url cumulative timeout (O.8 fix).

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |---------|---------------------|---------------------------------------|-----------------|-------|
    | TC-TO-01 | Fast fetch (< max_fetch_time) | Equivalence – normal | Fetch succeeds | - |
    | TC-TO-02 | Slow fetch (> max_fetch_time) | Equivalence – timeout | cumulative_timeout returned | - |
    | TC-TO-03 | max_fetch_time=0 | Boundary – zero | Immediate timeout | Edge case |
    | TC-TO-04 | Policy override of max_fetch_time | Equivalence – override | Uses policy value | - |
    | TC-TO-05 | Multi-stage escalation exceeds timeout | Equivalence – escalation | Aborts mid-escalation | - |
    """

    @pytest.mark.asyncio
    async def test_fetch_completes_within_timeout(self, mock_settings: Settings) -> None:
        """
        TC-TO-01: Fast fetch completes successfully.

        // Given: fetch_url_impl completes quickly
        // When: Calling fetch_url
        // Then: Returns successful result
        """
        from unittest.mock import patch

        mock_settings.crawler.max_fetch_time = 30

        mock_result = {
            "ok": True,
            "url": "https://example.com/page",
            "status": 200,
            "method": "http_client",
        }

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            with patch(
                "src.crawler.fetcher._fetch_url_impl", new=AsyncMock(return_value=mock_result)
            ):
                from src.crawler.fetcher import fetch_url

                result = await fetch_url("https://example.com/page")

                assert result["ok"] is True
                assert result["status"] == 200

    @pytest.mark.asyncio
    async def test_fetch_times_out_returns_cumulative_timeout(self, mock_settings: "Settings") -> None:
        """
        TC-TO-02: Slow fetch exceeds timeout.

        // Given: fetch_url_impl takes longer than max_fetch_time
        // When: Calling fetch_url
        // Then: Returns cumulative_timeout result
        """
        import asyncio
        from unittest.mock import patch

        mock_settings.crawler.max_fetch_time = 1  # 1 second timeout

        async def slow_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            await asyncio.sleep(5)  # Much longer than timeout
            return {"ok": True, "url": args[0]}

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            with patch("src.crawler.fetcher._fetch_url_impl", new=slow_fetch):
                from src.crawler.fetcher import fetch_url

                result = await fetch_url("https://slow.example.com/page")

                assert result["ok"] is False
                assert result["reason"] == "cumulative_timeout"
                assert result["method"] == "timeout"

    @pytest.mark.asyncio
    async def test_fetch_zero_timeout_immediate_failure(self, mock_settings: "Settings") -> None:
        """
        TC-TO-03: Zero timeout boundary.

        // Given: max_fetch_time=0
        // When: Calling fetch_url
        // Then: Returns timeout immediately (or nearly)
        """
        import asyncio
        from unittest.mock import patch

        mock_settings.crawler.max_fetch_time = 0  # Immediate timeout

        async def any_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            await asyncio.sleep(0.1)  # Even a small delay
            return {"ok": True, "url": args[0]}

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            with patch("src.crawler.fetcher._fetch_url_impl", new=any_fetch):
                from src.crawler.fetcher import fetch_url

                result = await fetch_url("https://example.com/page")

                # Zero timeout should cause immediate timeout
                assert result["ok"] is False
                assert result["reason"] == "cumulative_timeout"

    @pytest.mark.asyncio
    async def test_policy_override_max_fetch_time(self, mock_settings: "Settings") -> None:
        """
        TC-TO-04: Policy overrides default max_fetch_time.

        // Given: Policy specifies max_fetch_time=2
        // When: Calling fetch_url with slow implementation
        // Then: Uses policy timeout value
        """
        import asyncio
        from unittest.mock import patch

        mock_settings.crawler.max_fetch_time = 30  # Default is high

        async def medium_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            await asyncio.sleep(3)  # 3 seconds
            return {"ok": True, "url": args[0]}

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            with patch("src.crawler.fetcher._fetch_url_impl", new=medium_fetch):
                from src.crawler.fetcher import fetch_url

                # Policy overrides with shorter timeout
                result = await fetch_url(
                    "https://example.com/page",
                    policy={"max_fetch_time": 1},  # 1 second policy override
                )

                assert result["ok"] is False
                assert result["reason"] == "cumulative_timeout"

    @pytest.mark.asyncio
    async def test_cumulative_timeout_aborts_escalation(self, mock_settings: "Settings") -> None:
        """
        TC-TO-05: Timeout aborts multi-stage escalation.

        // Given: Fetch impl simulates slow multi-stage escalation
        // When: Calling fetch_url with short timeout
        // Then: Escalation is aborted mid-way
        """
        import asyncio
        from unittest.mock import patch

        mock_settings.crawler.max_fetch_time = 2  # Short timeout

        escalation_stages: list[str] = []

        async def multi_stage_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            for stage in ["http", "browser_headless", "browser_headful"]:
                escalation_stages.append(stage)
                await asyncio.sleep(1)  # Each stage takes 1 second
            return {"ok": True, "url": args[0]}

        with patch("src.crawler.fetcher.get_settings", return_value=mock_settings):
            with patch("src.crawler.fetcher._fetch_url_impl", new=multi_stage_fetch):
                from src.crawler.fetcher import fetch_url

                result = await fetch_url("https://example.com/page")

                assert result["ok"] is False
                assert result["reason"] == "cumulative_timeout"
                # Escalation should have been interrupted
                assert len(escalation_stages) < 3  # Not all stages completed
