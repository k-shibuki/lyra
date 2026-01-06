# commit

## Purpose

Create git commit(s) with **English message(s)** in the project's standard format.

## When to use

- After tests pass and you're ready to record changes (typically after `regression-test`)
- For WIP commits, prefer `suspend`

## Policy (rules)

Follow the commit message policy here:

- `@.cursor/rules/commit-message-format.mdc`

This command intentionally avoids duplicating the policy (format/prefixes/language). Keep `commit-message-format.mdc` as the single source of truth.

## Atomic commits (recommended)

Split changes into **logically cohesive, minimal commits** when beneficial:

| Split when | Keep together when |
|------------|-------------------|
| Multiple unrelated fixes in one session | Tightly coupled changes that break if separated |
| Refactor + feature in same diff | Single logical change across multiple files |
| Docs update independent of code change | Code + its corresponding test |

**Judgment criteria**:

- Each commit should be independently meaningful and pass tests
- Prefer 2-4 focused commits over 1 large commit or 10+ micro-commits
- When in doubt, fewer commits is safer

## Documentation alignment (required)

Before committing, ensure documentation is aligned with the change.

- Update any relevant documents as needed.
- If no docs changes are needed, explicitly state "No docs updates needed" and proceed.

## Workflow

```bash
git branch --show-current
git status --short

if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi

git diff --stat
git diff
```

### Single commit (simple case)

```bash
git add -A
git commit -m "<message>"
```

### Multiple commits (when splitting)

```bash
# Commit 1: e.g., refactor
git add <specific-files-or-hunks>
git commit -m "<message-1>"

# Commit 2: e.g., feature
git add <specific-files-or-hunks>
git commit -m "<message-2>"

# ... repeat as needed
```

**Useful commands for selective staging**:

- `git add -p` — interactive hunk selection
- `git add <file>` — stage specific file
- `git diff --cached` — review staged changes before commit

## Constraints

- Do **not** open an interactive editor (`git commit` without `-m`).
- Keep messages **English only**.

## Output (response format)

- **Branch**: current branch name
- **Commits**: list of commits created (message + short hash for each)
- **Summary**: `git log --oneline -n <count>` showing the new commits

## Related rules

- `@.cursor/rules/commit-message-format.mdc`