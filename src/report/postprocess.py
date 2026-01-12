#!/usr/bin/env python3
"""
Lyra Unified Postprocess + Validation (Stage 3).

This module is designed for an iterative, copy-forward workflow:

data/reports/{task_id}/
  drafts/
    - draft_01.md         # deterministic baseline (Stage 1-2)
    - draft_02.md         # LLM edits (Stage 4)
    - draft_03.md         # cp from draft_02.md when validation fails (LLM iterates)
    - draft_validated.md  # postprocessed + validated (Stage 3 output)
  outputs/
    - report.md           # FINAL (markers stripped) (Stage 4 finalize)
    - report_summary.json # LLM-authored sidecar (dashboard source-of-truth)
  validation_log.json     # LLM-readable JSON (info/warn/error with clear actions)

Stage 3 responsibilities:
  1) Validate edit-integrity vs draft_01.md:
     - LLM_READONLY blocks must be unchanged
     - LLM_DELETE_ONLY blocks may delete lines only (no edits)
  2) Postprocess:
     - Fill the Key Findings tables' "Cited" column from prose citations
     - Filter the References section to include only citations used in prose
     - Add Appendix D section for "available_but_unused" quality sources
  3) Validate content constraints on the postprocessed draft:
     - No hallucinated URLs (must exist in citation_index.json)
     - Footnotes referenced must exist and include page_id trace
     - No {{PENDING}} remains

All guidance comments for the LLM in draft_01.md are expected to be in English.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from src.report.evidence_pack import DEFAULT_OUTPUT_DIR, EvidencePack

Severity = Literal["info", "warn", "error"]


class LogItem(TypedDict, total=False):
    severity: Severity
    code: str
    message: str
    action: str
    location: str
    details: dict[str, Any]


@dataclass
class TaskPaths:
    task_id: str
    reports_dir: Path = DEFAULT_OUTPUT_DIR

    @property
    def root(self) -> Path:
        return self.reports_dir / self.task_id

    @property
    def evidence_pack(self) -> Path:
        return self.root / "evidence_pack.json"

    @property
    def citation_index(self) -> Path:
        return self.root / "citation_index.json"

    @property
    def drafts_dir(self) -> Path:
        return self.root / "drafts"

    @property
    def outputs_dir(self) -> Path:
        return self.root / "outputs"

    @property
    def draft_01(self) -> Path:
        return self.drafts_dir / "draft_01.md"

    @property
    def draft_02(self) -> Path:
        return self.drafts_dir / "draft_02.md"

    @property
    def draft_03(self) -> Path:
        return self.drafts_dir / "draft_03.md"

    @property
    def draft_validated(self) -> Path:
        return self.drafts_dir / "draft_validated.md"

    @property
    def report_summary(self) -> Path:
        return self.outputs_dir / "report_summary.json"

    @property
    def validation_log(self) -> Path:
        return self.root / "validation_log.json"


# ----------------------------
# Marker parsing
# ----------------------------

_RE_EDITABLE_START = re.compile(r"^\s*<!--\s*LLM_EDITABLE:\s*([A-Za-z0-9_]+)\s*-->\s*$")
_RE_EDITABLE_END = re.compile(r"^\s*<!--\s*/LLM_EDITABLE\s*-->\s*$")
_RE_READONLY_START = re.compile(r"^\s*<!--\s*LLM_READONLY\s*-->\s*$")
_RE_READONLY_END = re.compile(r"^\s*<!--\s*/LLM_READONLY\s*-->\s*$")
_RE_DELETE_ONLY_START = re.compile(r"^\s*<!--\s*LLM_DELETE_ONLY:\s*([A-Za-z0-9_]+)\s*-->\s*$")
_RE_DELETE_ONLY_END = re.compile(r"^\s*<!--\s*/LLM_DELETE_ONLY\s*-->\s*$")


class Block(TypedDict):
    kind: Literal["normal", "editable", "readonly", "delete_only"]
    name: str | None
    lines: list[str]


def _parse_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    cur_kind: Literal["normal", "editable", "readonly", "delete_only"] = "normal"
    cur_name: str | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_lines, cur_kind, cur_name
        if cur_lines:
            blocks.append({"kind": cur_kind, "name": cur_name, "lines": cur_lines})
            cur_lines = []

    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        if (
            _RE_EDITABLE_START.match(line)
            or _RE_READONLY_START.match(line)
            or _RE_DELETE_ONLY_START.match(line)
        ):
            flush()
            if m := _RE_EDITABLE_START.match(line):
                cur_kind, cur_name = "editable", m.group(1)
            elif _RE_READONLY_START.match(line):
                cur_kind, cur_name = "readonly", None
            else:
                m2 = _RE_DELETE_ONLY_START.match(line)
                cur_kind, cur_name = "delete_only", m2.group(1) if m2 else None
            # Keep marker lines as part of structure, not content
            blocks.append({"kind": "normal", "name": None, "lines": [raw_line]})
            continue

        if (
            _RE_EDITABLE_END.match(line)
            or _RE_READONLY_END.match(line)
            or _RE_DELETE_ONLY_END.match(line)
        ):
            flush()
            blocks.append({"kind": "normal", "name": None, "lines": [raw_line]})
            cur_kind, cur_name = "normal", None
            continue

        cur_lines.append(raw_line)

    flush()
    return blocks


def _is_subsequence(candidate: list[str], baseline: list[str]) -> bool:
    """True if candidate lines appear in baseline in order (deletions only)."""
    j = 0
    for line in candidate:
        while j < len(baseline) and baseline[j] != line:
            j += 1
        if j == len(baseline):
            return False
        j += 1
    return True


def validate_edit_integrity(baseline: str, candidate: str) -> list[LogItem]:
    """
    Validate that the LLM only modified EDITABLE blocks, and only deleted lines inside DELETE_ONLY blocks.
    """
    issues: list[LogItem] = []
    b_blocks = _parse_blocks(baseline)
    c_blocks = _parse_blocks(candidate)

    if len(b_blocks) != len(c_blocks):
        issues.append(
            {
                "severity": "error",
                "code": "marker_structure_mismatch",
                "message": "The report marker structure differs from the baseline draft_01.md.",
                "action": "Re-create draft_02.md by copying draft_01.md, then edit only within LLM_EDITABLE blocks (and delete lines only within LLM_DELETE_ONLY blocks).",
            }
        )
        return issues

    for i, (bb, cb) in enumerate(zip(b_blocks, c_blocks, strict=True)):
        if bb["kind"] != cb["kind"] or bb.get("name") != cb.get("name"):
            issues.append(
                {
                    "severity": "error",
                    "code": "marker_block_mismatch",
                    "message": "A marker block type/name does not match the baseline draft_01.md.",
                    "action": "Copy draft_01.md again to draft_02.md and re-apply edits without changing marker lines.",
                    "location": f"block_index={i}",
                    "details": {
                        "baseline_kind": bb["kind"],
                        "candidate_kind": cb["kind"],
                        "baseline_name": bb.get("name"),
                        "candidate_name": cb.get("name"),
                    },
                }
            )
            continue

        if bb["kind"] in ("normal", "readonly"):
            if bb["lines"] != cb["lines"]:
                issues.append(
                    {
                        "severity": "error",
                        "code": "readonly_modified",
                        "message": "Content outside LLM_EDITABLE (or within LLM_READONLY) was modified.",
                        "action": "Revert changes outside LLM_EDITABLE blocks. Only modify LLM_EDITABLE blocks.",
                        "location": f"block_index={i}",
                    }
                )
        elif bb["kind"] == "delete_only":
            if not _is_subsequence(cb["lines"], bb["lines"]):
                issues.append(
                    {
                        "severity": "error",
                        "code": "delete_only_edited",
                        "message": "A LLM_DELETE_ONLY block contains edits (not just deletions).",
                        "action": "Only delete full lines/rows inside LLM_DELETE_ONLY blocks. Do not edit remaining lines.",
                        "location": f"block_index={i}",
                        "details": {"block_name": bb.get("name")},
                    }
                )
        # editable blocks are unrestricted here

    return issues


# ----------------------------
# Citation extraction / mapping
# ----------------------------

_RE_CITE_TOKEN = re.compile(r"\{\{CITE:([A-Za-z0-9_-]+)\}\}")
_RE_NUMERIC_FOOTNOTE = re.compile(r"\[\^(\d+)\]")
_RE_PAGE_ID = re.compile(r"page_id=([^\s,\.\]]+)")


def _split_references_section(md: str) -> tuple[str, str]:
    """
    Split markdown into (before_references, references_and_after).
    If no References heading exists, returns (md, \"\").
    """
    m = re.search(r"^##\s+References\s*$", md, flags=re.MULTILINE)
    if not m:
        return md, ""
    return md[: m.start()], md[m.start() :]


def extract_used_page_ids_from_editable_blocks(md: str) -> list[str]:
    """
    Extract cite tokens from EDITABLE blocks only.

    Rationale:
      - READONLY sections may contain instructional examples (e.g., `{{CITE:page_id}}`)
      - We must not treat those examples as actual citations.
    """
    page_ids: list[str] = []
    for b in _parse_blocks(md):
        if b["kind"] != "editable":
            continue
        # Ignore HTML comments inside editable blocks (they contain instructional examples).
        text = "".join(ln for ln in b["lines"] if not ln.lstrip().startswith("<!--"))
        page_ids.extend(_RE_CITE_TOKEN.findall(text))
    return page_ids


def assign_citation_numbers(page_ids_in_order: list[str]) -> tuple[dict[str, int], dict[int, str]]:
    """
    Assign citation numbers by first appearance in prose.

    - Duplicate page_ids share the same number.
    - Numbers are 1..N (no gaps).
    """
    page_id_to_n: dict[str, int] = {}
    n_to_page_id: dict[int, str] = {}
    n = 1
    for pid in page_ids_in_order:
        if pid in page_id_to_n:
            continue
        page_id_to_n[pid] = n
        n_to_page_id[n] = pid
        n += 1
    return page_id_to_n, n_to_page_id


def footnote_number_to_page_id(def_text: str) -> str | None:
    m = _RE_PAGE_ID.search(def_text)
    return m.group(1) if m else None


def build_claim_to_pages(evidence_pack: EvidencePack) -> dict[str, set[str]]:
    claim_to_pages: dict[str, set[str]] = {}
    for ec in evidence_pack.get("evidence_chains", []):
        cid = ec.get("claim_id")
        pid = ec.get("page_id")
        if isinstance(cid, str) and isinstance(pid, str):
            claim_to_pages.setdefault(cid, set()).add(pid)
    return claim_to_pages


def _update_key_findings_tables(
    md: str,
    *,
    used_page_ids: set[str],
    page_id_to_n: dict[str, int],
    claim_to_pages: dict[str, set[str]],
) -> tuple[str, list[LogItem]]:
    """
    Replace {{PENDING}} in the Key Findings tables with claim-linked citations.
    """
    issues: list[LogItem] = []
    out_lines: list[str] = []

    for raw in md.splitlines(keepends=True):
        if "{{PENDING}}" not in raw or not raw.lstrip().startswith("|"):
            out_lines.append(raw)
            continue

        # Parse markdown table row
        parts = raw.split("|")
        if len(parts) < 8:
            out_lines.append(raw)
            continue

        claim_source_cell = parts[2].strip()  # `c_xxx`
        claim_id = claim_source_cell.strip().strip("`")
        cited_nums: list[int] = []
        for pid in claim_to_pages.get(claim_id, set()):
            if pid not in used_page_ids:
                continue
            n = page_id_to_n.get(pid)
            if n is not None:
                cited_nums.append(n)

        cited_nums = sorted(set(cited_nums))
        cited_str = "".join(f"[^{n}]" for n in cited_nums) if cited_nums else "-"
        parts[6] = f" {cited_str} "
        out_lines.append("|".join(parts))

    return "".join(out_lines), issues


def _render_reference_definition(citation: dict[str, Any], n: int) -> str:
    parts: list[str] = []

    author = citation.get("author_display")
    year = citation.get("year")
    if author:
        parts.append(str(author))
        parts.append(f", {year}." if year else ", n.d.")
    elif year:
        parts.append(f"{year}.")

    title = citation.get("title")
    if title:
        parts.append(f" {title}")

    doi = citation.get("doi")
    url = citation.get("url")
    if doi:
        parts.append(f" DOI:{doi}.")
    elif url:
        parts.append(f" {url}")

    page_id = citation.get("page_id")
    parts.append(f" Lyra: page_id={page_id}.")
    return f"[^{n}]: {''.join(parts)}"


def _replace_references_autogenerated(
    md: str, *, reference_lines: list[str]
) -> tuple[str, list[LogItem]]:
    """
    Replace the REFERENCES_AUTOGENERATED placeholder with actual numbered definitions.
    """
    issues: list[LogItem] = []
    if "<!-- REFERENCES_AUTOGENERATED -->" not in md:
        issues.append(
            {
                "severity": "warn",
                "code": "missing_references_placeholder",
                "message": "References placeholder '<!-- REFERENCES_AUTOGENERATED -->' was not found.",
                "action": "Ensure draft_01.md includes a References section with the placeholder, then copy-forward to draft_02.md.",
            }
        )
        return md, issues

    replacement = "\n".join(reference_lines) + ("\n" if reference_lines else "")
    md2 = md.replace("<!-- REFERENCES_AUTOGENERATED -->\n", replacement)
    md2 = md2.replace("<!-- REFERENCES_AUTOGENERATED -->", replacement.rstrip("\n"))
    return md2, issues


def replace_cite_tokens_with_numeric_footnotes(md: str, *, page_id_to_n: dict[str, int]) -> str:
    def repl(m: re.Match[str]) -> str:
        pid = m.group(1)
        n = page_id_to_n.get(pid)
        return f"[^{n}]" if n is not None else m.group(0)

    return _RE_CITE_TOKEN.sub(repl, md)


# ----------------------------
# Content validation (postprocessed)
# ----------------------------

_RE_URL = re.compile(r"https?://[^\s\)>\]]+")
_RE_DOI = re.compile(r"DOI:(\d+\.\d+/[^\s\]]+)")


def extract_urls(md: str) -> set[str]:
    urls: set[str] = set()
    for m in _RE_URL.finditer(md):
        urls.add(m.group(0).rstrip(".,;:"))
    for m in _RE_DOI.finditer(md):
        urls.add("DOI:" + m.group(1).rstrip(".,;:"))
    return urls


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_no_pending(md: str) -> list[LogItem]:
    if "{{PENDING}}" not in md:
        return []
    return [
        {
            "severity": "error",
            "code": "pending_placeholders_remain",
            "message": "The report still contains '{{PENDING}}' placeholders.",
            "action": "Ensure the draft has valid cite tokens {{CITE:page_id}} in prose, then re-run report-validate to fill the Cited column.",
        }
    ]


def validate_no_numeric_footnotes_in_llm_draft(md: str) -> list[LogItem]:
    """
    LLM must not generate numeric footnotes like [^1] in draft_02/draft_03.
    Stage 3 assigns numbers deterministically from {{CITE:page_id}}.
    """
    # Restrict to editable blocks so we don't flag instructional examples in READONLY sections.
    editable_text = "".join(
        ln
        for b in _parse_blocks(md)
        if b["kind"] == "editable"
        for ln in b["lines"]
        if not ln.lstrip().startswith("<!--")
    )
    found = sorted({int(n) for n in _RE_NUMERIC_FOOTNOTE.findall(editable_text)})
    if not found:
        return []
    return [
        {
            "severity": "error",
            "code": "numeric_footnotes_in_llm_stage",
            "message": f"Numeric citations like [^N] were found in prose: {found}",
            "action": "Replace all numeric citations with cite tokens {{CITE:page_id}} copied from the Citable Source Catalog, then re-run report-validate.",
        }
    ]


def validate_cite_tokens(
    *, used_page_ids_in_order: list[str], allowed_page_ids: set[str]
) -> list[LogItem]:
    issues: list[LogItem] = []
    unknown = sorted({pid for pid in used_page_ids_in_order if pid not in allowed_page_ids})
    if unknown:
        issues.append(
            {
                "severity": "error",
                "code": "unknown_cite_token",
                "message": "Cite tokens reference page_id values not present in the Citable Source Catalog.",
                "action": "Use only {{CITE:page_id}} values listed in the Citable Source Catalog (draft_01.md), then re-run report-validate.",
                "details": {"unknown_page_ids": unknown},
            }
        )
    return issues


def validate_urls_in_graph(md: str, citation_index: dict[str, Any]) -> list[LogItem]:
    allowed = set(citation_index.keys())
    urls = extract_urls(md)
    issues: list[LogItem] = []
    for url in sorted(urls):
        # Allow DOI references and doi.org URLs (treated as in-graph lookups in Lyra workflow)
        if url.startswith("DOI:") or "doi.org" in url:
            continue

        normalized = url.rstrip("/")
        is_valid = False
        for a in allowed:
            a_norm = a.rstrip("/")
            if normalized.startswith(a_norm) or a_norm.startswith(normalized):
                is_valid = True
                break

        if not is_valid:
            issues.append(
                {
                    "severity": "error",
                    "code": "hallucinated_url",
                    "message": f"URL not found in citation_index.json: {url}",
                    "action": "Remove the URL or cite only in-graph sources listed in citation_index.json.",
                }
            )
    return issues


def validate_report_summary_json(report_summary_path: Path, task_id: str) -> list[LogItem]:
    """
    outputs/report_summary.json is the dashboard source-of-truth.
    We validate its presence and basic schema.
    """
    from src.report.validator import validate_report_summary  # lightweight validation

    if not report_summary_path.exists():
        return [
            {
                "severity": "error",
                "code": "missing_report_summary",
                "message": "Missing outputs/report_summary.json (dashboard verdict source-of-truth).",
                "action": "Write outputs/report_summary.json for this task (Stage 4) and re-run report-validate.",
            }
        ]

    try:
        obj = json.loads(report_summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [
            {
                "severity": "error",
                "code": "invalid_report_summary_json",
                "message": "outputs/report_summary.json is not valid JSON.",
                "action": "Fix JSON syntax in outputs/report_summary.json and re-run report-validate.",
                "details": {"error": str(e)},
            }
        ]

    if not isinstance(obj, dict):
        return [
            {
                "severity": "error",
                "code": "report_summary_not_object",
                "message": "outputs/report_summary.json must be a JSON object.",
                "action": "Rewrite outputs/report_summary.json as an object matching report_summary_v1 schema.",
            }
        ]

    violations = validate_report_summary(task_id, obj)  # type: ignore[arg-type]
    items: list[LogItem] = []
    for v in violations:
        items.append(
            {
                "severity": "error",
                "code": "invalid_report_summary",
                "message": v.get("reason", "Invalid outputs/report_summary.json"),
                "action": "Fix outputs/report_summary.json fields (task_id/verdict/verdict_rationale) and re-run report-validate.",
                "details": v,
            }
        )
    return items


def info_evidence_chain_presence(
    *, used_page_ids: set[str], claim_to_pages: dict[str, set[str]]
) -> list[LogItem]:
    # Info-only: we don't attempt semantic support/refute mapping.
    all_pages = set().union(*claim_to_pages.values()) if claim_to_pages else set()
    issues: list[LogItem] = []
    for pid in sorted(used_page_ids):
        if pid not in all_pages:
            issues.append(
                {
                    "severity": "info",
                    "code": "cited_page_not_in_evidence_chains",
                    "message": f"Cited page_id={pid} does not appear in evidence_chains.",
                    "action": "If this citation is intended as evidence, consider citing a source that is linked via evidence_chains for the relevant claims.",
                }
            )
    return issues


def _extract_catalog_entries(md: str) -> dict[str, str]:
    """
    Parse `## Citable Source Catalog` table.

    Expected row shape:
      | `page_id` | source_str |
    """
    entries: dict[str, str] = {}
    m = re.search(r"^##\s+Citable Source Catalog\s*$", md, flags=re.MULTILINE)
    if not m:
        return entries
    start = m.end()
    next_h = re.search(r"^##\s+", md[start:], flags=re.MULTILINE)
    end = start + (next_h.start() if next_h else len(md[start:]))
    section = md[start:end]
    for ln in section.splitlines():
        if not ln.strip().startswith("|"):
            continue
        # Skip header/separator
        if "page_id" in ln or "---" in ln:
            continue
        parts = [p.strip() for p in ln.strip().strip("|").split("|")]
        if len(parts) < 2:
            continue
        pid_cell = parts[0]
        if pid_cell.startswith("`") and pid_cell.endswith("`"):
            pid = pid_cell.strip("`")
            entries[pid] = parts[1]
    return entries


def _append_available_but_unused(md: str, *, baseline: str, used_page_ids: set[str]) -> str:
    """
    Add a subsection under Appendix D listing quality sources not cited in prose.
    We derive the list from the Citable Source Catalog present in draft_01.md.
    """
    catalog = _extract_catalog_entries(baseline)
    unused_pids = sorted([pid for pid in catalog.keys() if pid not in used_page_ids])

    if not unused_pids:
        return md

    # Insert after "## Appendix D" heading if present; otherwise append at end.
    insert_point = re.search(r"^##\s+Appendix D:.*$", md, flags=re.MULTILINE)
    if not insert_point:
        return (
            md
            + "\n\n## Appendix D: Available but unused sources\n\n_(No insertion point found; appended)_\n"
        )

    # Find end of Appendix D section (before next ## heading or EOF)
    start = insert_point.end()
    next_h = re.search(r"^##\s+", md[start:], flags=re.MULTILINE)
    end = start + (next_h.start() if next_h else len(md[start:]))

    section = md[start:end]
    addition_lines = []
    addition_lines.append("")
    addition_lines.append("<!-- LLM_READONLY -->")
    addition_lines.append("")
    addition_lines.append("### Available but unused sources")
    addition_lines.append("")
    addition_lines.append(
        "The following sources were available (quality-filtered) but not cited in the prose:"
    )
    addition_lines.append("")
    addition_lines.append("| page_id | Source | Reason |")
    addition_lines.append("|---------|--------|--------|")
    for pid in unused_pids:
        src = catalog.get(pid, "")
        addition_lines.append(f"| `{pid}` | {src} | available_but_unused |")
    addition_lines.append("")
    addition_lines.append("<!-- /LLM_READONLY -->")
    addition_lines.append("")

    new_section = section + "\n".join(addition_lines)
    return md[:start] + new_section + md[end:]


def process_task(task_id: str, reports_dir: Path) -> tuple[bool, list[LogItem]]:
    paths = TaskPaths(task_id=task_id, reports_dir=reports_dir)
    logs: list[LogItem] = []

    if not paths.draft_01.exists():
        return False, [
            {
                "severity": "error",
                "code": "missing_draft_01",
                "message": f"Missing baseline draft_01.md: {paths.draft_01}",
                "action": 'Run: make report TASKS="task_id" to generate deterministic artifacts.',
            }
        ]

    candidate_path = paths.draft_03 if paths.draft_03.exists() else paths.draft_02
    if not candidate_path.exists():
        return False, [
            {
                "severity": "error",
                "code": "missing_draft_02",
                "message": f"Missing LLM draft (draft_02.md): {paths.draft_02}",
                "action": "Copy drafts/draft_01.md to drafts/draft_02.md and edit only within LLM_EDITABLE blocks.",
            }
        ]

    baseline = paths.draft_01.read_text(encoding="utf-8")
    candidate = candidate_path.read_text(encoding="utf-8")

    # 1) Edit-integrity
    integrity_issues = validate_edit_integrity(baseline, candidate)
    logs.extend(integrity_issues)
    if any(i["severity"] == "error" for i in integrity_issues):
        # Create draft_03.md only on first failure
        if candidate_path == paths.draft_02 and not paths.draft_03.exists():
            paths.draft_03.parent.mkdir(parents=True, exist_ok=True)
            paths.draft_03.write_text(candidate, encoding="utf-8")
            logs.append(
                {
                    "severity": "info",
                    "code": "created_draft_03",
                    "message": "Created drafts/draft_03.md for iterative fixes.",
                    "action": "Apply minimal edits to drafts/draft_03.md (do not regenerate from scratch), then re-run report-validate.",
                }
            )
        return False, logs

    # Load evidence + citation index
    if not paths.evidence_pack.exists() or not paths.citation_index.exists():
        logs.append(
            {
                "severity": "error",
                "code": "missing_inputs",
                "message": "Missing evidence_pack.json or citation_index.json.",
                "action": 'Run: make report TASKS="task_id" to regenerate deterministic artifacts.',
            }
        )
        return False, logs

    evidence_pack: EvidencePack = load_json(paths.evidence_pack)
    citation_index = load_json(paths.citation_index)

    # Validate outputs/report_summary.json presence + schema (required for dashboard)
    logs.extend(validate_report_summary_json(paths.report_summary, task_id))

    # 2) Postprocess: fill Cited + filter References + Appendix D
    logs.extend(validate_no_numeric_footnotes_in_llm_draft(candidate))

    used_page_ids_in_order = extract_used_page_ids_from_editable_blocks(candidate)
    used_page_ids_set = set(used_page_ids_in_order)
    allowed_page_ids = set(_extract_catalog_entries(baseline).keys())
    logs.extend(
        validate_cite_tokens(
            used_page_ids_in_order=used_page_ids_in_order, allowed_page_ids=allowed_page_ids
        )
    )

    page_id_to_n, n_to_page_id = assign_citation_numbers(used_page_ids_in_order)
    updated = replace_cite_tokens_with_numeric_footnotes(candidate, page_id_to_n=page_id_to_n)

    # Build reference definitions from evidence_pack.citations (traceable)
    citation_by_page: dict[str, dict[str, Any]] = {
        c.get("page_id"): cast(dict[str, Any], c)
        for c in evidence_pack.get("citations", [])
        if isinstance(c, dict)
    }
    reference_lines: list[str] = []
    for n in sorted(n_to_page_id.keys()):
        pid = n_to_page_id[n]
        c = citation_by_page.get(pid)
        if not c:
            logs.append(
                {
                    "severity": "error",
                    "code": "missing_citation_metadata",
                    "message": f"Missing citation metadata for page_id={pid} in evidence_pack.citations.",
                    "action": "Regenerate evidence_pack.json (make report) or cite only sources present in the Citable Source Catalog.",
                }
            )
            continue
        reference_lines.append(_render_reference_definition(c, n))

    updated, repl_issues = _replace_references_autogenerated(
        updated, reference_lines=reference_lines
    )
    logs.extend(repl_issues)

    # Even if footnotes are missing, continue to produce draft_validated for inspection.
    claim_to_pages = build_claim_to_pages(evidence_pack)
    updated, _ = _update_key_findings_tables(
        updated,
        used_page_ids=used_page_ids_set,
        page_id_to_n=page_id_to_n,
        claim_to_pages=claim_to_pages,
    )
    updated = _append_available_but_unused(
        updated, baseline=baseline, used_page_ids=used_page_ids_set
    )

    # 3) Validate postprocessed content constraints
    logs.extend(validate_no_pending(updated))
    logs.extend(validate_urls_in_graph(updated, citation_index))
    remaining_in_editable = extract_used_page_ids_from_editable_blocks(updated)
    if remaining_in_editable:
        logs.append(
            {
                "severity": "error",
                "code": "cite_tokens_remaining",
                "message": "Cite tokens '{{CITE:...}}' remain in editable prose after postprocess.",
                "action": "Ensure all cite tokens match page_id values in the Citable Source Catalog, then re-run report-validate.",
                "details": {"remaining_page_ids": sorted(set(remaining_in_editable))},
            }
        )
    logs.extend(
        info_evidence_chain_presence(used_page_ids=used_page_ids_set, claim_to_pages=claim_to_pages)
    )

    # Best-effort numeric sanity (warning-level; prose can include extra domain context)
    try:
        from src.report.validator import extract_numbers_from_report, validate_numbers

        report_numbers = extract_numbers_from_report(updated)
        evidence_chains = cast(list[dict[str, Any]], evidence_pack.get("evidence_chains", []))
        num_violations = validate_numbers(report_numbers, evidence_chains)
        for v in num_violations:
            logs.append(
                {
                    "severity": "warn",
                    "code": "fabricated_numbers",
                    "message": v.get("reason", "Potential fabricated number in prose."),
                    "action": "If this number is not in evidence_pack, remove it or qualify it as context (without presenting it as extracted evidence).",
                    "details": v,
                }
            )
    except Exception as e:
        logs.append(
            {
                "severity": "info",
                "code": "number_validation_skipped",
                "message": "Numeric validation was skipped due to an internal error.",
                "action": "You can ignore this if other checks pass; otherwise rerun after fixing the error.",
                "details": {"error": str(e)},
            }
        )

    # Write validated draft if no errors
    has_errors = any(i["severity"] == "error" for i in logs)
    if not has_errors:
        paths.draft_validated.parent.mkdir(parents=True, exist_ok=True)
        paths.draft_validated.write_text(updated, encoding="utf-8")
        logs.append(
            {
                "severity": "info",
                "code": "wrote_draft_validated",
                "message": f"Wrote postprocessed draft: {paths.draft_validated}",
                "action": 'Run: make report-finalize TASKS="task_id" to generate outputs/report.md (markers stripped).',
            }
        )
    else:
        # Ensure draft_03 exists for iterative fixes
        if not paths.draft_03.exists():
            paths.draft_03.parent.mkdir(parents=True, exist_ok=True)
            paths.draft_03.write_text(candidate, encoding="utf-8")
            logs.append(
                {
                    "severity": "info",
                    "code": "created_draft_03",
                    "message": "Created drafts/draft_03.md for iterative fixes.",
                    "action": "Apply minimal edits to drafts/draft_03.md, then re-run report-validate.",
                }
            )

    return (not has_errors), logs


def write_validation_log(path: Path, task_id: str, items: list[LogItem]) -> None:
    payload = {
        "schema_version": "validation_log_v1",
        "task_id": task_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "info": sum(1 for i in items if i.get("severity") == "info"),
            "warn": sum(1 for i in items if i.get("severity") == "warn"),
            "error": sum(1 for i in items if i.get("severity") == "error"),
        },
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lyra unified postprocess + validate (Stage 3)")
    parser.add_argument("--tasks", nargs="+", required=True, help="Task IDs to process")
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Reports directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args(argv)

    exit_code = 0
    for task_id in args.tasks:
        ok, items = process_task(task_id, args.reports_dir)
        paths = TaskPaths(task_id=task_id, reports_dir=args.reports_dir)
        paths.validation_log.parent.mkdir(parents=True, exist_ok=True)
        write_validation_log(paths.validation_log, task_id, items)
        if not ok:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
