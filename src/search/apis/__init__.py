"""
Academic API clients for Lancet.

Provides unified interface for accessing academic paper metadata from:
- Semantic Scholar
- OpenAlex
- Crossref
- arXiv
"""

from src.search.apis.arxiv import ArxivClient
from src.search.apis.base import BaseAcademicClient
from src.search.apis.crossref import CrossrefClient
from src.search.apis.openalex import OpenAlexClient
from src.search.apis.semantic_scholar import SemanticScholarClient
from src.search.apis.unpaywall import UnpaywallClient

__all__ = [
    "BaseAcademicClient",
    "SemanticScholarClient",
    "OpenAlexClient",
    "CrossrefClient",
    "ArxivClient",
    "UnpaywallClient",
]
