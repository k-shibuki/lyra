# parser-repair

## Purpose

Repair failing HTML parsers/selectors for search engines with AI-assisted diagnostics and verification.

## When to use

- Search results suddenly become empty
- A search-engine DOM changed and CSS selectors no longer match
- Parser diagnostics indicate selector failures

## Inputs (attach as `@...`)

- `@config/search_parsers.yaml` (recommended)
- Failing debug HTML under `debug/search_html/` (recommended)
- Relevant code: `@src/search/search_parsers.py`, `@src/search/parser_diagnostics.py` (recommended)

## Key files

- Selector config: `@config/search_parsers.yaml`
- Parser implementation: `@src/search/search_parsers.py`
- Diagnostics: `@src/search/parser_diagnostics.py`

## Workflow

1. Fetch the latest failing HTML (from `debug/search_html/`).
2. Generate a diagnostics report and candidate selectors.
3. Propose a fix in YAML form.
4. Apply the fix to `config/search_parsers.yaml`.
5. Verify using engine-specific E2E scripts.

## Diagnostics commands (examples)

Analyze latest failure:

```bash
podman exec lyra python -c "
from src.search.parser_diagnostics import get_latest_debug_html, analyze_debug_html
import json

path = get_latest_debug_html()
if path:
    report = analyze_debug_html(path)
    if report:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
else:
    print('No debug HTML found')
"
```

Analyze a specific engine:

```bash
podman exec lyra python -c "
from src.search.parser_diagnostics import get_latest_debug_html, analyze_debug_html
import json

path = get_latest_debug_html('duckduckgo')
if path:
    report = analyze_debug_html(path)
    if report:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
"
```

Verify after applying changes:

```bash
podman exec lyra python tests/scripts/verify_duckduckgo_search.py
podman exec lyra python tests/scripts/verify_ecosia_search.py
podman exec lyra python tests/scripts/verify_startpage_search.py
```

## Reading the diagnostics report

| Field | Meaning |
|------|---------|
| `engine` | Engine name |
| `failed_selectors` | Which selectors failed and why |
| `candidate_elements` | Candidate elements found in the HTML |
| `suggested_fixes` | Suggested YAML fixes |
| `html_path` | Path to the debug HTML |

Candidate interpretation:

- `selector`: candidate CSS selector
- `confidence`: confidence score (0.0–1.0)
- `occurrence_count`: occurrences in the HTML
- `reason`: why it was selected

## Common failure patterns

- **Class name change**: update selectors to new class names
- **DOM structure change**: adjust selector hierarchy/relationships
- **New stable attributes** (e.g., `data-testid`): prefer them for stability

## Output (response format)

- **Diagnostics summary**: what broke and where
- **Proposed YAML patch**: minimal, explicit
- **Files changed**: list
- **Verification**: E2E results
- **Next (manual)**: `NEXT_COMMAND: /quality-check`

## Related rules

- `@.cursor/rules/code-execution.mdc`
