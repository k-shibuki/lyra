"""
Identifier extractor for academic papers from URLs.

Extracts DOI, PMID, arXiv ID from SERP result URLs.
Per ADR-0008: S2 + OpenAlex two-pillar strategy.
"""

from __future__ import annotations

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
        "pmcid": re.compile(r"pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)", re.IGNORECASE),
        "arxiv": re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE),
        "openalex": re.compile(r"openalex\.org/(W\d+)", re.IGNORECASE),
        "s2": re.compile(r"semanticscholar\.org/paper/[^/]+/([a-f0-9]{40})", re.IGNORECASE),
        "jstage_doi": re.compile(r"jstage\.jst\.go\.jp/.*/(10\.\d+/[^/?#]+)", re.IGNORECASE),
        "nature_doi": re.compile(r"nature\.com/articles/(s\d+-\d+-\d+-\w+)", re.IGNORECASE),
        "sciencedirect_doi": re.compile(
            r"sciencedirect\.com/science/article/pii/([A-Z0-9]+)", re.IGNORECASE
        ),
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

        # Extract as many identifiers as possible; routing/priority is decided downstream.

        # 1. DOI (doi.org)
        doi_match = self.PATTERNS["doi"].search(url)
        if doi_match:
            identifier.doi = doi_match.group(1)
            logger.debug("Extracted DOI from URL", doi=identifier.doi, url=url)

        # 2. PMID (PubMed)
        pmid_match = self.PATTERNS["pmid"].search(url)
        if pmid_match:
            identifier.pmid = pmid_match.group(1)
            identifier.needs_meta_extraction = True  # DOI conversion needed
            logger.debug("Extracted PMID from URL", pmid=identifier.pmid, url=url)

            try:
                from src.utils.agent_debug import (
                    agent_debug_run_id,
                    agent_debug_session_id,
                    agent_log,
                )

                agent_log(
                    sessionId=agent_debug_session_id(),
                    runId=agent_debug_run_id(),
                    hypothesisId="H-PMID-01",
                    location="src/search/identifier_extractor.py:pmid_match",
                    message="Extracted PMID from URL",
                    data={"pmid": identifier.pmid, "url": url[:300]},
                )
            except Exception:
                pass

            # continue: other IDs may also exist in the URL

        # 2b. PMCID (PubMed Central)
        pmcid_match = self.PATTERNS["pmcid"].search(url)
        if pmcid_match:
            identifier.pmcid = pmcid_match.group(1)
            identifier.needs_meta_extraction = True  # PMID/DOI conversion needed
            logger.debug("Extracted PMCID from URL", pmcid=identifier.pmcid, url=url)

            try:
                from src.utils.agent_debug import (
                    agent_debug_run_id,
                    agent_debug_session_id,
                    agent_log,
                )

                agent_log(
                    sessionId=agent_debug_session_id(),
                    runId=agent_debug_run_id(),
                    hypothesisId="H-PMID-11",
                    location="src/search/identifier_extractor.py:pmcid_match",
                    message="Extracted PMCID from URL",
                    data={"pmcid": identifier.pmcid, "url": url[:300]},
                )
            except Exception:
                pass

            # continue

        # 3. arXiv ID
        arxiv_match = self.PATTERNS["arxiv"].search(url)
        if arxiv_match:
            identifier.arxiv_id = arxiv_match.group(1)
            identifier.needs_meta_extraction = True  # DOI conversion needed
            logger.debug("Extracted arXiv ID from URL", arxiv_id=identifier.arxiv_id, url=url)
            # continue

        # 3b. OpenAlex Work ID
        openalex_match = self.PATTERNS["openalex"].search(url)
        if openalex_match:
            identifier.openalex_work_id = openalex_match.group(1)
            logger.debug(
                "Extracted OpenAlex Work ID from URL",
                openalex_work_id=identifier.openalex_work_id,
                url=url,
            )

        # 3c. Semantic Scholar paper ID (paperId hash)
        s2_match = self.PATTERNS["s2"].search(url)
        if s2_match:
            identifier.s2_paper_id = s2_match.group(1)
            logger.debug(
                "Extracted S2 paper ID from URL", s2_paper_id=identifier.s2_paper_id, url=url
            )

        # 4. J-Stage DOI
        jstage_match = self.PATTERNS["jstage_doi"].search(url)
        if jstage_match:
            identifier.doi = jstage_match.group(1)
            logger.debug("Extracted DOI from J-Stage URL", doi=identifier.doi, url=url)
            return identifier

        # 5. Nature article ID (may contain DOI in meta tags)
        nature_match = self.PATTERNS["nature_doi"].search(url)
        if nature_match:
            identifier.needs_meta_extraction = True  # Need to extract DOI from meta tags
            logger.debug("Detected Nature article URL", url=url)
            return identifier

        # 6. ScienceDirect (may contain DOI in meta tags)
        sciencedirect_match = self.PATTERNS["sciencedirect_doi"].search(url)
        if sciencedirect_match:
            identifier.needs_meta_extraction = True  # Need to extract DOI from meta tags
            logger.debug("Detected ScienceDirect URL", url=url)
            return identifier

        # 7. Other academic domains (need meta tag extraction)
        parsed = urlparse(url)
        academic_domains = [
            "pubmed.gov",
            "ncbi.nlm.nih.gov",
            "arxiv.org",
            "jstage.jst.go.jp",
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
            logger.debug(
                "Detected academic domain, needs meta extraction", domain=domain_lower, url=url
            )

            try:
                from src.utils.agent_debug import (
                    agent_debug_run_id,
                    agent_debug_session_id,
                    agent_log,
                )

                agent_log(
                    sessionId=agent_debug_session_id(),
                    runId=agent_debug_run_id(),
                    hypothesisId="H-PMID-01",
                    location="src/search/identifier_extractor.py:academic_domain",
                    message="Academic domain detected but no direct ID pattern matched",
                    data={"domain": domain_lower, "url": url[:300]},
                )
            except Exception:
                pass

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
