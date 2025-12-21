# merge-complete

## Purpose

Merge the work branch into `main` and produce a completion report (including updating the implementation plan).

## When to use

- After `commit` and successful quality/tests
- As the final “done” step before `push`

## Inputs (attach as `@...`)

- `@docs/IMPLEMENTATION_PLAN.md` (recommended)

## Non-interactive merge (recommended)

```bash
git checkout main
git merge --no-edit <branch-name>
```

Constraints:

- Use non-interactive git flags (`--no-edit`, `--no-pager`) to avoid hangs.

## Update the implementation plan

In `@docs/IMPLEMENTATION_PLAN.md`, mark the completed task:

- `[ ]` → `[x]`
- Add completion date if the plan format expects it

## Output (response format)

- **Merged branch**: name + merge result
- **Changed files**: list
- **Test summary**: key numbers (passed/failed/skipped) + any relevant notes
- **Plan update**: what changed in `@docs/IMPLEMENTATION_PLAN.md`
- **Next (manual)**: `NEXT_COMMAND: /push`
