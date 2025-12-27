"""
Tests for b: general web citation detection.

This module tests CitationDetector behavior WITHOUT calling a real LLM.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CD-N-01 | BODY link + LLM returns YES | Equivalence – normal | DetectedCitation.is_citation=True | Outbound link in paragraph |
| TC-CD-N-02 | BODY link + LLM returns NO | Equivalence – normal | DetectedCitation.is_citation=False | - |
| TC-CD-N-03 | NAV link only | Equivalence – normal | No candidates, no LLM call | LinkType filtering |
| TC-CD-B-01 | PDF outbound link in BODY | Boundary – format | Candidate included (allow_pdf=True) | Ensures PDF not skipped |
| TC-CD-B-02 | Empty HTML | Boundary – empty | [] | - |
| TC-CD-B-03 | Same-domain link | Boundary – domain | No candidates (outbound only) | - |
| TC-CD-B-04 | max_candidates=1 with 2 links | Boundary – max | Only 1 candidate processed | - |
| TC-CD-A-01 | LLM error response | Abnormal – external failure | is_citation=False with raw_response populated | - |
| TC-CD-A-02 | LLM returns invalid response (not YES/NO) | Abnormal – invalid format | is_citation=False (normalized fails) | - |
| TC-CD-A-03 | HEADING link type | Equivalence – normal | Candidate included (BODY/HEADING allowed) | - |
"""

from __future__ import annotations

from typing import cast

import pytest

from src.extractor.citation_detector import CitationDetector
from src.filter.provider import (
    ChatMessage,
    LLMHealthStatus,
    LLMOptions,
    LLMProvider,
    LLMResponse,
    get_llm_registry,
    reset_llm_registry,
)


class FakeLLMProvider:
    """Minimal fake provider for CitationDetector tests."""

    def __init__(
        self,
        *,
        reply: str = "YES",
        replies: list[str] | None = None,
        ok: bool = True,
    ) -> None:
        self._reply = reply
        self._replies = list(replies) if replies is not None else None
        self._ok = ok
        self._calls: list[str] = []

    @property
    def name(self) -> str:  # registry key
        return "fake"

    async def generate(self, prompt: str, options: LLMOptions | None = None) -> LLMResponse:
        self._calls.append(prompt)
        if self._ok:
            if self._replies is not None and self._replies:
                text = self._replies.pop(0)
            else:
                text = self._reply
            return LLMResponse.success(text=text, model="fake", provider=self.name)
        return LLMResponse.make_error(error="fake error", model="fake", provider=self.name)

    async def chat(
        self, messages: list[ChatMessage], options: LLMOptions | None = None
    ) -> LLMResponse:
        """Not used in citation detection tests."""
        return LLMResponse.make_error(error="not implemented", model="fake", provider=self.name)

    async def get_health(self) -> LLMHealthStatus:
        """Not used in citation detection tests."""
        return LLMHealthStatus.healthy()

    async def close(self) -> None:
        """Not used in citation detection tests."""
        pass

    @property
    def calls(self) -> list[str]:
        return self._calls


@pytest.mark.asyncio
async def test_detects_citation_yes() -> None:
    # Given: outbound link in BODY + provider returns YES
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p>出典：<a href="https://example.org/source">Example Source</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1
    assert len(results) == 1
    assert results[0].url == "https://example.org/source"
    assert results[0].is_citation is True


@pytest.mark.asyncio
async def test_detects_citation_no() -> None:
    # Given: outbound link in BODY + provider returns NO
    reset_llm_registry()
    provider = FakeLLMProvider(reply="NO", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <article>
        <p><a href="https://example.org/related">Related</a></p>
      </article>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1
    assert len(results) == 1
    assert results[0].is_citation is False


@pytest.mark.asyncio
async def test_skips_navigation_links_without_llm_call() -> None:
    # Given: outbound link only in NAV (should not be a candidate)
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <nav><a href="https://example.org/source">Nav Link</a></nav>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert results == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_allows_pdf_outbound_links() -> None:
    # Given: outbound PDF link in BODY (allow_pdf=True in LinkExtractor)
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p>参考：<a href="https://example.org/report.pdf">Report</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1
    assert len(results) == 1
    assert results[0].url == "https://example.org/report.pdf"


@pytest.mark.asyncio
async def test_handles_llm_error() -> None:
    # Given: provider returns error
    reset_llm_registry()
    provider = FakeLLMProvider(reply="", ok=False)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p>出典：<a href="https://example.org/source">Example Source</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1
    assert len(results) == 1
    assert results[0].is_citation is False
    assert results[0].raw_response  # error text stored


@pytest.mark.asyncio
async def test_handles_invalid_llm_response() -> None:
    # Given: provider returns invalid response (not YES/NO)
    reset_llm_registry()
    provider = FakeLLMProvider(reply="MAYBE", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p>出典：<a href="https://example.org/source">Example Source</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 2  # tiered retry
    assert len(results) == 1
    assert results[0].is_citation is False  # Invalid response normalized to NO


@pytest.mark.asyncio
async def test_retries_invalid_llm_response_and_recovers() -> None:
    # Given: first output invalid, second output valid YES
    reset_llm_registry()
    provider = FakeLLMProvider(replies=["MAYBE", "YES"], ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p>出典：<a href="https://example.org/source">Example Source</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 2
    assert len(results) == 1
    assert results[0].is_citation is True


@pytest.mark.asyncio
async def test_excludes_same_domain_links() -> None:
    # Given: link to same domain (should be excluded)
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p><a href="https://example.com/other-page">Same Domain</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert results == []
    assert provider.calls == []  # No LLM call for same-domain links


@pytest.mark.asyncio
async def test_respects_max_candidates_limit() -> None:
    # Given: multiple outbound links, max_candidates=1
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <main>
        <p><a href="https://example.org/source1">Source 1</a></p>
        <p><a href="https://example.org/source2">Source 2</a></p>
      </main>
    </body></html>
    """

    detector = CitationDetector(max_candidates=1)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1  # Only 1 candidate processed
    assert len(results) <= 1


@pytest.mark.asyncio
async def test_includes_heading_link_type() -> None:
    # Given: outbound link in HEADING (should be candidate)
    reset_llm_registry()
    provider = FakeLLMProvider(reply="YES", ok=True)
    get_llm_registry().register(cast(LLMProvider, provider), set_default=True)

    html = """
    <html><body>
      <h1><a href="https://example.org/source">Reference</a></h1>
    </body></html>
    """

    detector = CitationDetector(max_candidates=10)

    # When
    results = await detector.detect_citations(
        html=html,
        base_url="https://example.com/article",
        source_domain="example.com",
    )

    # Then
    assert len(provider.calls) == 1
    assert len(results) == 1
    assert results[0].url == "https://example.org/source"
    assert results[0].is_citation is True
