"""
Unit tests for Session Transfer Utility (§3.1.2).

Tests the session transfer functionality for moving browser session context
to HTTP client requests, including:
- Cookie capture and transfer
- Same-domain restriction enforcement
- Sec-Fetch-*/Referer header consistency
- Session lifecycle management
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawler.session_transfer import (
    CookieData,
    SessionData,
    TransferResult,
    SessionTransferManager,
    get_session_transfer_manager,
    capture_browser_session,
    get_transfer_headers,
    update_session,
    invalidate_session,
)


# =============================================================================
# CookieData Tests
# =============================================================================

class TestCookieData:
    """Tests for CookieData class."""
    
    def test_cookie_not_expired_session_cookie(self):
        """Session cookies (no expires) should not be expired."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
            expires=None,
        )
        assert not cookie.is_expired()
    
    def test_cookie_not_expired_future(self):
        """Cookies with future expiration should not be expired."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
            expires=time.time() + 3600,  # 1 hour in future
        )
        assert not cookie.is_expired()
    
    def test_cookie_expired_past(self):
        """Cookies with past expiration should be expired."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
            expires=time.time() - 3600,  # 1 hour ago
        )
        assert cookie.is_expired()
    
    def test_cookie_matches_exact_domain(self):
        """Cookie should match exact domain."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
        )
        assert cookie.matches_domain("example.com")
    
    def test_cookie_matches_subdomain(self):
        """Cookie should match subdomains."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain=".example.com",  # Leading dot for subdomain matching
        )
        assert cookie.matches_domain("www.example.com")
        assert cookie.matches_domain("api.example.com")
        assert cookie.matches_domain("example.com")
    
    def test_cookie_no_match_different_domain(self):
        """Cookie should not match different domains."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
        )
        assert not cookie.matches_domain("other.com")
        assert not cookie.matches_domain("notexample.com")
    
    def test_cookie_to_header_value(self):
        """Cookie should format correctly for Cookie header."""
        cookie = CookieData(
            name="session_id",
            value="abc123",
            domain="example.com",
        )
        assert cookie.to_header_value() == "session_id=abc123"
    
    def test_cookie_from_playwright(self):
        """Cookie should be created from Playwright format."""
        playwright_cookie = {
            "name": "csrf_token",
            "value": "xyz789",
            "domain": ".example.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Strict",
            "expires": 1735689600.0,
        }
        cookie = CookieData.from_playwright_cookie(playwright_cookie)
        
        assert cookie.name == "csrf_token"
        assert cookie.value == "xyz789"
        assert cookie.domain == ".example.com"
        assert cookie.secure is True
        assert cookie.http_only is True
        assert cookie.same_site == "Strict"


# =============================================================================
# SessionData Tests
# =============================================================================

class TestSessionData:
    """Tests for SessionData class."""
    
    def test_session_valid_for_same_domain(self):
        """Session should be valid for same registrable domain."""
        session = SessionData(domain="example.com")
        
        assert session.is_valid_for_url("https://example.com/page")
        assert session.is_valid_for_url("https://www.example.com/page")
        assert session.is_valid_for_url("https://api.example.com/v1/data")
    
    def test_session_invalid_for_different_domain(self):
        """Session should be invalid for different domain (§3.1.2 restriction)."""
        session = SessionData(domain="example.com")
        
        assert not session.is_valid_for_url("https://other.com/page")
        assert not session.is_valid_for_url("https://example.org/page")
    
    def test_get_cookies_filters_by_domain(self):
        """get_cookies_for_url should filter by domain."""
        session = SessionData(
            domain="example.com",
            cookies=[
                CookieData(name="c1", value="v1", domain="example.com"),
                CookieData(name="c2", value="v2", domain="other.com"),
            ],
        )
        
        cookies = session.get_cookies_for_url("https://example.com/page")
        assert len(cookies) == 1
        assert cookies[0].name == "c1"
    
    def test_get_cookies_filters_expired(self):
        """get_cookies_for_url should filter expired cookies."""
        session = SessionData(
            domain="example.com",
            cookies=[
                CookieData(
                    name="valid",
                    value="v1",
                    domain="example.com",
                    expires=time.time() + 3600,
                ),
                CookieData(
                    name="expired",
                    value="v2",
                    domain="example.com",
                    expires=time.time() - 3600,
                ),
            ],
        )
        
        cookies = session.get_cookies_for_url("https://example.com/page")
        assert len(cookies) == 1
        assert cookies[0].name == "valid"
    
    def test_get_cookie_header(self):
        """get_cookie_header should format multiple cookies."""
        session = SessionData(
            domain="example.com",
            cookies=[
                CookieData(name="a", value="1", domain="example.com"),
                CookieData(name="b", value="2", domain="example.com"),
            ],
        )
        
        header = session.get_cookie_header("https://example.com/page")
        assert header is not None
        assert "a=1" in header
        assert "b=2" in header
        assert "; " in header
    
    def test_get_cookie_header_none_if_no_cookies(self):
        """get_cookie_header should return None if no valid cookies."""
        session = SessionData(domain="example.com", cookies=[])
        
        header = session.get_cookie_header("https://example.com/page")
        assert header is None
    
    def test_update_from_response(self):
        """update_from_response should update session data."""
        session = SessionData(domain="example.com")
        original_used_at = session.last_used_at
        
        time.sleep(0.01)  # Ensure time difference
        session.update_from_response(
            url="https://example.com/page",
            etag='"abc123"',
            last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
        )
        
        assert session.last_url == "https://example.com/page"
        assert session.etag == '"abc123"'
        assert session.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT"
        assert session.last_used_at > original_used_at
    
    def test_serialization_round_trip(self):
        """Session should serialize and deserialize correctly."""
        original = SessionData(
            domain="example.com",
            cookies=[
                CookieData(name="test", value="val", domain="example.com"),
            ],
            etag='"xyz"',
            last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
            user_agent="Test UA",
            accept_language="en-US",
            last_url="https://example.com/last",
        )
        
        data = original.to_dict()
        restored = SessionData.from_dict(data)
        
        assert restored.domain == original.domain
        assert len(restored.cookies) == 1
        assert restored.cookies[0].name == "test"
        assert restored.etag == original.etag
        assert restored.last_modified == original.last_modified
        assert restored.user_agent == original.user_agent


# =============================================================================
# SessionTransferManager Tests
# =============================================================================

class TestSessionTransferManager:
    """Tests for SessionTransferManager class."""
    
    def test_generate_transfer_headers_success(self):
        """Should generate headers from valid session."""
        manager = SessionTransferManager()
        
        # Create session manually
        session = SessionData(
            domain="example.com",
            cookies=[
                CookieData(name="auth", value="token123", domain="example.com"),
            ],
            etag='"etag-value"',
            last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
            user_agent="Test Browser",
            accept_language="ja,en;q=0.9",
            last_url="https://example.com/previous",
        )
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        result = manager.generate_transfer_headers(
            session_id,
            "https://example.com/new-page",
        )
        
        assert result.ok is True
        assert result.session_id == session_id
        assert "Cookie" in result.headers
        assert "auth=token123" in result.headers["Cookie"]
        assert "If-None-Match" in result.headers
        assert result.headers["If-None-Match"] == '"etag-value"'
        assert "If-Modified-Since" in result.headers
        assert "Sec-Fetch-Site" in result.headers
        assert "Sec-Fetch-Mode" in result.headers
        assert "Sec-CH-UA" in result.headers
        assert "Referer" in result.headers
    
    def test_generate_transfer_headers_domain_mismatch(self):
        """Should reject transfer to different domain (§3.1.2)."""
        manager = SessionTransferManager()
        
        session = SessionData(domain="example.com")
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        result = manager.generate_transfer_headers(
            session_id,
            "https://other.com/page",  # Different domain
        )
        
        assert result.ok is False
        assert result.reason == "domain_mismatch"
    
    def test_generate_transfer_headers_session_not_found(self):
        """Should handle missing session gracefully."""
        manager = SessionTransferManager()
        
        result = manager.generate_transfer_headers(
            "nonexistent-session",
            "https://example.com/page",
        )
        
        assert result.ok is False
        assert result.reason == "session_not_found"
    
    def test_session_expiration(self):
        """Expired sessions should not be returned."""
        manager = SessionTransferManager(session_ttl_seconds=0.01)  # Very short TTL
        
        session = SessionData(domain="example.com")
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        # Session should be available immediately
        assert manager.get_session(session_id) is not None
        
        # Wait for expiration
        time.sleep(0.02)
        
        # Session should be expired
        assert manager.get_session(session_id) is None
    
    def test_get_session_for_domain(self):
        """Should find most recent session for domain."""
        manager = SessionTransferManager()
        
        # Create two sessions for same domain
        session1 = SessionData(domain="example.com")
        session1.last_used_at = time.time() - 100
        
        session2 = SessionData(domain="example.com")
        session2.last_used_at = time.time()
        
        sid1 = manager._generate_session_id("example.com")
        sid2 = manager._generate_session_id("example.com")
        manager._sessions[sid1] = session1
        manager._sessions[sid2] = session2
        
        result = manager.get_session_for_domain("example.com")
        assert result is not None
        session_id, session = result
        assert session.last_used_at == session2.last_used_at  # Most recent
    
    def test_invalidate_session(self):
        """Should remove session on invalidation."""
        manager = SessionTransferManager()
        
        session = SessionData(domain="example.com")
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        assert manager.invalidate_session(session_id) is True
        assert manager.get_session(session_id) is None
    
    def test_invalidate_domain_sessions(self):
        """Should remove all sessions for a domain."""
        manager = SessionTransferManager()
        
        # Create sessions for two domains
        for domain in ["example.com", "example.com", "other.com"]:
            session = SessionData(domain=domain)
            sid = manager._generate_session_id(domain)
            manager._sessions[sid] = session
        
        # Invalidate example.com sessions
        count = manager.invalidate_domain_sessions("example.com")
        
        assert count == 2
        assert len([s for s in manager._sessions.values() if s.domain == "example.com"]) == 0
        assert len([s for s in manager._sessions.values() if s.domain == "other.com"]) == 1
    
    def test_max_sessions_enforcement(self):
        """Should enforce max sessions limit."""
        manager = SessionTransferManager(max_sessions=3)
        
        # Create more sessions than limit
        for i in range(5):
            session = SessionData(domain=f"domain{i}.com")
            session.last_used_at = time.time() - i  # Older sessions first
            sid = f"session{i}"
            manager._sessions[sid] = session
        
        # Trigger cleanup
        manager._cleanup_expired_sessions()
        
        assert len(manager._sessions) == 3
    
    def test_update_session_from_response(self):
        """Should update session with response data."""
        manager = SessionTransferManager()
        
        session = SessionData(domain="example.com")
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        success = manager.update_session_from_response(
            session_id,
            "https://example.com/new-page",
            {"ETag": '"new-etag"', "Last-Modified": "Thu, 02 Jan 2025 00:00:00 GMT"},
        )
        
        assert success is True
        updated = manager.get_session(session_id)
        assert updated.last_url == "https://example.com/new-page"
        assert updated.etag == '"new-etag"'
        assert updated.last_modified == "Thu, 02 Jan 2025 00:00:00 GMT"
    
    def test_session_stats(self):
        """Should return accurate session statistics."""
        manager = SessionTransferManager(max_sessions=10, session_ttl_seconds=3600)
        
        # Create sessions for different domains
        for domain in ["a.com", "a.com", "b.com"]:
            session = SessionData(domain=domain)
            sid = manager._generate_session_id(domain)
            manager._sessions[sid] = session
        
        stats = manager.get_session_stats()
        
        assert stats["total_sessions"] == 3
        assert stats["domains"]["a.com"] == 2
        assert stats["domains"]["b.com"] == 1
        assert stats["max_sessions"] == 10
        assert stats["ttl_seconds"] == 3600


# =============================================================================
# Browser Session Capture Tests
# =============================================================================

@pytest.mark.asyncio
class TestBrowserSessionCapture:
    """Tests for browser session capture functionality."""
    
    async def test_capture_from_browser_context(self):
        """Should capture session from Playwright browser context."""
        manager = SessionTransferManager()
        
        # Mock Playwright browser context
        mock_context = AsyncMock()
        mock_context.cookies.return_value = [
            {
                "name": "session",
                "value": "abc123",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
                "expires": time.time() + 3600,
            },
            {
                "name": "csrf",
                "value": "xyz789",
                "domain": "example.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Strict",
                "expires": None,
            },
        ]
        
        response_headers = {
            "ETag": '"response-etag"',
            "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
        }
        
        session_id = await manager.capture_from_browser(
            mock_context,
            "https://www.example.com/page",
            response_headers,
        )
        
        assert session_id is not None
        
        session = manager.get_session(session_id)
        assert session is not None
        assert session.domain == "example.com"
        assert len(session.cookies) == 2
        assert session.etag == '"response-etag"'
        assert session.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT"
    
    async def test_capture_with_no_cookies(self):
        """Should handle context with no cookies."""
        manager = SessionTransferManager()
        
        mock_context = AsyncMock()
        mock_context.cookies.return_value = []
        
        session_id = await manager.capture_from_browser(
            mock_context,
            "https://example.com/page",
            {},
        )
        
        assert session_id is not None
        session = manager.get_session(session_id)
        assert session is not None
        assert len(session.cookies) == 0


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_session_transfer_manager_singleton(self):
        """get_session_transfer_manager should return singleton."""
        manager1 = get_session_transfer_manager()
        manager2 = get_session_transfer_manager()
        
        assert manager1 is manager2
    
    def test_get_transfer_headers_with_session_id(self):
        """get_transfer_headers should work with session ID."""
        manager = get_session_transfer_manager()
        
        # Create a session
        session = SessionData(
            domain="test-example.com",
            cookies=[
                CookieData(name="test", value="value", domain="test-example.com"),
            ],
        )
        session_id = "test-session-id"
        manager._sessions[session_id] = session
        
        result = get_transfer_headers(
            "https://test-example.com/page",
            session_id=session_id,
        )
        
        assert result.ok is True
        assert "Cookie" in result.headers
        
        # Cleanup
        manager.invalidate_session(session_id)
    
    def test_get_transfer_headers_finds_domain_session(self):
        """get_transfer_headers should find session by domain if ID not provided."""
        manager = get_session_transfer_manager()
        
        # Create a session
        session = SessionData(domain="auto-find.com")
        session_id = manager._generate_session_id("auto-find.com")
        manager._sessions[session_id] = session
        
        result = get_transfer_headers(
            "https://auto-find.com/page",
            session_id=None,  # Should auto-find
        )
        
        assert result.ok is True
        
        # Cleanup
        manager.invalidate_domain_sessions("auto-find.com")
    
    def test_get_transfer_headers_no_session(self):
        """get_transfer_headers should fail gracefully if no session."""
        result = get_transfer_headers(
            "https://no-session-domain.com/page",
            session_id=None,
        )
        
        assert result.ok is False
        assert result.reason == "no_session_for_domain"


# =============================================================================
# Sec-Fetch Header Consistency Tests
# =============================================================================

class TestSecFetchHeaderConsistency:
    """Tests for sec-fetch-* header consistency in transfers."""
    
    def test_headers_include_sec_fetch(self):
        """Transfer headers should include proper Sec-Fetch-* headers."""
        manager = SessionTransferManager()
        
        session = SessionData(
            domain="example.com",
            last_url="https://example.com/previous",
        )
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        result = manager.generate_transfer_headers(
            session_id,
            "https://example.com/next",
        )
        
        assert result.ok is True
        headers = result.headers
        
        # Check Sec-Fetch-* headers are present
        assert "Sec-Fetch-Site" in headers
        assert "Sec-Fetch-Mode" in headers
        assert "Sec-Fetch-Dest" in headers
        
        # Same-origin navigation from previous page
        assert headers["Sec-Fetch-Site"] == "same-origin"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Sec-Fetch-Dest"] == "document"
    
    def test_headers_include_sec_ch_ua(self):
        """Transfer headers should include Sec-CH-UA-* headers."""
        manager = SessionTransferManager()
        
        session = SessionData(domain="example.com")
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        result = manager.generate_transfer_headers(
            session_id,
            "https://example.com/page",
        )
        
        headers = result.headers
        
        # Check Sec-CH-UA-* headers are present
        assert "Sec-CH-UA" in headers
        assert "Sec-CH-UA-Mobile" in headers
        assert "Sec-CH-UA-Platform" in headers
    
    def test_referer_from_last_url(self):
        """Transfer headers should use session's last_url as Referer."""
        manager = SessionTransferManager()
        
        session = SessionData(
            domain="example.com",
            last_url="https://example.com/source",
        )
        session_id = manager._generate_session_id("example.com")
        manager._sessions[session_id] = session
        
        result = manager.generate_transfer_headers(
            session_id,
            "https://example.com/target",
        )
        
        assert result.headers["Referer"] == "https://example.com/source"



