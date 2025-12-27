"""
Classify Tier-1 "stringly-typed keys" extracted from Python AST.

Input:
  - docs/archive/parameter-registry.code-string-keys.json

Output (docs-only artifacts for planning):
  - docs/archive/parameter-registry.tier1-classification.json
  - docs/archive/parameter-registry.tier1-contract-keys.json

Goal:
  Separate likely *contract keys* (JSON/dict interface keys worth normalizing)
  from obvious *data values* (HTTP headers, URL paths, human text literals, etc.).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KeyInfo:
    key: str
    occurrences: int
    files: int
    classes: list[str]
    reason: str
    priority: str  # high|medium|low
    normalization_policy: str  # normalize|keep|review


SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
TITLE_HEADER_RE = re.compile(r"^[A-Z][A-Za-z0-9]*(?:-[A-Z][A-Za-z0-9]*)+$")  # e.g. User-Agent

# Some common HTTP header keys without hyphen, seen as dict literal keys
HTTP_HEADER_NAMES = {
    "Accept",
    "Authorization",
    "Cookie",
    "Referer",
    "Origin",
    "Host",
    "Connection",
    "User-Agent",
    "Accept-Language",
    "Accept-Encoding",
    "Cache-Control",
    "If-Modified-Since",
    "If-None-Match",
    "Content-Type",
    "Content-Length",
    "Sec-Fetch-Mode",
    "Sec-Fetch-Site",
    "Sec-Fetch-User",
    "Sec-Fetch-Dest",
}

PARAM_TOKENS = {
    "confidence",
    "score",
    "weight",
    "threshold",
    "timeout",
    "ttl",
    "limit",
    "qps",
    "ratio",
    "count",
    "retries",
    "retry",
    "delay",
    "interval",
    "budget",
    "max",
    "min",
    "top_k",
    "top_p",
    "temperature",
    "status",
    "label",
}

INTERFACE_PATH_HINTS = (
    "/src/mcp/",
    "/src/storage/",
    "/src/research/",
    "/src/report/",
)


def _has_non_ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _looks_like_url_or_path(k: str) -> bool:
    return k.startswith("/") or "://" in k or k.startswith("http") or k.startswith("www.")


def _looks_like_mime(k: str) -> bool:
    return "/" in k and " " not in k and k.count("/") == 1 and len(k) <= 60


def _tokenize(k: str) -> list[str]:
    # crude tokenization for snake_case keys
    if "_" in k:
        return [t for t in k.split("_") if t]
    return []


def _path_kind(file_path: str) -> str:
    if "/src/" not in file_path and "/tests/" in file_path:
        return "tests"
    if "/src/mcp/" in file_path:
        return "mcp"
    if "/src/storage/" in file_path:
        return "storage"
    if "/src/research/" in file_path:
        return "research"
    if "/src/report/" in file_path:
        return "report"
    if "/src/crawler/" in file_path:
        return "crawler"
    if "/src/search/" in file_path:
        return "search"
    if "/src/filter/" in file_path:
        return "filter"
    if "/src/ml_server/" in file_path or "/src/ml_client" in file_path:
        return "ml"
    return "src_other"


def classify_key(key: str, occs_sample: list[dict[str, Any]], file_list: list[str], occurrences: int) -> KeyInfo:
    """
    Classify a key using:
    - occs_sample: bounded sample occurrences (for a representative path hint)
    - file_list: full unique file coverage
    - occurrences: full occurrence count
    """
    files = len(file_list)
    file_kinds = {_path_kind(f) for f in file_list}

    classes: list[str] = []

    # Hard excludes: obvious data literals
    if _has_non_ascii(key):
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=["data_literal"],
            reason="non-ascii literal (likely data value, not a parameter key)",
            priority="low",
            normalization_policy="keep",
        )

    if _looks_like_url_or_path(key):
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=["url_or_path"],
            reason="looks like URL/path literal",
            priority="low",
            normalization_policy="keep",
        )

    if _looks_like_mime(key):
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=["mime_or_content_type"],
            reason="looks like MIME/content-type literal",
            priority="low",
            normalization_policy="keep",
        )

    if key in HTTP_HEADER_NAMES or TITLE_HEADER_RE.match(key):
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=["http_header_key"],
            reason="HTTP header key (protocol surface; do not normalize)",
            priority="low",
            normalization_policy="keep",
        )

    # Candidate contract keys
    is_snake = bool(SNAKE_RE.match(key))
    is_camel = bool(CAMEL_RE.match(key))

    if not (is_snake or is_camel):
        # Examples: punctuation, mixed symbols, etc.
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=["data_literal"],
            reason="not snake_case/camelCase; likely literal data or external field",
            priority="low",
            normalization_policy="keep",
        )

    classes.append("contract_key")
    if is_snake:
        classes.append("snake_case")
    if is_camel and not is_snake:
        classes.append("camel_case")

    toks = set(_tokenize(key))
    if any(t in PARAM_TOKENS for t in toks) or any(key.endswith(f"_{t}") for t in PARAM_TOKENS):
        classes.append("parameterish")

    interfaceish = any(("/" + k + "/") in ("/" + "/".join(sorted(file_kinds)) + "/") for k in ["mcp", "storage", "research", "report"])
    if interfaceish or any(h in next(iter({o["file"] for o in occs_sample}), "") for h in INTERFACE_PATH_HINTS):
        classes.append("interfaceish")

    # Priority & policy
    if "parameterish" in classes and ("interfaceish" in classes or "mcp" in file_kinds or "storage" in file_kinds):
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=classes,
            reason="parameter-like key used near interface boundaries (MCP/storage/research/report)",
            priority="high",
            normalization_policy="normalize",
        )

    if "parameterish" in classes:
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=classes,
            reason="parameter-like key, but interface boundary unclear; requires review before normalization",
            priority="medium",
            normalization_policy="review",
        )

    # Generic contract keys might still matter if widely used
    if occurrences >= 20 or files >= 10:
        return KeyInfo(
            key=key,
            occurrences=occurrences,
            files=files,
            classes=classes,
            reason="widely used contract-like key; normalization depends on whether it crosses module boundaries",
            priority="medium",
            normalization_policy="review",
        )

    return KeyInfo(
        key=key,
        occurrences=occurrences,
        files=files,
        classes=classes,
        reason="likely local/internal contract key; keep unless promoted to interface contract",
        priority="low",
        normalization_policy="keep",
    )


def main() -> None:
    workspace = Path("/workspace")
    inp = workspace / "docs" / "archive" / "parameter-registry.code-string-keys.json"
    data = json.loads(inp.read_text(encoding="utf-8"))

    string_keys_sample: dict[str, list[dict[str, Any]]] = data["string_keys"]
    string_key_stats: dict[str, dict[str, Any]] = data.get("string_key_stats", {})
    classified: list[dict[str, Any]] = []

    counts = {"normalize": 0, "review": 0, "keep": 0}
    keys = sorted(set(string_keys_sample.keys()) | set(string_key_stats.keys()))
    for k in keys:
        occs_sample = string_keys_sample.get(k, [])
        st = string_key_stats.get(k) or {}
        occurrences = int(st.get("occurrences") or len(occs_sample))
        files_list = list(st.get("files") or sorted({o["file"] for o in occs_sample}))
        info = classify_key(k, occs_sample=occs_sample, file_list=files_list, occurrences=occurrences)
        counts[info.normalization_policy] += 1
        classified.append(
            {
                "key": info.key,
                "occurrences": info.occurrences,
                "files": info.files,
                "classes": info.classes,
                "reason": info.reason,
                "priority": info.priority,
                "normalization_policy": info.normalization_policy,
                "sample_occurrences": occs_sample[:5],
            }
        )

    # Sort: normalize first, then review, then keep; within by occurrences desc
    policy_order = {"normalize": 0, "review": 1, "keep": 2}
    classified.sort(key=lambda x: (policy_order[x["normalization_policy"]], -x["occurrences"], x["key"]))

    out = {
        "summary": {
            "input_unique_string_keys": len(keys),
            "policy_counts": counts,
        },
        "items": classified,
    }

    out_dir = workspace / "docs" / "archive"
    out_path = out_dir / "parameter-registry.tier1-classification.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_only = [x for x in classified if x["normalization_policy"] in ("normalize", "review")]
    contract_path = out_dir / "parameter-registry.tier1-contract-keys.json"
    contract_path.write_text(json.dumps({"summary": out["summary"], "items": contract_only}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {out_path}")
    print(f"wrote {contract_path}")
    print("policy_counts:", counts)


if __name__ == "__main__":
    main()

