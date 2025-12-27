"""
Review Tier-1 'review' keys and generate a normalization plan.

This is docs-only: it does NOT modify implementation code.

Inputs:
- docs/archive/parameter-registry.code-string-keys.json
- docs/archive/parameter-registry.tier1-contract-keys.json
- docs/archive/parameter-registry.db-columns.json
- docs/archive/parameter-registry.mcp-schema-paths.json

Outputs:
- docs/archive/parameter-registry.tier1-review-decisions.json

Design goals:
- Make an explicit decision for each Tier1 'review' key: keep|normalize|split
- Provide safe replacement guidance for rg-based migration (file-scoped, quoted keys only)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BOUNDARY_DIR_HINTS = ("/src/mcp/", "/src/storage/", "/src/research/", "/src/report/")


def _kind(path: str) -> str:
    if "/src/mcp/" in path:
        return "mcp"
    if "/src/storage/" in path:
        return "storage"
    if "/src/research/" in path:
        return "research"
    if "/src/report/" in path:
        return "report"
    if "/src/filter/" in path:
        return "filter"
    if "/src/search/" in path:
        return "search"
    if "/src/crawler/" in path:
        return "crawler"
    if "/src/ml_server/" in path or "/src/ml_client" in path:
        return "ml"
    if "/tests/" in path:
        return "tests"
    if "/src/" in path:
        return "src_other"
    return "other"


def _db_columns_set(db_cols: dict[str, list[str]]) -> set[str]:
    return {c for cols in db_cols.values() for c in cols}


def _mcp_leaf_props(mcp_paths: dict[str, list[str]]) -> set[str]:
    leafs: set[str] = set()
    for _, paths in mcp_paths.items():
        for p in paths:
            leaf = p.split(".")[-1]
            leaf = leaf.replace("[]", "")
            leafs.add(leaf)
    return leafs


def main() -> None:
    root = Path("/workspace/docs/archive")
    code_registry = json.loads((root / "parameter-registry.code-string-keys.json").read_text(encoding="utf-8"))
    code_keys_sample = code_registry["string_keys"]
    code_key_stats = code_registry.get("string_key_stats", {})
    contract = json.loads((root / "parameter-registry.tier1-contract-keys.json").read_text(encoding="utf-8"))["items"]
    db_cols = json.loads((root / "parameter-registry.db-columns.json").read_text(encoding="utf-8"))
    mcp_paths = json.loads((root / "parameter-registry.mcp-schema-paths.json").read_text(encoding="utf-8"))

    db_col_set = _db_columns_set(db_cols)
    mcp_leaf_set = _mcp_leaf_props(mcp_paths)

    review_items = [x for x in contract if x["normalization_policy"] == "review"]

    # Manual decisions for known high-risk ambiguous keys.
    # - split: must be file-scoped; never global replace.
    MANUAL: dict[str, dict[str, Any]] = {
        # This key is used in multiple semantics (timeline event confidence, decomposition confidence, legacy edge confidence, etc.)
        "confidence": {
            "decision": "split",
            "reason": "generic key with multiple semantics across modules; global replacement is unsafe",
            "replacements": [
                {
                    "when": "src/filter/evidence_graph.py evidence dicts",
                    "to": "__REMOVE__",
                    "notes": "edges.confidence is a compatibility alias (often == nli_confidence for evidence edges); remove the generic key and expose only the canonical NLI/Bayes fields",
                    "rg_scope_glob": "src/filter/evidence_graph.py",
                    "rg_patterns": [
                        "\"confidence\": edge_data.get(\"confidence\")",
                    ],
                    "expected_matches_in_scope": 3,
                },
                {
                    "when": "src/filter/claim_decomposition.py AtomicClaim serialization",
                    "to": "keep",
                    "notes": "internal decomposition confidence; does not map to llm/nli/bayes without further design",
                    "rg_scope_glob": "src/filter/claim_decomposition.py",
                    "rg_patterns": [],
                },
                {
                    "when": "src/filter/claim_timeline.py TimelineEvent serialization",
                    "to": "keep",
                    "notes": "timeline_json internal field; normalizing requires explicit JSON-column migration plan",
                    "rg_scope_glob": "src/filter/claim_timeline.py",
                    "rg_patterns": [],
                },
                {
                    "when": "src/filter/nli.py NLIModel predict output",
                    "to": "nli_edge_confidence_raw",
                    "notes": "NLI output uses generic key; normalize to producer/object specific key to avoid mixing with other confidences",
                    "rg_scope_glob": "src/filter/nli.py",
                    "rg_patterns": [
                        "\"confidence\":",
                        "result.get(\"confidence\"",
                        "prediction[\"confidence\"]",
                        "pred[\"confidence\"]",
                    ],
                },
            ],
            "rg_safety": [
                "Never do global replace of \"confidence\".",
                "If renaming, only replace quoted dict keys in a single file at a time.",
            ],
        },
        "type": {
            "decision": "split",
            "reason": "generic enum key; multiple unrelated meanings (claim_type, task type, JSON Schema keyword, etc.)",
            "replacements": [
                {
                    "when": "MCP JSON Schemas / sanitizer / server tool definitions",
                    "to": "keep",
                    "notes": "JSON Schema keyword 'type' is external spec; never rename",
                    "rg_scope_glob": "src/mcp/**",
                    "rg_patterns": [],
                },
                {
                    "when": "src/filter/claim_decomposition.py decompose-LLM output item.get(\"type\")",
                    "to": "meta_claim_label_type",
                    "notes": "ties to config/prompts/decompose.j2 output contract; rename prompt output key and parser together",
                    "rg_scope_glob": "src/filter/claim_decomposition.py",
                    "rg_patterns": [
                        "item.get(\"type\"",
                    ],
                    "expected_matches_in_scope": 1,
                },
                {
                    "when": "src/mcp/response_meta.py SecurityWarning.type",
                    "to": "keep",
                    "notes": "part of MCP meta contract; only rename under full-field normalization",
                    "rg_scope_glob": "src/mcp/response_meta.py",
                    "rg_patterns": [],
                }
            ],
            "rg_safety": [
                "Never global-replace \"type\".",
                "Do not touch JSON Schema 'type' fields.",
            ],
        },
        "status": {
            "decision": "split",
            "reason": "generic status key across tasks/jobs/domains; not a single canonical mapping",
            "replacements": [
                {
                    "when": "MCP get_status response and task lifecycle",
                    "to": "keep",
                    "notes": "aligns with DB tasks.status and MCP schema; full-field renaming requires coordinated migration",
                    "rg_scope_glob": "src/mcp/**",
                    "rg_patterns": [],
                },
                {
                    "when": "src/filter/provider.py LLMResponse.to_dict()",
                    "to": "keep",
                    "notes": "provider response contract; renaming to llm_response_status is possible but intentionally postponed",
                    "rg_scope_glob": "src/filter/provider.py",
                    "rg_patterns": [],
                },
            ],
            "rg_safety": [
                "Never global-replace \"status\".",
                "If a future full-field normalization renames it, do it per object (task_status/job_status/llm_response_status...).",
            ],
        },
    }

    # Canonical renames aligned with Tier0 signal normalization.
    SIGNAL_RENAMES: dict[str, str] = {
        "claim_confidence": "llm_claim_confidence_raw",
        "nli_confidence": "nli_edge_confidence_raw",
        "bm25_score": "rank_fragment_score_bm25",
        "embed_score": "rank_fragment_score_embed",
        "rerank_score": "rank_fragment_score_rerank",
        "final_score": "rank_fragment_score_final",
        "category_weight": "rank_fragment_weight_category",
        "expected_calibration_error": "calib_ece",
        "brier_score": "calib_brier_score_before",
        "brier_score_calibrated": "calib_brier_score_after",
    }

    decisions: list[dict[str, Any]] = []

    for item in review_items:
        key = item["key"]
        occs = code_keys_sample.get(key, [])
        st = code_key_stats.get(key) or {}
        file_list = list(st.get("files") or sorted({o["file"] for o in occs}))
        occ_count = int(st.get("occurrences") or len(occs))
        kinds = sorted({_kind(f) for f in file_list})
        boundary = any(any(h in o["file"] for h in BOUNDARY_DIR_HINTS) for o in occs)

        if key in MANUAL:
            d = {
                "key": key,
                "decision": MANUAL[key]["decision"],
                "reason": MANUAL[key]["reason"],
                "kinds": kinds,
                "occurrences": occ_count,
                "files": len(file_list),
                "replacements": MANUAL[key].get("replacements", []),
                "rg_safety": MANUAL[key].get("rg_safety", []),
            }
            decisions.append(d)
            continue

        if key in SIGNAL_RENAMES:
            decisions.append(
                {
                    "key": key,
                    "decision": "normalize",
                    "to": SIGNAL_RENAMES[key],
                    "reason": "align with Tier0 model-signal canonical naming",
                    "kinds": kinds,
                    "occurrences": occ_count,
                    "files": len(file_list),
                    "rg_safety": [
                        "Replace quoted dict keys only: [\"key\"] / .get(\"key\") / {\"key\": ...}.",
                        "Prefer file-scoped replacement (one module at a time).",
                    ],
                }
            )
            continue

        # IDs and stable identifiers should not be renamed (exception rule).
        if key.endswith("_id") or key.endswith("_at") or key in {"id", "url", "domain"}:
            decisions.append(
                {
                    "key": key,
                    "decision": "keep",
                    "reason": "identifier/timestamp field (canonical exception rule)",
                    "kinds": kinds,
                    "occurrences": occ_count,
                    "files": len(file_list),
                }
            )
            continue

        # If it matches DB column or MCP leaf property, keeping is often fine (non-signal).
        if key in db_col_set or key in mcp_leaf_set:
            decisions.append(
                {
                    "key": key,
                    "decision": "keep",
                    "reason": "already part of Tier0 DB/MCP surface; not prioritized for renaming in Tier1",
                    "kinds": kinds,
                    "occurrences": occ_count,
                    "files": len(file_list),
                }
            )
            continue

        # Boundary-used generic keys should be reviewed, not mass-normalized.
        if boundary:
            decisions.append(
                {
                    "key": key,
                    "decision": "keep",
                    "reason": "boundary-used but not a signal key; keep to avoid broad churn unless full-field normalization is approved",
                    "kinds": kinds,
                    "occurrences": occ_count,
                    "files": len(file_list),
                    "rg_safety": ["Do not global-replace this key without a full-field canonical map."],
                }
            )
            continue

        # Default: keep (likely local/internal)
        decisions.append(
            {
                "key": key,
                "decision": "keep",
                "reason": "likely internal/local key; keep unless promoted to an interface contract",
                "kinds": kinds,
                "occurrences": occ_count,
                "files": len(file_list),
            }
        )

    # Deterministic ordering: normalize, split, keep
    order = {"normalize": 0, "split": 1, "keep": 2}
    decisions.sort(key=lambda d: (order[d["decision"]], d["key"]))

    out = {
        "summary": {
            "review_keys": len(review_items),
            "decision_counts": {
                "normalize": sum(1 for d in decisions if d["decision"] == "normalize"),
                "split": sum(1 for d in decisions if d["decision"] == "split"),
                "keep": sum(1 for d in decisions if d["decision"] == "keep"),
            },
        },
        "decisions": decisions,
    }

    out_path = root / "parameter-registry.tier1-review-decisions.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out_path)
    print("decision_counts", out["summary"]["decision_counts"])


if __name__ == "__main__":
    main()

