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
3. If introducing new parameters/fields, create a **propagation map** (where the value is accepted, transformed, forwarded, and where it has effect).
4. Add a debug script at `tests/scripts/debug_{feature}_flow.py` that validates the end-to-end flow (including the propagation map checkpoints).
   - Prefer using an **isolated DB** so scripts do not mutate `data/lyra.db` and do not leave artifacts.
   - Utility: `src/storage/isolation.py` (`isolated_database_path`)
5. Run/verify the flow and update the sequence diagram to match reality.

## Output (response format)

- **Sequence diagram**: Mermaid
- **Data contracts**: Pydantic models
- **Propagation map** (if applicable): short table/bullets mapping boundaries and sinks
- **Debug script**: runnable script + how to run it
- **Verification**: what was checked and results

## Notes

### Execution environment

- **pytest tests**: Use `make test`, then `make test-check RUN_ID=<run_id>` (always specify `run_id` from output).
- **Debug scripts** (standalone Python): Run directly with venv Python:
  ```bash
  ./.venv/bin/python tests/scripts/debug_{feature}_flow.py
  ```
- Do **not** use system Python directly; the project uses `.venv` or Podman container.

### DB management

| Phase | Policy |
|-------|--------|
| Development (solo) | Recreate DB OK (`rm data/lyra.db` + reinitialize) |
| Post-release | Use migration (`scripts/migrate.py`) |

- Debug scripts should use `isolated_database_path()` to avoid touching `data/lyra.db`.
- pytest tests use fixtures (`test_database`) for automatic isolation.

**⚠️ Before modifying `data/lyra.db` or recreating the DB, ask the user:**

> 「現在のフェーズを確認させてください。DB作り直しOK（開発フェーズ）ですか、それとも migration 必須（リリース後）ですか？」

Do **not** assume the phase; always confirm to prevent data loss.

## Related rules

- `@.cursor/rules/integration-design.mdc`
- `@.cursor/rules/code-execution.mdc`
