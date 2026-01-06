# merge

## Purpose

Merge the work branch into `main` (non-interactive) and confirm the result.

## When to use

- After `commit` and successful quality/tests
- As the final merge step before `push`

## Inputs

- Work branch name to merge (required)
- Merge strategy: normal or squash (see below)

## Merge strategy selection

| Source | Commit count | Strategy | Rationale |
|--------|-------------|----------|-----------|
| Local development | 1-5 focused commits | Normal merge | Preserves atomic history |
| Cloud agent (Claude Code, Cursor) | Many micro-commits | **Squash merge** | Consolidates noise |
| Mixed/uncertain | Check with `git log` | Case-by-case | Review commit quality first |

**Decision heuristic**:

```bash
# Check commit count and quality
git log main..<branch> --oneline
```

- If commits are well-organized (2-5, each meaningful) → normal merge
- If commits are micro-commits (10+, or "wip", "fix typo" chains) → squash merge

## Normal merge (preserves history)

```bash
git checkout main
git merge --no-edit <branch-name>
```

## Squash merge (consolidates commits)

Use when the branch has many micro-commits (typical of cloud agents):

```bash
git checkout main
git merge --squash <branch-name>
# Creates a single staged change; requires explicit commit
git commit -m "<type>: <description>"
```

**Important**: After `--squash`, you must run `git commit` with a proper message.

## Constraints

- Use non-interactive git flags (`--no-edit`, `--no-pager`) to avoid hangs.
- For squash merge, write a consolidated commit message following `commit-message-format.mdc`.

## Output (response format)

- **Merged branch**: name + merge strategy used (normal/squash)
- **Merge result**: success/conflicts
- **Commit(s)**: resulting commit hash(es)
- **Notes**: any conflicts and how they were resolved (if applicable)
