"""
Parser Registry and Factory Functions.

Manages registration and retrieval of search engine parsers.
"""

from __future__ import annotations

from src.search.parser_config import get_parser_config_manager
from src.search.provider import SourceTag
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Import parsers here to avoid circular dependencies
# These will be imported after all parser modules are created
from src.search.parsers.base import BaseSearchParser

# Registry will be populated by __init__.py after all parsers are imported
_parser_registry: dict[str, type[BaseSearchParser]] = {}


def get_parser(engine_name: str) -> BaseSearchParser | None:
    """
    Get parser instance for an engine.

    Args:
        engine_name: Engine name (case-insensitive).

    Returns:
        Parser instance or None if not available.
    """
    name_lower = engine_name.lower()
    parser_class = _parser_registry.get(name_lower)

    if parser_class is None:
        logger.warning(f"No parser available for engine: {engine_name}")
        return None

    # Check if configuration exists
    manager = get_parser_config_manager()
    if not manager.is_engine_configured(name_lower):
        logger.warning(f"Engine {engine_name} not configured in search_parsers.yaml")
        return None

    # Type ignore: parser subclasses have engine name hardcoded in their __init__
    return parser_class()  # type: ignore[call-arg]


def get_available_parsers() -> list[str]:
    """Get list of available parser engine names."""
    manager = get_parser_config_manager()
    configured = set(manager.get_available_engines())
    registered = set(_parser_registry.keys())
    return sorted(configured & registered)


def register_parser(engine_name: str, parser_class: type[BaseSearchParser]) -> None:
    """
    Register a custom parser for an engine.

    Args:
        engine_name: Engine name.
        parser_class: Parser class (must inherit BaseSearchParser).
    """
    if not issubclass(parser_class, BaseSearchParser):
        raise TypeError("Parser must inherit from BaseSearchParser")

    _parser_registry[engine_name.lower()] = parser_class
    logger.info(f"Registered parser for engine: {engine_name}")


def _classify_source(url: str) -> SourceTag:
    """
    Classify source type based on URL.

    Reuses classification logic from search_api and converts to SourceTag enum.
    """
    # Import here to avoid circular dependency
    try:
        from src.search.search_api import _classify_source as classify_source

        tag_str = classify_source(url)
        # Convert string to SourceTag enum
        try:
            return SourceTag(tag_str)
        except ValueError:
            return SourceTag.UNKNOWN
    except ImportError:
        # Fallback classification
        url_lower = url.lower()

        if any(d in url_lower for d in ["arxiv.org", "pubmed", "scholar.google"]):
            return SourceTag.ACADEMIC
        if any(p in url_lower for p in [".gov", ".go.jp", ".gov.uk"]):
            return SourceTag.GOVERNMENT
        if "wikipedia.org" in url_lower:
            return SourceTag.KNOWLEDGE

        return SourceTag.UNKNOWN
