"""
Session Transfer Utility for Lancet.

Implements §3.1.2 requirement for safe session context transfer:
- Browser → HTTP Client session migration
- Cookie/ETag/UA/Accept-Language transfer
- Same-domain restriction enforcement
- Referer/sec-fetch-* header consistency maintenance

This enables efficient re-visits using HTTP client after initial browser fetch,
reducing exposure and load while maintaining session integrity.
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from src.utils.logging import get_logger
from src.crawler.sec_fetch import (
    NavigationContext,
    SecFetchDest,
    generate_sec_fetch_headers,
    generate_sec_ch_ua_headers,
    _get_registrable_domain,
)

logger = get_logger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================


class CookieData(BaseModel):
    """Cookie data structure for transfer.
    
    Represents a single cookie with its attributes.
    """
    
    model_config = ConfigDict(frozen=False)
    
    name: str = Field(..., description="Cookie name")
    value: str = Field(..., description="Cookie value")
    domain: str = Field(..., description="Cookie domain")
    path: str = Field(default="/", description="Cookie path")
    secure: bool = Field(default=True, description="Secure flag")
    http_only: bool = Field(default=False, description="HttpOnly flag")
    same_site: str = Field(default="Lax", description="SameSite attribute")
    expires: Optional[float] = Field(default=None, description="Expiration as Unix timestamp")
    
    def is_expired(self) -> bool:
        """Check if cookie has expired.
        
        Returns:
            True if cookie has expired.
        """
        if self.expires is None:
            return False  # Session cookie, not expired
        return time.time() > self.expires
    
    def matches_domain(self, target_domain: str) -> bool:
        """Check if cookie is valid for the target domain.
        
        Args:
            target_domain: Domain to check against.
            
        Returns:
            True if cookie is valid for the domain.
        """
        target = target_domain.lower()
        cookie_domain = self.domain.lower().lstrip(".")
        
        # Exact match
        if target == cookie_domain:
            return True
        
        # Subdomain match (cookie domain is suffix)
        if target.endswith("." + cookie_domain):
            return True
        
        return False
    
    def to_header_value(self) -> str:
        """Convert to HTTP Cookie header format.
        
        Returns:
            Cookie as "name=value" string.
        """
        return f"{self.name}={self.value}"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation.
        """
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "sameSite": self.same_site,
            "expires": self.expires,
        }
    
    @classmethod
    def from_playwright_cookie(cls, cookie: dict) -> "CookieData":
        """Create from Playwright cookie format.
        
        Args:
            cookie: Playwright cookie dictionary.
            
        Returns:
            CookieData instance.
        """
        return cls(
            name=cookie.get("name", ""),
            value=cookie.get("value", ""),
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
            secure=cookie.get("secure", True),
            http_only=cookie.get("httpOnly", False),
            same_site=cookie.get("sameSite", "Lax"),
            expires=cookie.get("expires"),
        )


