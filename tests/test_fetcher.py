"""
Tests for URL fetcher module.
"""

import gzip
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from warcio.archiveiterator import ArchiveIterator


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


class TestIsChallengePageFunction:
    """Tests for challenge page detection."""

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

