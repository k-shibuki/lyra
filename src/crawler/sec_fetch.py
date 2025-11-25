"""
Sec-Fetch-* Header Generation for Lancet.

Implements proper Sec-Fetch-* header generation per §4.3 (stealth requirements):
- sec-fetch-site: Indicates the relationship between request initiator and target
- sec-fetch-mode: Indicates the request mode (navigate, cors, no-cors, etc.)
- sec-fetch-dest: Indicates the request destination (document, image, etc.)
- sec-fetch-user: Indicates if user-activated (?1 for user-initiated navigation)

Reference: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Sec-Fetch-Site
"""

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from src.utils.logging import get_logger

logger = get_logger(__name__)


class SecFetchSite(str, Enum):
    """Sec-Fetch-Site header values.
    
    Indicates the relationship between origin of request initiator and target.
    """
    NONE = "none"           # User-initiated (address bar, bookmark)
    SAME_ORIGIN = "same-origin"  # Same scheme + host + port
    SAME_SITE = "same-site"      # Same registrable domain (e.g., a.example.com -> b.example.com)
    CROSS_SITE = "cross-site"    # Different registrable domain


class SecFetchMode(str, Enum):
    """Sec-Fetch-Mode header values.
    
    Indicates the mode of the request.
    """
    NAVIGATE = "navigate"     # Navigation request (document load)
    CORS = "cors"             # CORS request
    NO_CORS = "no-cors"       # no-cors request
    SAME_ORIGIN = "same-origin"  # Same-origin request
    WEBSOCKET = "websocket"   # WebSocket connection


class SecFetchDest(str, Enum):
    """Sec-Fetch-Dest header values.
    
    Indicates the destination of the request.
    """
    DOCUMENT = "document"     # Main frame document
    IFRAME = "iframe"         # iframe
    EMBED = "embed"           # <embed>
    OBJECT = "object"         # <object>
    IMAGE = "image"           # Image resource
    SCRIPT = "script"         # Script resource
    STYLE = "style"           # Stylesheet
    FONT = "font"             # Font resource
    AUDIO = "audio"           # Audio resource
    VIDEO = "video"           # Video resource
    WORKER = "worker"         # Web Worker
    MANIFEST = "manifest"     # Web Manifest
    EMPTY = "empty"           # Fetch/XHR


@dataclass
class NavigationContext:
    """Context information for navigation.
    
    Used to determine appropriate Sec-Fetch-* headers based on the
    navigation scenario (SERP -> article, direct navigation, etc.).
    """
    target_url: str
    referer_url: str | None = None
    is_user_initiated: bool = True
    destination: SecFetchDest = SecFetchDest.DOCUMENT
    is_download: bool = False


@dataclass
class SecFetchHeaders:
    """Generated Sec-Fetch-* headers for a request.
    
    Implements §4.3 requirement:
    `sec-ch-ua*`/`sec-fetch-*`/Referer/Origin を遷移コンテキストと整合
    """
    site: SecFetchSite
    mode: SecFetchMode
    dest: SecFetchDest
    user: bool = True  # ?1 for user-initiated
    
    def to_dict(self) -> dict[str, str]:
        """Convert to header dictionary for HTTP requests.
        
        Returns:
            Dictionary with Sec-Fetch-* headers.
        """
        headers = {
            "Sec-Fetch-Site": self.site.value,
            "Sec-Fetch-Mode": self.mode.value,
            "Sec-Fetch-Dest": self.dest.value,
        }
        
        # Sec-Fetch-User is only set for user-initiated navigations
        if self.user and self.mode == SecFetchMode.NAVIGATE:
            headers["Sec-Fetch-User"] = "?1"
        
        return headers


def _get_registrable_domain(hostname: str) -> str:
    """Extract the registrable domain (eTLD+1) from a hostname.
    
    For proper same-site detection, we need to compare registrable domains.
    This is a simplified implementation - a full implementation would use
    the Public Suffix List.
    
    Args:
        hostname: The hostname to extract domain from.
        
    Returns:
        Registrable domain (simplified: last two parts of hostname).
    """
    # Remove port if present
    if ":" in hostname:
        hostname = hostname.split(":")[0]
    
    # Remove trailing dot (FQDN notation)
    hostname = hostname.rstrip(".")
    
    parts = hostname.lower().split(".")
    
    # Handle special cases
    if len(parts) <= 2:
        return hostname.lower()
    
    # Common multi-part TLDs
    multi_part_tlds = {
        "co.uk", "co.jp", "com.au", "com.br", "co.nz",
        "go.jp", "or.jp", "ne.jp", "ac.jp", "ed.jp",
        "org.uk", "gov.uk", "ac.uk",
    }
    
    # Check for multi-part TLD
    last_two = ".".join(parts[-2:])
    if last_two in multi_part_tlds:
        # eTLD+1 = domain.co.uk
        if len(parts) >= 3:
            return ".".join(parts[-3:])
        return hostname.lower()
    
    # Standard TLD: return domain.tld
    return ".".join(parts[-2:])


