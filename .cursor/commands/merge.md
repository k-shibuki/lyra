# merge

## Purpose

Merge the work branch into `main` (non-interactive) and confirm the result.

## When to use

- After `commit` and successful quality/tests
- As the final merge step before `push`

## Inputs

- Work branch name to merge (required)

## Non-interactive merge (recommended)

```bash
git checkout main
git merge --no-edit <branch-name>
```

Constraints:

- Use non-interactive git flags (`--no-edit`, `--no-pager`) to avoid hangs.

## Output (response format)

- **Merged branch**: name + merge result (success/conflicts)
- **Changed files**: list (if available)
- **Notes**: any conflicts and how they were resolved (if applicable)
- **Next (manual)**: `NEXT_COMMAND: /push`

## Related rules

- `@.cursor/rules/code-execution.mdc`
