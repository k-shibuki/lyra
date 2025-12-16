"""
Base class for academic API clients.
"""

from abc import ABC, abstractmethod
from typing import Optional

import httpx

from src.utils.schemas import Paper, AcademicSearchResult
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BaseAcademicClient(ABC):
    """Base class for academic API clients."""
    
    def __init__(self, name: str):
        """Initialize client.
        
        Args:
            name: Client name
        """
        self.name = name
        self._session: Optional[httpx.AsyncClient] = None
    
    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Lancet/1.0 (research tool; mailto:lancet@example.com)"}
            )
        return self._session
    
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            AcademicSearchResult
        """
        pass
    
    @abstractmethod
    async def get_paper(self, paper_id: str) -> Optional[Paper]:
        """Get paper metadata.
        
        Args:
            paper_id: Paper ID (API-specific format)
            
        Returns:
            Paper object or None
        """
        pass
    
    @abstractmethod
    async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get references (papers cited by this paper).
        
        Args:
            paper_id: Paper ID
            
        Returns:
            List of (Paper, is_influential) tuples
        """
        pass
    
    @abstractmethod
    async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
        """Get citations (papers that cite this paper).
        
        Args:
            paper_id: Paper ID
            
        Returns:
            List of (Paper, is_influential) tuples
        """
        pass
    
    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.aclose()
            self._session = None
            logger.debug("Academic API client closed", client=self.name)
