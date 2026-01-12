#!/usr/bin/env python3
"""
Lyra Draft Report Generator.

Generates drafts/draft_01.md from evidence_pack.json using a fixed template.
The draft is fact-only (no AI interpretation) - Stage 4 adds interpretation.

The draft uses explicit markers to guide LLM editing:
- <!-- LLM_EDITABLE: name --> ... <!-- /LLM_EDITABLE -->  (LLM should fill/replace)
- <!-- LLM_READONLY --> ... <!-- /LLM_READONLY -->        (LLM must not modify)

Template follows lyra-report command structure:
- Header (date, task_id, hypothesis)
- 1-minute summary
- Verdict
- Key Findings (3 tables: Efficacy, Safety, Applicability)
- Short synthesis (observations only)
- Appendix (Methodology, Contradictions, Full references)

Usage:
    python -m src.report.draft_generator --tasks task_id1 task_id2
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from src.report.evidence_pack import DEFAULT_OUTPUT_DIR, EvidencePack

# =============================================================================
# Source Quality Filtering (Metadata-based, no hardcoded domain lists)
# =============================================================================

# Minimum quality score to be included in main references
# Sources below this threshold are moved to Appendix D
MIN_QUALITY_SCORE_FOR_REFERENCE = 3


def _detect_source_type(citation: dict[str, Any]) -> tuple[str, int]:
    """
    Detect source type from URL patterns and metadata (no hardcoded domain lists).

    Returns:
        (source_type, score_modifier)
        - source_type: human-readable classification
        - score_modifier: positive = boost, negative = penalty, -100 = exclude
    """
    url = citation.get("url", "").lower()
    domain = citation.get("domain", "").lower()

    # === Exclusion patterns (structural, not domain-based) ===

    # Wiki-style collaborative content (URL path pattern)
    if "/wiki/" in url:
        return ("User-editable wiki content", -100)

    # Patent databases (URL path pattern)
    if "/patent/" in url or "/patents/" in url:
        return ("Patent database (not clinical evidence)", -100)

    # Press releases (URL path pattern)
    if "/news-release" in url or "/press-release" in url:
        return ("Press release (secondary source)", -100)

    # === Quality signals from metadata ===

    # Academic API sourced (high confidence)
    source_api = citation.get("source_api")
    if source_api in {"semantic_scholar", "openalex"}:
        return ("Academic API verified", +3)

    # Has DOI = verifiable scholarly work
    if citation.get("doi"):
        return ("DOI-verified publication", +2)

    # === Domain TLD patterns (structural, not specific domains) ===

    # Government domains
    if domain.endswith(".gov") or domain.endswith(".go.jp"):
        return ("Government source", +2)

    # Academic institutions
    if domain.endswith(".edu") or domain.endswith(".ac.jp") or domain.endswith(".ac.uk"):
        return ("Academic institution", +2)

    # === No strong signals = unverified ===

    # Check if completely lacking metadata
    has_author = citation.get("author_display") is not None
    has_year = citation.get("year") is not None
    has_venue = citation.get("venue") is not None

    if not has_author and not has_year and not has_venue and not citation.get("doi"):
        return ("Unverified source (no metadata)", -2)

    return ("General source", 0)


def compute_source_quality_score(citation: dict[str, Any]) -> int:
    """
    Compute quality score for a citation source based on metadata signals.

    Higher score = more reliable source.
    Score < MIN_QUALITY_SCORE_FOR_REFERENCE = excluded from main references.

    Scoring (additive):
    - DOI present: +3 (verifiable, peer-reviewed indicator)
    - Author info: +1 (attributable)
    - Year info: +1 (temporal context)
    - Venue info: +1 (publication context)
    - Source type modifier: varies (-100 to +3)
    """
    source_type, type_modifier = _detect_source_type(citation)

    # Hard exclusions (wiki, patents, press releases)
    if type_modifier <= -100:
        return -100

    score = type_modifier

    # Metadata signals
    if citation.get("doi"):
        score += 3
    if citation.get("author_display"):
        score += 1
    if citation.get("year"):
        score += 1
    if citation.get("venue"):
        score += 1

    return score


def is_excluded_source(citation: dict[str, Any]) -> bool:
    """Check if a citation should be excluded from main references."""
    score = compute_source_quality_score(citation)
    return score < MIN_QUALITY_SCORE_FOR_REFERENCE


def get_exclusion_reason(citation: dict[str, Any]) -> str:
    """Get human-readable reason for exclusion."""
    source_type, type_modifier = _detect_source_type(citation)

    # Hard exclusions have explicit reasons
    if type_modifier <= -100:
        return source_type

    # Soft exclusions (low score)
    score = compute_source_quality_score(citation)
    if score < MIN_QUALITY_SCORE_FOR_REFERENCE:
        missing = []
        if not citation.get("doi"):
            missing.append("DOI")
        if not citation.get("author_display"):
            missing.append("author")
        if not citation.get("year"):
            missing.append("year")
        if missing:
            return f"Insufficient metadata (missing: {', '.join(missing)})"
        return "Quality score below threshold"

    return "Unknown"


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class DraftConfig:
    """Configuration for draft report generation."""

    task_ids: list[str] = field(default_factory=list)
    reports_dir: Path = DEFAULT_OUTPUT_DIR

    def get_evidence_pack_path(self, task_id: str) -> Path:
        """Get path to evidence_pack.json for a task."""
        return self.reports_dir / task_id / "evidence_pack.json"

    def get_draft_output_path(self, task_id: str) -> Path:
        """Get path to drafts/draft_01.md for a task."""
        return self.reports_dir / task_id / "drafts" / "draft_01.md"


# =============================================================================
# Marker Helpers
# =============================================================================


def editable_start(name: str) -> str:
    """Return LLM_EDITABLE start marker."""
    return f"<!-- LLM_EDITABLE: {name} -->"


def editable_end() -> str:
    """Return LLM_EDITABLE end marker."""
    return "<!-- /LLM_EDITABLE -->"


def readonly_start() -> str:
    """Return LLM_READONLY start marker."""
    return "<!-- LLM_READONLY -->"


def readonly_end() -> str:
    """Return LLM_READONLY end marker."""
    return "<!-- /LLM_READONLY -->"


def delete_only_start(name: str) -> str:
    """Return LLM_DELETE_ONLY start marker."""
    return f"<!-- LLM_DELETE_ONLY: {name} -->"


def delete_only_end() -> str:
    """Return LLM_DELETE_ONLY end marker."""
    return "<!-- /LLM_DELETE_ONLY -->"


# =============================================================================
# Helper Functions
# =============================================================================


def load_evidence_pack(path: Path) -> EvidencePack:
    """Load evidence pack from JSON file."""
    with open(path, encoding="utf-8") as f:
        return cast(EvidencePack, json.load(f))


def format_confidence(confidence: float) -> str:
    """Format confidence value."""
    return f"{confidence:.2f}"


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def escape_markdown(text: str) -> str:
    """Escape markdown special characters in text."""
    # Escape pipe characters for table cells
    return text.replace("|", "\\|").replace("\n", " ")


def get_author_year(citation: dict[str, Any]) -> str:
    """Format author and year for citation."""
    author = citation.get("author_display")
    year = citation.get("year")

    if author and year:
        return f"{author}, {year}"
    elif author:
        return f"{author}, n.d."
    elif year:
        return str(year)
    else:
        return "n.d."


def format_catalog_entry(citation: dict[str, Any]) -> str:
    """
    Build a short, human-readable bibliographic string (no numbering).

    NOTE: This is used in the draft's Citable Source Catalog. Stage 3 will generate
    numbered references from used {{CITE:page_id}} tokens.
    """
    parts: list[str] = []

    author_year = get_author_year(citation)
    if author_year:
        parts.append(author_year)

    title = citation.get("title")
    if title:
        parts.append(str(title))

    venue = citation.get("venue")
    if venue:
        parts.append(str(venue))

    doi = citation.get("doi")
    if doi:
        parts.append(f"DOI:{doi}")
    else:
        url = citation.get("url")
        if url:
            parts.append(str(url))

    domain = citation.get("domain")
    if domain:
        parts.append(str(domain))

    return " | ".join(parts)


# =============================================================================
# Draft Generation
# =============================================================================


def generate_draft(evidence_pack: EvidencePack, task_id: str) -> str:
    """
    Generate drafts/draft_01.md content from evidence pack.

    The draft is fact-only (no AI interpretation).
    Stage 4 will add interpretation and polish.

    Markers:
    - <!-- LLM_EDITABLE: name --> ... <!-- /LLM_EDITABLE -->: LLM should fill/replace
    - <!-- LLM_READONLY --> ... <!-- /LLM_READONLY -->: LLM must not modify
    """
    metadata = evidence_pack["metadata"]
    claims = evidence_pack["claims"]
    contradictions = evidence_pack["contradictions"]
    citations = evidence_pack["citations"]

    # Build citation lookup (page_id -> citation)
    citation_by_page: dict[str, dict[str, Any]] = {
        c["page_id"]: cast(dict[str, Any], c) for c in citations
    }

    # Separate high-quality and excluded sources
    quality_citations: dict[str, dict[str, Any]] = {}
    excluded_citations: list[dict[str, Any]] = []
    for page_id, citation in citation_by_page.items():
        if is_excluded_source(citation):
            excluded_citations.append(citation)
        else:
            quality_citations[page_id] = citation

    def _citation_sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, int, str, str, str]:
        page_id, c = item
        year = c.get("year")
        year_key = int(year) if isinstance(year, int) else -1
        has_doi = 1 if c.get("doi") else 0
        domain = str(c.get("domain") or "")
        title = str(c.get("title") or "")
        return (-year_key, -has_doi, domain, title, page_id)

    # NOTE:
    # Evidence pack fields are claim-level aggregates derived from fragment→claim NLI edges.
    # They are exploration aids (ranking/navigation), NOT hypothesis verdicts.
    # Hypothesis verdict is produced in Stage 4 (LLM interpretation) and should be stored in outputs/report_summary.json.
    if not claims:
        avg_ratio = 0.5
    else:
        avg_ratio = sum(c.get("nli_claim_support_ratio", 0.5) for c in claims) / len(claims)

    # Start building the draft
    lines: list[str] = []

    # ==========================================================================
    # Header (READONLY - generated metadata)
    # ==========================================================================
    lines.append(readonly_start())
    lines.append(f"# Research Report: {task_id}")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"**Task ID**: `{task_id}`")
    hypothesis = metadata.get("hypothesis", "(No hypothesis specified)")
    lines.append(f"**Hypothesis**: {hypothesis}")
    lines.append(readonly_end())
    lines.append("")
    lines.append("---")
    lines.append("")

    # ==========================================================================
    # 1-Minute Summary (EDITABLE)
    # ==========================================================================
    lines.append("## 1-Minute Summary")
    lines.append("")
    lines.append(editable_start("executive_summary"))
    lines.append("<!-- PURPOSE: Provide a decision-first executive summary for human readers. -->")
    lines.append(
        "<!-- TASK: Write 3-6 lines summarizing efficacy, safety, and key limitations. -->"
    )
    lines.append(
        "<!-- GUIDANCE: Use {{CITE:page_id}} tokens only when you actually use a source to support a statement. -->"
    )
    lines.append(
        "<!-- IMPORTANT: Do NOT write numeric citations like [^1]. Stage 3 will assign numbers. -->"
    )
    lines.append("")
    lines.append("_(Replace this placeholder with your summary)_")
    lines.append(editable_end())
    lines.append("")

    # Mini summary table (READONLY - computed from evidence_pack)
    lines.append(readonly_start())
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Top Claims Analyzed | {len(claims)} |")
    lines.append(f"| Contradictions Found | {len(contradictions)} |")
    lines.append(f"| Sources Cited | {len(citations)} |")
    lines.append(readonly_end())
    lines.append("")

    # ==========================================================================
    # Verdict (EDITABLE - LLM determines verdict)
    # ==========================================================================
    lines.append("## Verdict")
    lines.append("")
    lines.append(editable_start("verdict"))
    lines.append(f"**{hypothesis}**: **[SUPPORTED / REFUTED / INCONCLUSIVE]**")
    lines.append("")
    lines.append("<!-- PURPOSE: Provide a hypothesis-level verdict for decision-making. -->")
    lines.append(
        "<!-- TASK: Choose SUPPORTED/REFUTED/INCONCLUSIVE and justify in 2-4 sentences. -->"
    )
    lines.append(
        "<!-- GUIDANCE: Base your reasoning on evidence_pack.json. Use {{CITE:page_id}} tokens only if used. -->"
    )
    lines.append(
        "<!-- IMPORTANT: Do NOT write numeric citations like [^1]. Stage 3 will assign numbers. -->"
    )
    lines.append(
        "<!-- IMPORTANT: Also write outputs/report_summary.json with the same verdict. -->"
    )
    lines.append("")
    lines.append("_(Replace with your verdict rationale)_")
    lines.append(editable_end())
    lines.append("")

    # Score context (READONLY - computed, LLM-only guidance removed in postprocess)
    lines.append(readonly_start())
    lines.append(
        "<!-- LLM_GUIDANCE: `nli_claim_support_ratio` (0–1) is a deterministic, NLI-weighted "
        "support ratio derived from fragment→claim evidence edges (supports vs refutes weights). "
        '0.50 means "no net support-vs-refute tilt (or insufficient/offsetting evidence)", NOT "50% efficacy". '
        "This score is claim-level and is used for navigation/ranking only. -->"
    )
    lines.append(
        f"<!-- LLM_GUIDANCE: Context: average nli_claim_support_ratio across TOP{len(claims)} claims = {avg_ratio:.2f} -->"
    )
    lines.append(readonly_end())
    lines.append("")

    # ==========================================================================
    # Key Findings (READONLY tables + EDITABLE interpretation)
    # ==========================================================================
    lines.append("## Key Findings")
    lines.append("")

    def claim_source_id(claim_id: str) -> str:
        """Lyra trace ID for the claim (used for audit/traceability)."""
        return f"`{claim_id}`"

    # Table A: Top claims (by evidence_count)
    lines.append("### Table A: Efficacy")
    lines.append("")
    lines.append(readonly_start())
    lines.append(
        "| Claim | Claim Source | nli_claim_support_ratio | supports/refutes/neutral edges | Evidence | Cited |"
    )
    lines.append(
        "|-------|--------------|--------------------------|------------------------------|----------|-------|"
    )
    lines.append(readonly_end())
    lines.append(delete_only_start("table_a_rows"))
    lines.append("<!-- PURPOSE: Allow deleting rows the prose does not discuss. -->")
    lines.append("<!-- RULE: Delete only. Do NOT edit remaining rows. -->")
    if claims:
        for claim in claims[: min(10, len(claims))]:
            claim_text = truncate_text(escape_markdown(claim["claim_text"]), 80)
            src = claim_source_id(claim["claim_id"])
            ratio = format_confidence(claim.get("nli_claim_support_ratio", 0.5))
            counts = f"{claim.get('support_count', 0)}/{claim.get('refute_count', 0)}/{claim.get('neutral_count', 0)}"
            ev = str(claim.get("evidence_count", 0))
            lines.append(f"| {claim_text} | {src} | {ratio} | {counts} | {ev} | {{{{PENDING}}}} |")
    else:
        lines.append("| _(No claims found)_ | - | - | - | - | - |")
    lines.append(delete_only_end())
    lines.append("")

    # Interpretation for Table A (EDITABLE)
    lines.append(editable_start("efficacy_interpretation"))
    lines.append("<!-- PURPOSE: Interpret Table A (efficacy) for human readers. -->")
    lines.append(
        "<!-- TASK: Add 1-2 sentences connecting the table patterns to the hypothesis. -->"
    )
    lines.append(
        "<!-- GUIDANCE: Use {{CITE:page_id}} tokens only when you actually use a source to support a statement. -->"
    )
    lines.append(editable_end())
    lines.append("")

    # Table B: Safety / Refuting Evidence
    lines.append("### Table B: Safety / Refuting Evidence")
    lines.append("")
    lines.append(readonly_start())
    lines.append(
        "| Claim | Claim Source | nli_claim_support_ratio | supports/refutes/neutral edges | Evidence | Cited |"
    )
    lines.append(
        "|-------|--------------|--------------------------|------------------------------|----------|-------|"
    )
    lines.append(readonly_end())
    lines.append(delete_only_start("table_b_rows"))
    lines.append("<!-- PURPOSE: Allow deleting rows the prose does not discuss. -->")
    lines.append("<!-- RULE: Delete only. Do NOT edit remaining rows. -->")
    if claims:
        by_refute = sorted(
            claims,
            key=lambda c: (
                -(c.get("refute_count", 0)),
                -(c.get("evidence_count", 0)),
                c.get("claim_id", ""),
            ),
        )
        for claim in by_refute[: min(10, len(by_refute))]:
            claim_text = truncate_text(escape_markdown(claim["claim_text"]), 80)
            src = claim_source_id(claim["claim_id"])
            ratio = format_confidence(claim.get("nli_claim_support_ratio", 0.5))
            counts = f"{claim.get('support_count', 0)}/{claim.get('refute_count', 0)}/{claim.get('neutral_count', 0)}"
            ev = str(claim.get("evidence_count", 0))
            lines.append(f"| {claim_text} | {src} | {ratio} | {counts} | {ev} | {{{{PENDING}}}} |")
    else:
        lines.append("| _(No claims found)_ | - | - | - | - | - |")
    lines.append(delete_only_end())
    lines.append("")

    # Interpretation for Table B (EDITABLE)
    lines.append(editable_start("safety_interpretation"))
    lines.append(
        "<!-- PURPOSE: Interpret Table B (safety / refuting evidence) for human readers. -->"
    )
    lines.append(
        "<!-- TASK: Explain key risks, contradictions, and clinical caveats in 1-2 sentences. -->"
    )
    lines.append(
        "<!-- GUIDANCE: Use {{CITE:page_id}} tokens only when you actually use a source to support a statement. -->"
    )
    lines.append(editable_end())
    lines.append("")

    # Table C: Support Evidence (edge summary)
    lines.append("### Table C: Support Evidence (Edge Summary)")
    lines.append("")
    lines.append(readonly_start())
    lines.append(
        "| Claim | Claim Source | nli_claim_support_ratio | supports/refutes/neutral edges | Evidence | Cited |"
    )
    lines.append(
        "|-------|--------------|--------------------------|------------------------------|----------|-------|"
    )
    lines.append(readonly_end())
    lines.append(delete_only_start("table_c_rows"))
    lines.append("<!-- PURPOSE: Allow deleting rows the prose does not discuss. -->")
    lines.append("<!-- RULE: Delete only. Do NOT edit remaining rows. -->")
    if claims:
        by_support = sorted(
            claims,
            key=lambda c: (
                -(c.get("support_count", 0)),
                -(c.get("evidence_count", 0)),
                c.get("claim_id", ""),
            ),
        )
        for claim in by_support[: min(10, len(by_support))]:
            claim_text = truncate_text(escape_markdown(claim["claim_text"]), 80)
            src = claim_source_id(claim["claim_id"])
            ratio = format_confidence(claim.get("nli_claim_support_ratio", 0.5))
            counts = f"{claim.get('support_count', 0)}/{claim.get('refute_count', 0)}/{claim.get('neutral_count', 0)}"
            ev = str(claim.get("evidence_count", 0))
            lines.append(f"| {claim_text} | {src} | {ratio} | {counts} | {ev} | {{{{PENDING}}}} |")
    else:
        lines.append("| _(No claims found)_ | - | - | - | - | - |")
    lines.append(delete_only_end())
    lines.append("")

    # Interpretation for Table C (EDITABLE)
    lines.append(editable_start("support_interpretation"))
    lines.append("<!-- PURPOSE: Interpret Table C (support evidence) for human readers. -->")
    lines.append("<!-- TASK: Summarize the strongest support patterns and what they imply. -->")
    lines.append(
        "<!-- GUIDANCE: Use {{CITE:page_id}} tokens only when you actually use a source to support a statement. -->"
    )
    lines.append(editable_end())
    lines.append("")

    # ==========================================================================
    # Short Synthesis (READONLY facts + EDITABLE prose)
    # ==========================================================================
    lines.append("## Short Synthesis")
    lines.append("")
    lines.append(readonly_start())
    lines.append("**Observations from evidence:**")
    lines.append(
        "- Claim-level aggregates come from fragment→claim NLI edges (supports/refutes/neutral)."
    )
    lines.append(
        "- `nli_claim_support_ratio` is an exploration score (support-vs-refute tilt), not a verdict."
    )
    lines.append(f"- {len(contradictions)} claims show contradicting evidence")
    lines.append(f"- Total evidence sources: {len(citations)}")
    lines.append(readonly_end())
    lines.append("")
    lines.append(editable_start("synthesis_prose"))
    lines.append("<!-- PURPOSE: Convert observations into decision-first analytical prose. -->")
    lines.append(
        "<!-- TASK: Write 2-4 paragraphs connecting the evidence patterns to the hypothesis. -->"
    )
    lines.append(
        "<!-- GUIDANCE: Use {{CITE:page_id}} tokens only when you actually use a source to support a statement. -->"
    )
    lines.append(
        "<!-- IMPORTANT: Do NOT write numeric citations like [^1]. Stage 3 will assign numbers. -->"
    )
    lines.append("")
    lines.append("_(Replace with your synthesis)_")
    lines.append(editable_end())
    lines.append("")

    # ==========================================================================
    # References (READONLY - auto-generated from {{CITE:page_id}} tokens)
    # ==========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## References")
    lines.append("")
    lines.append(readonly_start())
    lines.append("<!-- REFERENCES_AUTOGENERATED -->")
    lines.append(readonly_end())
    lines.append("")

    # ==========================================================================
    # Appendix A: Methodology (READONLY)
    # ==========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## Appendix A: Methodology")
    lines.append("")
    lines.append(readonly_start())
    lines.append("This report was generated using the Lyra Evidence Graph system.")
    lines.append("")
    lines.append("**Stages executed**:")
    lines.append("- Stage 1: Evidence extraction from Lyra DB")
    lines.append("- Stage 2: Deterministic draft generation (this document)")
    lines.append("- Stage 3: Validation gate (after LLM enhancement)")
    lines.append("- Stage 4: AI enhancement (LLM adds interpretation)")
    lines.append("")
    lines.append("**Deterministic vs. interpretive**:")
    lines.append(
        "- This draft is fact-only and does NOT deterministically derive a hypothesis verdict."
    )
    lines.append(
        "- The report verdict is produced in Stage 4 and stored in outputs/report_summary.json."
    )
    lines.append(readonly_end())
    lines.append("")

    # ==========================================================================
    # Appendix B: Contradictions (READONLY table + EDITABLE interpretation)
    # ==========================================================================
    lines.append("## Appendix B: Contradictions")
    lines.append("")

    if contradictions:
        lines.append(readonly_start())
        lines.append("| Claim | Supports | Refutes | Controversy Score |")
        lines.append("|-------|----------|---------|-------------------|")
        for cont in contradictions:
            claim_text = truncate_text(escape_markdown(cont["claim_text"]), 60)
            lines.append(
                f"| {claim_text} | {cont['support_count']} | {cont['refute_count']} | "
                f"{cont['controversy_score']:.2f} |"
            )
        lines.append(readonly_end())
        lines.append("")
        lines.append(editable_start("contradictions_interpretation"))
        lines.append(
            "<!-- Explain each major contradiction. Why might these claims have conflicting evidence?"
        )
        lines.append(
            "     Consider methodological differences, population differences, or endpoint definitions. -->"
        )
        lines.append("")
        lines.append("_(Replace with your interpretation of contradictions)_")
        lines.append(editable_end())
    else:
        lines.append("_(No contradicting claims found)_")
    lines.append("")

    # ==========================================================================
    # Appendix C: Citable Source Catalog (READONLY - LLM reference only)
    # ==========================================================================
    lines.append("## Appendix C: Citable Source Catalog")
    lines.append("")
    lines.append(readonly_start())
    lines.append(
        "<!-- LLM_GUIDANCE: Use these sources for citations in prose by copying `page_id` into a cite token: "
        "`{{CITE:page_id}}` (example: `{{CITE:page_123abc}}`). "
        "Do NOT write numeric citations like `[^1]` directly. Stage 3 will assign citation numbers. "
        "Use only the `page_id` values listed below (in-graph sources). -->"
    )
    lines.append("")
    lines.append("| page_id | Source |")
    lines.append("|---------|--------|")
    for page_id, citation in sorted(quality_citations.items(), key=_citation_sort_key):
        short = format_catalog_entry(citation)
        lines.append(f"| `{page_id}` | {escape_markdown(short)} |")
    lines.append(readonly_end())
    lines.append("")

    # ==========================================================================
    # Appendix D: Excluded Sources (READONLY auto-generated + EDITABLE notes)
    # ==========================================================================
    lines.append("## Appendix D: Excluded / Unresolved Sources")
    lines.append("")

    if excluded_citations:
        lines.append(readonly_start())
        lines.append(
            "The following sources were used for claim extraction but excluded from main references:"
        )
        lines.append("")
        lines.append("| Domain | URL | Reason |")
        lines.append("|--------|-----|--------|")
        for citation in excluded_citations:
            domain = citation.get("domain", "unknown")
            url = citation.get("url", "")
            reason = get_exclusion_reason(citation)
            # Truncate URL for table display
            display_url = url[:50] + "..." if len(url) > 50 else url
            lines.append(f"| {domain} | {escape_markdown(display_url)} | {reason} |")
        lines.append(readonly_end())
        lines.append("")
        lines.append(editable_start("excluded_sources_notes"))
        lines.append(
            "<!-- Optional: Add any notes about excluded sources or explain decisions. -->"
        )
        lines.append(editable_end())
    else:
        lines.append("_(No sources were excluded from this report)_")
    lines.append("")

    return "\n".join(lines)


def generate_drafts(config: DraftConfig) -> dict[str, Path]:
    """
    Generate draft reports for all configured tasks.

    Returns:
        Dictionary mapping task_id to drafts/draft_01.md path
    """
    if not config.task_ids:
        raise ValueError("No task IDs specified")

    results: dict[str, Path] = {}

    for task_id in config.task_ids:
        print(f"\n=== Generating draft for: {task_id} ===")

        # Load evidence pack
        pack_path = config.get_evidence_pack_path(task_id)
        if not pack_path.exists():
            raise FileNotFoundError(
                f"Evidence pack not found: {pack_path}\n"
                f"Run 'python -m src.report.report pack --tasks {task_id}' first."
            )

        print(f"  Loading: {pack_path}")
        evidence_pack = load_evidence_pack(pack_path)

        # Generate draft
        print("  Generating draft...")
        draft_content = generate_draft(evidence_pack, task_id)

        # Write draft
        draft_path = config.get_draft_output_path(task_id)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(draft_content)
        print(f"  Written: {draft_path}")

        results[task_id] = draft_path

    return results


# =============================================================================
# CLI Interface
# =============================================================================


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate draft report from evidence pack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate draft for specific tasks
    python -m src.report.draft_generator --tasks task_ed3b72cf task_8f90d8f6

    # Custom reports directory
    python -m src.report.draft_generator --tasks task_xxx --reports-dir ./my_reports
        """,
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to process",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Reports directory (default: {DEFAULT_OUTPUT_DIR})",
    )

    parsed = parser.parse_args(args)

    config = DraftConfig(
        task_ids=parsed.tasks,
        reports_dir=parsed.reports_dir,
    )

    print("=== Lyra Draft Report Generator ===")
    print(f"Tasks: {config.task_ids}")
    print(f"Reports dir: {config.reports_dir}")

    try:
        results = generate_drafts(config)
        print("\n=== Generation Complete ===")
        for task_id, draft_path in results.items():
            print(f"  {task_id}: {draft_path}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
