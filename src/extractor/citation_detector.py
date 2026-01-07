"""
Citation detection for general web pages (b).

Detects whether outbound links in the main content are used as citations
("information source references") and returns structured results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.crawler.bfs import LinkExtractor, LinkType
from src.extractor.html_normalizer import get_effective_base_url
from src.filter.llm_security import validate_llm_output
from src.filter.ollama_provider import create_ollama_provider
from src.filter.provider import LLMOptions, get_llm_registry

if TYPE_CHECKING:
    from src.filter.provider import LLMProvider

from src.utils.logging import get_logger
from src.utils.prompt_manager import render_prompt

logger = get_logger(__name__)


_DETECT_CITATION_INSTRUCTIONS = "回答は YES または NO のみ。"
_DETECT_CITATION_RETRY_SUFFIX = (
    "\n\nIMPORTANT: Answer exactly YES or NO (no extra words).\n"
    "Examples:\n"
    'Context: "According to Smith et al. (2023) [1], ..." -> YES\n'
    'Context: "Read next: Related articles" -> NO\n'
)


@dataclass(frozen=True)
class DetectedCitation:
    """Detected citation candidate from a web page."""

    url: str
    link_text: str
    context: str
    link_type: str
    is_citation: bool
    raw_response: str


def _normalize_yes_no(text: str) -> str | None:
    cleaned = text.strip().upper()
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    if cleaned.startswith("YES"):
        return "YES"
    if cleaned.startswith("NO"):
        return "NO"
    return None


class CitationDetector:
    """Detect citation links from a general web page."""

    def __init__(self, *, max_candidates: int = 15) -> None:
        self._max_candidates = max_candidates
        self._link_extractor = LinkExtractor()

    async def detect_citations(
        self,
        *,
        html: str,
        base_url: str,
        source_domain: str,
    ) -> list[DetectedCitation]:
        """
        Detect citation links from a general web page.

        Strategy:
        - Extract outbound links from HTML (prefer BODY/HEADING links).
        - Ask local LLM (Ollama) to classify each link as citation YES/NO.
        """
        # Resolve effective base URL (respects <base href="..."> if present)
        effective_base_url = get_effective_base_url(html, base_url)

        # Extract outbound links (include external links; allow PDFs).
        links = self._link_extractor.extract_links(
            html,
            effective_base_url,
            source_domain,
            same_domain_only=False,
            allow_pdf=True,
        )

        # Candidate selection: outbound only + "content-ish" link types
        candidates = []
        for link in links:
            try:
                netloc = urlparse(link.url).netloc.lower()
            except Exception:
                continue
            if not netloc or netloc == source_domain.lower():
                continue
            if link.link_type not in (LinkType.BODY, LinkType.HEADING):
                continue
            if link.url == effective_base_url:
                continue
            candidates.append(link)
            if len(candidates) >= self._max_candidates:
                break

        if not candidates:
            return []

        # Acquire provider (reuse registry default if possible)
        registry = get_llm_registry()
        if not registry.list_providers():
            new_provider = create_ollama_provider()
            registry.register(new_provider, set_default=True)

        provider: LLMProvider | None = registry.get_default()
        if provider is None:
            raise RuntimeError("No LLM provider available")

        model = None
        if hasattr(provider, "model"):
            model = provider.model

        results: list[DetectedCitation] = []

        for link in candidates:
            prompt = render_prompt(
                "detect_citation",
                context=(link.context or "")[:800],
                url=link.url,
                link_text=(link.text or "")[:200],
            )

            try:
                options = LLMOptions(
                    model=model,
                    temperature=0.1,
                    max_tokens=8,
                    stop=["\n"],
                )
                response = await provider.generate(prompt, options)
                if not response.ok:
                    results.append(
                        DetectedCitation(
                            url=link.url,
                            link_text=link.text,
                            context=link.context,
                            link_type=link.link_type.value,
                            is_citation=False,
                            raw_response=response.error or "",
                        )
                    )
                    continue

                validation = validate_llm_output(
                    response.text,
                    system_prompt=_DETECT_CITATION_INSTRUCTIONS,
                    mask_leakage=True,
                )
                normalized = _normalize_yes_no(validation.validated_text)

                # Tiered prompting: if the model doesn't output YES/NO, retry once with stronger constraints.
                if normalized is None:
                    retry_prompt = prompt + _DETECT_CITATION_RETRY_SUFFIX
                    retry_response = await provider.generate(retry_prompt, options)
                    if retry_response.ok:
                        retry_validation = validate_llm_output(
                            retry_response.text,
                            system_prompt=_DETECT_CITATION_INSTRUCTIONS,
                            mask_leakage=True,
                        )
                        retry_normalized = _normalize_yes_no(retry_validation.validated_text)
                        if retry_normalized is not None:
                            validation = retry_validation
                            normalized = retry_normalized

                is_citation = normalized == "YES"

                results.append(
                    DetectedCitation(
                        url=link.url,
                        link_text=link.text,
                        context=link.context,
                        link_type=link.link_type.value,
                        is_citation=is_citation,
                        raw_response=validation.validated_text.strip(),
                    )
                )
            except Exception as e:
                logger.debug(
                    "Citation detection failed",
                    url=link.url[:100],
                    error=str(e),
                )
                results.append(
                    DetectedCitation(
                        url=link.url,
                        link_text=link.text,
                        context=link.context,
                        link_type=link.link_type.value,
                        is_citation=False,
                        raw_response="",
                    )
                )

        return results
