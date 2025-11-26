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

__all__ = [
    # SearXNG
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
]

