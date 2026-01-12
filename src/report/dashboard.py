#!/usr/bin/env python3
"""
Lyra Dashboard Generator.

Extracts complete task data from Lyra SQLite database and generates
a self-contained HTML visualization dashboard with data fidelity.

This module is designed to bypass AI context window limitations by
directly querying the database and generating HTML output.

Usage (CLI):
    python -m src.report.dashboard --tasks task_ed3b72cf task_8f90d8f6

Usage (Module):
    from src.report.dashboard import generate_dashboard, DashboardConfig

    config = DashboardConfig(
        db_path=Path("data/lyra.db"),
        task_reports=[("task_xxx", Path("report.md"))],
    )
    generate_dashboard(config)

Requirements:
    - Python 3.10+
    - SQLite database with Lyra schema
    - dashboard.html template with "__LYRA_DATA__" placeholder
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import struct
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

# Type alias for NLI edge relation values
Stance = Literal["supports", "refutes", "neutral"]

# Optional: numpy for dimensionality reduction (PCA without sklearn)
try:
    import numpy as np

    HAS_CLUSTERING = True
except ImportError:
    HAS_CLUSTERING = False
    np = None  # type: ignore[assignment]

#
# NOTE:
# This dashboard intentionally does NOT compute/emit statistical intervals or a
# deterministic supports/refutes/neutral verdict for claims. It consumes
# claim-level aggregates (counts/weights) and an exploration score.


# =============================================================================
# Constants
# =============================================================================

# Project root detection
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

# Default paths
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "lyra.db"
DEFAULT_TEMPLATE_PATH = PROJECT_DIR / "config" / "templates" / "dashboard.html"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "reports" / "dashboards"
DEFAULT_REPORTS_DIR = PROJECT_DIR / "data" / "reports"

# Color palette for automatic task color assignment (high-contrast, colorblind-friendly)
TASK_COLORS: tuple[str, ...] = (
    "#f59e0b",  # Amber
    "#06b6d4",  # Cyan
    "#8b5cf6",  # Violet
    "#10b981",  # Emerald
    "#f43f5e",  # Rose
    "#3b82f6",  # Blue
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
)


# =============================================================================
# Type Definitions
# =============================================================================


class ClaimData(TypedDict):
    """Claim data structure."""

    id: str
    text: str
    nli_claim_support_ratio: float
    support: int
    refute: int
    neutral: int
    evidence_count: int
    report_rank: int
    is_report_top: bool
    support_weight: float
    refute_weight: float


class SourceData(TypedDict):
    """Source (page) data structure."""

    id: str
    domain: str
    title: str | None
    url: str
    year: int | None
    doi: str | None
    venue: str | None
    authority_score: float
    claims_supported: int


class FragmentData(TypedDict):
    """Fragment data structure."""

    id: str
    page_id: str
    text: str
    heading: str | None
    claims: list[str]


class EdgeData(TypedDict):
    """Edge data structure."""

    id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation: str
    confidence: float


class TaskStats(TypedDict):
    """Task statistics."""

    claims: int
    pages: int
    fragments: int


class TaskMetadata(TypedDict):
    """Task metadata from database."""

    hypothesis: str
    name: str
    shortName: str
    color: str
    status: str
    created_at: str


class ReportSummary(TypedDict, total=False):
    """Structured report summary (sidecar) authored in Stage 4 for dashboard verdict display."""

    schema_version: str
    task_id: str
    hypothesis: str
    verdict: str  # SUPPORTED|REFUTED|INCONCLUSIVE
    verdict_rationale: str
    key_outcomes: list[dict[str, Any]]
    evidence_notes: list[str]
    generated_at: str


class ClaimGraphNode(TypedDict):
    """Node in the claim relation graph."""

    id: str
    task_id: str
    text: str
    nli_claim_support_ratio: float
    evidence_count: int
    support_count: int
    refute_count: int
    report_rank: int
    is_report_top: bool
    x: float  # PCA x coordinate for initial layout
    y: float  # PCA y coordinate for initial layout


class ClaimGraphEdge(TypedDict):
    """Edge in the claim relation graph."""

    source: str  # claim_id
    target: str  # claim_id
    kind: str  # semantic_sim | co_page | co_fragment
    weight: float  # Normalized weight [0, 1]
    explain: str  # Human-readable explanation


class ClaimGraphMeta(TypedDict):
    """Metadata for the claim relation graph."""

    total_nodes: int
    total_edges: int
    edge_counts: dict[str, int]  # By kind
    params: dict[str, Any]  # Generation parameters


class ClaimGraph(TypedDict):
    """Complete claim relation graph for visualization."""

    nodes: list[ClaimGraphNode]
    edges: list[ClaimGraphEdge]
    meta: ClaimGraphMeta


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class DashboardConfig:
    """Configuration for dashboard generation."""

    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    task_reports: list[tuple[str, Path | None]] = field(default_factory=list)
    template_path: Path = field(default_factory=lambda: DEFAULT_TEMPLATE_PATH)
    output_path: Path | None = None  # Auto-generated if None

    def __post_init__(self) -> None:
        """Resolve paths and set defaults."""
        self.db_path = Path(self.db_path)
        self.template_path = Path(self.template_path)
        if self.output_path:
            self.output_path = Path(self.output_path)

    @property
    def task_ids(self) -> list[str]:
        """Get list of task IDs."""
        return [t[0] for t in self.task_reports]

    def get_output_path(self) -> Path:
        """Get output path, auto-generating if not set."""
        if self.output_path:
            return self.output_path
        # Auto-generate: data/reports/dashboards/dashboard_{task_ids}_{timestamp}.html
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        task_ids_str = "_".join(self.task_ids)
        return DEFAULT_OUTPUT_DIR / f"dashboard_{task_ids_str}_{timestamp}.html"


# =============================================================================
# Database Extraction Functions
# =============================================================================


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create database connection with row factory."""
    conn = sqlite3.connect(str(db_path))
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


