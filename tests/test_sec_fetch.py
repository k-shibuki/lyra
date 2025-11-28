"""
Tests for Sec-Fetch-* and Sec-CH-UA-* header generation (§4.3 - stealth requirements).

Covers:
- SecFetchSite determination (none, same-origin, same-site, cross-site)
- SecFetchHeaders generation for various navigation contexts
- Helper functions for SERP clicks, direct navigation, internal links
- Edge cases (ports, subdomains, multi-part TLDs)
- Sec-CH-UA-* Client Hints headers
"""

import pytest

from src.crawler.sec_fetch import (
    SecFetchSite,
    SecFetchMode,
    SecFetchDest,
    SecFetchHeaders,
    NavigationContext,
    generate_sec_fetch_headers,
    generate_headers_for_serp_click,
    generate_headers_for_direct_navigation,
    generate_headers_for_internal_link,
    _get_registrable_domain,
    _determine_fetch_site,
    # Sec-CH-UA-* related imports
    Platform,
    BrandVersion,
    SecCHUAConfig,
    SecCHUAHeaders,
    generate_sec_ch_ua_headers,
    generate_all_security_headers,
    generate_complete_navigation_headers,
    update_default_sec_ch_ua_config,
)


@pytest.mark.unit
class TestSecFetchSiteEnums:
    """Tests for Sec-Fetch-* enum values."""

    def test_sec_fetch_site_values(self):
        """Test SecFetchSite enum has correct string values."""
        assert SecFetchSite.NONE.value == "none"
        assert SecFetchSite.SAME_ORIGIN.value == "same-origin"
        assert SecFetchSite.SAME_SITE.value == "same-site"
        assert SecFetchSite.CROSS_SITE.value == "cross-site"

    def test_sec_fetch_mode_values(self):
        """Test SecFetchMode enum has correct string values."""
        assert SecFetchMode.NAVIGATE.value == "navigate"
        assert SecFetchMode.CORS.value == "cors"
        assert SecFetchMode.NO_CORS.value == "no-cors"
        assert SecFetchMode.SAME_ORIGIN.value == "same-origin"

    def test_sec_fetch_dest_values(self):
        """Test SecFetchDest enum has correct string values."""
        assert SecFetchDest.DOCUMENT.value == "document"
        assert SecFetchDest.IMAGE.value == "image"
        assert SecFetchDest.SCRIPT.value == "script"
        assert SecFetchDest.STYLE.value == "style"


@pytest.mark.unit
class TestSecFetchHeaders:
    """Tests for SecFetchHeaders dataclass."""

    def test_to_dict_basic(self):
        """Test basic header generation."""
        headers = SecFetchHeaders(
            site=SecFetchSite.CROSS_SITE,
            mode=SecFetchMode.NAVIGATE,
            dest=SecFetchDest.DOCUMENT,
            user=True,
        )
        
        result = headers.to_dict()
        
        assert result["Sec-Fetch-Site"] == "cross-site"
        assert result["Sec-Fetch-Mode"] == "navigate"
        assert result["Sec-Fetch-Dest"] == "document"
        assert result["Sec-Fetch-User"] == "?1"

    def test_to_dict_no_user_for_non_navigate(self):
        """Test Sec-Fetch-User is not set for non-navigate mode."""
        headers = SecFetchHeaders(
            site=SecFetchSite.SAME_ORIGIN,
            mode=SecFetchMode.NO_CORS,
            dest=SecFetchDest.IMAGE,
            user=True,  # Should be ignored for non-navigate
        )
        
        result = headers.to_dict()
        
        assert "Sec-Fetch-User" not in result
        assert result["Sec-Fetch-Mode"] == "no-cors"

    def test_to_dict_no_user_when_false(self):
        """Test Sec-Fetch-User is not set when user=False."""
        headers = SecFetchHeaders(
            site=SecFetchSite.CROSS_SITE,
            mode=SecFetchMode.NAVIGATE,
            dest=SecFetchDest.DOCUMENT,
            user=False,
        )
        
        result = headers.to_dict()
        
        assert "Sec-Fetch-User" not in result


