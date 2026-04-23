# Lessons

Every time a human (user, reviewer, PR comment) corrects Claude Code in this repo, capture the lesson here so it doesn't happen twice. Treat this file as an evolving rulebook.

## Format

Each entry has three parts:

```
### <short title>

**Date:** YYYY-MM-DD
**Context:** what I was doing
**Mistake:** what went wrong
**Rule:** the one-sentence takeaway I should follow next time
```

## Entries

<!-- Delete this example once you have real entries. -->

### Example: do not mark done before running the tests

**Date:** 2026-01-01
**Context:** implementing a new route with TDD
**Mistake:** marked the task complete after writing the code, then discovered the tests hadn't actually been re-run and two were still failing
**Rule:** a task is never complete until the full test suite (not just the file I touched) has been re-run green.
