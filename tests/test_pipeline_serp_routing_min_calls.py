"""
Tests for SERP complement routing (fastest_min_calls).

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---|---|---|---|---|
| TC-ROUTE-N-01 | OpenAlex URL, OA returns abstract+DOI | Equivalence – normal | OA called once with openalex:W..., S2 not called, merged into doi:... | Minimal calls |
| TC-ROUTE-A-01 | OpenAlex URL, OA returns no abstract but has DOI | Abnormal – missing field | OA called, then S2 called with DOI:..., merged into doi:... | 2nd call only when needed |
| TC-ROUTE-A-02 | OpenAlex URL, OA raises exception | Abnormal – API failure | Exception handled gracefully, returns None | External dependency failure |
| TC-ROUTE-A-03 | Both OA and S2 return None | Abnormal – all fail | Returns None, no index merge | Complete failure path |
| TC-ROUTE-B-01 | Generic URL (no recognized ID) | Boundary – no complement possible | Returns None immediately | No API calls made |
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.research.pipeline import SearchPipeline
from src.research.state import ExplorationState
from src.search.canonical_index import CanonicalPaperIndex
from src.search.identifier_extractor import IdentifierExtractor
from src.search.provider import SERPResult
from src.utils.schemas import Paper


class _ResolverStub:
    async def resolve_pmcid(self, pmcid: str) -> None:  # noqa: ANN001
        raise AssertionError("Should not be called")

    async def resolve_pmid_to_doi(self, pmid: str) -> None:  # noqa: ANN001
        raise AssertionError("Should not be called")

    async def resolve_arxiv_to_doi(self, arxiv_id: str) -> None:  # noqa: ANN001
        raise AssertionError("Should not be called")


@pytest.mark.asyncio
async def test_route_openalex_url_min_calls_when_oa_has_abstract() -> None:
    # Given: SERP result with OpenAlex URL and OA returns abstract
    url = "https://openalex.org/W2741809807"
    serp = SERPResult(
        title="OpenAlex Work Page",
        url=url,
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    extractor = IdentifierExtractor()
    ident = extractor.extract(url)
    index = CanonicalPaperIndex()
    entry_cid = index.register_serp_result(serp, ident)

    oa_client = AsyncMock()
    oa_client.get_paper = AsyncMock(
        return_value=Paper(
            id="openalex:W2741809807",
            title="Example",
            abstract="Abstract from OpenAlex",
            authors=[],
            year=2020,
            published_date=None,
            doi="10.7717/peerj.4375",
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        )
    )
    s2_client = AsyncMock()
    s2_client.get_paper = AsyncMock()

    academic_provider = AsyncMock()

    async def _get_client(name: str) -> Any:  # noqa: ANN001
        return oa_client if name == "openalex" else s2_client

    academic_provider._get_client = AsyncMock(side_effect=_get_client)

    pipeline = SearchPipeline(task_id="t_api_02b", state=ExplorationState(task_id="t_api_02b"))

    # When: complementing
    paper = await pipeline._complement_serp_result(
        academic_provider=academic_provider,
        resolver=_ResolverStub(),
        extractor=extractor,
        index=index,
        serp_url=url,
        serp_result=serp,
        entry_canonical_id=entry_cid,
    )

    # Then: OA called once, S2 not called, and index merged to DOI canonical
    assert paper is not None
    oa_client.get_paper.assert_awaited_once_with("openalex:W2741809807")
    s2_client.get_paper.assert_not_awaited()
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].canonical_id == "doi:10.7717/peerj.4375"
    assert entries[0].source == "both"


@pytest.mark.asyncio
async def test_route_openalex_url_calls_s2_only_when_needed() -> None:
    # Given: OA returns no abstract but DOI exists; S2 returns abstract
    url = "https://openalex.org/W2741809807"
    serp = SERPResult(
        title="OpenAlex Work Page",
        url=url,
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    extractor = IdentifierExtractor()
    ident = extractor.extract(url)
    index = CanonicalPaperIndex()
    entry_cid = index.register_serp_result(serp, ident)

    oa_client = AsyncMock()
    oa_client.get_paper = AsyncMock(
        return_value=Paper(
            id="openalex:W2741809807",
            title="Example",
            abstract=None,  # Missing abstract triggers second call
            authors=[],
            year=2020,
            published_date=None,
            doi="10.7717/peerj.4375",
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="openalex",
        )
    )
    s2_client = AsyncMock()
    s2_client.get_paper = AsyncMock(
        return_value=Paper(
            id="s2:deadbeef" * 4,  # dummy
            title="Example",
            abstract="Abstract from S2",
            authors=[],
            year=2020,
            published_date=None,
            doi="10.7717/peerj.4375",
            arxiv_id=None,
            venue=None,
            citation_count=0,
            reference_count=0,
            is_open_access=False,
            oa_url=None,
            pdf_url=None,
            source_api="semantic_scholar",
        )
    )

    academic_provider = AsyncMock()

    async def _get_client(name: str) -> Any:  # noqa: ANN001
        return oa_client if name == "openalex" else s2_client

    academic_provider._get_client = AsyncMock(side_effect=_get_client)

    pipeline = SearchPipeline(task_id="t_api_02b", state=ExplorationState(task_id="t_api_02b"))

    # When: complementing
    paper = await pipeline._complement_serp_result(
        academic_provider=academic_provider,
        resolver=_ResolverStub(),
        extractor=extractor,
        index=index,
        serp_url=url,
        serp_result=serp,
        entry_canonical_id=entry_cid,
    )

    # Then: OA called, then S2 called with DOI, and DOI entry exists
    assert paper is not None
    oa_client.get_paper.assert_awaited_once_with("openalex:W2741809807")
    s2_client.get_paper.assert_awaited_once_with("DOI:10.7717/peerj.4375")
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].canonical_id == "doi:10.7717/peerj.4375"


@pytest.mark.asyncio
async def test_route_openalex_url_handles_api_exception() -> None:
    # Given: OA raises an exception
    url = "https://openalex.org/W2741809807"
    serp = SERPResult(
        title="OpenAlex Work Page",
        url=url,
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    extractor = IdentifierExtractor()
    ident = extractor.extract(url)
    index = CanonicalPaperIndex()
    entry_cid = index.register_serp_result(serp, ident)

    oa_client = AsyncMock()
    oa_client.get_paper = AsyncMock(side_effect=Exception("API timeout"))
    s2_client = AsyncMock()
    s2_client.get_paper = AsyncMock()

    academic_provider = AsyncMock()

    async def _get_client(name: str) -> Any:
        return oa_client if name == "openalex" else s2_client

    academic_provider._get_client = AsyncMock(side_effect=_get_client)

    pipeline = SearchPipeline(task_id="t_api_02b", state=ExplorationState(task_id="t_api_02b"))

    # When: complementing (OA throws)
    paper = await pipeline._complement_serp_result(
        academic_provider=academic_provider,
        resolver=_ResolverStub(),
        extractor=extractor,
        index=index,
        serp_url=url,
        serp_result=serp,
        entry_canonical_id=entry_cid,
    )

    # Then: gracefully returns None, no crash
    assert paper is None
    oa_client.get_paper.assert_awaited_once()
    # S2 not called because primary failed and no DOI to try secondary
    s2_client.get_paper.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_both_apis_return_none() -> None:
    # Given: Both OA and S2 return None
    url = "https://openalex.org/W2741809807"
    serp = SERPResult(
        title="OpenAlex Work Page",
        url=url,
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    extractor = IdentifierExtractor()
    ident = extractor.extract(url)
    index = CanonicalPaperIndex()
    entry_cid = index.register_serp_result(serp, ident)

    oa_client = AsyncMock()
    oa_client.get_paper = AsyncMock(return_value=None)
    s2_client = AsyncMock()
    s2_client.get_paper = AsyncMock(return_value=None)

    academic_provider = AsyncMock()

    async def _get_client(name: str) -> Any:
        return oa_client if name == "openalex" else s2_client

    academic_provider._get_client = AsyncMock(side_effect=_get_client)

    pipeline = SearchPipeline(task_id="t_api_02b", state=ExplorationState(task_id="t_api_02b"))

    # When: complementing (both return None)
    paper = await pipeline._complement_serp_result(
        academic_provider=academic_provider,
        resolver=_ResolverStub(),
        extractor=extractor,
        index=index,
        serp_url=url,
        serp_result=serp,
        entry_canonical_id=entry_cid,
    )

    # Then: returns None, index unchanged (SERP-only entry remains)
    assert paper is None
    oa_client.get_paper.assert_awaited_once()
    # S2 may not be called because OA returned None (no DOI to derive)
    # Actually depends on implementation: if needs_second triggers but no DOI, secondary skipped
    entries = index.get_all_entries()
    assert len(entries) == 1
    assert entries[0].canonical_id == "openalex:W2741809807"  # unchanged


@pytest.mark.asyncio
async def test_route_generic_url_no_complement() -> None:
    # Given: Generic URL with no recognized ID pattern
    url = "https://example.com/random-page"
    serp = SERPResult(
        title="Random Page",
        url=url,
        snippet="",
        engine="debug",
        rank=1,
        date=None,
    )
    extractor = IdentifierExtractor()
    ident = extractor.extract(url)
    index = CanonicalPaperIndex()
    entry_cid = index.register_serp_result(serp, ident)

    oa_client = AsyncMock()
    s2_client = AsyncMock()

    academic_provider = AsyncMock()

    async def _get_client(name: str) -> Any:
        return oa_client if name == "openalex" else s2_client

    academic_provider._get_client = AsyncMock(side_effect=_get_client)

    pipeline = SearchPipeline(task_id="t_api_02b", state=ExplorationState(task_id="t_api_02b"))

    # When: complementing (no recognized ID)
    paper = await pipeline._complement_serp_result(
        academic_provider=academic_provider,
        resolver=_ResolverStub(),
        extractor=extractor,
        index=index,
        serp_url=url,
        serp_result=serp,
        entry_canonical_id=entry_cid,
    )

    # Then: returns None immediately, no API calls made
    assert paper is None
    oa_client.get_paper.assert_not_awaited()
    s2_client.get_paper.assert_not_awaited()
