"""
Debug script: validate cross-module propagation for response_format and retry_count.

How to run:
    ./.venv/bin/python tests/scripts/debug_llm_response_format_flow.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.filter.llm_output import parse_and_validate
from src.filter.llm_schemas import ExtractedFact
from src.filter.ollama_provider import OllamaProvider
from src.filter.provider import LLMOptions
from src.filter.schemas import OllamaGenerateRequest
from src.storage.database import get_database
from src.storage.isolation import isolated_database_path


async def _check_payload_propagation() -> None:
    """Verify response_format/stop propagate into Ollama /api/generate payload."""
    provider = OllamaProvider(host="http://localhost:11434", model="test-model:3b")

    # First response: reject format (simulate older proxy), second: OK.
    mock_bad = MagicMock()
    mock_bad.status = 400
    mock_bad.text = AsyncMock(return_value="unknown field: format")

    mock_ok = MagicMock()
    mock_ok.status = 200
    mock_ok.json = AsyncMock(return_value={"response": "OK"})

    cm1 = AsyncMock()
    cm1.__aenter__.return_value = mock_bad
    cm1.__aexit__.return_value = None

    cm2 = AsyncMock()
    cm2.__aenter__.return_value = mock_ok
    cm2.__aexit__.return_value = None

    captured: list[dict[str, object]] = []
    call_n = {"n": 0}

    def capture_post(url: str, json: dict[str, object], timeout=None) -> AsyncMock:
        captured.append(dict(json))
        call_n["n"] += 1
        return cm1 if call_n["n"] == 1 else cm2

    mock_session = MagicMock()
    mock_session.post = capture_post

    with patch.object(provider, "_get_session", AsyncMock(return_value=mock_session)):
        resp = await provider.generate(
            prompt="Test",
            options=LLMOptions(
                temperature=0.1,
                max_tokens=8,
                stop=["\n"],
                response_format="json",
            ),
        )

    assert resp.ok is True
    assert resp.text == "OK"
    assert len(captured) == 2
    assert captured[0].get("format") == "json"
    assert "format" not in captured[1]
    _ = OllamaGenerateRequest.model_validate(captured[1])
    assert captured[1]["options"]["stop"] == ["\n"]

    print("[debug] payload propagation OK (format + stop + fallback)")


async def _check_retry_count_recording() -> None:
    """Verify retry_count is recorded as 'retries attempted' in the DB."""
    async with isolated_database_path() as db_path:
        print(f"[debug] Using isolated DB: {db_path}")

        db = await get_database()

        # Case: no llm_call provided -> no retries attempted.
        validated = await parse_and_validate(
            response="no json here",
            schema=ExtractedFact,
            template_name="extract_facts",
            expect_array=True,
            llm_call=None,
            max_retries=1,
            context={"case": "no_llm_call"},
        )
        assert validated is None

        row = await db.fetch_one(
            "SELECT retry_count FROM llm_extraction_errors WHERE template_name = ? ORDER BY created_at DESC LIMIT 1",
            ("extract_facts",),
        )
        assert row is not None
        assert row["retry_count"] == 0

        print("[debug] retry_count recording OK (0 when llm_call is None)")


async def main() -> None:
    await _check_payload_propagation()
    await _check_retry_count_recording()


if __name__ == "__main__":
    asyncio.run(main())





