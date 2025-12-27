"""
Debug script: validate LLM output parsing/validation flow end-to-end.

How to run:
    ./.venv/bin/python tests/scripts/debug_llm_output_flow.py
"""

from __future__ import annotations

import asyncio

from src.filter.llm_output import parse_and_validate
from src.filter.llm_schemas import ExtractedFact
from src.storage.database import get_database
from src.storage.isolation import isolated_database_path


async def main() -> None:
    async with isolated_database_path() as db_path:
        print(f"[debug] Using isolated DB: {db_path}")

        db = await get_database()

        # Case 1: json_parse -> retry once -> success
        calls: list[str] = []

        async def llm_call(prompt: str) -> str:
            calls.append(prompt)
            return '[{"fact":"A","confidence":"0.8","evidence_type":"UNKNOWN"}]'

        validated = await parse_and_validate(
            response="not json",
            schema=ExtractedFact,
            template_name="extract_facts",
            expect_array=True,
            llm_call=llm_call,
            max_retries=1,
            context={"case": "retry_success"},
        )
        assert validated is not None
        assert validated[0].fact == "A"
        assert validated[0].confidence == 0.8
        assert validated[0].evidence_type == "observation"
        assert len(calls) == 1
        print("[debug] Case 1 OK: retry succeeded")

        # Case 2: final failure -> DB record, returns None
        validated2 = await parse_and_validate(
            response="no json here",
            schema=ExtractedFact,
            template_name="extract_facts",
            expect_array=True,
            llm_call=None,
            max_retries=1,
            context={"case": "final_failure"},
        )
        assert validated2 is None

        rows = await db.fetch_all(
            "SELECT template_name, error_type, retry_count FROM llm_extraction_errors ORDER BY created_at"
        )
        assert rows, "Expected at least one llm_extraction_errors row"
        print(f"[debug] Case 2 OK: recorded {len(rows)} error row(s)")


if __name__ == "__main__":
    asyncio.run(main())