def _determine_fetch_site(
    target_url: str,
    referer_url: str | None,
) -> SecFetchSite:
    """Determine the Sec-Fetch-Site value based on URLs.
    
    Args:
        target_url: The URL being fetched.
        referer_url: The referer URL (if any).
        
    Returns:
        Appropriate SecFetchSite value.
    """
    # No referer = direct navigation (address bar, bookmark, etc.)
    if not referer_url:
        return SecFetchSite.NONE
    
    try:
        target_parsed = urlparse(target_url)
        referer_parsed = urlparse(referer_url)
        
        target_host = target_parsed.netloc.lower()
        referer_host = referer_parsed.netloc.lower()
        target_scheme = target_parsed.scheme.lower()
        referer_scheme = referer_parsed.scheme.lower()
        
        # Same-origin: same scheme + host + port
        if (target_scheme == referer_scheme and 
            target_host == referer_host):
            return SecFetchSite.SAME_ORIGIN
        
        # Same-site: same registrable domain
        target_domain = _get_registrable_domain(target_host)
        referer_domain = _get_registrable_domain(referer_host)
        
        if target_domain == referer_domain:
            return SecFetchSite.SAME_SITE
        
        # Cross-site: different registrable domains
        return SecFetchSite.CROSS_SITE
        
    except Exception as e:
        logger.debug("Error determining fetch site", error=str(e))
        # Default to cross-site for safety
        return SecFetchSite.CROSS_SITE


def generate_sec_fetch_headers(
    context: NavigationContext,
) -> SecFetchHeaders:
    """Generate Sec-Fetch-* headers for a navigation.
    
    Implements natural header generation per §4.3:
    - SERP → article transitions should look like cross-site navigation
    - Same-domain navigation should look like same-origin/same-site
    - Direct URL access should have Sec-Fetch-Site: none
    
    Args:
        context: Navigation context with target URL, referer, etc.
        
    Returns:
        SecFetchHeaders with appropriate values.
    """
    # Determine Sec-Fetch-Site
    site = _determine_fetch_site(context.target_url, context.referer_url)
    
    # Determine Sec-Fetch-Mode (document navigation = navigate)
    if context.destination == SecFetchDest.DOCUMENT:
        mode = SecFetchMode.NAVIGATE
    elif context.destination in (SecFetchDest.IMAGE, SecFetchDest.SCRIPT, 
                                  SecFetchDest.STYLE, SecFetchDest.FONT):
        mode = SecFetchMode.NO_CORS
    else:
        mode = SecFetchMode.NAVIGATE
    
    return SecFetchHeaders(
        site=site,
        mode=mode,
        dest=context.destination,
        user=context.is_user_initiated,
    )


def generate_headers_for_serp_click(
    target_url: str,
    serp_url: str,
) -> dict[str, str]:
    """Generate headers for clicking a SERP result.
    
    Per §4.3: SERP → article transitions should maintain natural header flow.
    
    Args:
        target_url: The article URL being clicked.
        serp_url: The SERP page URL (referer).
        
    Returns:
        Dictionary with all navigation headers including Sec-Fetch-*.
    """
    context = NavigationContext(
        target_url=target_url,
        referer_url=serp_url,
        is_user_initiated=True,
        destination=SecFetchDest.DOCUMENT,
    )
    
    sec_fetch = generate_sec_fetch_headers(context)
    headers = sec_fetch.to_dict()
    
    # Add Referer header (already handled by caller in most cases)
    # but we include it here for completeness
    if serp_url:
        headers["Referer"] = serp_url
    
    return headers


def generate_headers_for_direct_navigation(
    target_url: str,
) -> dict[str, str]:
    """Generate headers for direct URL navigation.
    
    Simulates user typing URL in address bar or opening from bookmark.
    
    Args:
        target_url: The URL being navigated to directly.
        
    Returns:
        Dictionary with Sec-Fetch-* headers for direct navigation.
    """
    context = NavigationContext(
        target_url=target_url,
        referer_url=None,  # No referer for direct navigation
        is_user_initiated=True,
        destination=SecFetchDest.DOCUMENT,
    )
    
    sec_fetch = generate_sec_fetch_headers(context)
    return sec_fetch.to_dict()


def generate_headers_for_internal_link(
    target_url: str,
    source_url: str,
) -> dict[str, str]:
    """Generate headers for following an internal link.
    
    Used when navigating within the same site (e.g., article -> related article).
    
    Args:
        target_url: The target page URL.
        source_url: The current page URL (referer).
        
    Returns:
        Dictionary with Sec-Fetch-* headers for internal navigation.
    """
    context = NavigationContext(
        target_url=target_url,
        referer_url=source_url,
        is_user_initiated=True,
        destination=SecFetchDest.DOCUMENT,
    )
    
    sec_fetch = generate_sec_fetch_headers(context)
    headers = sec_fetch.to_dict()
    headers["Referer"] = source_url
    
    return headers

