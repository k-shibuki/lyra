#!/usr/bin/env python3
"""
Lyra Report Validator.

Validates LLM-enhanced report.md against evidence_pack constraints.
Implements Stage 3 validation gate from lyra-report command.

Validation rules:
1. No hallucinated URLs - all cited URLs must be in citation_index
2. No fabricated numbers - effect sizes must match fragment snippets
3. Lyra trace IDs present - every footnote must have page_id
4. No new claims - all claims must be in evidence_pack

Usage:
    python -m src.report.validator --tasks task_id:report.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from src.report.evidence_pack import DEFAULT_OUTPUT_DIR

# =============================================================================
# Type Definitions
# =============================================================================


class ViolationReport(TypedDict):
    """Validation result for a single task."""

    task_id: str
    report_path: str
    validation_timestamp: str
    passed: bool
    violations: dict[str, list[dict[str, Any]]]
    summary: dict[str, int]


class ReportSummary(TypedDict, total=False):
    """Structured report summary used by dashboard as source-of-truth for verdict."""

    schema_version: str
    task_id: str
    hypothesis: str
    verdict: str  # SUPPORTED|REFUTED|INCONCLUSIVE
    verdict_rationale: str
    key_outcomes: list[dict[str, Any]]
    evidence_notes: list[str]
    generated_at: str


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class ValidationConfig:
    """Configuration for report validation."""

    task_reports: list[tuple[str, Path]] = field(default_factory=list)
    reports_dir: Path = DEFAULT_OUTPUT_DIR

    def get_evidence_pack_path(self, task_id: str) -> Path:
        """Get path to evidence_pack.json for a task."""
        return self.reports_dir / task_id / "evidence_pack.json"

    def get_citation_index_path(self, task_id: str) -> Path:
        """Get path to citation_index.json for a task."""
        return self.reports_dir / task_id / "citation_index.json"

    def get_violation_report_path(self, task_id: str) -> Path:
        """Get path to violation_report.json for a task."""
        return self.reports_dir / task_id / "violation_report.json"

    def get_report_summary_path(self, task_id: str) -> Path:
        """Get path to report_summary.json for a task (sidecar)."""
        return self.reports_dir / task_id / "outputs" / "report_summary.json"

    def get_suggested_fixes_patch_path(self, task_id: str) -> Path:
        """Get path to suggested_fixes.patch for a task."""
        return self.reports_dir / task_id / "suggested_fixes.patch"

    def get_suggested_fixes_md_path(self, task_id: str) -> Path:
        """Get path to suggested_fixes.md for a task."""
        return self.reports_dir / task_id / "suggested_fixes.md"


# =============================================================================
# Extraction Functions
# =============================================================================


def extract_urls_from_report(content: str) -> set[str]:
    """Extract all URLs from report content."""
    # Match URLs in footnotes and markdown links
    url_patterns = [
        r"https?://[^\s\)>\]]+",  # Standard URLs
        r"DOI:(\d+\.\d+/[^\s\]]+)",  # DOI references
    ]

    urls: set[str] = set()
    for pattern in url_patterns:
        for match in re.finditer(pattern, content):
            url = match.group(0)
            # Clean up trailing punctuation
            url = url.rstrip(".,;:")
            urls.add(url)

    return urls


def extract_footnotes(content: str) -> list[dict[str, Any]]:
    """Extract footnote definitions from report."""
    # Pattern: [^n]: content
    pattern = r"\[\^(\d+)\]:\s*(.+?)(?=\n\[\^|\n\n|\Z)"
    footnotes = []

    for match in re.finditer(pattern, content, re.DOTALL):
        footnote_num = int(match.group(1))
        footnote_content = match.group(2).strip()

        # Extract page_id if present
        page_id_match = re.search(r"page_id=([^\s,\.\]]+)", footnote_content)
        page_id = page_id_match.group(1) if page_id_match else None

        # Extract fragment_id if present
        fragment_id_match = re.search(r"fragment_id=([^\s,\.\]]+)", footnote_content)
        fragment_id = fragment_id_match.group(1) if fragment_id_match else None

        footnotes.append(
            {
                "number": footnote_num,
                "content": footnote_content,
                "page_id": page_id,
                "fragment_id": fragment_id,
                "has_trace_ids": page_id is not None,
            }
        )

    return footnotes


def extract_numbers_from_report(content: str) -> list[dict[str, Any]]:
    """Extract numerical values from report tables and claims."""
    # Patterns for various number formats
    patterns = [
        # Percentages: 0.5%, -0.7%, 0.5-0.8%
        (r"(-?\d+\.?\d*)\s*%", "percentage"),
        # Ranges: 0.5-0.8, -0.7 to -0.5
        (r"(-?\d+\.?\d*)\s*(?:to|-)\s*(-?\d+\.?\d*)", "range"),
        # Effect sizes with units: 0.5 kg, -0.7 mmol/L
        (r"(-?\d+\.?\d*)\s*(kg|g|mg|mmol/L|ml|L)", "effect_size"),
        # Confidence intervals: [0.45, 0.62]
        (r"\[(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\]", "ci"),
        # Sample sizes: n=100, N=50
        (r"[nN]\s*=\s*(\d+)", "sample_size"),
        # Study counts: 12 RCTs, 5 studies
        (r"(\d+)\s*(?:RCTs?|studies|trials|meta-analyses)", "study_count"),
    ]

    numbers: list[dict[str, Any]] = []
    for pattern, num_type in patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            numbers.append(
                {
                    "value": match.group(0),
                    "type": num_type,
                    "position": match.start(),
                    "context": content[max(0, match.start() - 50) : match.end() + 50],
                }
            )

    return numbers


def extract_claim_texts(content: str) -> list[str]:
    """Extract claim texts from report tables."""
    # Extract text from table cells (first column typically)
    # Pattern for table rows: | claim text | ... |
    pattern = r"\|\s*([^|]+)\s*\|"
    claims = []

    for match in re.finditer(pattern, content):
        text = match.group(1).strip()
        # Filter out headers and empty cells
        if text and not text.startswith("-") and text not in ("Claim", "Metric", "Value"):
            # Remove markdown formatting
            text = re.sub(r"\*+", "", text)
            text = re.sub(r"_+", "", text)
            text = text.strip()
            if len(text) > 10:  # Minimum claim length
                claims.append(text)

    return claims


# =============================================================================
# Report Summary Validation
# =============================================================================


def _is_valid_verdict(v: str) -> bool:
    return v in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"}


def validate_report_summary(
    task_id: str,
    report_summary: ReportSummary,
) -> list[dict[str, Any]]:
    """
    Validate report_summary.json basic integrity.

    This is intentionally lightweight: report_summary is authored by the LLM
    but must be machine-readable and task-consistent.
    """
    violations: list[dict[str, Any]] = []

    if report_summary.get("task_id") not in (None, task_id):
        violations.append(
            {
                "reason": "report_summary.task_id mismatch",
                "expected_task_id": task_id,
                "actual_task_id": report_summary.get("task_id"),
            }
        )

    verdict = report_summary.get("verdict")
    if verdict is None or not isinstance(verdict, str) or not _is_valid_verdict(verdict):
        violations.append(
            {
                "reason": "Invalid or missing verdict (SUPPORTED|REFUTED|INCONCLUSIVE)",
                "verdict": verdict,
            }
        )

    rationale = report_summary.get("verdict_rationale")
    if rationale is None or not isinstance(rationale, str) or len(rationale.strip()) < 10:
        violations.append(
            {
                "reason": "Missing/too-short verdict_rationale",
                "min_length": 10,
            }
        )

    return violations


# =============================================================================
# Suggested Fixes (Patch Proposals)
# =============================================================================


def _unified_diff(old: str, new: str, from_name: str, to_name: str) -> str:
    import difflib

    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=to_name))


def _extract_domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)/?", url)
    return m.group(1).lower() if m else ""


def _best_allowed_url_for(offending_url: str, allowed_urls: set[str]) -> str | None:
    """
    Pick a best-effort replacement URL from citation_index keys.
    Prefers same-domain and long common prefix.
    """
    if not allowed_urls:
        return None

    off_norm = offending_url.rstrip("/")
    off_domain = _extract_domain(off_norm)

    best: tuple[int, int, str] | None = None  # (domain_bonus, prefix_len, url)
    for cand in allowed_urls:
        cand_norm = cand.rstrip("/")
        cand_domain = _extract_domain(cand_norm)
        domain_bonus = 1 if (off_domain and off_domain == cand_domain) else 0
        # common prefix length (cheap similarity)
        prefix_len = 0
        for a, b in zip(off_norm, cand_norm, strict=False):
            if a != b:
                break
            prefix_len += 1
        score = (domain_bonus, prefix_len, cand)
        if best is None or score > best:
            best = score

    return best[2] if best else None


def propose_suggested_fixes(
    *,
    task_id: str,
    report_path: Path,
    report_content: str,
    violation_report: ViolationReport,
    evidence_pack: dict[str, Any],
    citation_index: dict[str, Any],
    config: ValidationConfig,
) -> tuple[str, str] | None:
    """
    Generate suggested fixes as:
    - suggested_fixes.patch: unified diff against report.md (proposal only)
    - suggested_fixes.md: human-readable explanation

    Scope: missing_trace_ids, hallucinated_urls (hard failures).
    """
    violations = violation_report.get("violations", {})
    trace_violations = violations.get("missing_trace_ids", [])
    url_violations = violations.get("hallucinated_urls", [])

    if not trace_violations and not url_violations:
        return None

    new_content = report_content
    notes: list[str] = []

    # --- missing_trace_ids ---
    if trace_violations:
        # Build DOI/page_id lookup from evidence_pack citations
        citations = evidence_pack.get("citations", [])
        doi_to_page_id: dict[str, str] = {}
        url_to_page_id: dict[str, str] = {}
        for c in citations:
            pid = c.get("page_id")
            if not pid:
                continue
            doi = c.get("doi")
            url = c.get("url")
            if isinstance(doi, str) and doi:
                doi_to_page_id[doi.lower()] = pid
            if isinstance(url, str) and url:
                url_to_page_id[url.rstrip("/")] = pid

        # Replace footnotes in a line-oriented way (best effort)
        lines = new_content.splitlines()
        changed = 0
        for i, line in enumerate(lines):
            m = re.match(r"^\[\^(\d+)\]:\s*(.*)$", line)
            if not m:
                continue
            if "page_id=" in line:
                continue

            # Try: URL match
            urls_in_line = extract_urls_from_report(line)
            page_id: str | None = None
            for u in urls_in_line:
                u_norm = u.rstrip("/")
                # prefix match against citation_index keys
                for allowed in citation_index.keys():
                    a_norm = str(allowed).rstrip("/")
                    if u_norm.startswith(a_norm) or a_norm.startswith(u_norm):
                        page_id = citation_index[allowed].get("page_id")
                        break
                if page_id:
                    break

            # Try: DOI match
            if not page_id:
                doi_match = re.search(r"DOI:([0-9]+\.[0-9]+/[^\s\]]+)", line, re.IGNORECASE)
                if doi_match:
                    doi_val = doi_match.group(1).lower()
                    page_id = doi_to_page_id.get(doi_val)

            if page_id:
                lines[i] = line.rstrip() + f" Lyra: page_id={page_id}."
                changed += 1

        if changed:
            new_content = "\n".join(lines) + ("\n" if new_content.endswith("\n") else "")
            notes.append(
                f"- Added `page_id=` to {changed} footnote(s) flagged by `missing_trace_ids`."
            )
        else:
            notes.append(
                "- Could not automatically match missing-trace footnotes to a `page_id` (needs manual fix)."
            )

    # --- hallucinated_urls ---
    if url_violations:
        allowed_urls = set(citation_index.keys())
        replaced = 0
        for v in url_violations:
            off_url = v.get("url")
            if not isinstance(off_url, str) or not off_url:
                continue
            replacement = _best_allowed_url_for(off_url, allowed_urls)
            if replacement and replacement != off_url:
                if off_url in new_content:
                    new_content = new_content.replace(off_url, replacement)
                    replaced += 1

        if replaced:
            notes.append(
                f"- Replaced {replaced} hallucinated URL occurrence(s) with best-match in-graph URLs."
            )
        else:
            notes.append(
                "- Hallucinated URLs detected but no safe automatic replacement found (suggest manual removal)."
            )

    patch = _unified_diff(
        report_content,
        new_content,
        from_name=str(report_path),
        to_name=str(report_path),
    )

    md = "\n".join(
        [
            f"# Suggested Fixes for {task_id}",
            "",
            "This file was generated by the validator. Review carefully before applying.",
            "",
            "## Summary",
            *notes,
            "",
            "## How to apply",
            "1. Review `suggested_fixes.patch`",
            "2. Apply manually (recommended) or via `git apply` / `patch`",
            "3. Re-run validation",
            "",
        ]
    )

    # Only emit if patch actually contains changes
    if patch.strip() == "":
        return md, ""
    return md, patch


# =============================================================================
# Validation Functions
# =============================================================================


def validate_urls(
    report_urls: set[str],
    citation_index: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Validate that all report URLs are in citation_index.

    Returns list of hallucinated URL violations.
    """
    allowed_urls = set(citation_index.keys())
    violations = []

    for url in report_urls:
        # Normalize URL for comparison
        normalized = url.rstrip("/")

        # Check if URL or a prefix matches
        is_valid = False
        for allowed in allowed_urls:
            if normalized.startswith(allowed.rstrip("/")) or allowed.rstrip("/").startswith(
                normalized
            ):
                is_valid = True
                break

        # Also allow DOI URLs
        if url.startswith("DOI:") or "doi.org" in url:
            is_valid = True

        if not is_valid:
            violations.append(
                {
                    "url": url,
                    "reason": "URL not found in citation_index",
                }
            )

    return violations


