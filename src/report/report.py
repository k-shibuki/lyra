#!/usr/bin/env python3
"""
Lyra Report Generator CLI.

Unified CLI for report generation pipeline:
- pack: Generate evidence_pack.json and citation_index.json
- draft: Generate drafts/draft_01.md from evidence_pack.json
- validate: Stage 3 unified postprocess + validate (draft_02/draft_03 → draft_validated + validation_log)
- finalize: Produce outputs/report.md (markers stripped) from drafts/draft_validated.md
- all: Run pack + draft (deterministic pipeline)

Usage:
    python -m src.report.report pack --tasks task_id1 task_id2
    python -m src.report.report draft --tasks task_id1 task_id2
    python -m src.report.report validate --tasks task_id1 task_id2
    python -m src.report.report finalize --tasks task_id1 task_id2
    python -m src.report.report all --tasks task_id1 task_id2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from src.report.evidence_pack import (
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT_DIR,
    EvidencePackConfig,
    generate_evidence_pack,
)


def _reset_task_workspace(output_dir: Path, task_id: str) -> None:
    """
    Reset task workspace for a fresh run:
      - evidence_pack.json / citation_index.json will be overwritten by Stage 1
      - drafts/ and outputs/ are deleted (if present)
      - validation_log.json is deleted (if present)
    """
    root = output_dir / task_id
    drafts_dir = root / "drafts"
    outputs_dir = root / "outputs"
    validation_log = root / "validation_log.json"

    def _rm_tree(dir_path: Path) -> None:
        if not dir_path.exists():
            return
        for p in sorted(dir_path.glob("**/*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        if dir_path.exists():
            dir_path.rmdir()

    _rm_tree(drafts_dir)
    _rm_tree(outputs_dir)
    if validation_log.exists():
        validation_log.unlink()

    drafts_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)


def cmd_pack(args: argparse.Namespace) -> int:
    """Generate evidence pack (evidence_pack.json + citation_index.json)."""
    for task_id in args.tasks:
        _reset_task_workspace(args.output_dir, task_id)

    config = EvidencePackConfig(
        db_path=args.db,
        task_ids=args.tasks,
        output_dir=args.output_dir,
        top_claims_limit=args.top_claims,
        contradictions_limit=args.contradictions,
    )

    try:
        results = generate_evidence_pack(config)
        print("\n=== Pack Generation Complete ===")
        for task_id, output_dir in results.items():
            print(f"  {task_id}:")
            print(f"    evidence_pack.json: {output_dir / 'evidence_pack.json'}")
            print(f"    citation_index.json: {output_dir / 'citation_index.json'}")
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_draft(args: argparse.Namespace) -> int:
    """Generate drafts/draft_01.md from evidence_pack.json."""
    from src.report.draft_generator import DraftConfig, generate_drafts

    config = DraftConfig(
        task_ids=args.tasks,
        reports_dir=args.output_dir,
    )

    try:
        results = generate_drafts(config)
        print("\n=== Draft Generation Complete ===")
        for task_id, draft_path in results.items():
            print(f"  {task_id}: {draft_path}")
        print("\nNext steps:")
        print("  1. Copy drafts/draft_01.md -> drafts/draft_02.md")
        print("  2. LLM edits drafts/draft_02.md (Stage 4) and writes outputs/report_summary.json")
        print(
            "  3. Validate: make report-validate TASKS='task_id' (or: python -m src.report.report validate --tasks task_id)"
        )
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Stage 3 unified postprocess + validate for drafts/draft_02.md (or draft_03.md)."""
    from src.report.postprocess import TaskPaths, process_task, write_validation_log

    ok_all = True
    for task_id in args.tasks:
        ok, items = process_task(task_id, args.output_dir)
        paths = TaskPaths(task_id=task_id, reports_dir=args.output_dir)
        paths.validation_log.parent.mkdir(parents=True, exist_ok=True)
        write_validation_log(paths.validation_log, task_id, items)
        ok_all = ok_all and ok
        status = "✓ PASSED" if ok else "✗ FAILED"
        print(f"{task_id}: {status} (log: {paths.validation_log})")

    return 0 if ok_all else 1


