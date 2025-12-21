# commit

## Purpose

Create a git commit with an English message in the project’s standard format.

## When to use

- After tests pass and you’re ready to record changes (typically after `regression-test`)
- For WIP commits, prefer `suspend`

## Policy (rules)

Follow the commit message policy here:

- `@.cursor/rules/commit-message-format.mdc`

This command intentionally avoids duplicating the policy (format/prefixes/language). Keep `commit-message-format.mdc` as the single source of truth.

## Documentation alignment (required)

Before committing, ensure documentation is aligned with the change.

- Run `NEXT_COMMAND: /docs-discover` in **Mode 2 (Update)** to update relevant docs.
- If the user did not attach any docs, `docs-discover` should still search under `docs/` and update what is relevant.
- If no docs changes are needed, explicitly state “No docs updates needed” and proceed.

## Non-interactive workflow (recommended)

```bash
git branch --show-current
git status --short

if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi

git diff --stat
git diff

## Update related docs (recommended)

Run `NEXT_COMMAND: /docs-discover` (Mode 2: Update). If it edits docs, include those edits in this commit.

git add -A
git commit -m "<message>"
```

Constraints:

- Do **not** open an interactive editor (`git commit` without `-m`).
- Keep messages **English only**.

## Output (response format)

- **Branch**: current branch name
- **Diff summary**: `git diff --stat`
- **Commit message**: final message used
- **Commit hash**: short hash
- **Last commit**: `git log -1 --oneline`
- **Next (manual)**: `NEXT_COMMAND: /merge`

## Related rules

- `@.cursor/rules/commit-message-format.mdc`