#!/usr/bin/env python3
"""
Lyra Evidence Dashboard Generator

Extracts complete task data from Lyra SQLite database and generates
a self-contained HTML visualization dashboard with 100% data fidelity.

This script is designed to bypass AI context window limitations by
directly querying the database and generating HTML output.

Usage:
    python generate_dashboard.py --db ../../../data/lyra.db \
        --tasks task_ed3b72cf task_8f90d8f6 \
        --template dashboard_template.html \
        --output evidence_dashboard.html

Requirements:
    - Python 3.10+
    - SQLite database with Lyra schema
    - dashboard_template.html with /* __LYRA_DATA__ */ placeholder

License: MIT
"""

import sqlite3
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Any
import hashlib
import re
import struct
from collections import defaultdict
import html

# Optional: numpy for dimensionality reduction (PCA without sklearn)
try:
    import numpy as np
    HAS_CLUSTERING = True
except ImportError:
    HAS_CLUSTERING = False
    np = None  # type: ignore


# Color palette for automatic task color assignment (high-contrast, colorblind-friendly)
TASK_COLORS = [
    "#f59e0b",  # Amber
    "#06b6d4",  # Cyan
    "#8b5cf6",  # Violet
    "#10b981",  # Emerald
    "#f43f5e",  # Rose
    "#3b82f6",  # Blue
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
]


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create database connection with row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


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
    patterns = [
        # Inhibitors (DPP-4, SGLT2, ACE, etc.)
        (r'\b(DPP-?4|SGLT-?2|ACE|ARB|PDE-?5)\s*inhibitors?\b', 
         lambda m: (f"{m.group(1).upper().replace('-', '-')} Inhibitors", f"{m.group(1).replace('-', '')}i")),
        # Receptor agonists (GLP-1)
        (r'\b(GLP-?1)\s*(?:receptor\s*)?agonists?\b',
         lambda m: (f"{m.group(1).upper()} Receptor Agonists", f"{m.group(1).replace('-', '')}RA")),
        # Generic drug names (ending in common suffixes)
        (r'\b([A-Z][a-z]+(?:metformin|gliptin|flozin|glutide|tide))\b',
         lambda m: (m.group(1).title(), m.group(1)[:8])),
        # Fallback: first capitalized word/phrase
        (r'^([A-Z][A-Za-z0-9\-]+(?:\s+[a-z]+)?)',
         lambda m: (m.group(1), m.group(1)[:8])),
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
    hash_val = int(hashlib.md5(task_id.encode()).hexdigest()[:8], 16)
    return TASK_COLORS[hash_val % len(TASK_COLORS)]


def extract_task_metadata(conn: sqlite3.Connection, task_id: str, task_index: int = 0) -> dict[str, Any]:
    """
    Extract task metadata from database.
    
    Dynamically derives display name and color from hypothesis and task_id.
    No hardcoded configuration required.
    """
    cursor = conn.execute(
        "SELECT hypothesis, status, created_at FROM tasks WHERE id = ?",
        (task_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Task {task_id} not found in database")
    
    hypothesis = row["hypothesis"]
    name, short_name = extract_drug_class_from_hypothesis(hypothesis)
    color = get_task_color(task_id, task_index)
    
    return {
        "hypothesis": hypothesis,
        "name": name,
        "shortName": short_name,
        "color": color,
        "status": row["status"],
        "created_at": row["created_at"],
    }


def extract_claim_embeddings(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, np.ndarray]:
    """
    Extract claim embeddings from database.
    
    Returns dict mapping claim_id -> embedding vector.
    """
    placeholders = ",".join("?" * len(task_ids))
    cursor = conn.execute(f"""
        SELECT e.target_id, e.embedding_blob, e.dimension
        FROM embeddings e
        JOIN claims c ON e.target_id = c.id
        WHERE e.target_type = 'claim'
          AND c.task_id IN ({placeholders})
    """, task_ids)
    
    embeddings = {}
    for row in cursor.fetchall():
        claim_id = row["target_id"]
        blob = row["embedding_blob"]
        dim = row["dimension"]
        # Unpack float32 array from blob
        vector = np.array(struct.unpack(f'{dim}f', blob))
        embeddings[claim_id] = vector
    
    return embeddings


def compute_claim_clusters(
    claims_by_task: dict[str, list[dict]], 
    embeddings: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    """
    Compute 2D coordinates for claims using PCA.
    
    Uses pure numpy PCA (no sklearn required) for dimensionality reduction.
    Returns list of {id, x, y, task_id, bayesian_confidence, text} for visualization.
    """
    if not HAS_CLUSTERING:
        return []
    
    # Collect all claims with embeddings
    claim_data = []
    vectors = []
    
    for task_id, claims in claims_by_task.items():
        for claim in claims:
            claim_id = claim["id"]
            if claim_id in embeddings:
                claim_data.append({
                    "id": claim_id,
                    "task_id": task_id,
                    "text": claim["text"][:100],  # Truncate for JSON size
                    "bayesian_confidence": claim["bayesian_confidence"],
                })
                vectors.append(embeddings[claim_id])
    
    if len(vectors) < 5:
        return []
    
    # Stack vectors
    X = np.vstack(vectors)
    
    # Standardize (zero mean, unit variance)
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1  # Avoid division by zero
    X_normalized = (X - X_mean) / X_std
    
    # PCA using SVD (pure numpy, no sklearn)
    # Compute covariance matrix and eigenvectors
    U, S, Vt = np.linalg.svd(X_normalized, full_matrices=False)
    
    # Project to 2D using first 2 principal components
    coords = X_normalized @ Vt[:2].T
    
    # Normalize to [0, 100] range for visualization
    coords_min = coords.min(axis=0)
    coords_max = coords.max(axis=0)
    coords_range = coords_max - coords_min
    coords_range[coords_range == 0] = 1  # Avoid division by zero
    coords_normalized = (coords - coords_min) / coords_range * 100
    
    # Combine with claim data
    result = []
    for i, data in enumerate(claim_data):
        data["x"] = float(coords_normalized[i, 0])
        data["y"] = float(coords_normalized[i, 1])
        result.append(data)
    
    return result


def extract_claims(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract ALL claims with real Bayesian confidence from NLI evidence.
    
    Uses v_claim_evidence_summary view for accurate Bayesian posterior.
    """
    cursor = conn.execute("""
        SELECT 
            c.id,
            c.claim_text as text,
            COALESCE(v.bayesian_truth_confidence, 0.5) as bayesian_confidence,
            COALESCE(v.support_count, 0) as support,
            COALESCE(v.refute_count, 0) as refute,
            COALESCE(v.neutral_count, 0) as neutral
        FROM claims c
        LEFT JOIN v_claim_evidence_summary v ON c.id = v.claim_id
        WHERE c.task_id = ?
        ORDER BY bayesian_confidence DESC, v.evidence_count DESC
    """, (task_id,))
    
    return [dict(row) for row in cursor.fetchall()]


def extract_sources(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract pages (sources) with real URLs and bibliographic metadata.
    
    Authority score = number of claims this source supports.
    """
    cursor = conn.execute("""
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
    """, (task_id,))
    
    sources = []
    for row in cursor.fetchall():
        sources.append({
            "id": row["id"],
            "domain": row["domain"],
            "title": row["title"],
            "url": row["url"],
            "year": row["year"],
            "doi": row["doi"],
            "venue": row["venue"],
            "authority_score": float(row["claims_supported"]),
            "claims_supported": row["claims_supported"],
        })
    return sources


def extract_fragments(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract fragments linked to task's claims via edges.
    
    Includes text content for tooltips and claim linkage.
    """
    cursor = conn.execute("""
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
    """, (task_id,))
    
    fragments = []
    for row in cursor.fetchall():
        # Get linked claims for this fragment
        claims_cursor = conn.execute("""
            SELECT DISTINCT e.target_id
            FROM edges e
            JOIN claims c ON e.target_id = c.id
            WHERE e.source_id = ? 
              AND e.source_type = 'fragment'
              AND e.target_type = 'claim'
              AND c.task_id = ?
        """, (row["id"], task_id))
        
        linked_claims = [r["target_id"] for r in claims_cursor.fetchall()]
        
        fragments.append({
            "id": row["id"],
            "page_id": row["page_id"],
            "text": row["text"][:500] if row["text"] else "",  # Truncate for size
            "heading": row["heading_context"],
            "claims": linked_claims,
        })
    
    return fragments


def extract_edges(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract ALL edges for the task.
    
    Includes fragment->claim (NLI) and page->page (cites) relationships.
    """
    # Fragment -> Claim edges
    cursor = conn.execute("""
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
    """, (task_id,))
    
    edges = [dict(row) for row in cursor.fetchall()]
    
    # Page -> Page citation edges (global, but filter to relevant pages)
    cursor = conn.execute("""
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
    """, (task_id, task_id))
    
    edges.extend([dict(row) for row in cursor.fetchall()])
    
    return edges


def extract_citations(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract page-to-page citations for visualization.
    """
    cursor = conn.execute("""
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
    """, (task_id,))
    
    return [dict(row) for row in cursor.fetchall()]


def extract_contradictions(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract claims with refuting evidence (real controversy).
    
    Controversy score = refute_count / (support_count + refute_count + 1)
    """
    cursor = conn.execute("""
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
    """, (task_id,))
    
    return [dict(row) for row in cursor.fetchall()]


def extract_timeline(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """
    Extract evidence timeline by publication year.
    
    Counts fragments and claims per year from works.year.
    """
    cursor = conn.execute("""
        SELECT 
            w.year,
            COUNT(DISTINCT f.id) as fragments,
            COUNT(DISTINCT c.id) as claims
        FROM works w
        JOIN pages p ON p.canonical_id = w.canonical_id
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
          AND w.year IS NOT NULL
        GROUP BY w.year
        ORDER BY w.year
    """, (task_id,))
    
    return [dict(row) for row in cursor.fetchall()]


def extract_stats(conn: sqlite3.Connection, task_id: str) -> dict[str, int]:
    """Extract basic statistics for a task."""
    # Claims count
    claims_cursor = conn.execute(
        "SELECT COUNT(*) as cnt FROM claims WHERE task_id = ?",
        (task_id,)
    )
    claims_count = claims_cursor.fetchone()["cnt"]
    
    # Pages count (linked to task via fragments/edges)
    pages_cursor = conn.execute("""
        SELECT COUNT(DISTINCT p.id) as cnt
        FROM pages p
        JOIN fragments f ON f.page_id = p.id
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id
        WHERE c.task_id = ?
    """, (task_id,))
    pages_count = pages_cursor.fetchone()["cnt"]
    
    # Fragments count
    fragments_cursor = conn.execute("""
        SELECT COUNT(DISTINCT f.id) as cnt
        FROM fragments f
        JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
        JOIN claims c ON e.target_id = c.id
        WHERE c.task_id = ?
    """, (task_id,))
    fragments_count = fragments_cursor.fetchone()["cnt"]
    
    return {
        "claims": claims_count,
        "pages": pages_count,
        "fragments": fragments_count,
    }


def build_task_data(conn: sqlite3.Connection, task_id: str, task_index: int = 0) -> dict[str, Any]:
    """
    Build complete task data structure from database.
    
    All display metadata (name, shortName, color) is derived dynamically
    from the hypothesis text and task_id - no hardcoding required.
    """
    metadata = extract_task_metadata(conn, task_id, task_index)
    
    print(f"  Extracting claims...", end=" ", flush=True)
    claims = extract_claims(conn, task_id)
    print(f"{len(claims)} claims")
    
    print(f"  Extracting sources...", end=" ", flush=True)
    sources = extract_sources(conn, task_id)
    print(f"{len(sources)} sources")
    
    print(f"  Extracting fragments...", end=" ", flush=True)
    fragments = extract_fragments(conn, task_id)
    print(f"{len(fragments)} fragments")
    
    print(f"  Extracting edges...", end=" ", flush=True)
    edges = extract_edges(conn, task_id)
    print(f"{len(edges)} edges")
    
    print(f"  Extracting citations...", end=" ", flush=True)
    citations = extract_citations(conn, task_id)
    print(f"{len(citations)} citations")
    
    print(f"  Extracting contradictions...", end=" ", flush=True)
    contradictions = extract_contradictions(conn, task_id)
    print(f"{len(contradictions)} controversies")
    
    print(f"  Extracting timeline...", end=" ", flush=True)
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


def markdown_to_html(md_content: str) -> str:
    """
    Simple markdown to HTML conversion for report.md files.
    
    Handles: headers, bold, italic, lists, tables, footnotes, horizontal rules.
    """
    lines = md_content.split('\n')
    html_lines = []
    in_list = False
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        
        # Horizontal rule
        if stripped == '---':
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            if in_table:
                html_lines.append('</tbody></table>')
                in_table = False
            html_lines.append('<hr style="border:none;border-top:1px solid var(--border);margin:1rem 0;">')
            continue
        
        # Headers
        if stripped.startswith('### '):
            html_lines.append(f'<h4 style="color:var(--text-primary);margin:1rem 0 0.5rem 0;font-size:0.95rem;">{html.escape(stripped[4:])}</h4>')
            continue
        if stripped.startswith('## '):
            html_lines.append(f'<h3 style="color:var(--accent-primary);margin:1.25rem 0 0.5rem 0;font-size:1rem;font-weight:600;">{html.escape(stripped[3:])}</h3>')
            continue
        if stripped.startswith('# '):
            html_lines.append(f'<h2 style="color:var(--text-primary);margin:0 0 0.5rem 0;font-size:1.1rem;font-weight:700;">{html.escape(stripped[2:])}</h2>')
            continue
        
        # Tables
        if stripped.startswith('|') and '|' in stripped[1:]:
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            
            # Check if this is a separator row
            if all(set(c) <= {'-', ':', ' '} for c in cells):
                continue
            
            if not in_table:
                html_lines.append('<table style="width:100%;border-collapse:collapse;font-size:0.75rem;margin:0.5rem 0;">')
                html_lines.append('<thead><tr style="border-bottom:1px solid var(--border);">')
                for cell in cells:
                    formatted = format_inline_markdown(cell)
                    html_lines.append(f'<th style="text-align:left;padding:0.4rem;color:var(--text-muted);font-weight:500;">{formatted}</th>')
                html_lines.append('</tr></thead><tbody>')
                in_table = True
            else:
                html_lines.append('<tr style="border-bottom:1px solid var(--border);">')
                for cell in cells:
                    formatted = format_inline_markdown(cell)
                    html_lines.append(f'<td style="padding:0.4rem;color:var(--text-secondary);line-height:1.4;">{formatted}</td>')
                html_lines.append('</tr>')
            continue
        elif in_table:
            html_lines.append('</tbody></table>')
            in_table = False
        
        # Lists
        if stripped.startswith('- '):
            if not in_list:
                html_lines.append('<ul style="margin:0.5rem 0;padding-left:1.25rem;color:var(--text-secondary);font-size:0.85rem;line-height:1.6;">')
                in_list = True
            formatted = format_inline_markdown(stripped[2:])
            html_lines.append(f'<li>{formatted}</li>')
            continue
        elif in_list and stripped:
            html_lines.append('</ul>')
            in_list = False
        
        # Empty lines
        if not stripped:
            continue
        
        # Regular paragraphs
        formatted = format_inline_markdown(stripped)
        html_lines.append(f'<p style="margin:0.5rem 0;color:var(--text-secondary);font-size:0.85rem;line-height:1.6;">{formatted}</p>')
    
    # Close any open tags
    if in_list:
        html_lines.append('</ul>')
    if in_table:
        html_lines.append('</tbody></table>')
    
    return '\n'.join(html_lines)


def format_inline_markdown(text: str) -> str:
    """Format inline markdown: bold, italic, code, links, footnotes."""
    # Escape HTML first
    text = html.escape(text)
    
    # Bold **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:var(--text-primary);">\1</strong>', text)
    # Italic *text*
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    # Code `text`
    text = re.sub(r'`([^`]+)`', r'<code style="background:var(--bg-card);padding:0.1rem 0.3rem;border-radius:3px;font-size:0.8rem;">\1</code>', text)
    # Footnote references [^1]
    text = re.sub(r'\[\^(\d+)\]', r'<sup style="color:var(--accent-primary);font-size:0.7rem;">[\1]</sup>', text)
    
    return text


def generate_analysis_results(tasks_data: dict[str, dict]) -> dict[str, Any]:
    """
    Generate basic analysis stats for the dashboard.
    
    The actual report content comes from report.md files (stored in data["reports"]).
    This function just provides supplementary statistics.
    """
    results = {
        "task_reports": [],
    }
    
    for task_id, task in tasks_data.items():
        claims = task["claims"]
        contros = task["contradictions"]
        timeline = task["timeline"]
        
        # Calculate basic stats
        confidences = [c["bayesian_confidence"] for c in claims] if claims else [0.5]
        avg_conf = sum(confidences) / len(confidences)
        max_conf = max(confidences) if confidences else 0.5
        supports = len([c for c in confidences if c > 0.50])
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
                "supports": supports,
                "controversy_count": len(contros),
                "year_range": year_range,
            },
        }
        
        results["task_reports"].append(task_report)
    
    return results


def render_html(template_content: str, data: dict[str, Any]) -> str:
    """Replace __LYRA_DATA__ placeholder with JSON data."""
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    
    # Replace placeholder
    if "/* __LYRA_DATA__ */" not in template_content:
        raise ValueError("Template does not contain /* __LYRA_DATA__ */ placeholder")
    
    return template_content.replace("/* __LYRA_DATA__ */", json_data)


def parse_task_report_pair(pair: str) -> tuple[str, Path | None]:
    """
    Parse task:report argument.
    
    Format: task_id or task_id:path/to/report.md
    """
    if ':' in pair:
        task_id, report_path = pair.split(':', 1)
        return task_id, Path(report_path)
    return pair, None


def main():
    parser = argparse.ArgumentParser(
        description="Generate Lyra Evidence Dashboard from SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example (run from src/ directory):
    python generate_dashboard.py

Or with custom paths:
    python generate_dashboard.py \\
        --db ../../../../data/lyra.db \\
        --tasks task_ed3b72cf:../../session_01/report.md \\
                task_8f90d8f6:../../session_02/report.md \\
        --output ../output/evidence_dashboard.html

Each --tasks argument can be:
  - task_id only: Extract data from Lyra DB
  - task_id:report.md: Also include pre-written report markdown
        """
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("../../../../data/lyra.db"),
        help="Path to Lyra SQLite database"
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["task_ed3b72cf:../../session_01/report.md", "task_8f90d8f6:../../session_02/report.md"],
        help="Task IDs with optional report paths (task_id:report.md)"
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("dashboard_template.html"),
        help="Path to HTML template (default: dashboard_template.html)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../output/evidence_dashboard.html"),
        help="Output HTML file path (default: ../output/evidence_dashboard.html)"
    )
    
    args = parser.parse_args()
    
    # Parse task:report pairs
    task_reports = []
    for pair in args.tasks:
        task_id, report_path = parse_task_report_pair(pair)
        task_reports.append((task_id, report_path))
    
    # Validate paths
    if not args.db.exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    
    if not args.template.exists():
        print(f"Error: Template not found: {args.template}", file=sys.stderr)
        sys.exit(1)
    
    # Validate report paths
    for task_id, report_path in task_reports:
        if report_path and not report_path.exists():
            print(f"Error: Report not found for {task_id}: {report_path}", file=sys.stderr)
            sys.exit(1)
    
    print(f"=== Lyra Evidence Dashboard Generator ===")
    print(f"Database: {args.db}")
    print(f"Tasks:")
    for task_id, report_path in task_reports:
        print(f"  - {task_id}" + (f" + {report_path}" if report_path else ""))
    print(f"Template: {args.template}")
    print(f"Output: {args.output}")
    print()
    
    # Connect to database
    conn = get_connection(args.db)
    
    # Build data structure
    data = {
        "generated_at": datetime.now().isoformat(),
        "tasks": {},
        "reports": {},  # task_id -> rendered HTML from report.md
    }
    
    task_ids = [t[0] for t in task_reports]
    
    for task_index, (task_id, report_path) in enumerate(task_reports):
        print(f"Processing {task_id}...")
        try:
            data["tasks"][task_id] = build_task_data(conn, task_id, task_index)
        except Exception as e:
            print(f"Error processing {task_id}: {e}", file=sys.stderr)
            sys.exit(1)
        
        # Load and convert report.md if provided
        if report_path:
            print(f"  Loading report: {report_path}")
            md_content = report_path.read_text(encoding="utf-8")
            html_content = markdown_to_html(md_content)
            data["reports"][task_id] = html_content
            print(f"  Converted {len(md_content)} chars markdown -> {len(html_content)} chars HTML")
    
    # Compute claim clusters using embeddings (requires numpy)
    if HAS_CLUSTERING:
        print()
        print("Computing claim similarity clusters...")
        try:
            embeddings = extract_claim_embeddings(conn, task_ids)
            print(f"  Loaded {len(embeddings)} embeddings")
            
            claims_by_task = {tid: t["claims"] for tid, t in data["tasks"].items()}
            clusters = compute_claim_clusters(claims_by_task, embeddings)
            data["claim_clusters"] = clusters
            print(f"  Generated {len(clusters)} cluster points")
        except Exception as e:
            print(f"  Warning: Clustering failed: {e}")
            data["claim_clusters"] = []
    else:
        data["claim_clusters"] = []
    
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
    print(f"Loading template: {args.template}")
    template_content = args.template.read_text(encoding="utf-8")
    
    print(f"Generating HTML...")
    html_content = render_html(template_content, data)
    
    # Write output
    args.output.write_text(html_content, encoding="utf-8")
    
    output_size = args.output.stat().st_size / 1024
    print()
    print(f"=== Generation Complete ===")
    print(f"Output: {args.output}")
    print(f"Size: {output_size:.1f} KB")
    print()
    print(f"View in browser:")
    print(f"  file://{args.output.absolute()}")


if __name__ == "__main__":
    main()