class SessionData(BaseModel):
    """Session data for transfer between browser and HTTP client.
    
    Contains all necessary session context for maintaining a consistent
    browsing session across different fetch methods.
    """
    
    model_config = ConfigDict(frozen=False)
    
    domain: str = Field(..., description="Registrable domain for this session")
    cookies: list[CookieData] = Field(default_factory=list, description="List of cookies")
    etag: Optional[str] = Field(default=None, description="ETag header value")
    last_modified: Optional[str] = Field(default=None, description="Last-Modified header value")
    user_agent: Optional[str] = Field(default=None, description="User-Agent string")
    accept_language: str = Field(default="ja,en-US;q=0.9,en;q=0.8", description="Accept-Language header")
    last_url: Optional[str] = Field(default=None, description="Last visited URL for Referer header")
    created_at: float = Field(default_factory=time.time, description="Session creation timestamp")
    last_used_at: float = Field(default_factory=time.time, description="Last usage timestamp")
    
    def is_valid_for_url(self, url: str) -> bool:
        """Check if session is valid for the target URL.
        
        Implements §3.1.2 same-domain restriction.
        
        Args:
            url: Target URL to check.
            
        Returns:
            True if session can be used for this URL.
        """
        try:
            parsed = urlparse(url)
            target_domain = _get_registrable_domain(parsed.netloc)
            return target_domain == self.domain
        except Exception:
            return False
    
    def get_cookies_for_url(self, url: str) -> list[CookieData]:
        """Get cookies valid for the target URL.
        
        Filters cookies by domain and expiration.
        
        Args:
            url: Target URL.
            
        Returns:
            List of valid cookies.
        """
        parsed = urlparse(url)
        target_domain = parsed.netloc.lower()
        
        valid_cookies = []
        for cookie in self.cookies:
            if cookie.is_expired():
                continue
            if cookie.matches_domain(target_domain):
                valid_cookies.append(cookie)
        
        return valid_cookies
    
    def get_cookie_header(self, url: str) -> Optional[str]:
        """Get Cookie header value for the target URL.
        
        Args:
            url: Target URL.
            
        Returns:
            Cookie header value or None if no cookies.
        """
        valid_cookies = self.get_cookies_for_url(url)
        if not valid_cookies:
            return None
        
        return "; ".join(c.to_header_value() for c in valid_cookies)
    
    def update_from_response(
        self,
        url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> None:
        """Update session data from response headers.
        
        Args:
            url: Response URL.
            etag: ETag header value.
            last_modified: Last-Modified header value.
        """
        self.last_url = url
        self.last_used_at = time.time()
        
        if etag:
            self.etag = etag
        if last_modified:
            self.last_modified = last_modified
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation.
        """
        return {
            "domain": self.domain,
            "cookies": [c.to_dict() for c in self.cookies],
            "etag": self.etag,
            "last_modified": self.last_modified,
            "user_agent": self.user_agent,
            "accept_language": self.accept_language,
            "last_url": self.last_url,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        """Create from dictionary.
        
        Args:
            data: Dictionary representation.
            
        Returns:
            SessionData instance.
        """
        cookies = [
            CookieData(
                name=c.get("name", ""),
                value=c.get("value", ""),
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
                secure=c.get("secure", True),
                http_only=c.get("httpOnly", False),
                same_site=c.get("sameSite", "Lax"),
                expires=c.get("expires"),
            )
            for c in data.get("cookies", [])
        ]
        
        return cls(
            domain=data.get("domain", ""),
            cookies=cookies,
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            user_agent=data.get("user_agent"),
            accept_language=data.get("accept_language", "ja,en-US;q=0.9,en;q=0.8"),
            last_url=data.get("last_url"),
            created_at=data.get("created_at", time.time()),
            last_used_at=data.get("last_used_at", time.time()),
        )


class TransferResult(BaseModel):
    """Result of session transfer operation.
    
    Contains the generated headers and validation status.
    """
    
    model_config = ConfigDict(frozen=False)
    
    ok: bool = Field(..., description="Whether transfer succeeded")
    headers: dict[str, str] = Field(default_factory=dict, description="Generated HTTP headers")
    reason: Optional[str] = Field(default=None, description="Failure reason if ok=False")
    session_id: Optional[str] = Field(default=None, description="Session identifier")
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation.
        """
        return {
            "ok": self.ok,
            "headers": self.headers,
            "reason": self.reason,
            "session_id": self.session_id,
        }


# =============================================================================
# Session Transfer Manager
# =============================================================================

class SessionTransferManager:
    """Manages session transfer between browser and HTTP client.
    
    Implements §3.1.2 session transfer requirements:
    - Safe cookie/header transfer from browser context
    - Same-domain restriction enforcement
    - Sec-Fetch-*/Referer consistency maintenance
    - Session caching and lifecycle management
    """
    
    def __init__(
        self,
        session_ttl_seconds: float = 3600.0,  # 1 hour default
        max_sessions: int = 100,
    ):
        """Initialize session transfer manager.
        
        Args:
            session_ttl_seconds: Session time-to-live in seconds.
            max_sessions: Maximum number of cached sessions.
        """
        self._sessions: dict[str, SessionData] = {}
        self._session_ttl = session_ttl_seconds
        self._max_sessions = max_sessions
        self._lock = None  # Initialized lazily for async
    
    def _generate_session_id(self, domain: str) -> str:
        """Generate unique session ID for domain.
        
        Args:
            domain: Registrable domain.
            
        Returns:
            Session ID string.
        """
        timestamp = str(time.time())
        data = f"{domain}:{timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def _cleanup_expired_sessions(self) -> None:
        """Remove expired sessions from cache."""
        now = time.time()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session.last_used_at > self._session_ttl
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.debug("Expired session removed", session_id=sid)
        
        # Enforce max sessions limit (remove oldest)
        if len(self._sessions) > self._max_sessions:
            sorted_sessions = sorted(
                self._sessions.items(),
                key=lambda x: x[1].last_used_at,
            )
            to_remove = len(self._sessions) - self._max_sessions
            for sid, _ in sorted_sessions[:to_remove]:
                del self._sessions[sid]
                logger.debug("Session evicted (max limit)", session_id=sid)
    
    async def capture_from_browser(
        self,
        context,  # Playwright BrowserContext
        url: str,
        response_headers: Optional[dict[str, str]] = None,
    ) -> Optional[str]:
        """Capture session data from browser context.
        
        Extracts cookies and headers from browser after successful fetch,
        preparing them for transfer to HTTP client.
        
        Args:
            context: Playwright browser context.
            url: The URL that was fetched.
            response_headers: Response headers from the fetch.
            
        Returns:
            Session ID if capture succeeded, None otherwise.
        """
        try:
            parsed = urlparse(url)
            domain = _get_registrable_domain(parsed.netloc)
            
            # Get cookies from browser context
            browser_cookies = await context.cookies()
            
            # Filter cookies for this domain
            cookies = []
            for bc in browser_cookies:
                cookie = CookieData.from_playwright_cookie(bc)
                if cookie.matches_domain(parsed.netloc):
                    cookies.append(cookie)
            
            if not cookies:
                logger.debug(
                    "No cookies found for domain",
                    domain=domain,
                    url=url[:80],
                )
            
            # Extract ETag and Last-Modified from response
            etag = None
            last_modified = None
            if response_headers:
                etag = response_headers.get("etag") or response_headers.get("ETag")
                last_modified = (
                    response_headers.get("last-modified") or
                    response_headers.get("Last-Modified")
                )
            
            # Get user agent from context (if available)
            # Note: Playwright doesn't expose UA directly, use default
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            # Create session data
            session = SessionData(
                domain=domain,
                cookies=cookies,
                etag=etag,
                last_modified=last_modified,
                user_agent=user_agent,
                last_url=url,
            )
            
            # Generate session ID and store
            session_id = self._generate_session_id(domain)
            self._sessions[session_id] = session
            
            # Cleanup expired sessions
            self._cleanup_expired_sessions()
            
            logger.info(
                "Session captured from browser",
                session_id=session_id,
                domain=domain,
                cookie_count=len(cookies),
                has_etag=bool(etag),
                has_last_modified=bool(last_modified),
            )
            
            return session_id
            
        except Exception as e:
            logger.error(
                "Failed to capture session from browser",
                url=url[:80],
                error=str(e),
            )
            return None
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get session by ID.
        
        Args:
            session_id: Session identifier.
            
        Returns:
            SessionData if found and valid, None otherwise.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        
        # Check TTL
        if time.time() - session.last_used_at > self._session_ttl:
            del self._sessions[session_id]
            logger.debug("Session expired on access", session_id=session_id)
            return None
        
        return session
    
    def get_session_for_domain(self, domain: str) -> Optional[tuple[str, SessionData]]:
        """Find a valid session for the given domain.
        
        Args:
            domain: Registrable domain to find session for.
            
        Returns:
            Tuple of (session_id, session_data) if found, None otherwise.
        """
        # Cleanup first
        self._cleanup_expired_sessions()
        
        # Find most recent session for domain
        candidates = [
            (sid, session) for sid, session in self._sessions.items()
            if session.domain == domain
        ]
        
        if not candidates:
            return None
        
        # Return most recently used
        return max(candidates, key=lambda x: x[1].last_used_at)
    
    def generate_transfer_headers(
        self,
        session_id: str,
        target_url: str,
        include_conditional: bool = True,
    ) -> TransferResult:
        """Generate HTTP headers from session data.
        
        Creates headers suitable for HTTP client requests, maintaining
        Referer/sec-fetch-* consistency per §3.1.2.
        
        Args:
            session_id: Session identifier.
            target_url: URL to generate headers for.
            include_conditional: Include If-None-Match/If-Modified-Since headers.
            
        Returns:
            TransferResult with generated headers.
        """
        session = self.get_session(session_id)
        if session is None:
            return TransferResult(
                ok=False,
                reason="session_not_found",
            )
        
        # Validate same-domain restriction
        if not session.is_valid_for_url(target_url):
            logger.warning(
                "Session transfer rejected: domain mismatch",
                session_domain=session.domain,
                target_url=target_url[:80],
            )
            return TransferResult(
                ok=False,
                reason="domain_mismatch",
                session_id=session_id,
            )
        
        headers: dict[str, str] = {}
        
        # Add Cookie header
        cookie_header = session.get_cookie_header(target_url)
        if cookie_header:
            headers["Cookie"] = cookie_header
        
        # Add User-Agent
        if session.user_agent:
            headers["User-Agent"] = session.user_agent
        
        # Add Accept-Language
        headers["Accept-Language"] = session.accept_language
        
        # Add Accept headers (standard browser headers)
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers["Accept-Encoding"] = "gzip, deflate, br"
        
        # Add conditional request headers for 304 support
        if include_conditional:
            if session.etag:
                headers["If-None-Match"] = session.etag
            if session.last_modified:
                headers["If-Modified-Since"] = session.last_modified
        
        # Generate Sec-Fetch-* headers with proper context
        # Use last_url as referer for natural navigation flow
        nav_context = NavigationContext(
            target_url=target_url,
            referer_url=session.last_url,
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        sec_fetch_headers = generate_sec_fetch_headers(nav_context)
        headers.update(sec_fetch_headers.to_dict())
        
        # Generate Sec-CH-UA-* headers
        sec_ch_ua_headers = generate_sec_ch_ua_headers()
        headers.update(sec_ch_ua_headers.to_dict())
        
        # Add Referer header
        if session.last_url:
            headers["Referer"] = session.last_url
        
        # Update session last used time
        session.last_used_at = time.time()
        
        logger.debug(
            "Transfer headers generated",
            session_id=session_id,
            target_url=target_url[:80],
            header_count=len(headers),
            has_cookies=bool(cookie_header),
        )
        
        return TransferResult(
            ok=True,
            headers=headers,
            session_id=session_id,
        )
    
    def update_session_from_response(
        self,
        session_id: str,
        url: str,
        response_headers: dict[str, str],
    ) -> bool:
        """Update session data from HTTP response.
        
        Call after successful HTTP client fetch to keep session in sync.
        
        Args:
            session_id: Session identifier.
            url: Response URL.
            response_headers: Response headers.
            
        Returns:
            True if session was updated.
        """
        session = self.get_session(session_id)
        if session is None:
            return False
        
        # Update ETag and Last-Modified
        etag = response_headers.get("etag") or response_headers.get("ETag")
        last_modified = (
            response_headers.get("last-modified") or
            response_headers.get("Last-Modified")
        )
        
        session.update_from_response(url, etag, last_modified)
        
        # Parse and update cookies from Set-Cookie headers
        # Note: This is simplified - full implementation would parse all Set-Cookie headers
        
        logger.debug(
            "Session updated from response",
            session_id=session_id,
            url=url[:80],
            has_new_etag=bool(etag),
            has_new_last_modified=bool(last_modified),
        )
        
        return True
    
    def invalidate_session(self, session_id: str) -> bool:
        """Invalidate and remove a session.
        
        Args:
            session_id: Session identifier.
            
        Returns:
            True if session was removed.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug("Session invalidated", session_id=session_id)
            return True
        return False
    
    def invalidate_domain_sessions(self, domain: str) -> int:
        """Invalidate all sessions for a domain.
        
        Useful when domain access is blocked or needs fresh session.
        
        Args:
            domain: Registrable domain.
            
        Returns:
            Number of sessions invalidated.
        """
        to_remove = [
            sid for sid, session in self._sessions.items()
            if session.domain == domain
        ]
        for sid in to_remove:
            del self._sessions[sid]
        
        if to_remove:
            logger.info(
                "Domain sessions invalidated",
                domain=domain,
                count=len(to_remove),
            )
        
        return len(to_remove)
    
    def get_session_stats(self) -> dict[str, Any]:
        """Get statistics about cached sessions.
        
        Returns:
            Dictionary with session statistics.
        """
        self._cleanup_expired_sessions()
        
        domains = {}
        for session in self._sessions.values():
            domains[session.domain] = domains.get(session.domain, 0) + 1
        
        return {
            "total_sessions": len(self._sessions),
            "domains": domains,
            "max_sessions": self._max_sessions,
            "ttl_seconds": self._session_ttl,
        }


# =============================================================================
# Global Instance
# =============================================================================

_session_transfer_manager: Optional[SessionTransferManager] = None


def get_session_transfer_manager() -> SessionTransferManager:
    """Get or create the global session transfer manager.
    
    Returns:
        SessionTransferManager instance.
    """
    global _session_transfer_manager
    if _session_transfer_manager is None:
        _session_transfer_manager = SessionTransferManager()
    return _session_transfer_manager


# =============================================================================
# Convenience Functions
# =============================================================================

async def capture_browser_session(
    context,
    url: str,
    response_headers: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Capture session from browser context.
    
    Convenience function for capturing session after browser fetch.
    
    Args:
        context: Playwright browser context.
        url: The URL that was fetched.
        response_headers: Response headers from the fetch.
        
    Returns:
        Session ID if successful.
    """
    manager = get_session_transfer_manager()
    return await manager.capture_from_browser(context, url, response_headers)


def get_transfer_headers(
    url: str,
    session_id: Optional[str] = None,
    include_conditional: bool = True,
) -> TransferResult:
    """Get transfer headers for HTTP client request.
    
    If session_id is not provided, attempts to find a session for the URL's domain.
    
    Args:
        url: Target URL.
        session_id: Optional session ID to use.
        include_conditional: Include conditional request headers.
        
    Returns:
        TransferResult with headers.
    """
    manager = get_session_transfer_manager()
    
    # Find session if not provided
    if session_id is None:
        parsed = urlparse(url)
        domain = _get_registrable_domain(parsed.netloc)
        result = manager.get_session_for_domain(domain)
        if result:
            session_id = result[0]
        else:
            return TransferResult(
                ok=False,
                reason="no_session_for_domain",
            )
    
    return manager.generate_transfer_headers(
        session_id,
        url,
        include_conditional,
    )


def update_session(
    session_id: str,
    url: str,
    response_headers: dict[str, str],
) -> bool:
    """Update session from HTTP response.
    
    Args:
        session_id: Session identifier.
        url: Response URL.
        response_headers: Response headers.
        
    Returns:
        True if updated.
    """
    manager = get_session_transfer_manager()
    return manager.update_session_from_response(session_id, url, response_headers)


def invalidate_session(session_id: str) -> bool:
    """Invalidate a session.
    
    Args:
        session_id: Session identifier.
        
    Returns:
        True if removed.
    """
    manager = get_session_transfer_manager()
    return manager.invalidate_session(session_id)





