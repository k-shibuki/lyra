# refactoring

## Purpose

Execute a refactor end-to-end (not just a design suggestion): scope impact, apply changes across the codebase, and verify quality.

## When to use

- You need to restructure code without changing intended behavior (or with explicitly approved behavior changes)
- A module is bloated and needs to be split into smaller modules
- You need to reshape boundaries/contracts between modules (often paired with `integration-design`)

## Inputs (attach as `@...`)

- Goal and constraints (required)
- Relevant code paths (`@src/...`) (recommended)
- Any failing tests/logs (`@tests/...`, output snippets) (recommended)
- Requirements/spec if behavior must remain aligned (`@docs/REQUIREMENTS.md`) (recommended)

## Modes (pick one)

### Mode A: Cross-module integration / contract refactor

Use when the change touches interfaces between modules, shared data shapes, or async/dataflow coordination.

- Recommended companion workflow: `NEXT_COMMAND: /integration-design`

Steps:

1. Identify involved modules and the current contract (inputs/outputs, types, error handling).
2. Define the target contract and boundary rules (what belongs where).
3. Apply changes across all impacted modules.
4. Add/adjust integration tests or debug scripts as needed.

Deliverables:

- Updated contracts/types
- Updated call sites across modules
- Verification notes (what was checked)

### Mode B: Split a bloated module (extract module)

Use when a single module/file has too many responsibilities.

Best practices:

- Extract one cohesive responsibility at a time (avoid “big bang” rewrites)
- Create a clear public API for the extracted module (small surface area)
- Prevent circular dependencies (introduce a boundary/facade if needed)
- Keep changes incremental and verifiable (small diffs, frequent checks)

Steps:

1. Choose the extraction seam (responsibility boundary) and list affected call sites.
2. Introduce a new module/package with a minimal public API.
3. Move code in small steps; keep behavior stable.
4. Update imports and call sites.
5. Delete dead code and ensure no duplicate logic remains.

Deliverables:

- New module/package (with clear API)
- Updated call sites
- Reduced size/complexity in the original module

## Standard refactoring workflow (always)

1. Impact analysis: list all files to touch (use search tools).
2. Plan: checklist per file (what changes, why).
3. Apply patches across all impacted files.
4. Verify quality (`NEXT_COMMAND: /quality-check`).
5. Summarize changes (files changed + key decisions).

## Output (response format)

- **Mode**: A or B (and why)
- **Impact scope**: file list + key contracts/boundaries
- **Plan (To-do)**: checklist with per-file tasks
- **Changes applied**: what changed, grouped by area
- **Verification**: what was run/checked
- **Next (manual)**: usually `NEXT_COMMAND: /quality-check`

## Related rules

- `@.cursor/rules/refactoring.mdc`
- `@.cursor/rules/integration-design.mdc` (especially Mode A)
- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/quality-check.mdc`
