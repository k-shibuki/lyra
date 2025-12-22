"""
Tests for Phase 4 / Task 4.0 prerequisite A:
Wire Step 7 (NLI) into the normal search path and persist edges.nli_confidence.

Goal:
- Prove SearchExecutor._persist_claim() calls NLI and persists a claim-evidence edge
  via add_claim_evidence() with (relation, nli_label, nli_confidence).
- Prove stance changes affect persisted edge relation (effect).
- Include failure cases so we don't silently skip wiring.

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-EX-NLI-N-01 | nli_judge returns supports(0.91) | Equivalence – normal | add_claim_evidence called with relation=supports, nli_confidence=0.91 | wiring + effect |
| TC-EX-NLI-N-02 | nli_judge returns refutes(0.80) | Equivalence – normal | add_claim_evidence called with relation=refutes, nli_confidence=0.80 | effect |
| TC-EX-NLI-A-01 | nli_judge returns invalid stance | Abnormal – invalid output | relation sanitized to neutral | no fabrication |
| TC-EX-NLI-A-02 | nli_judge raises exception | Abnormal – dependency failure | add_claim_evidence still called with neutral/0.0 | robust path |
| TC-EX-NLI-A-03 | fragment text missing in DB | Boundary – NULL | nli_judge called with fallback premise (claim_text) | avoids empty premise |
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.research.executor import SearchExecutor
from src.research.state import ExplorationState


def _make_executor() -> SearchExecutor:
    state = ExplorationState(task_id="test_task")
    return SearchExecutor(task_id="test_task", state=state)


@pytest.mark.asyncio
async def test_executor_persist_claim_wires_nli_supports() -> None:
    # Given: executor + DB with a fragment premise
    ex = _make_executor()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value={"text_content": "premise text" * 50})

    with (
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "supports", "confidence": 0.91}]),
        ) as nli_judge,
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()) as add_claim_evidence,
    ):
        # When: persisting a claim
        await ex._persist_claim(
            claim_id="c1",
            claim_text="Hypothesis text",
            confidence=0.70,  # LLM-extracted confidence (not Bayesian input)
            source_url="https://example.com/a",
            source_fragment_id="f1",
        )

        # Then: NLI is called
        assert nli_judge.await_count == 1
        nli_call = nli_judge.await_args
        assert nli_call is not None
        called_pairs = nli_call.kwargs["pairs"]
        assert called_pairs[0]["pair_id"] == "f1:c1"
        assert called_pairs[0]["premise"]
        assert called_pairs[0]["hypothesis"] == "Hypothesis text"

        # Then: edge persistence is wired with NLI-derived fields
        assert add_claim_evidence.await_count == 1
        edge_call = add_claim_evidence.await_args
        assert edge_call is not None
        kwargs = edge_call.kwargs
        assert kwargs["claim_id"] == "c1"
        assert kwargs["fragment_id"] == "f1"
        assert kwargs["task_id"] == "test_task"
        assert kwargs["relation"] == "supports"
        assert kwargs["nli_label"] == "supports"
        assert kwargs["nli_confidence"] == pytest.approx(0.91)
        # Legacy: confidence aligned to nli_confidence
        assert kwargs["confidence"] == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_executor_persist_claim_wires_nli_refutes() -> None:
    # Given
    ex = _make_executor()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value={"text_content": "premise"})

    with (
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "refutes", "confidence": 0.80}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()) as add_claim_evidence,
    ):
        # When
        await ex._persist_claim(
            claim_id="c1",
            claim_text="H",
            confidence=0.50,
            source_url="https://example.com/a",
            source_fragment_id="f1",
        )

        # Then
        edge_call = add_claim_evidence.await_args
        assert edge_call is not None
        kwargs = edge_call.kwargs
        assert kwargs["relation"] == "refutes"
        assert kwargs["nli_label"] == "refutes"
        assert kwargs["nli_confidence"] == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_executor_persist_claim_sanitizes_invalid_stance_to_neutral() -> None:
    # Given
    ex = _make_executor()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value={"text_content": "premise"})

    with (
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "entailment", "confidence": 0.99}]),
        ),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()) as add_claim_evidence,
    ):
        # When
        await ex._persist_claim(
            claim_id="c1",
            claim_text="H",
            confidence=0.50,
            source_url="https://example.com/a",
            source_fragment_id="f1",
        )

        # Then: invalid stance is not propagated
        edge_call = add_claim_evidence.await_args
        assert edge_call is not None
        kwargs = edge_call.kwargs
        assert kwargs["relation"] == "neutral"
        assert kwargs["nli_label"] == "neutral"


@pytest.mark.asyncio
async def test_executor_persist_claim_nli_failure_does_not_skip_edge_persist() -> None:
    # Given
    ex = _make_executor()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value={"text_content": "premise"})

    with (
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db)),
        patch("src.filter.nli.nli_judge", AsyncMock(side_effect=RuntimeError("nli down"))),
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()) as add_claim_evidence,
    ):
        # When
        await ex._persist_claim(
            claim_id="c1",
            claim_text="H",
            confidence=0.50,
            source_url="https://example.com/a",
            source_fragment_id="f1",
        )

        # Then: still persists with neutral/0.0 (no fabrication)
        edge_call = add_claim_evidence.await_args
        assert edge_call is not None
        kwargs = edge_call.kwargs
        assert kwargs["relation"] == "neutral"
        assert kwargs["nli_label"] == "neutral"
        assert kwargs["nli_confidence"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_executor_persist_claim_uses_fallback_premise_when_fragment_missing() -> None:
    # Given: fragment text missing in DB (NULL)
    ex = _make_executor()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value=None)  # fragment not found

    with (
        patch("src.research.executor.get_database", AsyncMock(return_value=mock_db)),
        patch(
            "src.filter.nli.nli_judge",
            AsyncMock(return_value=[{"stance": "supports", "confidence": 0.55}]),
        ) as nli_judge,
        patch("src.filter.evidence_graph.add_claim_evidence", AsyncMock()),
    ):
        # When
        await ex._persist_claim(
            claim_id="c1",
            claim_text="Hypothesis text",
            confidence=0.70,
            source_url="https://example.com/a",
            source_fragment_id="f1",
        )

        # Then: premise falls back to claim_text (not empty)
        nli_call = nli_judge.await_args
        assert nli_call is not None
        called_pairs = nli_call.kwargs["pairs"]
        assert called_pairs[0]["premise"] == "Hypothesis text"