@pytest.mark.unit
class TestGetRegistrableDomain:
    """Tests for registrable domain extraction."""

    def test_simple_domain(self):
        """Test simple two-part domain."""
        assert _get_registrable_domain("example.com") == "example.com"
        assert _get_registrable_domain("google.com") == "google.com"

    def test_subdomain(self):
        """Test subdomain is stripped to registrable domain."""
        assert _get_registrable_domain("www.example.com") == "example.com"
        assert _get_registrable_domain("api.example.com") == "example.com"
        assert _get_registrable_domain("deep.nested.example.com") == "example.com"

    def test_multi_part_tld_japan(self):
        """Test Japanese multi-part TLDs."""
        assert _get_registrable_domain("example.go.jp") == "example.go.jp"
        assert _get_registrable_domain("www.example.go.jp") == "example.go.jp"
        assert _get_registrable_domain("example.co.jp") == "example.co.jp"
        assert _get_registrable_domain("example.or.jp") == "example.or.jp"

    def test_multi_part_tld_uk(self):
        """Test UK multi-part TLDs."""
        assert _get_registrable_domain("example.co.uk") == "example.co.uk"
        assert _get_registrable_domain("www.example.co.uk") == "example.co.uk"
        assert _get_registrable_domain("example.org.uk") == "example.org.uk"

    def test_port_stripped(self):
        """Test port number is stripped."""
        assert _get_registrable_domain("example.com:8080") == "example.com"
        assert _get_registrable_domain("www.example.com:443") == "example.com"

    def test_case_insensitive(self):
        """Test domain comparison is case-insensitive."""
        assert _get_registrable_domain("EXAMPLE.COM") == "example.com"
        assert _get_registrable_domain("WWW.Example.Com") == "example.com"


@pytest.mark.unit
class TestDetermineFetchSite:
    """Tests for Sec-Fetch-Site determination."""

    def test_no_referer_is_none(self):
        """Test no referer results in 'none'."""
        result = _determine_fetch_site("https://example.com/page", None)
        assert result == SecFetchSite.NONE

    def test_empty_referer_is_none(self):
        """Test empty referer results in 'none'."""
        result = _determine_fetch_site("https://example.com/page", "")
        assert result == SecFetchSite.NONE

    def test_same_origin(self):
        """Test same-origin detection (same scheme + host + port)."""
        result = _determine_fetch_site(
            "https://example.com/page2",
            "https://example.com/page1",
        )
        assert result == SecFetchSite.SAME_ORIGIN

    def test_same_origin_different_path(self):
        """Test same-origin with different paths."""
        result = _determine_fetch_site(
            "https://example.com/deep/nested/page",
            "https://example.com/other",
        )
        assert result == SecFetchSite.SAME_ORIGIN

    def test_same_site_different_subdomain(self):
        """Test same-site detection (different subdomain, same registrable domain)."""
        result = _determine_fetch_site(
            "https://api.example.com/data",
            "https://www.example.com/page",
        )
        assert result == SecFetchSite.SAME_SITE

    def test_cross_site(self):
        """Test cross-site detection (different registrable domains)."""
        result = _determine_fetch_site(
            "https://example.com/page",
            "https://google.com/search?q=test",
        )
        assert result == SecFetchSite.CROSS_SITE

    def test_serp_to_article_is_cross_site(self):
        """Test SERP to article is cross-site (typical search flow).
        
        Per §4.3: SERP → article transitions should look like cross-site navigation.
        """
        result = _determine_fetch_site(
            "https://example.com/article",
            "https://www.google.com/search?q=test",
        )
        assert result == SecFetchSite.CROSS_SITE

    def test_duckduckgo_to_article_is_cross_site(self):
        """Test DuckDuckGo SERP to article is cross-site."""
        result = _determine_fetch_site(
            "https://example.com/page",
            "https://duckduckgo.com/?q=test",
        )
        assert result == SecFetchSite.CROSS_SITE

    def test_scheme_difference_is_cross_site(self):
        """Test different schemes (http vs https) treated as different origin.
        
        Note: This is stricter than same-site but appropriate for security.
        """
        result = _determine_fetch_site(
            "https://example.com/page",
            "http://example.com/page",
        )
        # Same registrable domain, so same-site (not same-origin due to scheme)
        assert result == SecFetchSite.SAME_SITE


