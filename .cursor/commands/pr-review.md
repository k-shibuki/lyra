# pr-review

## Purpose

Review a PR (or a PR-like branch) end-to-end **without depending on other Cursor commands**: gather context, inspect diff/commits, run quality checks + tests, and produce a merge/push recommendation.

Note: This workflow is independent from `wf-dev`.

## Contract (must follow)

1. Read all user-attached `@...` context first (PR description, diff, requirements).
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Determine Scenario A vs B and show evidence (commands/logs reviewed).
3. Produce a Plan-mode checklist To-do that is **self-contained** (i.e., includes the exact shell commands to run).
4. Merge/push are **always** gated behind explicit user approval (never do them automatically).
5. Do not assume other Cursor commands exist; if you mention them, they must be strictly optional.

## Inputs (ask if missing)

- PR description / intent (required)
- Target branch / PR branch name (recommended if available)
- Base branch (default: `origin/main`)
- Diff summary (file list + key changes) (required if you cannot access git)
- Requirements/acceptance criteria (`@docs/adr/`) (recommended)
- Any CI/test output (recommended)

## Branch detection patterns (important)

Treat branches starting with these prefixes as PR candidates:

- `pr`, `PR`, `pull`, `merge`, `claude`, `cursor`, `feature`

To avoid missing things:

- Always print the count of detected PR branches
- Show merge status (merged vs not merged to `origin/main`)
- Keep debug output on in scripts

## Output (response format)

### Context read

- `@...` files read
- Key acceptance criteria (bullets)

### Scenario

- Scenario: A / B
- Evidence: (bullets)

### Plan (To-do)

- [ ] ... (include purpose / inputs / done criteria per item)

Must include (at minimum):

- [ ] Confirm PR / branch state (git commands)
- [ ] Discover relevant docs and acceptance criteria (standalone; do not rely on other commands)
- [ ] Run quality checks (`make quality`)
- [ ] Run regression tests (`make test`)
- [ ] Make merge decision (with reasons)
- [ ] After approval only: merge (non-interactive `git merge --no-edit` or manual steps)
- [ ] After approval only: push (`git push origin main`)

### Next (manual)

- Provide the next concrete shell command to run (single line), but do **not** auto-run merge/push.

## Related rules

- `@.cursor/rules/code-execution.mdc`
- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/commit-message-format.mdc`

## Workflow overview

First, determine which scenario applies:

- **Scenario A (unmerged PR branches exist)**: review and merge each PR branch, then push
- **Scenario B (already merged locally, not pushed)**: validate `main` and then push `main` (no re-merge needed)

### Scenario detection

```bash
set -euo pipefail
git fetch origin

# Compare local main vs origin/main
echo "=== main vs origin/main (commits to push) ==="
git --no-pager log origin/main..main --oneline || true

# Candidate patterns: pr, PR, pull, merge, claude, cursor, feature
pattern='(pr|PR|pull|merge|claude|cursor|feature)'

echo "=== PR candidate branches (origin/*) ==="
branches=$(git for-each-ref --format='%(refname:short)' refs/remotes/origin \
  | grep -E "$pattern" \
  | grep -vE 'origin/HEAD$' || true)

if [ -z "${branches:-}" ]; then
  echo "No PR candidate branches found"
  exit 0
fi

echo "$branches"
total=$(printf '%s\n' "$branches" | wc -l | tr -d ' ')
echo "Total PR branches: $total"

echo "=== Checking merge status vs origin/main ==="
unmerged=0
while IFS= read -r branch; do
  if git log origin/main.."$branch" --oneline 2>/dev/null | head -1 > /dev/null; then
    echo "✓ $branch: Not merged to origin/main"
    unmerged=$((unmerged + 1))
  else
    echo "  $branch: Already merged to origin/main (skipped)"
  fi
done <<< "$branches"

