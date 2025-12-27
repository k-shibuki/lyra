"""
Extract 'stringly-typed' parameter keys from Python source code.

This is intentionally for *list refinement* only (docs scope):
- Dict subscription keys: foo["bar"]
- Dict get keys: foo.get("bar")
- Dict literal keys: {"bar": ...}
- Environment variables: os.getenv("NAME"), os.environ.get("NAME"), os.environ["NAME"]

Outputs JSON files under docs/archive/ for human triage.

Important:
- We keep output size manageable by storing only a *sample* of occurrences per key,
  but we also store full counts and full file coverage (unique file list) so that
  analysis does not become biased by sampling.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict
from collections import defaultdict


@dataclass(frozen=True)
class Occurrence:
    file: str
    line: int
    kind: str


def _is_os_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class KeyVisitor(ast.NodeVisitor):
    def __init__(self, file: Path) -> None:
        self.file = file
        self.string_keys: DefaultDict[str, list[Occurrence]] = defaultdict(list)
        self.env_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)

    def _add(self, store: DefaultDict[str, list[Occurrence]], key: str, node: ast.AST, kind: str) -> None:
        lineno = getattr(node, "lineno", 0) or 0
        store[key].append(Occurrence(file=str(self.file), line=lineno, kind=kind))

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        # foo["bar"]
        key = _const_str(node.slice)
        if key is not None:
            self._add(self.string_keys, key, node, kind="subscript")

        # os.environ["NAME"]
        # Match: Attribute(value=Name('os'), attr='environ')[...]
        if isinstance(node.value, ast.Attribute) and node.value.attr == "environ" and _is_os_name(node.value.value):
            env = _const_str(node.slice)
            if env is not None:
                self._add(self.env_vars, env, node, kind="os.environ[]")

        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        # foo.get("bar")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            key = _const_str(node.args[0])
            if key is not None:
                self._add(self.string_keys, key, node, kind=".get()")

        # os.getenv("NAME")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "getenv" and _is_os_name(node.func.value) and node.args:
            env = _const_str(node.args[0])
            if env is not None:
                self._add(self.env_vars, env, node, kind="os.getenv()")

        # os.environ.get("NAME")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and _is_os_name(node.func.value.value)
            and node.args
        ):
            env = _const_str(node.args[0])
            if env is not None:
                self._add(self.env_vars, env, node, kind="os.environ.get()")

        return self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> Any:
        # {"bar": ...}
        for k in node.keys:
            key = _const_str(k)
            if key is not None:
                self._add(self.string_keys, key, node, kind="dict_literal")
        return self.generic_visit(node)


def _cap_occurrences(d: dict[str, list[Occurrence]], max_per_key: int) -> dict[str, list[dict[str, Any]]]:
    """
    Return a bounded sample of occurrences per key.

    NOTE: Sampling is only for size. Full counts & file coverage are stored separately.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for k, occs in d.items():
        trimmed = occs[:max_per_key]
        out[k] = [o.__dict__ for o in trimmed]
    return out


def _key_stats(d: dict[str, list[Occurrence]]) -> dict[str, dict[str, Any]]:
    """
    Summarize each key without losing file coverage.
    """
    stats: dict[str, dict[str, Any]] = {}
    for k, occs in d.items():
        files = sorted({o.file for o in occs})
        stats[k] = {
            "occurrences": len(occs),
            "unique_files": len(files),
            "files": files,
        }
    return stats


def main() -> None:
    workspace = Path("/workspace")
    targets = [workspace / "src", workspace / "tests"]
    py_files: list[Path] = []
    for t in targets:
        if t.exists():
            py_files.extend(sorted(t.rglob("*.py")))

    all_string_keys: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    all_env_vars: DefaultDict[str, list[Occurrence]] = defaultdict(list)

    parse_failures: list[str] = []

    for f in py_files:
        try:
            text = f.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(f))
        except Exception:
            parse_failures.append(str(f))
            continue

        v = KeyVisitor(f)
        v.visit(tree)
        for k, occs in v.string_keys.items():
            all_string_keys[k].extend(occs)
        for k, occs in v.env_vars.items():
            all_env_vars[k].extend(occs)

    # Deterministic ordering
    string_keys_sorted = dict(sorted(all_string_keys.items(), key=lambda kv: kv[0]))
    env_vars_sorted = dict(sorted(all_env_vars.items(), key=lambda kv: kv[0]))

    out_dir = workspace / "docs" / "archive"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep JSON size manageable (sampling only; full stats stored separately)
    max_per_key = 20
    out = {
        "summary": {
            "python_files_scanned": len(py_files),
            "parse_failures": len(parse_failures),
            "unique_string_keys": len(string_keys_sorted),
            "unique_env_vars": len(env_vars_sorted),
            "max_occurrences_per_key": max_per_key,
        },
        "parse_failure_files": parse_failures,
        "string_key_stats": _key_stats(string_keys_sorted),
        "env_var_stats": _key_stats(env_vars_sorted),
        "string_keys": _cap_occurrences(string_keys_sorted, max_per_key=max_per_key),
        "env_vars": _cap_occurrences(env_vars_sorted, max_per_key=max_per_key),
    }

    out_path = out_dir / "parameter-registry.code-string-keys.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Convenience: env vars only
    env_only_path = out_dir / "parameter-registry.env-vars.json"
    env_only_path.write_text(
        json.dumps(
            {
                "summary": out["summary"],
                "env_vars": out["env_vars"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote {out_path}")
    print(f"wrote {env_only_path}")


if __name__ == "__main__":
    main()

