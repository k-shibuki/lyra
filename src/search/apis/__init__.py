"""
Academic API clients for Lyra.

Provides unified interface for accessing academic paper metadata from:
- Semantic Scholar
- OpenAlex
"""

from src.search.apis.base import BaseAcademicClient
from src.search.apis.openalex import OpenAlexClient
from src.search.apis.semantic_scholar import SemanticScholarClient

__all__ = [
    "BaseAcademicClient",
    "SemanticScholarClient",
    "OpenAlexClient",
]
