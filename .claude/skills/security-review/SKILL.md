---
name: security-review
description: Complete a security review of the pending changes on the current branch. Invokes the security-reviewer agent on every modified file and summarizes the findings.
---

Run a security review over everything this branch changes vs `main`.

## Steps

1. List files changed on the branch: `git diff --name-only main...HEAD`
2. For each changed file that is application code (not docs, tests, or config), delegate to the `security-reviewer` subagent, passing the file path.
3. Collect all findings into a single combined report grouped by severity.
4. Produce a final summary:
   - Total findings by severity (HIGH / MEDIUM / LOW)
   - Top 3 most important findings to address before merging
   - Any file that came back clean (explicitly list them for confidence)

## Output format

```
# Branch Security Review: <branch-name>

## Must-fix before merge
1. <HIGH finding, 1 line>
2. <HIGH finding, 1 line>
3. <MEDIUM finding, 1 line>

## Per-file findings
<full reports grouped by file>

## Clean files
- <path> — no findings
- <path> — no findings
```

## Constraints

- Delegate to the `security-reviewer` subagent per file, do not audit inline.
- Do not modify any file. This skill reports only.
- Skip files under `tests/`, `docs/`, and config-only files unless they contain secrets.
- If `git diff --name-only main...HEAD` returns nothing, say so and stop.
