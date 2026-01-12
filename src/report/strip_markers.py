#!/usr/bin/env python3
"""
Strip LLM editing markers from report files.

Removes:
- <!-- LLM_EDITABLE: name --> ... <!-- /LLM_EDITABLE -->
- <!-- LLM_READONLY --> ... <!-- /LLM_READONLY -->
 - <!-- LLM_DELETE_ONLY: name --> ... <!-- /LLM_DELETE_ONLY -->

The content inside the markers is preserved; only the HTML comment markers are removed.

Usage:
    python -m src.report.strip_markers report.md
    python -m src.report.strip_markers report.md --output clean_report.md
    python -m src.report.strip_markers report.md --inplace
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns for markers
EDITABLE_START = re.compile(r"^\s*<!-- LLM_EDITABLE: \w+ -->\s*\n?", re.MULTILINE)
EDITABLE_END = re.compile(r"^\s*<!-- /LLM_EDITABLE -->\s*\n?", re.MULTILINE)
READONLY_START = re.compile(r"^\s*<!-- LLM_READONLY -->\s*\n?", re.MULTILINE)
READONLY_END = re.compile(r"^\s*<!-- /LLM_READONLY -->\s*\n?", re.MULTILINE)
DELETE_ONLY_START = re.compile(r"^\s*<!-- LLM_DELETE_ONLY: \w+ -->\s*\n?", re.MULTILINE)
DELETE_ONLY_END = re.compile(r"^\s*<!-- /LLM_DELETE_ONLY -->\s*\n?", re.MULTILINE)

# Also remove instruction comments inside editable blocks
INSTRUCTION_COMMENT = re.compile(
    r"^\s*<!-- (?!LLM_)[^>]+-->\s*\n?",  # HTML comments that don't start with LLM_
    re.MULTILINE,
)

# LLM guidance comments (LLM-only context, not for final report)
LLM_GUIDANCE_COMMENT = re.compile(
    r"^\s*<!-- LLM_GUIDANCE:[^>]+-->\s*\n?",
    re.MULTILINE,
)


def strip_markers(content: str, *, remove_instructions: bool = True) -> str:
    """
    Remove LLM editing markers from content.

    Args:
        content: Markdown content with markers
        remove_instructions: Also remove instruction comments inside editable blocks

    Returns:
        Content with markers removed
    """
    result = content

    # Remove markers
    result = EDITABLE_START.sub("", result)
    result = EDITABLE_END.sub("", result)
    result = READONLY_START.sub("", result)
    result = READONLY_END.sub("", result)
    result = DELETE_ONLY_START.sub("", result)
    result = DELETE_ONLY_END.sub("", result)

    if remove_instructions:
        result = INSTRUCTION_COMMENT.sub("", result)
        result = LLM_GUIDANCE_COMMENT.sub("", result)

    # Clean up excessive blank lines (more than 2 consecutive)
    result = re.sub(r"\n{4,}", "\n\n\n", result)

    return result


def strip_file(
    input_path: Path,
    output_path: Path | None = None,
    *,
    inplace: bool = False,
    remove_instructions: bool = True,
) -> str:
    """
    Strip markers from a file.

    Args:
        input_path: Path to input file
        output_path: Path to output file (if None and not inplace, prints to stdout)
        inplace: Modify input file in place
        remove_instructions: Also remove instruction comments

    Returns:
        Stripped content
    """
    content = input_path.read_text(encoding="utf-8")
    stripped = strip_markers(content, remove_instructions=remove_instructions)

    if inplace:
        input_path.write_text(stripped, encoding="utf-8")
        print(f"Stripped markers from {input_path} (in-place)", file=sys.stderr)
    elif output_path:
        output_path.write_text(stripped, encoding="utf-8")
        print(f"Stripped markers: {input_path} -> {output_path}", file=sys.stderr)
    else:
        print(stripped)

    return stripped


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Strip LLM editing markers from report files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Print stripped content to stdout
    python -m src.report.strip_markers data/reports/task_xxx/report.md

    # Write to a different file
    python -m src.report.strip_markers report.md --output clean_report.md

    # Modify file in place
    python -m src.report.strip_markers report.md --inplace

    # Keep instruction comments (only remove LLM_EDITABLE/READONLY markers)
    python -m src.report.strip_markers report.md --keep-instructions
        """,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input markdown file with markers",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    parser.add_argument(
        "--inplace",
        "-i",
        action="store_true",
        help="Modify input file in place",
    )
    parser.add_argument(
        "--keep-instructions",
        action="store_true",
        help="Keep instruction comments (only remove LLM_EDITABLE/READONLY markers)",
    )

    parsed = parser.parse_args(args)

    if not parsed.input.exists():
        print(f"Error: File not found: {parsed.input}", file=sys.stderr)
        return 1

    if parsed.inplace and parsed.output:
        print("Error: Cannot use both --inplace and --output", file=sys.stderr)
        return 1

    strip_file(
        parsed.input,
        parsed.output,
        inplace=parsed.inplace,
        remove_instructions=not parsed.keep_instructions,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
