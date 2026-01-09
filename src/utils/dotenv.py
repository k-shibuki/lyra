"""Minimal .env loader for Lyra (Python runtime).

Why:
- Shell scripts already source `.env` via `scripts/common.sh`.
- Python code historically read only `os.environ`, so values in `.env` did not apply
  unless the user exported them in the shell.

Policy:
- Best-effort, no external dependency (no python-dotenv).
- Never overrides already-set environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_project_root(start: Path) -> Path:
    cur = start
    while True:
        if (cur / "pyproject.toml").exists():
            return cur
        if cur.parent == cur:
            return start  # fallback
        cur = cur.parent


def load_dotenv_if_present(*, dotenv_path: Path | None = None) -> bool:
    """Load `.env` into os.environ (best-effort).

    Rules:
    - Ignores blank lines and comments.
    - Supports optional leading `export `.
    - Supports single/double quoted values (no escape processing beyond stripping quotes).
    - Does NOT overwrite existing os.environ entries.

    Returns:
        True if a dotenv file existed and was parsed, else False.
    """
    if dotenv_path is None:
        root = _find_project_root(Path(__file__).resolve())
        dotenv_path = root / ".env"

    if not dotenv_path.exists():
        return False

    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if key in os.environ:
                continue
            if len(value) >= 2 and (
                (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
            ):
                value = value[1:-1]
            os.environ[key] = value
        return True
    except Exception:
        # Best-effort: never crash the process on dotenv parsing issues.
        return True
