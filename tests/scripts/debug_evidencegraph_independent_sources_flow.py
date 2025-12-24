"""
Debug script for EVIDENCE_SYSTEM_CURRENT_STATUS.md inconsistency #2.

Goal:
- Reproduce the runtime mismatch where EvidenceGraph.calculate_claim_confidence()
  counts independent_sources based on PAGE nodes, while the production path
  persists FRAGMENT->CLAIM evidence edges.

This script uses an isolated DB and prints diagnostic output to stdout.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

from src.filter.evidence_graph import EvidenceGraph, add_claim_evidence
from src.filter.source_verification import SourceVerifier
from src.research.materials import get_materials_action
from src.storage.database import get_database
from src.storage.isolation import isolated_database_path


async def main() -> int:
    # Given: fresh isolated DB
    async with isolated_database_path() as db_path:
        db = await get_database()

        task_id = await db.create_task(query="debug: independent_sources mismatch")
        claim_id = "c_debug_1"

        # Create 2 pages (different domains) and 2 fragments (one per page)
        page_a_id = "p_debug_a"
        page_b_id = "p_debug_b"
        url_a = "https://alpha.example.test/a"
        url_b = "https://beta.example.test/b"
        paper_metadata_a = json.dumps(
            {
                "paper_id": "paper_alpha",
                "year": 2020,
                "doi": "10.0000/alpha",
                "venue": "AlphaConf",
                "source_api": "debug",
            }
        )
        paper_metadata_b = json.dumps(
            {
                "paper_id": "paper_beta",
                "year": 2021,
                "doi": "10.0000/beta",
                "venue": "BetaConf",
                "source_api": "debug",
            }
        )

        await db.insert(
            "pages",
            {
                "id": page_a_id,
                "url": url_a,
                "domain": urlparse(url_a).netloc.lower(),
                "paper_metadata": paper_metadata_a,
            },
            or_replace=True,
        )
        await db.insert(
            "pages",
            {
                "id": page_b_id,
                "url": url_b,
                "domain": urlparse(url_b).netloc.lower(),
                "paper_metadata": paper_metadata_b,
            },
            or_replace=True,
        )

        fragment_a_id = "f_debug_a"
        fragment_b_id = "f_debug_b"
        await db.execute(
            """
            INSERT OR REPLACE INTO fragments
            (id, page_id, fragment_type, text_content, heading_context, is_relevant, relevance_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fragment_a_id,
                page_a_id,
                "paragraph",
                "Alpha fragment evidence text.",
                "alpha",
                1,
                f"primary_source=True; url={url_a}",
            ),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO fragments
            (id, page_id, fragment_type, text_content, heading_context, is_relevant, relevance_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fragment_b_id,
                page_b_id,
                "paragraph",
                "Beta fragment evidence text.",
                "beta",
                1,
                f"primary_source=True; url={url_b}",
            ),
        )

        # Create claim
        await db.execute(
            """
            INSERT OR REPLACE INTO claims
            (id, task_id, claim_text, claim_type, claim_confidence, source_fragment_ids, verification_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                task_id,
                "Debug claim: independent sources should be 2 if based on pages.",
                "fact",
                0.5,
                json.dumps([fragment_a_id, fragment_b_id]),
                f"source_url={url_a}",
            ),
        )

        print(
            "Setup complete:", {"db_path": str(db_path), "task_id": task_id, "claim_id": claim_id}
        )

        # When: persist evidence edges via production helper (FRAGMENT->CLAIM)
        await add_claim_evidence(
            claim_id=claim_id,
            fragment_id=fragment_a_id,
            relation="supports",
            confidence=0.9,
            nli_label="supports",
            nli_confidence=0.9,
            task_id=task_id,
        )
        await add_claim_evidence(
            claim_id=claim_id,
            fragment_id=fragment_b_id,
            relation="supports",
            confidence=0.9,
            nli_label="supports",
            nli_confidence=0.9,
            task_id=task_id,
        )

        # Then: calculate confidence and observe independent_sources
        graph = EvidenceGraph(task_id=task_id)
        await graph.load_from_db(task_id=task_id)
        confidence_info = graph.calculate_claim_confidence(claim_id)

        expected_independent_sources_by_page = len({page_a_id, page_b_id})
        actual_independent_sources = int(confidence_info.get("independent_sources") or 0)

        print("=== EvidenceGraph independent_sources debug ===")
        print(f"DB path: {db_path}")
        print(f"task_id={task_id} claim_id={claim_id}")
        print(f"expected_independent_sources_by_page={expected_independent_sources_by_page}")
        print(f"actual_independent_sources={actual_independent_sources}")
        print(
            "evidence_years=",
            confidence_info.get("evidence_years"),
            "evidence_count=",
            confidence_info.get("evidence_count"),
        )

        # Also observe SourceVerifier decision behavior
        verifier = SourceVerifier()
        domain_for_verification = urlparse(url_a).netloc.lower()
        verification = verifier.verify_claim(
            claim_id=claim_id,
            domain=domain_for_verification,
            evidence_graph=graph,
        )
        print("verification_status=", verification.verification_status.value)
        print("verification_details=", verification.details.to_dict())

        # Finally, check get_materials_action path (claims output fields)
        materials = await get_materials_action(task_id=task_id, include_graph=False)
        print("materials.ok=", materials.get("ok"))
        first_claim = (materials.get("claims") or [{}])[0]
        print("materials.claim[0].evidence_years=", first_claim.get("evidence_years"))
        print(
            "materials.claim[0].evidence_types=",
            [e.get("source_type") for e in (first_claim.get("evidence") or [])],
        )

        mismatch = actual_independent_sources != expected_independent_sources_by_page
        print(
            "Result:",
            {
                "expected_independent_sources_by_page": expected_independent_sources_by_page,
                "actual_independent_sources": actual_independent_sources,
                "mismatch": mismatch,
                "verification_status": verification.verification_status.value,
            },
        )

        return 2 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
