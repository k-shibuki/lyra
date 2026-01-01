"""
Lyra search module.

Provides unified search interface through provider abstraction.
All search operations now go through SearchProvider interface by default.

Main entry point:
    search_serp() - Execute search queries via registered provider

Provider system:
    SearchProvider - Protocol for search providers
    SearchProviderRegistry - Registry for provider management
    get_registry() - Get global provider registry
    BrowserSearchProvider - Direct Playwright-based search (default)

Engine configuration:
    SearchEngineConfigManager - Centralized engine configuration
    get_engine_config_manager() - Get global engine config manager
    EngineConfig - Individual engine configuration

Parser system:
    ParserConfigManager - Parser configuration management
    get_parser() - Get parser for a search engine

All searches use BrowserSearchProvider for direct browser-based search.
"""

# Core search function (uses provider by default)
# Browser-based search provider (default)
from src.search.browser_search_provider import (
    BrowserSearchProvider,
    cleanup_browser_search_provider,
    get_browser_search_provider,
)

# Engine configuration
from src.search.engine_config import (
    DirectSource,
    EngineCategory,
    EngineConfig,
    EngineStatus,
    SearchEngineConfigManager,
    get_available_search_engines,
    get_engine_config,
    get_engine_config_manager,
    get_engine_operator_mapping,
    is_search_engine_available,
    reset_engine_config_manager,
)

# Parser system
from src.search.parser_config import (
    ParserConfigManager,
    get_engine_parser_config,
    get_parser_config_manager,
)
from src.search.parsers import (
    BaseSearchParser,
    get_available_parsers,
    get_parser,
)

# Provider abstraction
from src.search.provider import (
    BaseSearchProvider,
    HealthState,
    HealthStatus,
    SearchProvider,
    SearchProviderOptions,
    SearchProviderRegistry,
    SearchResponse,
    SERPResult,
    SourceTag,
    cleanup_registry,
    get_registry,
)
from src.search.search_api import (
    QueryExpander,
    QueryOperatorProcessor,
    build_search_query,
    expand_query,
    generate_mirror_queries,
    generate_mirror_query,
    parse_query_operators,
    search_serp,
    transform_query_for_engine,
)

__all__ = [
    # Core search (provider-based)
    "search_serp",
    "expand_query",
    "generate_mirror_query",
    "generate_mirror_queries",
    "QueryExpander",
    "QueryOperatorProcessor",
    "parse_query_operators",
    "transform_query_for_engine",
    "build_search_query",
    # Provider abstraction
    "SearchProvider",
    "BaseSearchProvider",
    "SERPResult",
    "SearchResponse",
    "SearchProviderOptions",
    "HealthStatus",
    "HealthState",
    "SourceTag",
    "SearchProviderRegistry",
    "get_registry",
    "cleanup_registry",
    # Browser search provider (default)
    "BrowserSearchProvider",
    "get_browser_search_provider",
    "cleanup_browser_search_provider",
    # Parser system
    "ParserConfigManager",
    "get_parser_config_manager",
    "get_engine_parser_config",
    "BaseSearchParser",
    "get_parser",
    "get_available_parsers",
    # Engine configuration
    "SearchEngineConfigManager",
    "get_engine_config_manager",
    "reset_engine_config_manager",
    "EngineConfig",
    "EngineCategory",
    "EngineStatus",
    "DirectSource",
    "get_engine_config",
    "get_available_search_engines",
    "get_engine_operator_mapping",
    "is_search_engine_available",
]
