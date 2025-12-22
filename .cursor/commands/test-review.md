# test-review

## Purpose

Review tests against `@.cursor/rules/test-strategy.mdc` and improve them until they meet the bar.

## When to use

- After creating tests (typically after `test-create`)
- Any time test quality is questionable (coverage gaps, flakiness, unclear assertions)

## Inputs (attach as `@...`)

- The test files to review (`@tests/...`) — required if known; otherwise specify scope
- Any context documents (requirements, specs) for understanding expected behavior
- Relevant implementation files (`@src/...`) if known

**Note**: This command will search the codebase to find related implementation files and understand the expected behavior if not explicitly attached.

## Constraints

- Do **not** reference planning documents in code comments.
- Negative tests must be **>=** positive tests (unless there is a clear reason).

## Review checklist

1. Test matrix exists and matches the change surface.
2. Positive/negative balance is acceptable.
3. Boundary cases are covered (0, min, max, ±1, empty, NULL/None).
4. Given/When/Then comments exist.
5. Exceptions validate both type and message where meaningful.
6. Branch/behavioral coverage is reasonable (focus on meaningful branches).
7. If a new parameter/field was introduced, tests include at least one **wiring/effect** assertion so "validated-but-unused / not propagated" cannot pass.

## Steps

1. Confirm scope: which tests are in/out.
2. Review and list issues by severity.
3. Propose a fix plan (smallest effective edits first).
4. Apply fixes if approved (or if the workflow expects auto-fix).

## Output (response format)

- **Review summary**: pass/fail + reasoning
- **Missing coverage**: bullet list
- **Fixes applied** (if any): list of changes

## Related rules

- `@.cursor/rules/test-strategy.mdc`
- `@.cursor/rules/code-execution.mdc`
