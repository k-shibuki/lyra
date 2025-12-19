"""
Identifier extractor for academic papers from URLs.

Extracts DOI, PMID, arXiv ID, CiNii CRID, etc. from SERP result URLs.
"""

import re
from urllib.parse import urlparse

from src.utils.logging import get_logger
from src.utils.schemas import PaperIdentifier

logger = get_logger(__name__)


class IdentifierExtractor:
    """Extract paper identifiers from URLs."""

    # Regex patterns for academic sites
    PATTERNS = {
        "doi": re.compile(r"doi\.org/(10\.\d{4,}/[^\s?#]+)", re.IGNORECASE),
        "pmid": re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE),
        "arxiv": re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE),
        "jstage_doi": re.compile(r"jstage\.jst\.go\.jp/.*/(10\.\d+/[^/?#]+)", re.IGNORECASE),
        "cinii_crid": re.compile(r"cir\.nii\.ac\.jp/crid/(\d+)", re.IGNORECASE),
        "nature_doi": re.compile(r"nature\.com/articles/(s\d+-\d+-\d+-\w+)", re.IGNORECASE),
        "sciencedirect_doi": re.compile(r"sciencedirect\.com/science/article/pii/([A-Z0-9]+)", re.IGNORECASE),
    }

    def extract(self, url: str) -> PaperIdentifier:
        """Extract identifiers from URL.

        Args:
            url: Paper URL

        Returns:
            PaperIdentifier with extracted identifiers
        """
        if not url:
            return PaperIdentifier(url=url)

        identifier = PaperIdentifier(url=url)

        # 1. DOI (doi.org)
        doi_match = self.PATTERNS["doi"].search(url)
        if doi_match:
            identifier.doi = doi_match.group(1)
            logger.debug("Extracted DOI from URL", doi=identifier.doi, url=url)
            return identifier

        # 2. PMID (PubMed)
        pmid_match = self.PATTERNS["pmid"].search(url)
        if pmid_match:
            identifier.pmid = pmid_match.group(1)
            identifier.needs_meta_extraction = True  # DOI conversion needed
            logger.debug("Extracted PMID from URL", pmid=identifier.pmid, url=url)
            return identifier

        # 3. arXiv ID
        arxiv_match = self.PATTERNS["arxiv"].search(url)
        if arxiv_match:
            identifier.arxiv_id = arxiv_match.group(1)
            identifier.needs_meta_extraction = True  # DOI conversion needed
            logger.debug("Extracted arXiv ID from URL", arxiv_id=identifier.arxiv_id, url=url)
            return identifier

        # 4. J-Stage DOI
        jstage_match = self.PATTERNS["jstage_doi"].search(url)
        if jstage_match:
            identifier.doi = jstage_match.group(1)
            logger.debug("Extracted DOI from J-Stage URL", doi=identifier.doi, url=url)
            return identifier

        # 5. CiNii CRID
        cinii_match = self.PATTERNS["cinii_crid"].search(url)
        if cinii_match:
            identifier.crid = cinii_match.group(1)
            identifier.needs_meta_extraction = True  # DOI conversion needed
            logger.debug("Extracted CRID from URL", crid=identifier.crid, url=url)
            return identifier

        # 6. Nature article ID (may contain DOI in meta tags)
        nature_match = self.PATTERNS["nature_doi"].search(url)
        if nature_match:
            identifier.needs_meta_extraction = True  # Need to extract DOI from meta tags
            logger.debug("Detected Nature article URL", url=url)
            return identifier

        # 7. ScienceDirect (may contain DOI in meta tags)
        sciencedirect_match = self.PATTERNS["sciencedirect_doi"].search(url)
        if sciencedirect_match:
            identifier.needs_meta_extraction = True  # Need to extract DOI from meta tags
            logger.debug("Detected ScienceDirect URL", url=url)
            return identifier

        # 8. Other academic domains (need meta tag extraction)
        parsed = urlparse(url)
        academic_domains = [
            "pubmed.gov",
            "ncbi.nlm.nih.gov",
            "arxiv.org",
            "jstage.jst.go.jp",
            "cir.nii.ac.jp",
            "nature.com",
            "sciencedirect.com",
            "ieee.org",
            "acm.org",
            "springer.com",
            "wiley.com",
        ]

        domain_lower = parsed.netloc.lower()
        if any(academic_domain in domain_lower for academic_domain in academic_domains):
            identifier.needs_meta_extraction = True
            logger.debug("Detected academic domain, needs meta extraction", domain=domain_lower, url=url)

        return identifier

    @staticmethod
    def extract_doi_from_text(text: str) -> str | None:
        """Extract DOI from text (meta tags, etc.).

        Args:
            text: HTML text or meta tag content

        Returns:
            DOI string or None
        """
        # DOI pattern: 10.xxxx/...
        doi_pattern = re.compile(r"10\.\d{4,}/[^\s<>\"']+", re.IGNORECASE)
        match = doi_pattern.search(text)
        if match:
            return match.group(0)
        return None