echo "Unmerged branches: $unmerged"
```

Decision rules:

- If `git log origin/main..main` is empty and there exist unmerged PR branches → **Scenario A**
- If `git log origin/main..main` has commits and all PR branches are already merged to local `main` → **Scenario B**

### Scenario A (unmerged PR branches exist)

- Fetch PR branch(es)
- Review diff(s)
- Run quality checks (`make quality`)
- Run regression tests (`make test`)
- Decide mergeability (with reasons)
- After approval only: merge to `main`
- After approval only: push (`git push origin main`)

### Scenario B (already merged locally, not pushed)

- Validate local `main` vs `origin/main`
- Run quality checks on `main` (`make quality`)
- Run regression tests on `main` (`make test`)
- Decide whether it is safe to push
- After approval only: push `main` (`git push origin main`)

Note: In Scenario B you do not need to re-merge PR branches; validate `main` and then push.

## 1. Fetch PR branches (Scenario A only)

### 1.1 Fetch remote and list candidates

```bash
set -euo pipefail
git fetch origin
pattern='(pr|PR|pull|merge|claude|cursor|feature)'
git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -E "$pattern" | grep -vE 'origin/HEAD$'
count=$(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -E "$pattern" | grep -vE 'origin/HEAD$' | wc -l | tr -d ' ')
echo "Found $count PR candidate branches"
```

### 1.2 Review ordering (optional optimization)

Decide the review order using these priorities:

Important: include PRs that were already merged locally (still check differences vs `origin/main`).

#### Priority 1: change size (small → large)

- Rationale: smaller PRs reduce conflict risk and review time
- How: `git diff main..<branch> --stat`

#### Priority 2: commit age (old → new)

- Rationale: older PRs often unblock dependencies
- How: `git log main..<branch> --format="%ci %s" | head -1`

#### Priority 3: change type

- Preferred order: bug fixes → refactors → features → docs
- How: infer from commit message prefixes (`fix:` > `refactor:` > `feat:` > `docs:`)

#### Priority 4: dependencies

- Rationale: PRs depending on other PRs should be reviewed later
- How: infer from branch names/commit messages

#### Implementation example (script)

```bash
#!/bin/bash
# Sort PR candidates by an optimization heuristic

# 1) Sort by change size (small → large)
# Include PRs already merged locally; also compare against origin/main when needed
# Candidate patterns: pr, PR, pull, merge, claude, cursor, feature
get_pr_by_changes() {
    for branch in $(git branch -r | grep -E '(pr|PR|pull|merge|claude|cursor|feature)' | grep -v "HEAD"); do
        # Check diff vs local main (also detects PRs already merged locally)
        # If `git log main..$branch` is empty, the branch is already merged into local main
        if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            # If already merged locally, check diff vs origin/main
            if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
                continue  # skip if also merged into origin/main
            fi
            # If not merged into origin/main, treat it as “needs push”
        fi

        # Extra check: confirm if merged into origin/main via merge-base
        branch_commit=$(git rev-parse $branch 2>/dev/null)
        origin_main_commit=$(git rev-parse origin/main 2>/dev/null)
        if [ -n "$branch_commit" ] && [ -n "$origin_main_commit" ]; then
            if git merge-base --is-ancestor $branch_commit $origin_main_commit 2>/dev/null; then
                # Skip if merged into origin/main
                continue
            fi
        fi

        # Get diff stats vs main
        stat=$(git diff main..$branch --stat 2>/dev/null | tail -1)
        if [ -z "$stat" ]; then
            # If no diff vs main, fall back to origin/main
            stat=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1)
            if [ -z "$stat" ]; then
                continue
            fi
        fi

        # Extract total change count (additions + deletions)
        changes=$(echo "$stat" | awk '{print $4+$6}' | sed 's/[^0-9]//g')
        if [ -z "$changes" ] || [ "$changes" = "0" ]; then
            changes=0
        fi

        # Get commit date (ISO; prefer diff vs main)
        date=$(git log main..$branch --format="%ci" 2>/dev/null | tail -1)
        if [ -z "$date" ]; then
            # If no diff vs main, fall back to origin/main
            date=$(git log origin/main..$branch --format="%ci" 2>/dev/null | tail -1)
            if [ -z "$date" ]; then
                date="9999-12-31 00:00:00 +0000"
            fi
        fi

        # Get commit message prefix (prefer diff vs main)
        subject=$(git log main..$branch --format="%s" 2>/dev/null | head -1)
        if [ -z "$subject" ]; then
            # If no diff vs main, fall back to origin/main
            subject=$(git log origin/main..$branch --format="%s" 2>/dev/null | head -1)
        fi
        # Extract conventional-commit-like type:
        # - "fix: ..." -> fix
        # - "fix(scope): ..." -> fix
        # - "feat!: ..." -> feat
        prefix=$(echo "$subject" | sed -E 's/^([A-Za-z]+)(\([^)]*\))?!?:.*/\1/' | tr '[:upper:]' '[:lower:]')
        case "$prefix" in
            fix) priority=1 ;;
            refactor) priority=2 ;;
            feat) priority=3 ;;
            docs) priority=4 ;;
            *) priority=5 ;;
        esac

        echo "$changes|$date|$priority|$branch"
    done | sort -t'|' -k1,1n -k2,2 -k3,3n | cut -d'|' -f4
}

