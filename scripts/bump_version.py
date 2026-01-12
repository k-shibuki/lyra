#!/usr/bin/env python3
"""
Bump version in pyproject.toml and CITATION.cff.

Single source of truth: pyproject.toml
Synced files: CITATION.cff

Usage:
    python scripts/bump_version.py 0.2.0
    python scripts/bump_version.py --show  # Show current version
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Files to update with their patterns
VERSION_FILES = {
    "pyproject.toml": {
        "pattern": r'^(version\s*=\s*")[^"]+(")',
        "replacement": r"\g<1>{version}\g<2>",
    },
    "CITATION.cff": {
        "pattern": r"^(version:\s*).+$",
        "replacement": r"\g<1>{version}",
    },
}


def get_current_version() -> str:
    """Read current version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def validate_version(version: str) -> bool:
    """Validate semantic version format (X.Y.Z or X.Y.Z-suffix)."""
    pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$"
    return bool(re.match(pattern, version))


def bump_version(new_version: str, dry_run: bool = False) -> dict[str, bool]:
    """Update version in all tracked files.

    Args:
        new_version: New version string (e.g., "0.2.0")
        dry_run: If True, don't write changes

    Returns:
        Dict mapping filename to success status
    """
    results: dict[str, bool] = {}

    for filename, config in VERSION_FILES.items():
        filepath = PROJECT_ROOT / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} (not found)")
            results[filename] = False
            continue

        content = filepath.read_text()
        pattern = config["pattern"]
        replacement = config["replacement"].format(version=new_version)

        new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

        if count == 0:
            print(f"  SKIP: {filename} (pattern not found)")
            results[filename] = False
            continue

        if not dry_run:
            filepath.write_text(new_content)
            print(f"  OK: {filename}")
        else:
            print(f"  DRY-RUN: {filename} (would update)")

        results[filename] = True

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump version in pyproject.toml and CITATION.cff"
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="New version (e.g., 0.2.0). Omit to show current version.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current version and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing",
    )

    args = parser.parse_args()

    # Show current version
    if args.show or args.version is None:
        try:
            current = get_current_version()
            print(f"Current version: {current}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Validate new version
    if not validate_version(args.version):
        print(
            f"Error: Invalid version format '{args.version}'. "
            "Expected: X.Y.Z or X.Y.Z-suffix",
            file=sys.stderr,
        )
        return 1

    # Get current version for comparison
    try:
        current = get_current_version()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.version == current:
        print(f"Version is already {current}")
        return 0

    # Bump version
    print(f"Bumping version: {current} → {args.version}")
    results = bump_version(args.version, dry_run=args.dry_run)

    # Summary
    success = sum(results.values())
    total = len(results)
    print(f"\nUpdated {success}/{total} files")

    if not args.dry_run and success > 0:
        print(f"\nNext steps:")
        print(f"  git add pyproject.toml CITATION.cff")
        print(f"  git commit -m 'chore: bump version to {args.version}'")
        print(f"  git tag v{args.version}")

    return 0 if success == total else 1


if __name__ == "__main__":
    sys.exit(main())
