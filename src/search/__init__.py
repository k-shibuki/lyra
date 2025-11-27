"""
Lancet search module.

Provides unified search interface through provider abstraction (Phase 17.1.1).
All search operations now go through SearchProvider interface by default.

Main entry point:
    search_serp() - Execute search queries via registered provider

Provider system:
    SearchProvider - Protocol for search providers
    SearchProviderRegistry - Registry for provider management
    get_registry() - Get global provider registry
    SearXNGProvider - Default SearXNG implementation

Engine configuration (Phase 17.2.2):
    SearchEngineConfigManager - Centralized engine configuration
    get_engine_config_manager() - Get global engine config manager
    EngineConfig - Individual engine configuration
"""

# Core search function (uses provider by default)
from src.search.searxng import (
    search_serp,
    expand_query,
    generate_mirror_query,
    generate_mirror_queries,
    QueryExpander,
    QueryOperatorProcessor,
    parse_query_operators,
    transform_query_for_engine,
    build_search_query,
)

# Engine configuration (Phase 17.2.2)
from src.search.engine_config import (
    SearchEngineConfigManager,
    get_engine_config_manager,
    reset_engine_config_manager,
    EngineConfig,
    EngineCategory,
    EngineStatus,
    DirectSource,
    get_engine_config,
    get_available_search_engines,
    get_engine_operator_mapping,
    is_search_engine_available,
)

# A/B Testing
from src.search.ab_test import (
    run_query_ab_test,
    get_optimized_query,
    generate_query_variants,
    QueryVariant,
    VariantType,
    ABTestSession,
    ABTestResult,
    ABTestExecutor,
    QueryVariantGenerator,
    HighYieldQueryCache,
)

# Provider abstraction (Phase 17.1.1)
from src.search.provider import (
    SearchProvider,
    BaseSearchProvider,
    SearchResult,
    SearchResponse,
    SearchOptions,
    HealthStatus,
    HealthState,
    SourceTag,
    SearchProviderRegistry,
    get_registry,
    cleanup_registry,
)
from src.search.searxng_provider import (
    SearXNGProvider,
    get_searxng_provider,
    cleanup_searxng_provider,
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
    # A/B Testing
    "run_query_ab_test",
    "get_optimized_query",
    "generate_query_variants",
    "QueryVariant",
    "VariantType",
    "ABTestSession",
    "ABTestResult",
    "ABTestExecutor",
    "QueryVariantGenerator",
    "HighYieldQueryCache",
    # Provider abstraction (Phase 17.1.1)
    "SearchProvider",
    "BaseSearchProvider",
    "SearchResult",
    "SearchResponse",
    "SearchOptions",
    "HealthStatus",
    "HealthState",
    "SourceTag",
    "SearchProviderRegistry",
    "get_registry",
    "cleanup_registry",
    "SearXNGProvider",
    "get_searxng_provider",
    "cleanup_searxng_provider",
    # Engine configuration (Phase 17.2.2)
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