# Usage
get_pr_by_changes
```

#### Simple version (change size only)

```bash
# Sort PR candidates by change size (simplest)
# Include PRs already merged locally
# Candidate patterns: pr, PR, pull, merge, claude, cursor, feature
for branch in $(git branch -r | grep -E '(pr|PR|pull|merge|claude|cursor|feature)' | grep -v "HEAD"); do
    # Check diff vs local main (also detects PRs already merged locally)
    if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        # If already merged locally, check diff vs origin/main
        if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            continue  # skip if also merged into origin/main
        fi
        # If not merged into origin/main, treat it as “needs push”
    fi

    # Extra check: confirm if merged into origin/main via merge-base
    branch_commit=$(git rev-parse $branch 2>/dev/null)
    origin_main_commit=$(git rev-parse origin/main 2>/dev/null)
    if [ -n "$branch_commit" ] && [ -n "$origin_main_commit" ]; then
        if git merge-base --is-ancestor $branch_commit $origin_main_commit 2>/dev/null; then
            continue  # skip if merged into origin/main
        fi
    fi

    # Get change size vs main
    changes=$(git diff main..$branch --stat 2>/dev/null | tail -1 | awk '{print $4+$6}' | sed 's/[^0-9]//g')
    if [ -z "$changes" ]; then
        # If no diff vs main, fall back to origin/main
        changes=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1 | awk '{print $4+$6}' | sed 's/[^0-9]//g')
    fi
    echo "${changes:-0} $branch"
done | sort -n | awk '{print $2}'
```

### 1.3 Check out the PR branch

```bash
# Check out a PR branch in the chosen order
git checkout -b <pr-branch> origin/<pr-branch>
```

### 1.4 How to run the ordering (practical steps)

1. List PR candidates via `git branch -r` (include `cursor` branches).
2. Determine merge state:
   - If `git log main..<branch>` is empty, check `origin/main` diff.
   - Skip if merged into both local `main` and `origin/main`.
   - Use `git merge-base --is-ancestor <branch> origin/main` as an extra merge check.
3. Compute change size: `git diff main..<branch> --stat`
4. Compute “first commit date” for ordering: `git log main..<branch> --format="%ci" | tail -1`
5. Infer change type from commit message prefix.
6. Sort by: change size → commit age → change type.

Notes:

- Treat `cursor` branches as PR branches (Cursor Cloud Agent output).
- Even if merged locally, include PRs not pushed to `origin/main` in review scope.

## 1B. State check for already-merged PRs (Scenario B only)

If PRs are already merged into local `main` but not pushed to `origin/main`:

```bash
# Compare local main vs origin/main
git log origin/main..main --oneline
git diff origin/main..main --stat

# Check PR branches (candidate patterns: pr, PR, pull, merge, claude, cursor, feature)
pattern='(pr|PR|pull|merge|claude|cursor|feature)'
git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -E "$pattern" | grep -vE 'origin/HEAD$' | while IFS= read -r branch; do
    if ! git log origin/main.."$branch" --oneline 2>/dev/null | head -1 > /dev/null; then
        echo "$branch: Already merged to origin/main"
    else
        if ! git log main.."$branch" --oneline 2>/dev/null | head -1 > /dev/null; then
            echo "$branch: Merged to local main, but not pushed to origin/main"
        fi
    fi
