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
    
    def __init__(self, name: str, base_url: Optional[str] = None, timeout: Optional[float] = None, headers: Optional[dict[str, str]] = None):
        """Initialize client.
        
        Args:
            name: Client name
            base_url: Base URL for API (if None, will try to load from config)
            timeout: Timeout in seconds (if None, will try to load from config)
            headers: HTTP headers (if None, will use default)
        """
        self.name = name
        self._session: Optional[httpx.AsyncClient] = None
        
        # Load configuration if not provided
        if base_url is None or timeout is None:
            try:
                from src.utils.config import get_academic_apis_config
                config = get_academic_apis_config()
                api_config = config.apis.get(name, {})
                
                if base_url is None:
                    base_url = api_config.base_url if api_config.base_url else None
                if timeout is None:
                    timeout = float(api_config.timeout_seconds) if api_config.timeout_seconds else 30.0
                if headers is None and api_config.headers:
                    headers = api_config.headers.copy()
            except Exception as e:
                logger.debug("Failed to load config for academic API", api=name, error=str(e))
                if base_url is None:
                    base_url = None  # Will be set by subclass
                if timeout is None:
                    timeout = 30.0
        
        self.base_url = base_url
        self.timeout = timeout or 30.0
        
        # Default headers
        default_headers = {"User-Agent": "Lancet/1.0 (research tool; mailto:lancet@example.com)"}
        if headers:
            default_headers.update(headers)
        self.default_headers = default_headers
    
    async def _get_session(self) -> httpx.AsyncClient:
        """Get HTTP session (lazy initialization)."""
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.default_headers
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
