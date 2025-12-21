"""
arXiv API client.

Preprint search (priority=4).
"""

from datetime import datetime
from xml.etree import ElementTree as ET

from src.search.apis.base import BaseAcademicClient
from src.utils.api_retry import ACADEMIC_API_POLICY, retry_api_call
from src.utils.logging import get_logger
from src.utils.schemas import AcademicSearchResult, Author, Paper

logger = get_logger(__name__)


class ArxivClient(BaseAcademicClient):
    """arXiv API client."""

    def __init__(self) -> None:
        """Initialize arXiv client."""
        # Load config
        try:
            from src.utils.config import get_academic_apis_config

            config = get_academic_apis_config()
            api_config = config.get_api_config("arxiv")
            base_url = api_config.base_url
            timeout = float(api_config.timeout_seconds)
            headers = api_config.headers
        except Exception:
            # Fallback to defaults if config loading fails
            base_url = "http://export.arxiv.org/api/query"
            timeout = 30.0
            headers = None

        super().__init__("arxiv", base_url=base_url, timeout=timeout, headers=headers)

    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """Search for papers (Atom XML format)."""
        session = await self._get_session()
        base_url = self.base_url
        assert base_url is not None, "base_url must be set"

        async def _search() -> str:
            response = await session.get(
                base_url,
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": limit,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
            response.raise_for_status()
            return response.text

        try:
            xml_text = await retry_api_call(_search, policy=ACADEMIC_API_POLICY)
            papers = self._parse_atom_feed(xml_text)

            return AcademicSearchResult(
                papers=papers, total_count=len(papers), next_cursor=None, source_api="arxiv"
            )
        except Exception as e:
            logger.error("arXiv search failed", query=query, error=str(e))
            return AcademicSearchResult(
                papers=[], total_count=0, next_cursor=None, source_api="arxiv"
            )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Get paper metadata from arXiv ID."""
        session = await self._get_session()
        base_url = self.base_url
        assert base_url is not None, "base_url must be set"

        async def _fetch() -> str:
            # paper_id is "2301.12345" format or "arXiv:2301.12345"
            arxiv_id = paper_id.replace("arXiv:", "").replace("arxiv:", "")
            response = await session.get(base_url, params={"id_list": arxiv_id})
            response.raise_for_status()
            return response.text

        try:
            xml_text = await retry_api_call(_fetch, policy=ACADEMIC_API_POLICY)
            papers = self._parse_atom_feed(xml_text)
            return papers[0] if papers else None
        except Exception as e:
            logger.warning("Failed to get paper", paper_id=paper_id, error=str(e))
            return None

    async def get_references(self, paper_id: str) -> list[Paper]:
        """Get references (arXiv API does not support references)."""
        logger.debug("arXiv does not support references", paper_id=paper_id)
        return []

    async def get_citations(self, paper_id: str) -> list[Paper]:
        """Get citations (arXiv API does not support citations)."""
        logger.debug("arXiv does not support citations", paper_id=paper_id)
        return []

    def _parse_atom_feed(self, xml_text: str) -> list[Paper]:
        """Parse Atom XML feed and convert to Paper list."""
        papers = []

        try:
            root = ET.fromstring(xml_text)

            # Atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                paper = self._parse_entry(entry, ns)
                if paper:
                    papers.append(paper)
        except Exception as e:
            logger.error("Failed to parse arXiv Atom feed", error=str(e))

        return papers

    def _parse_entry(self, entry: ET.Element, ns: dict) -> Paper | None:
        """Convert Atom entry element to Paper."""
        try:
            # Extract arXiv ID from ID element
            id_elem = entry.find("atom:id", ns)
            if id_elem is None or id_elem.text is None:
                return None

            arxiv_url = id_elem.text
            arxiv_id = (
                arxiv_url.split("/")[-1]
                if "/" in arxiv_url
                else arxiv_url.replace("http://arxiv.org/abs/", "")
            )

            # Title
            title_elem = entry.find("atom:title", ns)
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""

            # Abstract
            summary_elem = entry.find("atom:summary", ns)
            abstract = (
                summary_elem.text.strip()
                if summary_elem is not None and summary_elem.text
                else None
            )

            # Authors
            authors = []
            for author_elem in entry.findall("atom:author", ns):
                name_elem = author_elem.find("atom:name", ns)
                if name_elem is not None and name_elem.text:
                    authors.append(
                        Author(name=name_elem.text.strip(), affiliation=None, orcid=None)
                    )

            # Publication year
            published_elem = entry.find("atom:published", ns)
            year = None
            if published_elem is not None and published_elem.text:
                try:
                    dt = datetime.fromisoformat(published_elem.text.replace("Z", "+00:00"))
                    year = dt.year
                except Exception:
                    pass

            # PDF URL
            pdf_url = None
            for link_elem in entry.findall("atom:link", ns):
                if link_elem.get("type") == "application/pdf":
                    pdf_url = link_elem.get("href")
                    break

            return Paper(
                id=f"arxiv:{arxiv_id}",
                title=title,
                abstract=abstract,
                authors=authors,
                year=year,
                published_date=None,  # arXiv date handled via year
                doi=None,  # arXiv papers may not have DOI
                arxiv_id=arxiv_id,
                venue="arXiv",
                citation_count=0,  # arXiv API does not have citation count
                reference_count=0,
                is_open_access=True,  # arXiv is all open access
                oa_url=pdf_url or f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=pdf_url,
                source_api="arxiv",
            )
        except Exception as e:
            logger.warning("Failed to parse arXiv entry", error=str(e))
            return None
