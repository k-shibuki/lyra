#!/usr/bin/env python3
"""
Lyra Evidence Pack Generator.

Extracts evidence data from Lyra SQLite database and generates:
- evidence_pack.json: Facts for report generation
- citation_index.json: URL→metadata lookup

Implements an exploration-oriented score derived from NLI evidence edges:
`nli_claim_support_ratio` (0..1).

This ratio is NOT a hypothesis verdict and must not be interpreted as a
statistically rigorous probability of truth. It is a deterministic aggregate
of fragment→claim NLI edges intended for ranking and navigation.

Usage:
    python -m src.report.evidence_pack --tasks task_id1 task_id2

See ADR-0005 for background on the evidence graph design.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

# =============================================================================
# Constants
# =============================================================================

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "lyra.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "reports"

# Top claims selection
TOP_CLAIMS_LIMIT = 30
CONTRADICTIONS_LIMIT = 15

# =============================================================================
# Type Definitions
# =============================================================================

Stance = Literal["supports", "refutes", "neutral"]


class ClaimRecord(TypedDict):
    """Claim with evidence summary and exploration score."""

    claim_id: str
    claim_text: str
    task_id: str
    support_count: int
    refute_count: int
    neutral_count: int
    evidence_count: int
    support_weight: float
    refute_weight: float
    # Exploration score (NOT a verdict): NLI-weighted support ratio
    nli_claim_support_ratio: float
    # Ranking
    report_rank: int
    is_report_top: bool


class ContradictionRecord(TypedDict):
    """Claim with contradicting evidence."""

    claim_id: str
    claim_text: str
    task_id: str
    support_count: int
    refute_count: int
    neutral_count: int
    evidence_count: int
    controversy_score: float


class EvidenceChainRecord(TypedDict):
    """Fragment→Claim evidence with page provenance."""

    edge_id: str
    relation: str
    nli_edge_confidence: float
    fragment_id: str
    heading_context: str | None
    page_id: str
    url: str
    domain: str
    claim_id: str
    claim_text: str
    # Bibliographic metadata
    year: int | None
    venue: str | None
    doi: str | None
    source_api: str | None
    author_display: str | None


class CitationRecord(TypedDict):
    """Page citation metadata."""

    page_id: str
    url: str
    title: str | None
    domain: str
    # Bibliographic metadata from works
    year: int | None
    venue: str | None
    doi: str | None
    source_api: str | None
    author_display: str | None
    # Evidence stats
    claims_supported: int


class CitationFlowRecord(TypedDict):
    """Page→Page citation relationship."""

    citing_page_id: str
    cited_page_id: str
    citation_source: str | None


class TaskMetadata(TypedDict):
    """Task metadata from DB."""

    task_id: str
    hypothesis: str | None
    created_at: str | None
    status: str | None


class EvidencePack(TypedDict):
    """Complete evidence pack for a task."""

    schema_version: str
    metadata: dict[str, Any]
    claims: list[ClaimRecord]
    contradictions: list[ContradictionRecord]
    evidence_chains: list[EvidenceChainRecord]
    citations: list[CitationRecord]
    citation_flow: list[CitationFlowRecord]


class CitationIndex(TypedDict):
    """URL→page_id lookup with metadata flags."""

    page_id: str
    has_doi: bool
    has_author: bool
    has_year: bool
    domain: str


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class EvidencePackConfig:
    """Configuration for evidence pack generation."""

    db_path: Path = DEFAULT_DB_PATH
    task_ids: list[str] = field(default_factory=list)
    output_dir: Path = DEFAULT_OUTPUT_DIR
    top_claims_limit: int = TOP_CLAIMS_LIMIT
    contradictions_limit: int = CONTRADICTIONS_LIMIT

    def get_task_output_dir(self, task_id: str) -> Path:
        """Get output directory for a specific task."""
        return self.output_dir / task_id


# =============================================================================
# Database Extraction Functions
# =============================================================================


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Get SQLite connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_latest_views(conn)
    return conn


def ensure_latest_views(conn: sqlite3.Connection) -> None:
    """Refresh SQL views in an existing DB without destructive rebuild.

    SQLite won't replace existing views on `CREATE VIEW IF NOT EXISTS`, so we
    execute the project `schema.sql` which contains `DROP VIEW IF EXISTS ...`
    for a clean in-place refresh. Underlying data tables are preserved.
    """
    schema_path = PROJECT_DIR / "src" / "storage" / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.sql not found: {schema_path}")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def extract_task_metadata(conn: sqlite3.Connection, task_id: str) -> TaskMetadata:
    """Extract task metadata from DB."""
    cursor = conn.execute(
        """
        SELECT id, hypothesis, created_at, status
        FROM tasks
        WHERE id = ?
        """,
        (task_id,),
    )
    row = cursor.fetchone()
    if not row:
        return TaskMetadata(
            task_id=task_id,
            hypothesis=None,
            created_at=None,
            status=None,
        )
    return TaskMetadata(
        task_id=row["id"],
        hypothesis=row["hypothesis"],
        created_at=row["created_at"],
        status=row["status"],
    )


def extract_top_claims(
    conn: sqlite3.Connection,
    task_id: str,
    limit: int = TOP_CLAIMS_LIMIT,
) -> list[ClaimRecord]:
    """
    Extract top claims with evidence summary and exploration score.

    Order matches lyra-report TOP30 selection logic:
        evidence_count DESC, refute_count DESC, nli_claim_support_ratio DESC, claim_id ASC
    """
    cursor = conn.execute(
        """
        SELECT
            claim_id,
            claim_text,
            task_id,
            COALESCE(support_count, 0) as support_count,
            COALESCE(refute_count, 0) as refute_count,
            COALESCE(neutral_count, 0) as neutral_count,
            COALESCE(evidence_count, 0) as evidence_count,
            COALESCE(support_weight, 0.0) as support_weight,
            COALESCE(refute_weight, 0.0) as refute_weight,
            COALESCE(nli_claim_support_ratio, 0.5) as nli_claim_support_ratio
        FROM v_claim_evidence_summary
        WHERE task_id = ?
        ORDER BY
            COALESCE(evidence_count, 0) DESC,
            COALESCE(refute_count, 0) DESC,
            COALESCE(nli_claim_support_ratio, 0.5) DESC,
            claim_id ASC
        LIMIT ?
        """,
        (task_id, limit),
    )

    claims: list[ClaimRecord] = []
    for rank, row in enumerate(cursor.fetchall(), start=1):
        support_weight = row["support_weight"]
        refute_weight = row["refute_weight"]

        claims.append(
            ClaimRecord(
                claim_id=row["claim_id"],
                claim_text=row["claim_text"],
                task_id=row["task_id"],
                support_count=row["support_count"],
                refute_count=row["refute_count"],
                neutral_count=row["neutral_count"],
                evidence_count=row["evidence_count"],
                support_weight=support_weight,
                refute_weight=refute_weight,
                nli_claim_support_ratio=row["nli_claim_support_ratio"],
                report_rank=rank,
                is_report_top=rank <= TOP_CLAIMS_LIMIT,
            )
        )
    return claims


def extract_contradictions(
    conn: sqlite3.Connection,
    task_id: str,
    limit: int = CONTRADICTIONS_LIMIT,
) -> list[ContradictionRecord]:
    """Extract claims with contradicting evidence."""
    cursor = conn.execute(
        """
        SELECT
            claim_id,
            claim_text,
            task_id,
            support_count,
            refute_count,
            neutral_count,
            evidence_count,
            controversy_score
        FROM v_contradictions
        WHERE task_id = ?
        ORDER BY controversy_score DESC, evidence_count DESC
        LIMIT ?
        """,
        (task_id, limit),
    )

    return [
        ContradictionRecord(
            claim_id=row["claim_id"],
            claim_text=row["claim_text"],
            task_id=row["task_id"],
            support_count=row["support_count"],
            refute_count=row["refute_count"],
            neutral_count=row["neutral_count"],
            evidence_count=row["evidence_count"],
            controversy_score=row["controversy_score"],
        )
        for row in cursor.fetchall()
    ]


def extract_evidence_chains(
    conn: sqlite3.Connection,
    task_id: str,
    claim_ids: list[str],
) -> list[EvidenceChainRecord]:
    """
    Extract evidence chains for specified claims.

    Only includes NLI evidence edges (supports/refutes/neutral).
    """
    if not claim_ids:
        return []

    placeholders = ",".join("?" * len(claim_ids))
    cursor = conn.execute(
        f"""
        SELECT
            edge_id,
            relation,
            COALESCE(nli_edge_confidence, 0.0) as nli_edge_confidence,
            fragment_id,
            heading_context,
            page_id,
            url,
            domain,
            claim_id,
            claim_text,
            year,
            venue,
            doi,
            source_api,
            author_display
        FROM v_evidence_chain
        WHERE task_id = ? AND claim_id IN ({placeholders})
        ORDER BY nli_edge_confidence DESC
        """,
        [task_id, *claim_ids],
    )

    return [
        EvidenceChainRecord(
            edge_id=row["edge_id"],
            relation=row["relation"],
            nli_edge_confidence=row["nli_edge_confidence"],
            fragment_id=row["fragment_id"],
            heading_context=row["heading_context"],
            page_id=row["page_id"],
            url=row["url"],
            domain=row["domain"],
            claim_id=row["claim_id"],
            claim_text=row["claim_text"],
            year=row["year"],
            venue=row["venue"],
            doi=row["doi"],
            source_api=row["source_api"],
            author_display=row["author_display"],
        )
        for row in cursor.fetchall()
    ]


def extract_citations(
    conn: sqlite3.Connection,
    task_id: str,
    page_ids: list[str],
) -> list[CitationRecord]:
    """
    Extract citation metadata for specified pages.

    Includes bibliographic metadata from works table.
    """
    if not page_ids:
        return []

    placeholders = ",".join("?" * len(page_ids))
    cursor = conn.execute(
        f"""
        SELECT
            p.id as page_id,
            p.url,
            p.title,
            p.domain,
            w.year,
            w.venue,
            w.doi,
            w.source_api,
            CASE
                WHEN w.canonical_id IS NULL THEN NULL
                WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN NULL
                WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1
                    THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
                ELSE (SELECT wa.name FROM work_authors wa
                      WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
            END AS author_display,
            (SELECT COUNT(DISTINCT e.target_id)
             FROM edges e
             JOIN fragments f ON e.source_id = f.id
             JOIN claims c ON e.target_id = c.id
             WHERE f.page_id = p.id
               AND e.source_type = 'fragment'
               AND e.target_type = 'claim'
               AND e.relation = 'supports'
               AND c.task_id = ?) as claims_supported
        FROM pages p
        LEFT JOIN works w ON p.canonical_id = w.canonical_id
        WHERE p.id IN ({placeholders})
        """,
        [task_id, *page_ids],
    )

    return [
        CitationRecord(
            page_id=row["page_id"],
            url=row["url"],
            title=row["title"],
            domain=row["domain"],
            year=row["year"],
            venue=row["venue"],
            doi=row["doi"],
            source_api=row["source_api"],
            author_display=row["author_display"],
            claims_supported=row["claims_supported"] or 0,
        )
        for row in cursor.fetchall()
    ]


def extract_citation_flow(
    conn: sqlite3.Connection,
    page_ids: list[str],
) -> list[CitationFlowRecord]:
    """
    Extract citation flow (page→page) for specified pages.

    Returns all citations where either citing or cited page is in the set.
    """
    if not page_ids:
        return []

    placeholders = ",".join("?" * len(page_ids))
    cursor = conn.execute(
        f"""
        SELECT
            citing_page_id,
            cited_page_id,
            citation_source
        FROM v_citation_flow
        WHERE citing_page_id IN ({placeholders})
           OR cited_page_id IN ({placeholders})
        """,
        [*page_ids, *page_ids],
    )

    return [
        CitationFlowRecord(
            citing_page_id=row["citing_page_id"],
            cited_page_id=row["cited_page_id"],
            citation_source=row["citation_source"],
        )
        for row in cursor.fetchall()
    ]


# =============================================================================
# Evidence Pack Generation
# =============================================================================


def build_evidence_pack(
    conn: sqlite3.Connection,
    task_id: str,
    config: EvidencePackConfig,
) -> EvidencePack:
    """
    Build complete evidence pack for a task.

    Extracts:
    - Top claims with exploration score (nli_claim_support_ratio)
    - Contradictions
    - Evidence chains (for top claims)
    - Citations (for pages in evidence chains)
    - Citation flow (for cited pages)
    """
    print("  Extracting task metadata...")
    metadata = extract_task_metadata(conn, task_id)

    print(f"  Extracting top {config.top_claims_limit} claims...")
    claims = extract_top_claims(conn, task_id, config.top_claims_limit)
    claim_ids = [c["claim_id"] for c in claims]
    print(f"    Found {len(claims)} claims")

    print(f"  Extracting contradictions (limit {config.contradictions_limit})...")
    contradictions = extract_contradictions(conn, task_id, config.contradictions_limit)
    print(f"    Found {len(contradictions)} contradictions")

    print("  Extracting evidence chains...")
    evidence_chains = extract_evidence_chains(conn, task_id, claim_ids)
    print(f"    Found {len(evidence_chains)} evidence chains")

    # Collect unique page_ids from evidence chains
    page_ids = list({ec["page_id"] for ec in evidence_chains})
    print(f"  Extracting citations for {len(page_ids)} pages...")
    citations = extract_citations(conn, task_id, page_ids)
    print(f"    Found {len(citations)} citations")

    print("  Extracting citation flow...")
    citation_flow = extract_citation_flow(conn, page_ids)
    print(f"    Found {len(citation_flow)} citation relationships")

    return EvidencePack(
        schema_version="evidence_pack_v2",
        metadata={
            "task_id": task_id,
            "hypothesis": metadata.get("hypothesis"),
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": {
                "claims": len(claims),
                "contradictions": len(contradictions),
                "evidence_chains": len(evidence_chains),
                "citations": len(citations),
                "citation_flow": len(citation_flow),
            },
        },
        claims=claims,
        contradictions=contradictions,
        evidence_chains=evidence_chains,
        citations=citations,
        citation_flow=citation_flow,
    )


def build_citation_index(evidence_pack: EvidencePack) -> dict[str, CitationIndex]:
    """
    Build URL→page_id lookup with metadata flags.

    Used for Stage 3 validation to check if cited URLs are in the graph.
    """
    index: dict[str, CitationIndex] = {}
    for citation in evidence_pack["citations"]:
        url = citation["url"]
        index[url] = CitationIndex(
            page_id=citation["page_id"],
            has_doi=citation["doi"] is not None,
            has_author=citation["author_display"] is not None,
            has_year=citation["year"] is not None,
            domain=citation["domain"],
        )
    return index


def generate_evidence_pack(config: EvidencePackConfig) -> dict[str, Path]:
    """
    Generate evidence packs for all configured tasks.

    Returns:
        Dictionary mapping task_id to output directory path
    """
    if not config.db_path.exists():
        raise FileNotFoundError(f"Database not found: {config.db_path}")

    if not config.task_ids:
        raise ValueError("No task IDs specified")

    conn = get_connection(config.db_path)
    results: dict[str, Path] = {}

    for task_id in config.task_ids:
        print(f"\n=== Processing task: {task_id} ===")

        # Build evidence pack
        evidence_pack = build_evidence_pack(conn, task_id, config)

        # Build citation index
        citation_index = build_citation_index(evidence_pack)

        # Create output directory
        output_dir = config.get_task_output_dir(task_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write evidence_pack.json
        pack_path = output_dir / "evidence_pack.json"
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(evidence_pack, f, indent=2, ensure_ascii=False)
        print(f"  Written: {pack_path}")

        # Write citation_index.json
        index_path = output_dir / "citation_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(citation_index, f, indent=2, ensure_ascii=False)
        print(f"  Written: {index_path}")

        results[task_id] = output_dir

    conn.close()
    return results


# =============================================================================
# CLI Interface
# =============================================================================


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Lyra Evidence Pack from SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate evidence pack for specific tasks
    python -m src.report.evidence_pack --tasks task_ed3b72cf task_8f90d8f6

    # Custom output directory
    python -m src.report.evidence_pack --tasks task_xxx --output-dir ./my_reports
        """,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to Lyra SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to process",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--top-claims",
        type=int,
        default=TOP_CLAIMS_LIMIT,
        help=f"Number of top claims to extract (default: {TOP_CLAIMS_LIMIT})",
    )
    parser.add_argument(
        "--contradictions",
        type=int,
        default=CONTRADICTIONS_LIMIT,
        help=f"Number of contradictions to extract (default: {CONTRADICTIONS_LIMIT})",
    )

    parsed = parser.parse_args(args)

    config = EvidencePackConfig(
        db_path=parsed.db,
        task_ids=parsed.tasks,
        output_dir=parsed.output_dir,
        top_claims_limit=parsed.top_claims,
        contradictions_limit=parsed.contradictions,
    )

    print("=== Lyra Evidence Pack Generator ===")
    print(f"Database: {config.db_path}")
    print(f"Tasks: {config.task_ids}")
    print(f"Output: {config.output_dir}")
    try:
        results = generate_evidence_pack(config)
        print("\n=== Generation Complete ===")
        for task_id, output_dir in results.items():
            print(f"  {task_id}: {output_dir}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=__import__("sys").stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
