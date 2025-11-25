"""
Lancet Crawler Module.

Provides URL fetching, robots.txt compliance, and sitemap parsing.
"""

from src.crawler.fetcher import (
    FetchResult,
    HTTPFetcher,
    BrowserFetcher,
    HumanBehavior,
    TorController,
    RateLimiter,
    fetch_url,
    get_tor_controller,
)

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
)

from src.crawler.robots import (
    RobotsChecker,
    RobotsRule,
    SitemapParser,
    SitemapEntry,
    SitemapResult,
    RobotsManager,
    get_robots_manager,
    check_robots_compliance,
    get_sitemap_urls,
)

from src.crawler.bfs import (
    LinkType,
    ExtractedLink,
    BFSResult,
    LinkExtractor,
    DomainBFSCrawler,
    get_bfs_crawler,
    explore_domain,
    extract_page_links,
)

from src.crawler.site_search import (
    SearchTemplate,
    SiteSearchResult,
    DomainSearchStats,
    SiteSearchManager,
    get_site_search_manager,
    site_search,
    get_site_search_stats,
    list_allowlisted_domains,
)

from src.crawler.wayback import (
    Snapshot,
    ContentDiff,
    TimelineEntry,
    WaybackResult,
    WaybackClient,
    ContentAnalyzer,
    WaybackExplorer,
    WaybackBudgetManager,
    get_wayback_explorer,
    get_wayback_budget_manager,
    explore_wayback,
    get_archived_content,
    check_content_modified,
)

__all__ = [
    # Fetcher
    "FetchResult",
    "HTTPFetcher",
    "BrowserFetcher",
    "HumanBehavior",
    "TorController",
    "RateLimiter",
    "fetch_url",
    "get_tor_controller",
    # Sec-Fetch Headers
    "SecFetchSite",
    "SecFetchMode",
    "SecFetchDest",
    "SecFetchHeaders",
    "NavigationContext",
    "generate_sec_fetch_headers",
    "generate_headers_for_serp_click",
    "generate_headers_for_direct_navigation",
    "generate_headers_for_internal_link",
    # Robots/Sitemap
    "RobotsChecker",
    "RobotsRule",
    "SitemapParser",
    "SitemapEntry",
    "SitemapResult",
    "RobotsManager",
    "get_robots_manager",
    "check_robots_compliance",
    "get_sitemap_urls",
    # BFS
    "LinkType",
    "ExtractedLink",
    "BFSResult",
    "LinkExtractor",
    "DomainBFSCrawler",
    "get_bfs_crawler",
    "explore_domain",
    "extract_page_links",
    # Site Search
    "SearchTemplate",
    "SiteSearchResult",
    "DomainSearchStats",
    "SiteSearchManager",
    "get_site_search_manager",
    "site_search",
    "get_site_search_stats",
    "list_allowlisted_domains",
    # Wayback
    "Snapshot",
    "ContentDiff",
    "TimelineEntry",
    "WaybackResult",
    "WaybackClient",
    "ContentAnalyzer",
    "WaybackExplorer",
    "WaybackBudgetManager",
    "get_wayback_explorer",
    "get_wayback_budget_manager",
    "explore_wayback",
    "get_archived_content",
    "check_content_modified",
]