done
```

Important: in this scenario you do not re-merge PRs. Validate local `main` (quality + tests) and then push to `origin/main`.

## 2. Code review (Scenario A only)

### Review checklist

| Category | What to check |
|---------|---------------|
| **Change overview** | files changed, diff size |
| **Code quality** | readability, naming, duplication |
| **Spec alignment** | aligns with ADRs (`docs/adr/`) |
| **Tests** | tests exist, coverage signals |
| **Security** | authn/authz, data validation |

### Diff commands

```bash
# Diff against main
git diff main..HEAD --stat
git diff main..HEAD
```

## 3. Quality checks

Run lint/format/type checks and fix issues.

Important:

- Do not merge/push with warnings
- If `ruff check` shows issues, try `ruff check --fix`
- Use `git diff --check` to detect trailing whitespace warnings

Scenario A: run quality checks on the PR branch
Scenario B: run quality checks on `main`

Commands:

```bash
# Using make (recommended)
make lint           # Lint check
make lint-fix       # Lint with auto-fix
make format-check   # Format check
make format         # Format auto-fix
make typecheck      # Type check
make quality        # All quality checks

# Trailing whitespace check (use the relevant range)
git diff --check
```

## 4. Regression tests

Run the test suite and confirm all tests pass.

Scenario A: run tests on the PR branch
Scenario B: run tests on `main`

### Example

```bash
# Start tests
make test
# Output shows: run_id: 20251225_123456_12345

# Check completion (always specify RUN_ID)
make test-check RUN_ID=<run_id_from_output>
```

> **CRITICAL:** Always capture `run_id` from `make test` output and pass it to `make test-check RUN_ID=xxx`.

## 5. Merge decision

### Merge criteria

- [ ] Code review has no critical issues
- [ ] Lint/type checks pass (`make quality`)
- [ ] All tests pass (`make test`)
- [ ] Change aligns with requirements/spec
- [ ] **No warnings remain** (required)

### Merge strategy selection

Determine whether to use normal merge or squash merge:

```bash
# Check commit count and quality
git log main..<branch> --oneline | head -20
```

| Source | Pattern | Strategy |
|--------|---------|----------|
| Local human work | 2-5 meaningful commits | Normal merge |
| Claude Code / Cursor Cloud Agent | 10+ micro-commits, "wip" chains | **Squash merge** |
| Mixed | Some good, some noise | Case-by-case |

**Squash indicators** (any of these → consider squash):

- 10+ commits for a small change
- Multiple "fix typo", "wip", "fixup" commits
- Commit messages lack semantic meaning
- Branch created by cloud agent (`cursor/*`, `claude/*`)

### Decision output template

```text
## Merge decision

### Conclusion: ✅ Mergeable / ❌ Changes required

### Merge strategy: Normal / Squash
- Reason: (e.g., "Cloud agent branch with 15 micro-commits")

### Reasons
- Aligns with requirements
- Tests pass
- Code quality acceptable
- No warnings remain

### Required changes (if any)
1. Fix xxx
2. Add yyy
3. Do not merge with remaining warnings
```

## 6. Merge execution (Scenario A only)

Execute only after explicit user approval. Follow the same procedure as `merge`.

### 6.1 Pre-merge checks

Before merging, confirm:

1. **No warnings remain** from `ruff check` / `mypy`
2. **No unresolved conflicts**
3. **No trailing whitespace warnings** from `git diff --check`

```bash
# Warning checks (using make)
make lint
make format-check
make typecheck

# Or run all quality checks at once
make quality

# Trailing whitespace check
git diff --check

# If applicable, try auto-fix
make lint-fix
make format
```

### 6.2 Merge

```bash
git checkout main
git merge --no-edit <pr-branch>
```

Notes:

- Use `--no-edit` to avoid interactive prompts
- Do not merge if any warnings remain

### 6.3 Push to remote

After merge, push to remote (after approval if your process requires it):

```bash
git push origin main
git --no-pager log origin/main..main --oneline
```

Rationale:

- Keeps remote up-to-date
- Team synchronization
- CI/CD runs
- Acts as backup

Notes:

- Confirm merge succeeded before pushing
- Resolve conflicts before pushing

## 6B. Push-only flow (Scenario B only)

If PRs are already merged into local `main` but not pushed to `origin/main`:

- After quality/tests pass, push:

```bash
git push origin main
git --no-pager log origin/main..main --oneline
```

Notes:

- Do not push with remaining warnings
- Confirm quality checks + tests completed before pushing

## Output (detailed)

- PR summary (branch name, files changed, diff size)
- Code review results
- Quality check results (lint/type)
- Test results summary
- Merge decision (with reasons)
- Merge/push execution results (if performed)
