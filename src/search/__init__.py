"""
Lancet search module.
Provides search engine integration and query management.
"""

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
    # SearXNG (legacy)
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
]