def validate_footnote_traces(
    footnotes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate that all footnotes have Lyra trace IDs.

    Returns list of missing trace ID violations.
    """
    violations = []

    for fn in footnotes:
        if not fn["has_trace_ids"]:
            violations.append(
                {
                    "footnote_number": fn["number"],
                    "content_preview": fn["content"][:100] + "..."
                    if len(fn["content"]) > 100
                    else fn["content"],
                    "reason": "Missing page_id in footnote",
                }
            )

    return violations


def validate_numbers(
    report_numbers: list[dict[str, Any]],
    evidence_chains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate that numerical values match evidence chain fragments.

    This is a heuristic check - exact matching is difficult.
    Returns list of potentially fabricated number violations.
    """
    # Build a set of all numbers mentioned in evidence chains
    # For now, we just check that numbers appear somewhere in the evidence
    evidence_text = " ".join(
        str(ec.get("heading_context", "")) + " " + str(ec.get("claim_text", ""))
        for ec in evidence_chains
    )

    violations = []

    for num in report_numbers:
        value = num["value"]
        # Extract just the numeric part for comparison
        numeric_match = re.search(r"-?\d+\.?\d*", value)
        if numeric_match:
            numeric_value = numeric_match.group(0)
            # Check if this number appears in evidence
            # This is a loose check - false positives are possible
            if numeric_value not in evidence_text and len(numeric_value) > 2:
                # Only flag larger numbers that don't appear
                # Small numbers like 0, 1, 2 are common and not useful to validate
                try:
                    if abs(float(numeric_value)) > 0.01:
                        violations.append(
                            {
                                "value": value,
                                "type": num["type"],
                                "context": num["context"],
                                "reason": "Number not found in evidence chains (may need verification)",
                                "severity": "warning",  # Not a hard failure
                            }
                        )
                except ValueError:
                    pass

    # Filter to unique violations
    seen = set()
    unique_violations = []
    for v in violations:
        key = v["value"]
        if key not in seen:
            seen.add(key)
            unique_violations.append(v)

    return unique_violations


def validate_claims(
    report_claims: list[str],
    evidence_pack_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate that report claims match evidence pack claims.

    Returns list of potentially new/hallucinated claim violations.
    """
    # Build set of known claim texts (normalized)
    known_claims = {c["claim_text"].lower().strip() for c in evidence_pack_claims}

    violations = []

    for claim in report_claims:
        claim_lower = claim.lower().strip()
        # Check for fuzzy match (claim is substring of known claim or vice versa)
        is_known = False
        for known in known_claims:
            if claim_lower in known or known in claim_lower:
                is_known = True
                break
            # Also check for high overlap
            claim_words = set(claim_lower.split())
            known_words = set(known.split())
            if len(claim_words) > 3:
                overlap = len(claim_words & known_words) / len(claim_words)
                if overlap > 0.6:
                    is_known = True
                    break

        if not is_known and len(claim) > 30:  # Only flag substantial claims
            violations.append(
                {
                    "claim": claim[:100] + "..." if len(claim) > 100 else claim,
                    "reason": "Claim not found in evidence pack (may be paraphrased)",
                    "severity": "warning",
                }
            )

    # Limit to first 10 to avoid noise
    return violations[:10]


# =============================================================================
# Main Validation
# =============================================================================


def validate_report(
    task_id: str,
    report_path: Path,
    config: ValidationConfig,
) -> ViolationReport:
    """
    Validate a single report against evidence pack constraints.

    Returns ViolationReport with all validation results.
    """
    # Load report
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")
    report_content = report_path.read_text(encoding="utf-8")

    # Load evidence pack
    pack_path = config.get_evidence_pack_path(task_id)
    if not pack_path.exists():
        raise FileNotFoundError(f"Evidence pack not found: {pack_path}")
    with open(pack_path, encoding="utf-8") as f:
        evidence_pack = json.load(f)

    # Load citation index
    index_path = config.get_citation_index_path(task_id)
    if not index_path.exists():
        raise FileNotFoundError(f"Citation index not found: {index_path}")
    with open(index_path, encoding="utf-8") as f:
        citation_index = json.load(f)

    # Load report_summary.json if present (dashboard source of truth for verdict)
    summary_path = config.get_report_summary_path(task_id)
    report_summary: dict[str, Any] | None = None
    report_summary_violations: list[dict[str, Any]] = []
    if summary_path.exists():
        try:
            with open(summary_path, encoding="utf-8") as f:
                report_summary = json.load(f)
            if isinstance(report_summary, dict):
                report_summary_violations = validate_report_summary(task_id, report_summary)  # type: ignore[arg-type]
            else:
                report_summary_violations = [{"reason": "report_summary.json is not an object"}]
        except json.JSONDecodeError as e:
            report_summary_violations = [
                {"reason": "Invalid JSON in report_summary.json", "error": str(e)}
            ]
    else:
        # Backward-compatible: warning only (not a hard failure)
        report_summary_violations = [
            {
                "reason": "Missing report_summary.json (dashboard verdict source of truth)",
                "path": str(summary_path),
                "severity": "warning",
            }
        ]

    # Extract data from report
    report_urls = extract_urls_from_report(report_content)
    footnotes = extract_footnotes(report_content)
    report_numbers = extract_numbers_from_report(report_content)
    report_claims = extract_claim_texts(report_content)

    # Run validations
    url_violations = validate_urls(report_urls, citation_index)
    trace_violations = validate_footnote_traces(footnotes)
    number_violations = validate_numbers(report_numbers, evidence_pack.get("evidence_chains", []))
    claim_violations = validate_claims(report_claims, evidence_pack.get("claims", []))

    # Compile results
    violations = {
        "hallucinated_urls": url_violations,
        "missing_trace_ids": trace_violations,
        "fabricated_numbers": number_violations,
        "unknown_claims": claim_violations,
        "report_summary": report_summary_violations,
    }

    # Determine pass/fail
    # Hard failures: hallucinated URLs, missing trace IDs
    # Warnings: fabricated numbers, unknown claims (may be paraphrased)
    hard_failures = len(url_violations) + len(trace_violations)
    passed = hard_failures == 0

    summary = {
        "urls_checked": len(report_urls),
        "footnotes_checked": len(footnotes),
        "numbers_checked": len(report_numbers),
        "claims_checked": len(report_claims),
        "hard_violations": hard_failures,
        "warnings": len(number_violations) + len(claim_violations) + len(report_summary_violations),
    }

    return ViolationReport(
        task_id=task_id,
        report_path=str(report_path),
        validation_timestamp=datetime.now(UTC).isoformat(),
        passed=passed,
        violations=violations,
        summary=summary,
    )


def validate_reports(config: ValidationConfig) -> dict[str, ViolationReport]:
    """
    Validate all configured reports.

    Returns dictionary mapping task_id to ViolationReport.
    """
    if not config.task_reports:
        raise ValueError("No task:report pairs specified")

    results: dict[str, ViolationReport] = {}

    for task_id, report_path in config.task_reports:
        print(f"\n=== Validating: {task_id} ===")
        print(f"  Report: {report_path}")

        try:
            result = validate_report(task_id, report_path, config)

            # Write violation report
            violation_path = config.get_violation_report_path(task_id)
            violation_path.parent.mkdir(parents=True, exist_ok=True)
            with open(violation_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"  Violation report: {violation_path}")

            # If failed, propose safe fixes for hard violations (patch proposal only)
            if not result["passed"]:
                pack_path = config.get_evidence_pack_path(task_id)
                index_path = config.get_citation_index_path(task_id)
                if pack_path.exists() and index_path.exists():
                    try:
                        evidence_pack = json.loads(pack_path.read_text(encoding="utf-8"))
                        citation_index = json.loads(index_path.read_text(encoding="utf-8"))
                        report_content = report_path.read_text(encoding="utf-8")
                        proposal = propose_suggested_fixes(
                            task_id=task_id,
                            report_path=report_path,
                            report_content=report_content,
                            violation_report=result,
                            evidence_pack=evidence_pack,
                            citation_index=citation_index,
                            config=config,
                        )
                        if proposal is not None:
                            md, patch = proposal
                            md_path = config.get_suggested_fixes_md_path(task_id)
                            md_path.write_text(md, encoding="utf-8")
                            patch_path = config.get_suggested_fixes_patch_path(task_id)
                            patch_path.write_text(patch, encoding="utf-8")
                            print(f"  Suggested fixes: {md_path}")
                            print(f"  Suggested patch: {patch_path}")
                    except Exception as e:
                        print(f"  Suggested fixes generation failed: {e}")

            # Print summary
            status = "✓ PASSED" if result["passed"] else "✗ FAILED"
            print(f"  Result: {status}")
            print(f"  Summary: {result['summary']}")

            results[task_id] = result

        except FileNotFoundError as e:
            print(f"  Error: {e}")
            results[task_id] = ViolationReport(
                task_id=task_id,
                report_path=str(report_path),
                validation_timestamp=datetime.now(UTC).isoformat(),
                passed=False,
                violations={"error": [{"message": str(e)}]},
                summary={"error": 1},
            )

    return results


# =============================================================================
# CLI Interface
# =============================================================================


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Validate report against evidence pack constraints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Validate a single report
    python -m src.report.validator --tasks task_ed3b72cf:path/to/report.md

    # Validate multiple reports
    python -m src.report.validator --tasks task_1:report1.md task_2:report2.md

    # Custom reports directory
    python -m src.report.validator --tasks task_xxx:report.md --reports-dir ./my_reports
        """,
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task:report pairs (e.g., task_id:path/to/report.md)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Reports directory (default: {DEFAULT_OUTPUT_DIR})",
    )

    parsed = parser.parse_args(args)

    # Parse task:report pairs
    task_reports: list[tuple[str, Path]] = []
    for pair in parsed.tasks:
        if ":" not in pair:
            print(f"Error: Invalid format '{pair}'. Expected task_id:report.md", file=sys.stderr)
            return 1
        task_id, report_path = pair.split(":", 1)
        task_reports.append((task_id, Path(report_path)))

    config = ValidationConfig(
        task_reports=task_reports,
        reports_dir=parsed.reports_dir,
    )

    print("=== Lyra Report Validator ===")
    print(f"Tasks: {[t[0] for t in config.task_reports]}")
    print(f"Reports dir: {config.reports_dir}")

    try:
        results = validate_reports(config)

        all_passed = all(r["passed"] for r in results.values())
        print("\n=== Validation Complete ===")
        for task_id, result in results.items():
            status = "PASSED" if result["passed"] else "FAILED"
            print(f"  {task_id}: {status}")

        return 0 if all_passed else 1

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
