"""
Extract operational knobs from:
- .env.example (authoritative env var surface for Lyra)
- Makefile (variables passed into recipes)
- scripts/**/*.sh (only *exported* env vars; ignore local shell variables)

Purpose: improve parameter registry coverage (docs-only work).
Key point: for parameter normalization, we only treat *externally settable* knobs as in-scope:
- Declared in `.env.example`, or
- `export VAR=...` in scripts, or
- referenced as env var in Makefile recipes (best-effort)

Local shell variables like `ACTION=...` are intentionally out of scope.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict
from collections import defaultdict


@dataclass(frozen=True)
class Occurrence:
    file: str
    line: int
    kind: str


ENV_NAME_RE = r"[A-Za-z_][A-Za-z0-9_]*"

RE_EXPORT = re.compile(rf"^\s*export\s+({ENV_NAME_RE})\s*=", re.MULTILINE)
RE_MAKE_ASSIGN = re.compile(rf"^\s*({ENV_NAME_RE})\s*[:?+]?=", re.MULTILINE)
RE_DOLLAR_BRACE = re.compile(rf"\$\{{({ENV_NAME_RE})(?::[^}}]+)?\}}")
RE_DOLLAR = re.compile(rf"(?<!\$)\$({ENV_NAME_RE})\b")
RE_ENV_EXAMPLE = re.compile(rf"^\s*#?\s*({ENV_NAME_RE})\s*=", re.MULTILINE)


def _add(store: DefaultDict[str, list[Occurrence]], key: str, file: Path, line: int, kind: str) -> None:
    store[key].append(Occurrence(file=str(file), line=line, kind=kind))


def _scan_makefile(file: Path, text: str) -> dict[str, list[Occurrence]]:
    """
    Extract variables defined in Makefile.
    Note: Many are internal Make vars; we keep them as a separate list.
    """
    make_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    for i, line in enumerate(text.splitlines(), start=1):
        m = RE_MAKE_ASSIGN.match(line)
        if m:
            _add(make_vars, m.group(1), file, i, "make_assign")
    return dict(make_vars)


def _scan_shell_exported_envs(file: Path, text: str) -> dict[str, list[Occurrence]]:
    envs: DefaultDict[str, list[Occurrence]] = defaultdict(list)

    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        m = re.match(rf"^\s*export\s+({ENV_NAME_RE})\s*=", line)
        if m:
            _add(envs, m.group(1), file, i, "export")
    return dict(envs)


def _merge(dst: DefaultDict[str, list[Occurrence]], src: dict[str, list[Occurrence]]) -> None:
    for k, occs in src.items():
        dst[k].extend(occs)


def _cap(d: dict[str, list[Occurrence]], max_per_key: int) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for k in sorted(d.keys()):
        occs = d[k][:max_per_key]
        out[k] = [o.__dict__ for o in occs]
    return out


def main() -> None:
    workspace = Path("/workspace")
    out_dir = workspace / "docs" / "archive"
    out_dir.mkdir(parents=True, exist_ok=True)

    env_surface: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    exported_envs: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    make_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    scanned_files: list[str] = []

    # .env.example
    env_example = workspace / ".env.example"
    if env_example.exists():
        text = env_example.read_text(encoding="utf-8")
        scanned_files.append(str(env_example))
        # Treat commented example lines as env var declarations too.
        for m in RE_ENV_EXAMPLE.finditer(text):
            # Approximate line number by counting newlines up to match.
            line = text.count("\n", 0, m.start()) + 1
            _add(env_surface, m.group(1), env_example, line, ".env.example")

    # Makefile
    makefile = workspace / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8")
        scanned_files.append(str(makefile))
        for k, occs in _scan_makefile(makefile, text).items():
            make_vars[k].extend(occs)

    # scripts/**/*.sh
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists():
        for sh in sorted(scripts_dir.rglob("*.sh")):
            text = sh.read_text(encoding="utf-8", errors="replace")
            scanned_files.append(str(sh))
            envs = _scan_shell_exported_envs(sh, text)
            _merge(exported_envs, envs)

    max_per_key = 30
    out = {
        "summary": {
            "files_scanned": len(scanned_files),
            "unique_env_surface_vars": len(env_surface),
            "unique_exported_env_vars": len(exported_envs),
            "unique_make_vars": len(make_vars),
            "max_occurrences_per_key": max_per_key,
        },
        "env_surface_vars": _cap(dict(env_surface), max_per_key=max_per_key),
        "exported_env_vars": _cap(dict(exported_envs), max_per_key=max_per_key),
        "make_vars": _cap(dict(make_vars), max_per_key=max_per_key),
    }

    out_path = out_dir / "parameter-registry.shell-make-env.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