def extract_drug_class_from_hypothesis(hypothesis: str) -> tuple[str, str]:
    """
    Extract drug class name from hypothesis text.

    Returns (full_name, short_name) tuple.

    Examples:
        "DPP-4 inhibitors are effective..." -> ("DPP-4 Inhibitors", "DPP-4i")
        "SGLT2 inhibitors are efficacious..." -> ("SGLT2 Inhibitors", "SGLT2i")
        "Metformin reduces..." -> ("Metformin", "Metformin")
    """
    # Common drug class patterns
    # Type: (pattern, formatter) where formatter takes a Match and returns (full_name, short_name)
    patterns: list[tuple[str, Callable[[re.Match[str]], tuple[str, str]]]] = [
        # Inhibitors (DPP-4, SGLT2, ACE, etc.)
        (
            r"\b(DPP-?4|SGLT-?2|ACE|ARB|PDE-?5)\s*inhibitors?\b",
            lambda m: (
                f"{m.group(1).upper().replace('-', '-')} Inhibitors",
                f"{m.group(1).replace('-', '')}i",
            ),
        ),
        # Receptor agonists (GLP-1)
        (
            r"\b(GLP-?1)\s*(?:receptor\s*)?agonists?\b",
            lambda m: (
                f"{m.group(1).upper()} Receptor Agonists",
                f"{m.group(1).replace('-', '')}RA",
            ),
        ),
        # Generic drug names (ending in common suffixes)
        (
            r"\b([A-Z][a-z]+(?:metformin|gliptin|flozin|glutide|tide))\b",
            lambda m: (m.group(1).title(), m.group(1)[:8]),
        ),
        # Fallback: first capitalized word/phrase
        (
            r"^([A-Z][A-Za-z0-9\-]+(?:\s+[a-z]+)?)",
            lambda m: (m.group(1), m.group(1)[:8]),
        ),
    ]

    for pattern, formatter in patterns:
        match = re.search(pattern, hypothesis, re.IGNORECASE)
        if match:
            return formatter(match)

    # Ultimate fallback: use first 20 chars
    short = hypothesis[:20].strip()
    return (short, short[:8])


def get_task_color(task_id: str, task_index: int) -> str:
    """
    Get a consistent color for a task.

    Uses task_index for ordered assignment, with hash fallback for consistency.
    """
    if task_index < len(TASK_COLORS):
        return TASK_COLORS[task_index]

    # Hash-based fallback for many tasks
    hash_val = int(hashlib.md5(task_id.encode()).hexdigest()[:8], 16)  # noqa: S324
    return TASK_COLORS[hash_val % len(TASK_COLORS)]


