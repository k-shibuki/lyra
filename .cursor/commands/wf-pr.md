# wf-pr

## Purpose

Orchestrate PR review and merge: read the provided context, decide which scenario applies, and output a Plan-mode To-do checklist that uses the single-purpose commands.

Note: This workflow is independent from `wf-dev`.

## Contract (must follow)

1. Read all user-attached `@...` context first (PR description, diff, requirements).
   - If required context is missing, ask for the exact `@...` files/info and stop.
2. Determine Scenario A vs B and show evidence (commands/logs reviewed).
3. Produce a Plan-mode checklist To-do where tasks include “run another Cursor command”.
4. Merge/push are **always** gated behind explicit user approval.
5. This command **does not auto-transition**:
   - Do **not** output a slash command as a standalone line.
   - Use `NEXT_COMMAND: /...` (inline) to make it easy to copy without auto-running.

## Inputs (ask if missing)

- PR description / intent (required)
- Diff summary (file list + key changes) (required)
- Requirements/acceptance criteria (`@docs/REQUIREMENTS.md`) (recommended)
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
- [ ] First: run `NEXT_COMMAND: /docs-discover` (discover relevant docs; attach what’s needed)
- [ ] Run: `/quality-check`
- [ ] Run: `/regression-test`
- [ ] Make merge decision (with reasons)
- [ ] After approval only: merge (`NEXT_COMMAND: /merge` or manual merge steps)
- [ ] After approval only: push (`NEXT_COMMAND: /push`)

### Next (manual)

- `NEXT_COMMAND: /quality-check` (or whichever is next)

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
# Compare local main vs origin/main
git log origin/main..main --oneline

# Check PR candidate branches and whether they are merged into origin/main
echo "=== Checking PR branches ==="
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do
    if git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        echo "✓ $branch: Not merged to origin/main"
    else
        echo "  $branch: Already merged to origin/main (skipped)"
    fi
done

echo "=== Summary ==="
echo "Total PR branches: $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | wc -l)"
echo "Unmerged branches: $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null && echo "$branch"; done | wc -l)"
```

Decision rules:

- If `git log origin/main..main` is empty and there exist unmerged PR branches → **Scenario A**
- If `git log origin/main..main` has commits and all PR branches are already merged to local `main` → **Scenario B**

### Scenario A (unmerged PR branches exist)

- Fetch PR branch(es)
- Review diff(s)
- Run `NEXT_COMMAND: /quality-check`
- Run `NEXT_COMMAND: /regression-test`
- Decide mergeability (with reasons)
- After approval only: merge to `main`
- After approval only: push (`NEXT_COMMAND: /push`)

### Scenario B (already merged locally, not pushed)

- Validate local `main` vs `origin/main`
- Run `NEXT_COMMAND: /quality-check` on `main`
- Run `NEXT_COMMAND: /regression-test` on `main`
- Decide whether it is safe to push
- After approval only: push `main` (`NEXT_COMMAND: /push`)

Note: In Scenario B you do not need to re-merge PR branches; validate `main` and then push.

## 1. Fetch PR branches (Scenario A only)

### 1.1 Fetch remote and list candidates

```bash
git fetch origin
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"
echo "Found $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | wc -l) PR candidate branches"
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
    for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"); do
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
        prefix=$(git log main..$branch --format="%s" 2>/dev/null | head -1 | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
        if [ -z "$prefix" ]; then
            # If no diff vs main, fall back to origin/main
            prefix=$(git log origin/main..$branch --format="%s" 2>/dev/null | head -1 | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
        fi
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
for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"); do
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
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do
    if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        echo "$branch: Already merged to origin/main"
    else
        if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
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
| **Spec alignment** | aligns with `docs/REQUIREMENTS.md` |
| **Tests** | tests exist, coverage signals |
| **Security** | authn/authz, data validation |

### Diff commands

```bash
# Diff against main
git diff main..HEAD --stat
git diff main..HEAD
```

## 3. Quality checks

Run `/quality-check` and fix lint/type issues.

Important:

- Do not merge/push with warnings
- If `ruff check` shows issues, try `ruff check --fix`
- Use `git diff --check` to detect trailing whitespace warnings

Scenario A: run quality checks on the PR branch
Scenario B: run quality checks on `main`

## 4. Regression tests

Run `/regression-test` and confirm all tests pass.

Scenario A: run tests on the PR branch
Scenario B: run tests on `main`

### Example

```bash
# Start tests
./scripts/test.sh run tests/

# Poll for completion (max 5 minutes, 5s interval)
for i in {1..60}; do
    sleep 5
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    # Done criteria: "DONE" or result keywords (passed/failed/skipped)
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done

# Fetch results
./scripts/test.sh get
```

Note: `check` returns `DONE` if output includes `passed`/`failed`/`skipped`/`deselected`, so explicit `DONE` checks are usually unnecessary.

## 5. Merge decision

### Merge criteria

- [ ] Code review has no critical issues
- [ ] Lint/type checks pass (`/quality-check`)
- [ ] All tests pass (`/regression-test`)
- [ ] Change aligns with requirements/spec
- [ ] **No warnings remain** (required)

### Decision output template

```text
## Merge decision

### Conclusion: ✅ Mergeable / ❌ Changes required

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
# Warning checks
podman exec lyra ruff check src/ tests/
podman exec lyra mypy src/ tests/

# Trailing whitespace check
git diff --check

# If applicable, try auto-fix
podman exec lyra ruff check --fix src/ tests/
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

- Run `NEXT_COMMAND: /push`

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

- Run `NEXT_COMMAND: /push` after quality/tests pass

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

