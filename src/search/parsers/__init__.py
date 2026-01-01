"""
Search Result Parsers for Direct Browser Search.

Parses search engine result pages (SERPs) to extract structured results.

Design Philosophy:
- Selectors are loaded from config/search_parsers.yaml (not hardcoded)
- Required selectors fail loudly with diagnostic messages
- Failed HTML is saved for debugging
- AI-friendly error messages enable quick fixes
"""

from src.search.parsers.base import BaseSearchParser, ParsedResult, ParseResult
from src.search.parsers.bing import BingParser
from src.search.parsers.brave import BraveParser
from src.search.parsers.duckduckgo import DuckDuckGoParser
from src.search.parsers.ecosia import EcosiaParser
from src.search.parsers.google import GoogleParser
from src.search.parsers.mojeek import MojeekParser
from src.search.parsers.registry import (
    get_available_parsers,
    get_parser,
    register_parser,
)
from src.search.parsers.startpage import StartpageParser

# Register all parsers
register_parser("duckduckgo", DuckDuckGoParser)
register_parser("mojeek", MojeekParser)
register_parser("google", GoogleParser)
register_parser("brave", BraveParser)
register_parser("ecosia", EcosiaParser)
register_parser("startpage", StartpageParser)
register_parser("bing", BingParser)

__all__ = [
    "BaseSearchParser",
    "ParsedResult",
    "ParseResult",
    "DuckDuckGoParser",
    "MojeekParser",
    "GoogleParser",
    "BraveParser",
    "EcosiaParser",
    "StartpageParser",
    "BingParser",
    "get_parser",
    "get_available_parsers",
    "register_parser",
]
