"""
Sec-Fetch-* and Sec-CH-UA-* Header Generation for Lancet.

Implements proper security header generation per §4.3 (stealth requirements):

Sec-Fetch-* Headers:
- sec-fetch-site: Indicates the relationship between request initiator and target
- sec-fetch-mode: Indicates the request mode (navigate, cors, no-cors, etc.)
- sec-fetch-dest: Indicates the request destination (document, image, etc.)
- sec-fetch-user: Indicates if user-activated (?1 for user-initiated navigation)

Sec-CH-UA-* Headers (Client Hints):
- sec-ch-ua: Browser brand and major version list
- sec-ch-ua-mobile: Mobile device indicator
- sec-ch-ua-platform: Operating system platform

References:
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Sec-Fetch-Site
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Sec-CH-UA
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
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
    Align `sec-ch-ua*`/`sec-fetch-*`/Referer/Origin with navigation context.
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


# =============================================================================
# Sec-CH-UA-* (Client Hints) Headers
# =============================================================================

class Platform(str, Enum):
    """Platform values for Sec-CH-UA-Platform header."""
    WINDOWS = "Windows"
    MACOS = "macOS"
    LINUX = "Linux"
    ANDROID = "Android"
    IOS = "iOS"
    CHROME_OS = "Chrome OS"
    UNKNOWN = "Unknown"


@dataclass
class BrandVersion:
    """Browser brand with version information.
    
    Used to construct the Sec-CH-UA header which contains a list of
    browser brands with their major versions.
    """
    brand: str
    major_version: str
    full_version: Optional[str] = None
    
    def to_ua_item(self, include_full_version: bool = False) -> str:
        """Format as Sec-CH-UA item.
        
        Args:
            include_full_version: If True, use full version instead of major.
            
        Returns:
            Formatted string like '"Chromium";v="120"'.
        """
        version = self.full_version if include_full_version and self.full_version else self.major_version
        # Properly escape the brand name (quotes need escaping)
        escaped_brand = self.brand.replace('"', '\\"')
        return f'"{escaped_brand}";v="{version}"'


@dataclass
class SecCHUAConfig:
    """Configuration for Sec-CH-UA-* header generation.
    
    Provides realistic Chrome browser identifiers for stealth purposes.
    """
    # Chrome major version (e.g., "120", "121")
    chrome_major_version: str = "120"
    
    # Chrome full version (e.g., "120.0.6099.130")
    chrome_full_version: str = "120.0.6099.130"
    
    # Platform
    platform: Platform = Platform.WINDOWS
    
    # Platform version (e.g., "15.0.0" for Windows 11)
    platform_version: str = "15.0.0"
    
    # Is mobile device
    is_mobile: bool = False
    
    # Additional brands (for GREASE mechanism)
    # Chrome uses "Not_A Brand" as a GREASE brand to prevent fingerprinting
    grease_brand: str = "Not_A Brand"
    grease_version: str = "8"
    
    @property
    def brands(self) -> list[BrandVersion]:
        """Get the list of browser brands.
        
        Chrome sends three brands:
        1. GREASE brand (to prevent fingerprinting)
        2. Chromium (the engine)
        3. Google Chrome (the browser)
        
        Returns:
            List of BrandVersion objects.
        """
        return [
            BrandVersion(
                brand=self.grease_brand,
                major_version=self.grease_version,
                full_version=f"{self.grease_version}.0.0.0",
            ),
            BrandVersion(
                brand="Chromium",
                major_version=self.chrome_major_version,
                full_version=self.chrome_full_version,
            ),
            BrandVersion(
                brand="Google Chrome",
                major_version=self.chrome_major_version,
                full_version=self.chrome_full_version,
            ),
        ]


@dataclass
class SecCHUAHeaders:
    """Generated Sec-CH-UA-* headers for a request.
    
    Implements §4.3 requirement for Client Hints headers:
    - Sec-CH-UA: Browser brand and version list
    - Sec-CH-UA-Mobile: Mobile device indicator
    - Sec-CH-UA-Platform: Operating system platform
    
    Optional headers (only sent when server requests them via Accept-CH):
    - Sec-CH-UA-Platform-Version: OS version
    - Sec-CH-UA-Full-Version-List: Full browser versions
    """
    brands: list[BrandVersion] = field(default_factory=list)
    is_mobile: bool = False
    platform: Platform = Platform.WINDOWS
    platform_version: Optional[str] = None
    
    def to_dict(
        self,
        include_optional: bool = False,
    ) -> dict[str, str]:
        """Convert to header dictionary for HTTP requests.
        
        Args:
            include_optional: Include optional headers that are normally
                             only sent on server request.
        
        Returns:
            Dictionary with Sec-CH-UA-* headers.
        """
        # Format brands list: "Brand1";v="Ver1", "Brand2";v="Ver2", ...
        ua_list = ", ".join(brand.to_ua_item() for brand in self.brands)
        
        headers = {
            "Sec-CH-UA": ua_list,
            "Sec-CH-UA-Mobile": "?1" if self.is_mobile else "?0",
            "Sec-CH-UA-Platform": f'"{self.platform.value}"',
        }
        
        if include_optional:
            if self.platform_version:
                headers["Sec-CH-UA-Platform-Version"] = f'"{self.platform_version}"'
            
            # Full version list
            full_list = ", ".join(
                brand.to_ua_item(include_full_version=True) 
                for brand in self.brands
            )
            headers["Sec-CH-UA-Full-Version-List"] = full_list
        
        return headers


# Default configuration matching Chrome on Windows
_DEFAULT_SEC_CH_UA_CONFIG = SecCHUAConfig()


def generate_sec_ch_ua_headers(
    config: Optional[SecCHUAConfig] = None,
    include_optional: bool = False,
) -> SecCHUAHeaders:
    """Generate Sec-CH-UA-* headers with realistic Chrome values.
    
    Per §4.3: sec-ch-ua* headers should match the browser impersonation
    settings used by curl_cffi to maintain consistency.
    
    Args:
        config: Configuration for header generation. Uses defaults if None.
        include_optional: Include optional headers (platform version, full versions).
        
    Returns:
        SecCHUAHeaders with appropriate values.
    """
    if config is None:
        config = _DEFAULT_SEC_CH_UA_CONFIG
    
    return SecCHUAHeaders(
        brands=config.brands,
        is_mobile=config.is_mobile,
        platform=config.platform,
        platform_version=config.platform_version if include_optional else None,
    )


def update_default_sec_ch_ua_config(
    chrome_version: Optional[str] = None,
    platform: Optional[Platform] = None,
    is_mobile: Optional[bool] = None,
) -> None:
    """Update the default Sec-CH-UA configuration.
    
    This can be called to keep the headers in sync with the actual
    Chrome version being used for browser automation.
    
    Args:
        chrome_version: Chrome full version string (e.g., "121.0.6167.85").
        platform: Target platform.
        is_mobile: Mobile device flag.
    """
    global _DEFAULT_SEC_CH_UA_CONFIG
    
    new_config = SecCHUAConfig(
        chrome_major_version=_DEFAULT_SEC_CH_UA_CONFIG.chrome_major_version,
        chrome_full_version=_DEFAULT_SEC_CH_UA_CONFIG.chrome_full_version,
        platform=_DEFAULT_SEC_CH_UA_CONFIG.platform,
        platform_version=_DEFAULT_SEC_CH_UA_CONFIG.platform_version,
        is_mobile=_DEFAULT_SEC_CH_UA_CONFIG.is_mobile,
    )
    
    if chrome_version:
        # Extract major version from full version
        match = re.match(r"^(\d+)", chrome_version)
        if match:
            new_config = SecCHUAConfig(
                chrome_major_version=match.group(1),
                chrome_full_version=chrome_version,
                platform=new_config.platform,
                platform_version=new_config.platform_version,
                is_mobile=new_config.is_mobile,
            )
    
    if platform is not None:
        new_config = SecCHUAConfig(
            chrome_major_version=new_config.chrome_major_version,
            chrome_full_version=new_config.chrome_full_version,
            platform=platform,
            platform_version=new_config.platform_version,
            is_mobile=new_config.is_mobile,
        )
    
    if is_mobile is not None:
        new_config = SecCHUAConfig(
            chrome_major_version=new_config.chrome_major_version,
            chrome_full_version=new_config.chrome_full_version,
            platform=new_config.platform,
            platform_version=new_config.platform_version,
            is_mobile=is_mobile,
        )
    
    _DEFAULT_SEC_CH_UA_CONFIG = new_config
    logger.debug(
        "Updated default Sec-CH-UA config",
        chrome_version=new_config.chrome_full_version,
        platform=new_config.platform.value,
        is_mobile=new_config.is_mobile,
    )


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


# =============================================================================
# Combined Header Generation
# =============================================================================

def generate_all_security_headers(
    context: NavigationContext,
    sec_ch_ua_config: Optional[SecCHUAConfig] = None,
    include_optional_ch_ua: bool = False,
) -> dict[str, str]:
    """Generate all security headers for a navigation.
    
    Combines Sec-Fetch-* and Sec-CH-UA-* headers for complete stealth.
    Implements §4.3 requirement:
    Align `sec-ch-ua*`/`sec-fetch-*`/Referer/Origin with navigation context.
    
    Args:
        context: Navigation context with target URL, referer, etc.
        sec_ch_ua_config: Configuration for Client Hints headers.
        include_optional_ch_ua: Include optional Client Hints headers.
        
    Returns:
        Dictionary with all security headers.
    """
    headers: dict[str, str] = {}
    
    # Add Sec-Fetch-* headers
    sec_fetch = generate_sec_fetch_headers(context)
    headers.update(sec_fetch.to_dict())
    
    # Add Sec-CH-UA-* headers
    sec_ch_ua = generate_sec_ch_ua_headers(
        config=sec_ch_ua_config,
        include_optional=include_optional_ch_ua,
    )
    headers.update(sec_ch_ua.to_dict(include_optional=include_optional_ch_ua))
    
    # Add Referer if provided
    if context.referer_url:
        headers["Referer"] = context.referer_url
    
    return headers


def generate_complete_navigation_headers(
    target_url: str,
    referer_url: Optional[str] = None,
    is_user_initiated: bool = True,
) -> dict[str, str]:
    """Convenience function to generate complete headers for document navigation.
    
    This is the recommended function for most fetch operations as it
    generates all required security headers in one call.
    
    Args:
        target_url: The URL being navigated to.
        referer_url: The referer URL (if any).
        is_user_initiated: Whether this is a user-initiated navigation.
        
    Returns:
        Dictionary with all security headers for navigation.
    """
    context = NavigationContext(
        target_url=target_url,
        referer_url=referer_url,
        is_user_initiated=is_user_initiated,
        destination=SecFetchDest.DOCUMENT,
    )
    
    return generate_all_security_headers(context)

