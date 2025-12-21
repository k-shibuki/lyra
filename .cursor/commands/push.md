# push

## Purpose

Push `main` to `origin/main` safely.

## When to use

- After merging to `main` (typically after `merge`)
- When local `main` is ahead of `origin/main`

## Preconditions

- If this is immediately after `merge`, quality/tests are typically already done.
- If running directly, run quality checks and regression tests first.

## Steps (non-interactive)

1. Confirm you are on `main` and there are commits to push:

```bash
current_branch=$(git branch --show-current)
echo "Current branch: $current_branch"

if [ "$current_branch" != "main" ]; then
    git checkout main
fi

echo "=== Commits to push ==="
git log origin/main..main --oneline

if [ -z "$(git log origin/main..main --oneline)" ]; then
    echo "No commits to push"
    exit 0
fi
```

2. Pre-push checks (do not push with warnings):

```bash
podman exec lyra ruff check src/ tests/
podman exec lyra mypy src/ tests/
podman exec lyra ruff check --fix src/ tests/  # if needed

git diff origin/main..main --check
```

3. Push:

```bash
git push origin main
```

4. Verify:

```bash
git log origin/main..main --oneline
```

## Output (response format)

- **Branch**: current branch
- **Commits pushed**: list (or “none”)
- **Pre-push checks**: warnings/trailing whitespace status
- **Push result**: success/failure + error summary if failed

## Related rules

- `@.cursor/rules/code-execution.mdc`
