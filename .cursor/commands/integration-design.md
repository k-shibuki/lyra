# integration-design

## Purpose

Design and verify cross-module integration (interfaces, types, and data flow).

## When to use

- A feature spans multiple modules and breaks when combined
- There is a type/contract mismatch between modules
- A refactor changes public interfaces

## Inputs (attach as `@...`)

- Any context documents (requirements, specs, design docs) relevant to the integration
- The involved modules/files (`@src/...`) if known
- Any failing logs/scripts/tests (`@tests/...`) if available

**Note**: Specific document attachments are optional. This command will search the codebase to discover involved modules, existing contracts, and integration points.

## Policy (rules)

Follow the integration policy here:

- `@.cursor/rules/integration-design.mdc`

This command focuses on the concrete deliverables and how to produce them.

## Steps (deliverables)

1. Produce a Mermaid sequence diagram and save it under `docs/sequences/`.
2. Define shared data contracts as Pydantic models in `src/{module}/schemas.py`.
3. Add a debug script at `tests/scripts/debug_{feature}_flow.py` that validates the end-to-end flow.
4. Run/verify the flow and update the sequence diagram to match reality.

## Output (response format)

- **Sequence diagram**: Mermaid
- **Data contracts**: Pydantic models
- **Debug script**: runnable script + how to run it
- **Verification**: what was checked and results
- **Next (manual)**: `NEXT_COMMAND: /quality-check`

## Related rules

- `@.cursor/rules/integration-design.mdc`
- `@.cursor/rules/code-execution.mdc`
