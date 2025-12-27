"""
Extract environment-variable-like keys from:
- .env.example
- Makefile
- scripts/**/*.sh

Purpose: improve parameter registry coverage (docs-only work).
This is heuristic (shell parsing is hard), but good enough for a migration checklist.
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
RE_ASSIGN = re.compile(rf"^\s*({ENV_NAME_RE})\s*=", re.MULTILINE)
RE_DOLLAR_BRACE = re.compile(rf"\$\{{({ENV_NAME_RE})(?::[^}}]+)?\}}")
RE_DOLLAR = re.compile(rf"(?<!\$)\$({ENV_NAME_RE})\b")
RE_ENV_EXAMPLE = re.compile(rf"^\s*#?\s*({ENV_NAME_RE})\s*=", re.MULTILINE)


def _add(store: DefaultDict[str, list[Occurrence]], key: str, file: Path, line: int, kind: str) -> None:
    store[key].append(Occurrence(file=str(file), line=line, kind=kind))


def _scan_text_lines(file: Path, text: str) -> tuple[dict[str, list[Occurrence]], dict[str, list[Occurrence]]]:
    envs: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    make_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)

    # Line-based scanning for assignments/exports so we can provide line numbers.
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        m = re.match(rf"^\s*export\s+({ENV_NAME_RE})\s*=", line)
        if m:
            _add(envs, m.group(1), file, i, "export")
        m = re.match(rf"^\s*({ENV_NAME_RE})\s*=", line)
        if m:
            name = m.group(1)
            # Makefile defines lots of variables; treat separately by file suffix.
            if file.name == "Makefile":
                _add(make_vars, name, file, i, "make_assign")
            else:
                _add(envs, name, file, i, "assign")

        for var in RE_DOLLAR_BRACE.findall(line):
            _add(envs, var, file, i, "ref:${...}")
        for var in RE_DOLLAR.findall(line):
            _add(envs, var, file, i, "ref:$VAR")

    return dict(envs), dict(make_vars)


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

    all_envs: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    all_make_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)
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
            _add(all_envs, m.group(1), env_example, line, ".env.example")

    # Makefile
    makefile = workspace / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8")
        scanned_files.append(str(makefile))
        envs, make_vars = _scan_text_lines(makefile, text)
        _merge(all_envs, envs)
        _merge(all_make_vars, make_vars)

    # scripts/**/*.sh
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists():
        for sh in sorted(scripts_dir.rglob("*.sh")):
            text = sh.read_text(encoding="utf-8", errors="replace")
            scanned_files.append(str(sh))
            envs, _ = _scan_text_lines(sh, text)
            _merge(all_envs, envs)

    max_per_key = 30
    out = {
        "summary": {
            "files_scanned": len(scanned_files),
            "unique_env_like_keys": len(all_envs),
            "unique_make_vars": len(all_make_vars),
            "max_occurrences_per_key": max_per_key,
        },
        "env_like_keys": _cap(dict(all_envs), max_per_key=max_per_key),
        "make_vars": _cap(dict(all_make_vars), max_per_key=max_per_key),
    }

    out_path = out_dir / "parameter-registry.shell-make-env.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