def cmd_finalize(args: argparse.Namespace) -> int:
    """Finalize drafts/draft_validated.md into outputs/report.md (markers stripped)."""
    from src.report.strip_markers import strip_markers

    ok_all = True
    for task_id in args.tasks:
        root = args.output_dir / task_id
        draft_validated = root / "drafts" / "draft_validated.md"
        outputs_dir = root / "outputs"
        report_md = outputs_dir / "report.md"
        report_summary = outputs_dir / "report_summary.json"

        if not draft_validated.exists():
            print(f"{task_id}: ✗ FAILED (missing drafts/draft_validated.md)", file=sys.stderr)
            ok_all = False
            continue
        if not report_summary.exists():
            print(f"{task_id}: ✗ FAILED (missing outputs/report_summary.json)", file=sys.stderr)
            ok_all = False
            continue

        outputs_dir.mkdir(parents=True, exist_ok=True)
        content = draft_validated.read_text(encoding="utf-8")
        report_md.write_text(strip_markers(content), encoding="utf-8")
        print(f"{task_id}: ✓ Wrote {report_md}")

    return 0 if ok_all else 1


def cmd_all(args: argparse.Namespace) -> int:
    """Run pack + draft (full deterministic pipeline)."""
    print("=== Stage 1: Generating Evidence Pack ===")
    pack_result = cmd_pack(args)
    if pack_result != 0:
        return pack_result

    print("\n=== Stage 2: Generating Draft Report ===")
    draft_result = cmd_draft(args)
    if draft_result != 0:
        return draft_result

    print("\n=== Pipeline Complete ===")
    print("Next steps:")
    print("  1. Copy drafts/draft_01.md -> drafts/draft_02.md")
    print("  2. LLM edits drafts/draft_02.md (Stage 4) and writes outputs/report_summary.json")
    print("  3. Validate: make report-validate TASKS='task_id'")
    print("  4. Finalize: make report-finalize TASKS='task_id'")
    print("  5. Dashboard: make report-dashboard TASKS='task_a [task_b ...]'")
    return 0


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Lyra Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  pack      Generate evidence_pack.json and citation_index.json from DB
  draft     Generate drafts/draft_01.md from evidence_pack.json
  validate  Stage 3 unified postprocess + validate
  finalize  Produce outputs/report.md (markers stripped)
  all       Run pack + draft (deterministic pipeline)

Examples:
  # Generate evidence pack for tasks
  python -m src.report.report pack --tasks task_ed3b72cf task_8f90d8f6

  # Generate draft reports
  python -m src.report.report draft --tasks task_ed3b72cf task_8f90d8f6

  # Validate (postprocess + validate) draft_02.md / draft_03.md
  python -m src.report.report validate --tasks task_ed3b72cf

  # Finalize to outputs/report.md
  python -m src.report.report finalize --tasks task_ed3b72cf

  # Full pipeline (pack + draft)
  python -m src.report.report all --tasks task_ed3b72cf
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    def add_common_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--db",
            type=Path,
            default=DEFAULT_DB_PATH,
            help=f"Path to Lyra SQLite database (default: {DEFAULT_DB_PATH})",
        )
        subparser.add_argument(
            "--output-dir",
            type=Path,
            default=DEFAULT_OUTPUT_DIR,
            help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
        )
        subparser.add_argument(
            "--top-claims",
            type=int,
            default=30,
            help="Number of top claims to extract (default: 30)",
        )
        subparser.add_argument(
            "--contradictions",
            type=int,
            default=15,
            help="Number of contradictions to extract (default: 15)",
        )

    # pack subcommand
    pack_parser = subparsers.add_parser("pack", help="Generate evidence pack from DB")
    pack_parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to process",
    )
    add_common_args(pack_parser)
    pack_parser.set_defaults(func=cmd_pack)

    # draft subcommand
    draft_parser = subparsers.add_parser("draft", help="Generate draft report from evidence pack")
    draft_parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to process",
    )
    add_common_args(draft_parser)
    draft_parser.set_defaults(func=cmd_draft)

    # validate subcommand
    validate_parser = subparsers.add_parser(
        "validate", help="Stage 3: unified postprocess + validate (draft_02/draft_03)"
    )
    validate_parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to validate (uses drafts/draft_03.md if present, else drafts/draft_02.md)",
    )
    add_common_args(validate_parser)
    validate_parser.set_defaults(func=cmd_validate)

    # finalize subcommand
    finalize_parser = subparsers.add_parser(
        "finalize", help="Finalize validated draft into outputs/report.md"
    )
    finalize_parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to finalize (reads drafts/draft_validated.md)",
    )
    add_common_args(finalize_parser)
    finalize_parser.set_defaults(func=cmd_finalize)

    # all subcommand
    all_parser = subparsers.add_parser("all", help="Run full deterministic pipeline (pack + draft)")
    all_parser.add_argument(
        "--tasks",
        nargs="+",
        required=True,
        help="Task IDs to process",
    )
    add_common_args(all_parser)
    all_parser.set_defaults(func=cmd_all)

    parsed = parser.parse_args(args)
    return cast(int, parsed.func(parsed))


if __name__ == "__main__":
    raise SystemExit(main())