def extract_task_metadata(
    conn: sqlite3.Connection, task_id: str, task_index: int = 0
) -> TaskMetadata:
    """
    Extract task metadata from database.

    Dynamically derives display name and color from hypothesis and task_id.
    No hardcoded configuration required.
    """
    cursor = conn.execute(
        "SELECT hypothesis, status, created_at FROM tasks WHERE id = ?", (task_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Task {task_id} not found in database")

    hypothesis: str = row["hypothesis"]
    name, short_name = extract_drug_class_from_hypothesis(hypothesis)
    color = get_task_color(task_id, task_index)

    return TaskMetadata(
        hypothesis=hypothesis,
        name=name,
        shortName=short_name,
        color=color,
        status=row["status"],
        created_at=row["created_at"],
    )


def extract_claim_embeddings(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, Any]:
    """
    Extract claim embeddings from database.

    Returns dict mapping claim_id -> embedding vector.
    """
    if not HAS_CLUSTERING or np is None:
        return {}

    placeholders = ",".join("?" * len(task_ids))
    cursor = conn.execute(
        f"""
        SELECT e.target_id, e.embedding_blob, e.dimension
        FROM embeddings e
        JOIN claims c ON e.target_id = c.id
        WHERE e.target_type = 'claim'
          AND c.task_id IN ({placeholders})
    """,
        task_ids,
    )

    embeddings: dict[str, Any] = {}
    for row in cursor.fetchall():
        claim_id = row["target_id"]
        blob = row["embedding_blob"]
        dim = row["dimension"]
        # Unpack float32 array from blob
        vector = np.array(struct.unpack(f"{dim}f", blob))
        embeddings[claim_id] = vector

    return embeddings


def compute_claim_clusters(
    claims_by_task: dict[str, list[dict[str, Any]]],
    embeddings: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Compute 2D coordinates for claims using PCA.

    Uses pure numpy PCA (no sklearn required) for dimensionality reduction.
    Returns list of {id, x, y, task_id, nli_claim_support_ratio, text} for visualization.
    """
    if not HAS_CLUSTERING or np is None:
        return []

    # Collect all claims with embeddings
    claim_data: list[dict[str, Any]] = []
    vectors: list[Any] = []

    for task_id, claims in claims_by_task.items():
        for claim in claims:
            claim_id = claim["id"]
            if claim_id in embeddings:
                claim_data.append(
                    {
                        "id": claim_id,
                        "task_id": task_id,
                        "text": claim["text"][:100],  # Truncate for JSON size
                        "nli_claim_support_ratio": claim["nli_claim_support_ratio"],
                    }
                )
                vectors.append(embeddings[claim_id])

    if len(vectors) < 5:
        return []

    # Stack vectors
    x_matrix = np.vstack(vectors)

    # Standardize (zero mean, unit variance)
    x_mean = x_matrix.mean(axis=0)
    x_std = x_matrix.std(axis=0)
    x_std[x_std == 0] = 1  # Avoid division by zero
    x_normalized = (x_matrix - x_mean) / x_std

    # PCA using SVD (pure numpy, no sklearn)
    # Compute covariance matrix and eigenvectors
    _u, _s, vt = np.linalg.svd(x_normalized, full_matrices=False)

    # Project to 2D using first 2 principal components
    coords = x_normalized @ vt[:2].T

    # Normalize to [0, 100] range for visualization
    coords_min = coords.min(axis=0)
    coords_max = coords.max(axis=0)
    coords_range = coords_max - coords_min
    coords_range[coords_range == 0] = 1  # Avoid division by zero
    coords_normalized = (coords - coords_min) / coords_range * 100

    # Combine with claim data
    result: list[dict[str, Any]] = []
    for i, data in enumerate(claim_data):
        data["x"] = float(coords_normalized[i, 0])
        data["y"] = float(coords_normalized[i, 1])
        result.append(data)

    return result


def build_claim_relation_graph(
    conn: sqlite3.Connection,
    claims_by_task: dict[str, list[dict[str, Any]]],
    embeddings: dict[str, Any],
    *,
    semantic_top_k: int = 8,
    semantic_min_sim: float = 0.72,
    max_edges: int = 3000,
    report_top_n: int = 30,
) -> ClaimGraph:
    """
    Build a relation graph between claims for network visualization.

    Creates three types of edges:
    - semantic_sim: Based on embedding cosine similarity (k-NN)
    - co_fragment: Claims extracted from the same fragment
    - co_page: Claims derived from the same source page

    Args:
        conn: Database connection
        claims_by_task: Dict mapping task_id -> list of claim dicts
        embeddings: Dict mapping claim_id -> embedding vector
        semantic_top_k: Number of nearest neighbors per claim for semantic edges
        semantic_min_sim: Minimum cosine similarity threshold
        max_edges: Maximum total edges (prioritizes co_fragment > co_page > semantic)
        report_top_n: Number of top claims (report-grade) to prioritize

    Returns:
        ClaimGraph with nodes, edges, and metadata
    """
    if not HAS_CLUSTERING or np is None:
        return ClaimGraph(
            nodes=[],
            edges=[],
            meta=ClaimGraphMeta(
                total_nodes=0,
                total_edges=0,
                edge_counts={},
                params={"error": "numpy not available"},
            ),
        )

    # Flatten claims and create lookup
    all_claims: list[dict[str, Any]] = []
    claim_lookup: dict[str, dict[str, Any]] = {}
    for task_id, claims in claims_by_task.items():
        for claim in claims:
            claim["task_id"] = task_id
            all_claims.append(claim)
            claim_lookup[claim["id"]] = claim

    if len(all_claims) < 2:
        return ClaimGraph(
            nodes=[],
            edges=[],
            meta=ClaimGraphMeta(
                total_nodes=0,
                total_edges=0,
                edge_counts={},
                params={"error": "insufficient claims"},
            ),
        )

    # Build PCA coordinates for layout and prepare normalized vectors for similarity
    coords_by_id: dict[str, tuple[float, float]] = {}
    claim_ids_with_emb = [c["id"] for c in all_claims if c["id"] in embeddings]
    vectors_normalized: Any = None  # Will be set if enough embeddings

    if len(claim_ids_with_emb) >= 2:
        vectors = np.vstack([embeddings[cid] for cid in claim_ids_with_emb])
        # Normalize for cosine similarity (used for semantic_sim edges)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors_normalized = vectors / norms

    if len(claim_ids_with_emb) >= 5:
        # PCA for layout (requires at least 5 points for meaningful reduction)
        x_mean = vectors.mean(axis=0)
        x_std = vectors.std(axis=0)
        x_std[x_std == 0] = 1
        x_norm = (vectors - x_mean) / x_std
        _u, _s, vt = np.linalg.svd(x_norm, full_matrices=False)
        coords = x_norm @ vt[:2].T
        coords_min = coords.min(axis=0)
        coords_max = coords.max(axis=0)
        coords_range = coords_max - coords_min
        coords_range[coords_range == 0] = 1
        coords_scaled = (coords - coords_min) / coords_range * 100

        for i, cid in enumerate(claim_ids_with_emb):
            coords_by_id[cid] = (float(coords_scaled[i, 0]), float(coords_scaled[i, 1]))

    # Build nodes
    nodes: list[ClaimGraphNode] = []
    for claim in all_claims:
        cid = claim["id"]
        x, y = coords_by_id.get(cid, (50.0, 50.0))
        nodes.append(
            ClaimGraphNode(
                id=cid,
                task_id=claim["task_id"],
                text=claim["text"][:120],
                nli_claim_support_ratio=claim.get("nli_claim_support_ratio", 0.5),
                evidence_count=claim.get("evidence_count", 0),
                support_count=claim.get("support", 0),
                refute_count=claim.get("refute", 0),
                report_rank=claim.get("report_rank", 999),
                is_report_top=claim.get("is_report_top", False),
                x=x,
                y=y,
            )
        )

    # =========================================================================
    # Build edges
    # =========================================================================
    edges: list[ClaimGraphEdge] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_edge(src: str, tgt: str, kind: str, weight: float, explain: str) -> bool:
        """Add edge if not duplicate. Returns True if added."""
        pair = (min(src, tgt), max(src, tgt))
        if pair in seen_pairs or src == tgt:
            return False
        seen_pairs.add(pair)
        edges.append(
            ClaimGraphEdge(source=src, target=tgt, kind=kind, weight=weight, explain=explain)
        )
        return True

    # 1) co_fragment edges (strongest: same fragment -> very related claims)
    fragment_claims: dict[str, list[str]] = {}
    task_ids = list(claims_by_task.keys())
    placeholders = ",".join("?" * len(task_ids))
    cursor = conn.execute(
        f"""
        SELECT e.source_id AS fragment_id, e.target_id AS claim_id
        FROM edges e
        JOIN claims c ON e.target_id = c.id
        WHERE e.source_type = 'fragment'
          AND e.target_type = 'claim'
          AND c.task_id IN ({placeholders})
    """,
        task_ids,
    )
    for row in cursor:
        fid = row["fragment_id"]
        cid = row["claim_id"]
        if fid not in fragment_claims:
            fragment_claims[fid] = []
        fragment_claims[fid].append(cid)

    # Edge caps per kind: ensure the graph remains readable and that semantic links
    # are still available when co_fragment/co_page are filtered off in the UI.
    co_fragment_cap = int(max_edges * 0.35)
    co_page_cap = int(max_edges * 0.25)
    semantic_cap = max_edges - co_fragment_cap - co_page_cap

    co_fragment_count = 0
    for _fid, cids in fragment_claims.items():
        if len(cids) < 2:
            continue
        # Create edges between all pairs from same fragment
        for i, c1 in enumerate(cids):
            for c2 in cids[i + 1 :]:
                if c1 in claim_lookup and c2 in claim_lookup:
                    added = add_edge(
                        c1,
                        c2,
                        "co_fragment",
                        0.9,
                        "Same fragment (shared evidence)",
                    )
                    if added:
                        co_fragment_count += 1
                    if co_fragment_count >= co_fragment_cap:
                        break
            if co_fragment_count >= co_fragment_cap:
                break
        if co_fragment_count >= co_fragment_cap:
            break

    # 2) co_page edges (claims from same source page)
    page_claims: dict[str, list[str]] = {}
    cursor = conn.execute(
        f"""
        SELECT DISTINCT p.id AS page_id, c.id AS claim_id
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id IN ({placeholders})
    """,
        task_ids,
    )
    for row in cursor:
        pid = row["page_id"]
        cid = row["claim_id"]
        if pid not in page_claims:
            page_claims[pid] = []
        page_claims[pid].append(cid)

    co_page_count = 0
    for _pid, cids in page_claims.items():
        if len(cids) < 2:
            continue
        # Create edges for claims sharing the same source page
        for i, c1 in enumerate(cids):
            for c2 in cids[i + 1 :]:
                if c1 in claim_lookup and c2 in claim_lookup:
                    # Check if already connected via co_fragment (skip if so)
                    pair = (min(c1, c2), max(c1, c2))
                    if pair in seen_pairs:
                        continue
                    added = add_edge(c1, c2, "co_page", 0.6, "Same source page")
                    if added:
                        co_page_count += 1
                    if co_page_count >= co_page_cap:
                        break
            if co_page_count >= co_page_cap:
                break
        if co_page_count >= co_page_cap:
            break

    # 3) semantic_sim edges (k-NN from embeddings)
    semantic_count = 0
    if semantic_cap > 0 and len(claim_ids_with_emb) >= 2 and vectors_normalized is not None:
        # Compute cosine similarity matrix
        sim_matrix = vectors_normalized @ vectors_normalized.T

        # For each claim, find top-k most similar (excluding self)
        for i, src_id in enumerate(claim_ids_with_emb):
            sims = sim_matrix[i]
            # Get indices sorted by similarity (descending)
            sorted_indices = np.argsort(-sims)

            k_found = 0
            for j in sorted_indices:
                if j == i:
                    continue
                tgt_id = claim_ids_with_emb[j]
                sim_val = float(sims[j])

                if sim_val < semantic_min_sim:
                    break  # No more similar enough

                pair = (min(src_id, tgt_id), max(src_id, tgt_id))
                if pair in seen_pairs:
                    continue

                added = add_edge(
                    src_id,
                    tgt_id,
                    "semantic_sim",
                    round(sim_val, 3),
                    f"Semantic similarity: {sim_val:.2f}",
                )
                if added:
                    semantic_count += 1
                    k_found += 1
                    if semantic_count >= semantic_cap:
                        break

                if k_found >= semantic_top_k:
                    break

            # Early stop if we hit semantic cap
            if semantic_count >= semantic_cap:
                break

    # Sort edges by weight (descending) for consistent output
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))

    # Trim to max_edges if needed
    if len(edges) > max_edges:
        edges = edges[:max_edges]

    # Build metadata
    edge_counts = {"co_fragment": 0, "co_page": 0, "semantic_sim": 0}
    for e in edges:
        edge_counts[e["kind"]] = edge_counts.get(e["kind"], 0) + 1

    meta = ClaimGraphMeta(
        total_nodes=len(nodes),
        total_edges=len(edges),
        edge_counts=edge_counts,
        params={
            "semantic_top_k": semantic_top_k,
            "semantic_min_sim": semantic_min_sim,
            "max_edges": max_edges,
            "report_top_n": report_top_n,
        },
    )

    return ClaimGraph(nodes=nodes, edges=edges, meta=meta)


# =============================================================================
# Database Extraction Functions
# =============================================================================


def extract_claims(conn: sqlite3.Connection, task_id: str) -> list[ClaimData]:
    """
    Extract ALL claims with NLI-weighted claim support ratio from NLI evidence.

    Uses v_claim_evidence_summary view for accurate computed aggregates.
    Order matches lyra-report TOP30 selection logic:
      evidence_count DESC, refute_count DESC, nli_claim_support_ratio DESC, claim_id ASC
    This ensures dashboard and report show claims in identical order.
    """
    cursor = conn.execute(
        """
        SELECT
            c.id,
            c.claim_text as text,
            COALESCE(v.nli_claim_support_ratio, 0.5) as nli_claim_support_ratio,
            COALESCE(v.support_count, 0) as support,
            COALESCE(v.refute_count, 0) as refute,
            COALESCE(v.neutral_count, 0) as neutral,
            COALESCE(v.evidence_count, 0) as evidence_count,
            COALESCE(v.support_weight, 0.0) as support_weight,
            COALESCE(v.refute_weight, 0.0) as refute_weight
        FROM claims c
        LEFT JOIN v_claim_evidence_summary v ON c.id = v.claim_id
        WHERE c.task_id = ?
        ORDER BY
            COALESCE(v.evidence_count, 0) DESC,
            COALESCE(v.refute_count, 0) DESC,
            COALESCE(v.nli_claim_support_ratio, 0.5) DESC,
            c.id ASC
    """,
        (task_id,),
    )

    # Build claims list with report_rank and is_report_top
    claims: list[ClaimData] = []
    for rank, row in enumerate(cursor.fetchall(), start=1):
        support_weight = row["support_weight"]
        refute_weight = row["refute_weight"]

        claims.append(
            ClaimData(
                id=row["id"],
                text=row["text"],
                nli_claim_support_ratio=row["nli_claim_support_ratio"],
                support=row["support"],
                refute=row["refute"],
                neutral=row["neutral"],
                evidence_count=row["evidence_count"],
                report_rank=rank,
                is_report_top=rank <= 30,
                support_weight=support_weight,
                refute_weight=refute_weight,
            )
        )
    return claims


def extract_sources(conn: sqlite3.Connection, task_id: str) -> list[SourceData]:
    """
    Extract pages (sources) with real URLs and bibliographic metadata.

    Authority score = number of claims this source supports.
    """
    cursor = conn.execute(
        """
        SELECT
            p.id,
            p.domain,
            p.title,
            p.url,
            w.year,
            w.doi,
            w.venue,
            COUNT(DISTINCT e.target_id) as claims_supported
        FROM pages p
        LEFT JOIN works w ON p.canonical_id = w.canonical_id
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id
            AND e.source_type = 'fragment'
            AND e.target_type = 'claim'
            AND e.relation IN ('supports', 'origin')
        JOIN claims c ON e.target_id = c.id AND c.task_id = ?
        GROUP BY p.id
        ORDER BY claims_supported DESC
    """,
        (task_id,),
    )

    return [
        SourceData(
            id=row["id"],
            domain=row["domain"],
            title=row["title"],
            url=row["url"],
            year=row["year"],
            doi=row["doi"],
            venue=row["venue"],
            authority_score=float(row["claims_supported"]),
            claims_supported=row["claims_supported"],
        )
        for row in cursor.fetchall()
    ]


def extract_fragments(conn: sqlite3.Connection, task_id: str) -> list[FragmentData]:
    """
    Extract fragments linked to task's claims via edges.

    Includes text content for tooltips and claim linkage.
    """
    cursor = conn.execute(
        """
        SELECT DISTINCT
            f.id,
            f.page_id,
            f.text_content as text,
            f.heading_context
        FROM fragments f
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        ORDER BY f.page_id, f.position
    """,
        (task_id,),
    )

    fragments: list[FragmentData] = []
    for row in cursor.fetchall():
        # Get linked claims for this fragment
        claims_cursor = conn.execute(
            """
            SELECT DISTINCT e.target_id
            FROM edges e
            JOIN claims c ON e.target_id = c.id
            WHERE e.source_id = ?
              AND e.source_type = 'fragment'
              AND e.target_type = 'claim'
              AND c.task_id = ?
        """,
            (row["id"], task_id),
        )

        linked_claims = [r["target_id"] for r in claims_cursor.fetchall()]
        text_content: str = row["text"] or ""

        fragments.append(
            FragmentData(
                id=row["id"],
                page_id=row["page_id"],
                text=text_content[:500],  # Truncate for size
                heading=row["heading_context"],
                claims=linked_claims,
            )
        )

    return fragments


def extract_edges(conn: sqlite3.Connection, task_id: str) -> list[EdgeData]:
    """
    Extract ALL edges for the task.

    Includes fragment->claim (NLI) and page->page (cites) relationships.
    """
    # Fragment -> Claim edges
    cursor = conn.execute(
        """
        SELECT
            e.id,
            e.source_type,
            e.source_id,
            e.target_type,
            e.target_id,
            e.relation,
            e.nli_edge_confidence as confidence
        FROM edges e
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
          AND e.source_type = 'fragment'
    """,
        (task_id,),
    )

    edges: list[EdgeData] = [
        EdgeData(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            relation=row["relation"],
            confidence=row["confidence"] or 0.0,
        )
        for row in cursor.fetchall()
    ]

    # Page -> Page citation edges (global, but filter to relevant pages)
    cursor = conn.execute(
        """
        SELECT DISTINCT
            e.id,
            e.source_type,
            e.source_id,
            e.target_type,
            e.target_id,
            e.relation,
            1.0 as confidence
        FROM edges e
        WHERE e.source_type = 'page'
          AND e.target_type = 'page'
          AND e.relation = 'cites'
          AND (
              e.source_id IN (
                  SELECT DISTINCT p.id FROM pages p
                  JOIN fragments f ON f.page_id = p.id
                  JOIN edges e2 ON e2.source_id = f.id AND e2.source_type = 'fragment'
                  JOIN claims c ON e2.target_id = c.id
                  WHERE c.task_id = ?
              )
              OR e.target_id IN (
                  SELECT DISTINCT p.id FROM pages p
                  JOIN fragments f ON f.page_id = p.id
                  JOIN edges e2 ON e2.source_id = f.id AND e2.source_type = 'fragment'
                  JOIN claims c ON e2.target_id = c.id
                  WHERE c.task_id = ?
              )
          )
    """,
        (task_id, task_id),
    )

    edges.extend(
        EdgeData(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            relation=row["relation"],
            confidence=row["confidence"],
        )
        for row in cursor.fetchall()
    )

    return edges


def extract_citations(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """Extract page-to-page citations for visualization."""
    cursor = conn.execute(
        """
        SELECT DISTINCT
            e.source_id as "from",
            e.target_id as "to",
            e.citation_context as context
        FROM edges e
        WHERE e.source_type = 'page'
          AND e.target_type = 'page'
          AND e.relation = 'cites'
          AND e.source_id IN (
              SELECT DISTINCT p.id FROM pages p
              JOIN fragments f ON f.page_id = p.id
              JOIN edges e2 ON e2.source_id = f.id AND e2.source_type = 'fragment'
              JOIN claims c ON e2.target_id = c.id
              WHERE c.task_id = ?
          )
    """,
        (task_id,),
    )

    return [dict(row) for row in cursor.fetchall()]


def extract_contradictions(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract claims with refuting evidence (real controversy).

    Controversy score = refute_count / (support_count + refute_count + 1)
    """
    cursor = conn.execute(
        """
        SELECT
            c.id,
            c.claim_text as text,
            COALESCE(v.support_count, 0) as support,
            COALESCE(v.refute_count, 0) as refute,
            ROUND(
                CAST(COALESCE(v.refute_count, 0) AS REAL) /
                (COALESCE(v.support_count, 0) + COALESCE(v.refute_count, 0) + 1.0),
                3
            ) as controversy_score
        FROM claims c
        LEFT JOIN v_claim_evidence_summary v ON c.id = v.claim_id
        WHERE c.task_id = ?
          AND COALESCE(v.refute_count, 0) > 0
        ORDER BY controversy_score DESC, v.refute_count DESC
    """,
        (task_id,),
    )

    return [dict(row) for row in cursor.fetchall()]


def extract_timeline(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract evidence timeline by publication year.

    Counts fragments and evidence links per year from works.year.

    NOTE:
    - Old implementation counted distinct claims per year. Summing across years
      double-counts the same claim across multiple publications, which misleads
      "Recent Activity" summaries.
    - New implementation uses evidence links (edges) as an activity proxy.
    """
    cursor = conn.execute(
        """
        SELECT
            w.year,
            COUNT(DISTINCT f.id) as fragments,
            COUNT(e.id) as links
        FROM works w
        JOIN pages p ON p.canonical_id = w.canonical_id
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
          AND w.year IS NOT NULL
        GROUP BY w.year
        ORDER BY w.year
    """,
        (task_id,),
    )

    return [dict(row) for row in cursor.fetchall()]


def extract_stats(conn: sqlite3.Connection, task_id: str) -> TaskStats:
    """Extract basic statistics for a task."""
    # Claims count
    claims_cursor = conn.execute("SELECT COUNT(*) as cnt FROM claims WHERE task_id = ?", (task_id,))
    claims_count: int = claims_cursor.fetchone()["cnt"]

    # Pages count (linked to task via fragments/edges)
    pages_cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT p.id) as cnt
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id
        WHERE c.task_id = ?
    """,
        (task_id,),
    )
    pages_count: int = pages_cursor.fetchone()["cnt"]

    # Fragments count
    fragments_cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT f.id) as cnt
        FROM fragments f
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id
        WHERE c.task_id = ?
    """,
        (task_id,),
    )
    fragments_count: int = fragments_cursor.fetchone()["cnt"]

    return TaskStats(
        claims=claims_count,
        pages=pages_count,
        fragments=fragments_count,
    )


def build_task_data(conn: sqlite3.Connection, task_id: str, task_index: int = 0) -> dict[str, Any]:
    """
    Build complete task data structure from database.

    All display metadata (name, shortName, color) is derived dynamically
    from the hypothesis text and task_id - no hardcoding required.
    """
    metadata = extract_task_metadata(conn, task_id, task_index)

    print("  Extracting claims...", end=" ", flush=True)
    claims = extract_claims(conn, task_id)
    print(f"{len(claims)} claims")

    print("  Extracting sources...", end=" ", flush=True)
    sources = extract_sources(conn, task_id)
    print(f"{len(sources)} sources")

    print("  Extracting fragments...", end=" ", flush=True)
    fragments = extract_fragments(conn, task_id)
    print(f"{len(fragments)} fragments")

    print("  Extracting edges...", end=" ", flush=True)
    edges = extract_edges(conn, task_id)
    print(f"{len(edges)} edges")

    print("  Extracting citations...", end=" ", flush=True)
    citations = extract_citations(conn, task_id)
    print(f"{len(citations)} citations")

    print("  Extracting contradictions...", end=" ", flush=True)
    contradictions = extract_contradictions(conn, task_id)
    print(f"{len(contradictions)} controversies")

    print("  Extracting timeline...", end=" ", flush=True)
    timeline = extract_timeline(conn, task_id)
    print(f"{len(timeline)} years")

    stats = extract_stats(conn, task_id)

    return {
        "id": task_id,
        "name": metadata["name"],
        "shortName": metadata["shortName"],
        "color": metadata["color"],
        "hypothesis": metadata["hypothesis"],
        "stats": stats,
        "claims": claims,
        "sources": sources,
        "fragments": fragments,
        "edges": edges,
        "citations": citations,
        "contradictions": contradictions,
        "timeline": timeline,
    }


# =============================================================================
# Markdown to HTML Conversion
# =============================================================================


def markdown_to_html(md_content: str) -> str:
    """
    Simple markdown to HTML conversion for report.md files.

    Handles: headers, bold, italic, lists, tables, footnotes, horizontal rules.
    """
    lines = md_content.split("\n")
    html_lines: list[str] = []
    in_list = False
    in_table = False

    # First pass: collect footnote definitions for tooltip display
    footnotes: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        fn_match = re.match(r"^\[\^(\d+)\]:\s*(.*)$", stripped)
        if fn_match:
            fn_num = fn_match.group(1)
            fn_content = fn_match.group(2)
            footnotes[fn_num] = fn_content

    # Second pass: convert markdown to HTML
    for line in lines:
        stripped = line.strip()

        # Horizontal rule
        if stripped == "---":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
            html_lines.append(
                '<hr style="border:none;border-top:1px solid var(--border);margin:1rem 0;">'
            )
            continue

        # If a new block starts, close any open table/list first.
        # (Important for back-to-back tables separated by headings.)
        if stripped.startswith("#"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False

        # Headers
        if stripped.startswith("### "):
            html_lines.append(
                f'<h4 style="color:var(--text-primary);margin:1rem 0 0.5rem 0;'
                f'font-size:0.95rem;">{html.escape(stripped[4:])}</h4>'
            )
            continue
        if stripped.startswith("## "):
            heading_text = stripped[3:]
            html_lines.append(
                f'<h3 style="color:var(--accent-primary);margin:1.25rem 0 0.5rem 0;'
                f'font-size:1rem;font-weight:600;">{html.escape(heading_text)}</h3>'
            )
            # Insert footnote list after "References" heading
            if heading_text.lower() == "references" and footnotes:
                html_lines.append(
                    '<ol style="margin:0.5rem 0;padding-left:1.5rem;'
                    'color:var(--text-secondary);font-size:0.8rem;line-height:1.6;">'
                )
                for fn_num in sorted(footnotes.keys(), key=int):
                    fn_content = format_inline_markdown(footnotes[fn_num], footnotes)
                    html_lines.append(
                        f'<li id="fn-{fn_num}" value="{fn_num}" style="margin:0.3rem 0;">'
                        f"{fn_content}</li>"
                    )
                html_lines.append("</ol>")
            continue
        if stripped.startswith("# "):
            html_lines.append(
                f'<h2 style="color:var(--text-primary);margin:0 0 0.5rem 0;'
                f'font-size:1.1rem;font-weight:700;">{html.escape(stripped[2:])}</h2>'
            )
            continue

        # Tables
        if stripped.startswith("|") and "|" in stripped[1:]:
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Check if this is a separator row
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue

            if not in_table:
                html_lines.append(
                    '<table style="width:100%;border-collapse:collapse;'
                    'font-size:0.75rem;margin:0.5rem 0;">'
                )
                html_lines.append('<thead><tr style="border-bottom:1px solid var(--border);">')
                for cell in cells:
                    formatted = format_inline_markdown(cell, footnotes)
                    html_lines.append(
                        f'<th style="text-align:left;padding:0.4rem;'
                        f'color:var(--text-muted);font-weight:500;">{formatted}</th>'
                    )
                html_lines.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_lines.append('<tr style="border-bottom:1px solid var(--border);">')
                for cell in cells:
                    formatted = format_inline_markdown(cell, footnotes)
                    html_lines.append(
                        f'<td style="padding:0.4rem;color:var(--text-secondary);'
                        f'line-height:1.4;">{formatted}</td>'
                    )
                html_lines.append("</tr>")
            continue
        elif in_table:
            html_lines.append("</tbody></table>")
            in_table = False

        # Lists
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append(
                    '<ul style="margin:0.5rem 0;padding-left:1.25rem;'
                    'color:var(--text-secondary);font-size:0.85rem;line-height:1.6;">'
                )
                in_list = True
            formatted = format_inline_markdown(stripped[2:], footnotes)
            html_lines.append(f"<li>{formatted}</li>")
            continue
        elif in_list and stripped:
            html_lines.append("</ul>")
            in_list = False

        # Empty lines
        if not stripped:
            continue

        # Footnote definitions [^1]: ... - skip (already collected, shown as tooltips)
        footnote_match = re.match(r"^\[\^(\d+)\]:\s*(.*)$", stripped)
        if footnote_match:
            continue

        # Regular paragraphs
        formatted = format_inline_markdown(stripped, footnotes)
        html_lines.append(
            f'<p style="margin:0.5rem 0;color:var(--text-secondary);'
            f'font-size:0.85rem;line-height:1.6;">{formatted}</p>'
        )

    # Close any open tags
    if in_list:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append("</tbody></table>")

    return "\n".join(html_lines)


def format_inline_markdown(text: str, footnotes: dict[str, str] | None = None) -> str:
    """Format inline markdown: bold, italic, code, links, footnotes."""
    # Escape HTML first
    text = html.escape(text)

    # Bold **text**
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:var(--text-primary);">\1</strong>', text)
    # Italic *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    # Code `text`
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:var(--bg-card);padding:0.1rem 0.3rem;'
        r'border-radius:3px;font-size:0.8rem;">\1</code>',
        text,
    )

    # Footnote references [^1] - tooltip on hover
    def footnote_replacer(match: re.Match[str]) -> str:
        fn_num = match.group(1)
        fn_text = footnotes.get(fn_num, "") if footnotes else ""
        # Escape for title attribute (already HTML escaped, but need to escape quotes)
        fn_title = fn_text.replace('"', "&quot;")
        return (
            f'<span class="footnote-ref" data-fn="{fn_num}" title="{fn_title}" '
            f'style="color:var(--accent-primary);font-size:0.7rem;cursor:help;'
            f'border-bottom:1px dotted var(--accent-primary);">'
            f"<sup>[{fn_num}]</sup></span>"
        )

    text = re.sub(r"\[\^(\d+)\]", footnote_replacer, text)

    return text


# =============================================================================
# Analysis Generation
# =============================================================================


def generate_analysis_results(tasks_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Generate basic analysis stats for the dashboard.

    The actual report content comes from report.md files (stored in data["reports"]).
    This function just provides supplementary statistics.
    """
    results: dict[str, Any] = {
        "task_reports": [],
    }

    for task_id, task in tasks_data.items():
        claims = task["claims"]
        contros = task["contradictions"]
        timeline = task["timeline"]

        # Calculate basic stats
        confidences = [c["nli_claim_support_ratio"] for c in claims] if claims else [0.5]
        avg_conf = sum(confidences) / len(confidences)
        max_conf = max(confidences) if confidences else 0.5

        # Evidence edge totals (fragment→claim NLI edges)
        support_edges = sum(int(c.get("support", 0)) for c in claims)
        refute_edges = sum(int(c.get("refute", 0)) for c in claims)
        neutral_edges = sum(int(c.get("neutral", 0)) for c in claims)
        years = [t["year"] for t in timeline if t["year"]]
        year_range = f"{min(years)}–{max(years)}" if years else "N/A"

        task_report = {
            "task_name": task["shortName"],
            "task_id": task_id,
            "color": task["color"],
            "stats": {
                "total_claims": len(claims),
                "total_pages": task["stats"]["pages"],
                "avg_confidence": round(avg_conf, 2),
                "max_confidence": round(max_conf, 2),
                "support_edges": support_edges,
                "refute_edges": refute_edges,
                "neutral_edges": neutral_edges,
                "controversy_count": len(contros),
                "year_range": year_range,
            },
        }

        results["task_reports"].append(task_report)

    return results


# =============================================================================
# HTML Rendering
# =============================================================================


def escape_json_for_html(json_str: str) -> str:
    """
    Escape JSON string for safe embedding in HTML <script> tags.

    Prevents XSS attacks by escaping sequences that could break out of
    the script context or be interpreted as HTML.

    See: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
    """
    # Escape </script> and <!-- to prevent breaking out of script tags
    # Also escape U+2028/U+2029 which are line terminators in JS but not JSON
    return (
        json_str.replace("</", r"<\/")
        .replace("<!--", r"<\!--")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


def render_html(template_content: str, data: dict[str, Any]) -> str:
    """
    Replace __LYRA_DATA__ placeholder with JSON data.

    JSON data is escaped to prevent XSS when embedded in HTML script tags.
    """
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    safe_json = escape_json_for_html(json_data)

    # Replace placeholder
    if '"__LYRA_DATA__"' not in template_content:
        raise ValueError('Template does not contain "__LYRA_DATA__" placeholder')

    return template_content.replace('"__LYRA_DATA__"', safe_json)


# =============================================================================
# Main Generation Function
# =============================================================================


def generate_dashboard(config: DashboardConfig) -> Path:
    """
    Generate a dashboard HTML file from Lyra database.

    Args:
        config: Dashboard configuration

    Returns:
        Path to the generated HTML file
    """
    # Validate paths
    if not config.db_path.exists():
        raise FileNotFoundError(f"Database not found: {config.db_path}")

    if not config.template_path.exists():
        raise FileNotFoundError(f"Template not found: {config.template_path}")

    # Validate report paths
    for task_id, report_path in config.task_reports:
        if report_path and not report_path.exists():
            raise FileNotFoundError(f"Report not found for {task_id}: {report_path}")

    output_path = config.get_output_path()

    print("=== Lyra Data Exploration Dashboard Generator ===")
    print(f"Database: {config.db_path}")
    print("Tasks:")
    for task_id, report_path in config.task_reports:
        print(f"  - {task_id}" + (f" + {report_path}" if report_path else ""))
    print(f"Template: {config.template_path}")
    print(f"Output: {output_path}")
    print()

    # Connect to database
    conn = get_connection(config.db_path)

    # Build data structure
    data: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tasks": {},
        "reports": {},  # task_id -> rendered HTML from report.md
        "report_summaries": {},  # task_id -> report_summary.json (verdict source of truth)
    }

    for task_index, (task_id, report_path) in enumerate(config.task_reports):
        print(f"Processing {task_id}...")
        data["tasks"][task_id] = build_task_data(conn, task_id, task_index)

        # Load outputs/report_summary.json (preferred for verdict / summary display)
        summary_path = DEFAULT_REPORTS_DIR / task_id / "outputs" / "report_summary.json"
        if summary_path.exists():
            try:
                summary_obj = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(summary_obj, dict):
                    data["report_summaries"][task_id] = summary_obj
            except json.JSONDecodeError as e:
                # Keep dashboard generation resilient
                print(f"  Warning: invalid report_summary.json for {task_id}: {e}")

        # Load and convert report.md if provided
        if report_path:
            print(f"  Loading report: {report_path}")
            md_content = report_path.read_text(encoding="utf-8")
            html_content = markdown_to_html(md_content)
            data["reports"][task_id] = html_content
            print(f"  Converted {len(md_content)} chars markdown -> {len(html_content)} chars HTML")

    # Compute claim clusters and relation graph using embeddings (requires numpy)
    if HAS_CLUSTERING:
        print()
        print("Computing claim similarity clusters...")
        try:
            embeddings = extract_claim_embeddings(conn, config.task_ids)
            print(f"  Loaded {len(embeddings)} embeddings")

            claims_by_task = {tid: t["claims"] for tid, t in data["tasks"].items()}
            clusters = compute_claim_clusters(claims_by_task, embeddings)
            data["claim_clusters"] = clusters
            print(f"  Generated {len(clusters)} cluster points")

            # Build claim relation graph for network visualization
            print()
            print("Building claim relation graph...")
            claim_graph = build_claim_relation_graph(
                conn, claims_by_task, embeddings, max_edges=3000
            )
            data["claim_graph"] = claim_graph
            meta = claim_graph["meta"]
            print(f"  Nodes: {meta['total_nodes']}, Edges: {meta['total_edges']}")
            print(f"  Edge breakdown: {meta['edge_counts']}")
        except Exception as e:
            print(f"  Warning: Clustering/graph failed: {e}")
            data["claim_clusters"] = []
            data["claim_graph"] = {"nodes": [], "edges": [], "meta": {"error": str(e)}}
    else:
        data["claim_clusters"] = []
        data["claim_graph"] = {"nodes": [], "edges": [], "meta": {"error": "numpy not available"}}

    conn.close()

    # Generate basic analysis stats (reports are now in data["reports"])
    print()
    print("Generating analysis summary...")
    data["analysis"] = generate_analysis_results(data["tasks"])
    print(f"  Task reports: {len(data['analysis']['task_reports'])}")
    for tr in data["analysis"]["task_reports"]:
        has_report = "✓ report.md" if tr["task_id"] in data["reports"] else "stats only"
        print(f"    - {tr['task_name']}: {has_report}")

    # Calculate totals
    total_claims = sum(t["stats"]["claims"] for t in data["tasks"].values())
    total_pages = sum(t["stats"]["pages"] for t in data["tasks"].values())
    total_edges = sum(len(t["edges"]) for t in data["tasks"].values())

    print()
    print(f"Total: {total_claims} claims, {total_pages} pages, {total_edges} edges")

    # Load template and render
    print(f"Loading template: {config.template_path}")
    template_content = config.template_path.read_text(encoding="utf-8")

    print("Generating HTML...")
    html_content = render_html(template_content, data)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    output_size = output_path.stat().st_size / 1024
    print()
    print("=== Generation Complete ===")
    print(f"Output: {output_path}")
    print(f"Size: {output_size:.1f} KB")
    print()
    print("View in browser:")
    print(f"  file://{output_path.absolute()}")

    return output_path


# =============================================================================
# CLI Interface
# =============================================================================


def parse_task_report_pair(pair: str) -> tuple[str, Path | None]:
    """
    Parse task:report argument.

    Format: task_id (dashboard requires outputs/report.md to exist)
    """
    if ":" in pair:
        raise ValueError("Invalid --tasks value. Pass task_id only (no task_id:report.md).")
    task_id = pair
    report_path = DEFAULT_REPORTS_DIR / task_id / "outputs" / "report.md"
    return task_id, report_path


def main(args: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Lyra Data Exploration Dashboard from SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate dashboard for specific tasks
    python -m src.report.dashboard --tasks task_ed3b72cf task_8f90d8f6

    # Custom output path
    python -m src.report.dashboard --tasks task_xxx --output dashboard.html

Each --tasks argument must be:
  - task_id only (dashboard resolves data/reports/{task_id}/outputs/report.md)
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
        help="Task IDs (dashboard requires outputs/report.md for each task)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE_PATH,
        help=f"Path to HTML template (default: {DEFAULT_TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML file path (default: auto-generated in data/reports/dashboards/)",
    )

    parsed = parser.parse_args(args)

    # Resolve task -> outputs/report.md
    task_reports = [parse_task_report_pair(pair) for pair in parsed.tasks]

    for task_id, report_path in task_reports:
        if report_path is None or not report_path.exists():
            raise FileNotFoundError(f"Missing report.md for {task_id}: {report_path}")

    config = DashboardConfig(
        db_path=parsed.db,
        task_reports=task_reports,
        template_path=parsed.template,
        output_path=parsed.output,
    )

    try:
        generate_dashboard(config)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