@pytest.mark.unit
class TestGenerateSecFetchHeaders:
    """Tests for generate_sec_fetch_headers function."""

    def test_direct_navigation(self):
        """Test headers for direct navigation (no referer)."""
        context = NavigationContext(
            target_url="https://example.com/page",
            referer_url=None,
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        
        headers = generate_sec_fetch_headers(context)
        
        assert headers.site == SecFetchSite.NONE
        assert headers.mode == SecFetchMode.NAVIGATE
        assert headers.dest == SecFetchDest.DOCUMENT
        assert headers.user is True

    def test_cross_site_navigation(self):
        """Test headers for cross-site navigation."""
        context = NavigationContext(
            target_url="https://example.com/article",
            referer_url="https://google.com/search?q=test",
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        
        headers = generate_sec_fetch_headers(context)
        
        assert headers.site == SecFetchSite.CROSS_SITE
        assert headers.mode == SecFetchMode.NAVIGATE
        assert headers.dest == SecFetchDest.DOCUMENT

    def test_same_origin_navigation(self):
        """Test headers for same-origin navigation."""
        context = NavigationContext(
            target_url="https://example.com/page2",
            referer_url="https://example.com/page1",
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        
        headers = generate_sec_fetch_headers(context)
        
        assert headers.site == SecFetchSite.SAME_ORIGIN
        assert headers.mode == SecFetchMode.NAVIGATE

    def test_image_request(self):
        """Test headers for image resource request."""
        context = NavigationContext(
            target_url="https://cdn.example.com/image.png",
            referer_url="https://example.com/page",
            is_user_initiated=False,
            destination=SecFetchDest.IMAGE,
        )
        
        headers = generate_sec_fetch_headers(context)
        
        assert headers.mode == SecFetchMode.NO_CORS
        assert headers.dest == SecFetchDest.IMAGE


@pytest.mark.unit
class TestGenerateHeadersForSerpClick:
    """Tests for generate_headers_for_serp_click helper."""

    def test_google_serp_to_article(self):
        """Test clicking Google search result."""
        headers = generate_headers_for_serp_click(
            target_url="https://example.com/article",
            serp_url="https://www.google.com/search?q=test+query",
        )
        
        assert headers["Sec-Fetch-Site"] == "cross-site"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Sec-Fetch-Dest"] == "document"
        assert headers["Sec-Fetch-User"] == "?1"
        assert headers["Referer"] == "https://www.google.com/search?q=test+query"

    def test_duckduckgo_serp_to_article(self):
        """Test clicking DuckDuckGo search result."""
        headers = generate_headers_for_serp_click(
            target_url="https://example.jp/page",
            serp_url="https://duckduckgo.com/?q=test",
        )
        
        assert headers["Sec-Fetch-Site"] == "cross-site"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Referer"] == "https://duckduckgo.com/?q=test"


@pytest.mark.unit
class TestGenerateHeadersForDirectNavigation:
    """Tests for generate_headers_for_direct_navigation helper."""

    def test_direct_url_access(self):
        """Test simulating direct URL access (address bar)."""
        headers = generate_headers_for_direct_navigation(
            target_url="https://example.com/page",
        )
        
        assert headers["Sec-Fetch-Site"] == "none"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Sec-Fetch-Dest"] == "document"
        assert headers["Sec-Fetch-User"] == "?1"
        assert "Referer" not in headers

    def test_bookmark_access(self):
        """Test simulating bookmark access."""
        headers = generate_headers_for_direct_navigation(
            target_url="https://example.com/bookmarked-page",
        )
        
        assert headers["Sec-Fetch-Site"] == "none"
        assert "Referer" not in headers


@pytest.mark.unit
class TestGenerateHeadersForInternalLink:
    """Tests for generate_headers_for_internal_link helper."""

    def test_same_origin_internal_link(self):
        """Test following internal link on same origin."""
        headers = generate_headers_for_internal_link(
            target_url="https://example.com/page2",
            source_url="https://example.com/page1",
        )
        
        assert headers["Sec-Fetch-Site"] == "same-origin"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Referer"] == "https://example.com/page1"

    def test_subdomain_internal_link(self):
        """Test following link to subdomain (same-site)."""
        headers = generate_headers_for_internal_link(
            target_url="https://blog.example.com/post",
            source_url="https://www.example.com/",
        )
        
        assert headers["Sec-Fetch-Site"] == "same-site"
        assert headers["Referer"] == "https://www.example.com/"


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_ipv4_address(self):
        """Test handling of IPv4 address URLs."""
        result = _determine_fetch_site(
            "http://192.168.1.1/page",
            "http://192.168.1.1/other",
        )
        assert result == SecFetchSite.SAME_ORIGIN

    def test_ipv4_different_hosts(self):
        """Test different IPv4 addresses are cross-site."""
        result = _determine_fetch_site(
            "http://192.168.1.1/page",
            "http://192.168.1.2/other",
        )
        assert result == SecFetchSite.CROSS_SITE

    def test_localhost(self):
        """Test localhost handling."""
        result = _determine_fetch_site(
            "http://localhost:8080/page",
            "http://localhost:8080/other",
        )
        assert result == SecFetchSite.SAME_ORIGIN

    def test_localhost_different_ports(self):
        """Test localhost with different ports (different origin, same site)."""
        # Ports differ, so not same-origin, but localhost is same "site"
        result = _determine_fetch_site(
            "http://localhost:8080/page",
            "http://localhost:3000/other",
        )
        # localhost:8080 vs localhost:3000 - same registrable domain (localhost)
        assert result == SecFetchSite.SAME_SITE

    def test_single_label_domain(self):
        """Test single-label domain (e.g., intranet)."""
        assert _get_registrable_domain("intranet") == "intranet"
        assert _get_registrable_domain("localhost") == "localhost"

    def test_trailing_dot_domain(self):
        """Test domain with trailing dot (FQDN)."""
        # The dot should be handled gracefully
        domain = _get_registrable_domain("example.com.")
        # Empty string at end from split, but should still work
        assert "example" in domain.lower()


@pytest.mark.unit
class TestHeaderConsistency:
    """Tests to ensure header consistency with browser behavior."""

    def test_all_required_headers_present_for_navigation(self):
        """Test all required Sec-Fetch-* headers are present for navigation."""
        headers = generate_headers_for_serp_click(
            target_url="https://example.com/page",
            serp_url="https://google.com/search",
        )
        
        required = ["Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest"]
        for header in required:
            assert header in headers, f"Missing required header: {header}"

    def test_sec_fetch_user_only_for_user_initiated(self):
        """Test Sec-Fetch-User is only set for user-initiated navigations."""
        # User-initiated (default)
        context = NavigationContext(
            target_url="https://example.com/",
            referer_url=None,
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        headers = generate_sec_fetch_headers(context)
        result = headers.to_dict()
        assert "Sec-Fetch-User" in result
        
        # Not user-initiated (e.g., redirect)
        context = NavigationContext(
            target_url="https://example.com/",
            referer_url=None,
            is_user_initiated=False,
            destination=SecFetchDest.DOCUMENT,
        )
        headers = generate_sec_fetch_headers(context)
        result = headers.to_dict()
        assert "Sec-Fetch-User" not in result

    def test_header_values_are_strings(self):
        """Test all header values are strings (not enum objects)."""
        headers = generate_headers_for_direct_navigation(
            target_url="https://example.com/",
        )
        
        for key, value in headers.items():
            assert isinstance(value, str), f"Header {key} value should be string, got {type(value)}"


# =============================================================================
# Sec-CH-UA-* (Client Hints) Header Tests
# =============================================================================

@pytest.mark.unit
class TestPlatformEnum:
    """Tests for Platform enum values."""

    def test_platform_values(self):
        """Test Platform enum has correct string values."""
        assert Platform.WINDOWS.value == "Windows"
        assert Platform.MACOS.value == "macOS"
        assert Platform.LINUX.value == "Linux"
        assert Platform.ANDROID.value == "Android"
        assert Platform.IOS.value == "iOS"
        assert Platform.CHROME_OS.value == "Chrome OS"
        assert Platform.UNKNOWN.value == "Unknown"


@pytest.mark.unit
class TestBrandVersion:
    """Tests for BrandVersion dataclass."""

    def test_to_ua_item_basic(self):
        """Test basic UA item formatting."""
        brand = BrandVersion(
            brand="Google Chrome",
            major_version="120",
        )
        
        result = brand.to_ua_item()
        
        assert result == '"Google Chrome";v="120"'

    def test_to_ua_item_with_special_characters(self):
        """Test UA item with special characters in brand name."""
        brand = BrandVersion(
            brand="Not_A Brand",
            major_version="8",
        )
        
        result = brand.to_ua_item()
        
        assert result == '"Not_A Brand";v="8"'

    def test_to_ua_item_full_version(self):
        """Test UA item with full version when requested."""
        brand = BrandVersion(
            brand="Chromium",
            major_version="120",
            full_version="120.0.6099.130",
        )
        
        result = brand.to_ua_item(include_full_version=True)
        
        assert result == '"Chromium";v="120.0.6099.130"'

    def test_to_ua_item_full_version_fallback(self):
        """Test UA item falls back to major version if no full version."""
        brand = BrandVersion(
            brand="Test",
            major_version="10",
        )
        
        result = brand.to_ua_item(include_full_version=True)
        
        assert result == '"Test";v="10"'


@pytest.mark.unit
class TestSecCHUAConfig:
    """Tests for SecCHUAConfig configuration class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SecCHUAConfig()
        
        assert config.chrome_major_version == "120"
        assert config.platform == Platform.WINDOWS
        assert config.is_mobile is False
        assert config.grease_brand == "Not_A Brand"
        assert config.grease_version == "8"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = SecCHUAConfig(
            chrome_major_version="121",
            chrome_full_version="121.0.6167.85",
            platform=Platform.LINUX,
            is_mobile=False,
        )
        
        assert config.chrome_major_version == "121"
        assert config.platform == Platform.LINUX

    def test_brands_property(self):
        """Test brands property returns correct list."""
        config = SecCHUAConfig(
            chrome_major_version="120",
            chrome_full_version="120.0.6099.130",
        )
        
        brands = config.brands
        
        assert len(brands) == 3
        # First is GREASE brand
        assert brands[0].brand == "Not_A Brand"
        assert brands[0].major_version == "8"
        # Second is Chromium
        assert brands[1].brand == "Chromium"
        assert brands[1].major_version == "120"
        # Third is Google Chrome
        assert brands[2].brand == "Google Chrome"
        assert brands[2].major_version == "120"


@pytest.mark.unit
class TestSecCHUAHeaders:
    """Tests for SecCHUAHeaders dataclass."""

    def test_to_dict_basic(self):
        """Test basic header generation."""
        headers = SecCHUAHeaders(
            brands=[
                BrandVersion("Not_A Brand", "8"),
                BrandVersion("Chromium", "120"),
                BrandVersion("Google Chrome", "120"),
            ],
            is_mobile=False,
            platform=Platform.WINDOWS,
        )
        
        result = headers.to_dict()
        
        assert "Sec-CH-UA" in result
        assert "Sec-CH-UA-Mobile" in result
        assert "Sec-CH-UA-Platform" in result
        
        assert result["Sec-CH-UA-Mobile"] == "?0"
        assert result["Sec-CH-UA-Platform"] == '"Windows"'

    def test_to_dict_mobile(self):
        """Test mobile device header generation."""
        headers = SecCHUAHeaders(
            brands=[BrandVersion("Chrome", "120")],
            is_mobile=True,
            platform=Platform.ANDROID,
        )
        
        result = headers.to_dict()
        
        assert result["Sec-CH-UA-Mobile"] == "?1"
        assert result["Sec-CH-UA-Platform"] == '"Android"'

    def test_to_dict_linux_platform(self):
        """Test Linux platform header generation."""
        headers = SecCHUAHeaders(
            brands=[BrandVersion("Chrome", "120")],
            is_mobile=False,
            platform=Platform.LINUX,
        )
        
        result = headers.to_dict()
        
        assert result["Sec-CH-UA-Platform"] == '"Linux"'

    def test_to_dict_with_optional_headers(self):
        """Test optional headers are included when requested."""
        headers = SecCHUAHeaders(
            brands=[
                BrandVersion("Chrome", "120", "120.0.6099.130"),
            ],
            is_mobile=False,
            platform=Platform.WINDOWS,
            platform_version="15.0.0",
        )
        
        result = headers.to_dict(include_optional=True)
        
        assert "Sec-CH-UA-Platform-Version" in result
        assert result["Sec-CH-UA-Platform-Version"] == '"15.0.0"'
        assert "Sec-CH-UA-Full-Version-List" in result

    def test_to_dict_without_optional_headers(self):
        """Test optional headers are excluded by default."""
        headers = SecCHUAHeaders(
            brands=[BrandVersion("Chrome", "120", "120.0.6099.130")],
            is_mobile=False,
            platform=Platform.WINDOWS,
            platform_version="15.0.0",
        )
        
        result = headers.to_dict(include_optional=False)
        
        assert "Sec-CH-UA-Platform-Version" not in result
        assert "Sec-CH-UA-Full-Version-List" not in result

    def test_sec_ch_ua_format(self):
        """Test Sec-CH-UA header format matches browser output."""
        headers = SecCHUAHeaders(
            brands=[
                BrandVersion("Not_A Brand", "8"),
                BrandVersion("Chromium", "120"),
                BrandVersion("Google Chrome", "120"),
            ],
            is_mobile=False,
            platform=Platform.WINDOWS,
        )
        
        result = headers.to_dict()
        sec_ch_ua = result["Sec-CH-UA"]
        
        # Should be comma-separated list
        assert '"Not_A Brand";v="8"' in sec_ch_ua
        assert '"Chromium";v="120"' in sec_ch_ua
        assert '"Google Chrome";v="120"' in sec_ch_ua
        assert ", " in sec_ch_ua  # Items separated by ", "


@pytest.mark.unit
class TestGenerateSecCHUAHeaders:
    """Tests for generate_sec_ch_ua_headers function."""

    def test_default_generation(self):
        """Test header generation with default config."""
        headers = generate_sec_ch_ua_headers()
        result = headers.to_dict()
        
        # Should have all required headers
        assert "Sec-CH-UA" in result
        assert "Sec-CH-UA-Mobile" in result
        assert "Sec-CH-UA-Platform" in result
        
        # Default is desktop Windows
        assert result["Sec-CH-UA-Mobile"] == "?0"
        assert result["Sec-CH-UA-Platform"] == '"Windows"'

    def test_custom_config(self):
        """Test header generation with custom config."""
        config = SecCHUAConfig(
            chrome_major_version="121",
            platform=Platform.MACOS,
            is_mobile=False,
        )
        
        headers = generate_sec_ch_ua_headers(config=config)
        result = headers.to_dict()
        
        assert result["Sec-CH-UA-Platform"] == '"macOS"'
        assert '"121"' in result["Sec-CH-UA"]

    def test_with_optional_headers(self):
        """Test generation includes optional headers when requested."""
        config = SecCHUAConfig(
            platform_version="15.0.0",
        )
        
        headers = generate_sec_ch_ua_headers(
            config=config,
            include_optional=True,
        )
        result = headers.to_dict(include_optional=True)
        
        assert "Sec-CH-UA-Platform-Version" in result


@pytest.mark.unit
class TestGenerateAllSecurityHeaders:
    """Tests for combined header generation functions."""

    def test_generate_all_security_headers(self):
        """Test combined Sec-Fetch-* and Sec-CH-UA-* generation."""
        context = NavigationContext(
            target_url="https://example.com/page",
            referer_url="https://google.com/search",
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        
        headers = generate_all_security_headers(context)
        
        # Sec-Fetch-* headers
        assert headers["Sec-Fetch-Site"] == "cross-site"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Sec-Fetch-Dest"] == "document"
        assert headers["Sec-Fetch-User"] == "?1"
        
        # Sec-CH-UA-* headers
        assert "Sec-CH-UA" in headers
        assert "Sec-CH-UA-Mobile" in headers
        assert "Sec-CH-UA-Platform" in headers
        
        # Referer
        assert headers["Referer"] == "https://google.com/search"

    def test_generate_all_security_headers_no_referer(self):
        """Test combined headers without referer."""
        context = NavigationContext(
            target_url="https://example.com/page",
            referer_url=None,
            is_user_initiated=True,
            destination=SecFetchDest.DOCUMENT,
        )
        
        headers = generate_all_security_headers(context)
        
        assert headers["Sec-Fetch-Site"] == "none"
        assert "Referer" not in headers

    def test_generate_complete_navigation_headers(self):
        """Test convenience function for complete navigation headers."""
        headers = generate_complete_navigation_headers(
            target_url="https://example.com/page",
            referer_url="https://google.com/search",
        )
        
        # Should have all Sec-Fetch-* headers
        assert "Sec-Fetch-Site" in headers
        assert "Sec-Fetch-Mode" in headers
        assert "Sec-Fetch-Dest" in headers
        
        # Should have all Sec-CH-UA-* headers
        assert "Sec-CH-UA" in headers
        assert "Sec-CH-UA-Mobile" in headers
        assert "Sec-CH-UA-Platform" in headers
        
        # Should have Referer
        assert "Referer" in headers

    def test_generate_complete_navigation_headers_direct(self):
        """Test convenience function for direct navigation (no referer)."""
        headers = generate_complete_navigation_headers(
            target_url="https://example.com/page",
        )
        
        assert headers["Sec-Fetch-Site"] == "none"
        assert "Referer" not in headers


@pytest.mark.unit
class TestSecCHUAHeadersIntegration:
    """Integration tests for Sec-CH-UA-* headers with browser impersonation."""

    def test_headers_match_chrome_format(self):
        """Test generated headers match real Chrome browser format."""
        config = SecCHUAConfig(
            chrome_major_version="120",
            chrome_full_version="120.0.6099.130",
            platform=Platform.WINDOWS,
            is_mobile=False,
        )
        
        headers = generate_sec_ch_ua_headers(config=config)
        result = headers.to_dict()
        
        # Chrome's Sec-CH-UA format (order may vary)
        sec_ch_ua = result["Sec-CH-UA"]
        
        # Should contain three brands
        assert sec_ch_ua.count(';v="') == 3
        
        # Mobile should be ?0 for desktop
        assert result["Sec-CH-UA-Mobile"] == "?0"
        
        # Platform should be quoted
        assert result["Sec-CH-UA-Platform"] == '"Windows"'

    def test_header_values_are_all_strings(self):
        """Test all header values are strings for HTTP client compatibility."""
        headers = generate_sec_ch_ua_headers()
        result = headers.to_dict(include_optional=True)
        
        for key, value in result.items():
            assert isinstance(value, str), f"Header {key} should be string, got {type(value)}"

    def test_mobile_detection_headers(self):
        """Test mobile device headers are correctly set."""
        config = SecCHUAConfig(
            platform=Platform.ANDROID,
            is_mobile=True,
        )
        
        headers = generate_sec_ch_ua_headers(config=config)
        result = headers.to_dict()
        
        assert result["Sec-CH-UA-Mobile"] == "?1"
        assert result["Sec-CH-UA-Platform"] == '"Android"'

    def test_ios_platform(self):
        """Test iOS platform headers."""
        config = SecCHUAConfig(
            platform=Platform.IOS,
            is_mobile=True,
        )
        
        headers = generate_sec_ch_ua_headers(config=config)
        result = headers.to_dict()
        
        assert result["Sec-CH-UA-Platform"] == '"iOS"'
        assert result["Sec-CH-UA-Mobile"] == "?1"

