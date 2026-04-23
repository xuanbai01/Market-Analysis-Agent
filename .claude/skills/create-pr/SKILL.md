---
name: create-pr
description: Generates a pull request with structured description, test plan, C.L.E.A.R. review checklist, and AI disclosure metadata. Run from any feature branch.
---

Create a pull request for the current branch against `main`.

## Steps

**1. Gather branch context**

Run the following to understand what changed:
- `git log main..HEAD --oneline` — list of commits in this branch
- `git diff main...HEAD --stat` — files changed and line counts
- `git diff main...HEAD` — full diff (read this to understand the changes)

**2. Determine PR metadata**

From the diff, determine:
- **Title:** Imperative mood, under 70 chars. Prefix with type: `feat:`, `fix:`, `chore:`, `test:`, `docs:`
- **Summary:** 3–5 bullet points describing what changed and why. Focus on the "why", not the "what".
- **Test plan:** Bulleted checklist of steps a reviewer can follow to verify the change works. Be specific, include routes, UI flows, or commands to run.
- **Risk level:** LOW / MEDIUM / HIGH based on blast radius of the change.

**3. Assess AI contribution**

Estimate the percentage of the diff that was AI-generated vs. human-written. Be honest:
- Count lines written by Claude vs. lines written by the developer
- Express as a range (e.g., "70–80% AI-generated")

**4. Apply C.L.E.A.R. framework**

Include a C.L.E.A.R. review checklist in the PR body:
- **C — Correct:** Does the code do what it claims?
- **L — Legible:** Is the code easy to read and understand?
- **E — Efficient:** Are there obvious performance or redundancy issues?
- **A — Assessable:** Are there tests that verify the behavior?
- **R — Resilient:** Does it handle edge cases and failures gracefully?

**5. Create the PR**

Use `gh pr create` with the following body structure:

```
## Summary
<3–5 bullet points>

## Test Plan
<bulleted checklist, specific steps to verify>

## Risk
<LOW / MEDIUM / HIGH>, <one sentence explaining why>

## C.L.E.A.R. Checklist
- [ ] **Correct** — behavior matches intent
- [ ] **Legible** — code is readable without extra context
- [ ] **Efficient** — no obvious waste or redundancy
- [ ] **Assessable** — tests cover the happy path and key failure modes
- [ ] **Resilient** — edge cases and errors are handled

## AI Disclosure
- **AI-generated:** ~<X>% (Claude via Claude Code)
- **Human review:** Yes, all changes reviewed and approved before commit
- **Tool:** Claude Code (claude.ai/code)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Constraints

- Do not push to `main` directly. Always target `main` as base branch.
- Do not fabricate test results. Only claim tests pass if you have actually run them.
- If the branch has no commits beyond `main`, stop and tell the user there is nothing to PR.
- If `gh` CLI is not authenticated, tell the user to run `gh auth login` first.
