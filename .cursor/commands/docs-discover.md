# docs-discover

## Purpose

Identify which project documents are relevant to the current work, and ensure they get updated at the right time.

This command is designed to be usable both:

- Standalone (run it directly), and
- As the first phase in all `wf-*` workflows, and as a required pre-commit step in `commit`.

## When to use

- You changed behavior, APIs, data contracts, or workflows and documentation likely needs to follow.
- You are preparing to ship (`wf-ship`) and want to avoid “code changed but docs didn’t”.
- You have some docs attached and want to ensure all related docs are updated, not only one file.

## Modes

This command supports two modes depending on the stage:

- **Mode 1: Discover (early stage)**: identify candidate docs and request missing attachments; do **not** edit docs yet if the change is not finalized.
- **Mode 2: Update (pre-commit stage)**: update the chosen docs and report edits; this is the “make it real” step.

## Inputs (attach as `@...`)

- Any docs you already know are relevant (`@docs/...`) (recommended)
- Requirements/spec (`@docs/REQUIREMENTS.md`) (recommended)
- Implementation plan (`@docs/IMPLEMENTATION_PLAN.md`) (optional)
- Optional: code context (`@src/...`) and/or diff summary (`git diff --stat` output)

## Discovery heuristics (how to find related docs)

Use multiple signals (don’t rely on one):

1. **Attached docs**: any `@docs/...` attached by the user are always candidates.
2. **Changed areas**: use the current diff to list touched modules/paths (e.g. `git diff --name-only`, `git diff --stat`).
3. **Repository docs search**:
   - Start under `docs/` and search for keywords (module names, feature names, API names).
   - If the repo has “system docs” (e.g. architecture, evidence, design), consider them if the change touches those areas.
4. **Workflow docs**: if you changed Cursor commands/rules, update `docs/CURSOR_RULES_COMMANDS.md`.

## Steps

1. List candidate docs (file paths) and explain why each is relevant.
2. Decide which docs must be updated vs can be skipped (with reasons).
3. If in **Mode 1 (Discover)**:
   - Ask the user to attach the missing `@docs/...` files you need.
   - Stop after discovery (no doc edits yet).
4. If in **Mode 2 (Update)**:
   - Apply doc updates (edit files) with:
     - What changed (bullets)
     - Why (if non-obvious)
     - Any user-facing impact or migration notes
   - Report what was updated and what was intentionally left unchanged.

## Output (response format)

- **Candidates**: list of doc paths + relevance signal(s)
- **Chosen docs to update**: list + rationale
- **Edits made**: per doc file, bullet summary
- **Skipped docs**: list + reason
- **Next (manual)**: usually `NEXT_COMMAND: /quality-check` or `NEXT_COMMAND: /commit` (depending on stage)

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/refactoring.mdc` (when restructuring requires doc alignment)
