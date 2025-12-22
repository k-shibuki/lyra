# task-plan

## Purpose

Select exactly one implementation task from the given context, collect the missing information, and produce a concrete implementation plan (code + tests).

## When to use

- Start of the development workflow
- When you need to pick the next unit of work from planning documents
- After `discover-docs` to select a task from discovered documents
- Before `/implement` when you want an agreed plan (including a test plan)

## Inputs (attach as `@...`)

- User instructions describing the task to work on
- Any planning/task documents (e.g. `@docs/IMPLEMENTATION_PLAN.md`, `@docs/TODO.md`, issue files)
- `@docs/REQUIREMENTS.md` (recommended if the task is user-facing or has acceptance criteria)

**Note**: This command does not require a specific document format. It will extract tasks from whatever documents or instructions the user provides.

## Constraints

- Do not start implementing code in this step. This command produces a plan only.
- Do not run terminal commands unless the user explicitly approves (see `code-execution.mdc`).
- Do not include chapter/section numbering in the plan headings (see `integration-design.mdc`).
- Code comments (including test comments) must be in English.

## Steps

1. Review the attached documents and/or user instructions to identify candidate tasks.
2. If no documents are attached and no clear task is given, ask the user what to work on.
3. Pick **exactly one** task considering:
   - User's explicit request (highest priority)
   - Priority and dependencies (if specified in documents)
   - Logical ordering of work
4. Define acceptance criteria (1–5 bullets). If acceptance criteria are not explicit in the context, propose them and ask for confirmation.
5. Collect necessary context (prefer search over guessing):
   - Requirements/spec references (what must remain true)
   - Existing code paths, patterns, and conventions
   - Affected modules and integration points (APIs, schemas, config, CLI, scripts)
   - If adding a new parameter/field: a **propagation map** (where it is accepted, transformed, forwarded, and where it has effect)
   - Existing tests and fixtures that should be extended
   - Risks, unknowns, and how to validate them (e.g., debug script, targeted test run)
6. Produce an implementation plan that includes both:
   - Code changes (minimal set of files + intended changes)
   - Test changes (test matrix + where/how to implement tests)
7. (Optional) Create a work branch:
   - Ask the user for approval **before** creating a branch.
   - After approval, create a branch using:

```bash
feature/{short-description}
```

Or if phases are defined in the plan:

```bash
feature/phase-{N}-{M}-{short-description}
```

## Output (response format)

- **Selected task**: title + short description
- **Source**: which document(s) or user instruction the task came from
- **Rationale**: why now, dependency notes
- **Acceptance criteria**: 1–5 bullets
- **Context collected**:
  - Key docs/requirements sections
  - Key files/modules discovered (and why they matter)
  - Open questions / unknowns (if any)
- **Implementation plan (code)**:
  - Approach (high-level)
  - Files to change (path list) + intended edits (brief)
  - Integration/contract notes (if cross-module)
- **Implementation plan (tests)**:
  - Test matrix (Markdown table; include equivalence partitions + boundary cases)
  - Test files to add/update
  - Wiring/effect coverage for any new parameters/fields (how propagation is asserted so “validated-but-unused” cannot pass)
  - Notes on mocks/stubs, negative tests (>= positive tests), and exception/message assertions
- **Verification plan**:
  - What to run (recommend `/test-create`, `/test-review`, `/quality-check`, `/regression-test`)
- **Branch name**: proposed (and created if approved)

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/integration-design.mdc`
- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/quality-check.mdc`
- `@.cursor/rules/refactoring.mdc`
