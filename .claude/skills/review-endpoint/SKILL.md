---
name: review-endpoint
description: Reviews an HTTP API route file for error handling gaps, input validation issues, and missing test coverage. Outputs a structured findings report and offers to apply fixes. Framework-agnostic, tested with FastAPI, Express, and Hono.
---

Review the API route file provided as an argument (e.g. `/review-endpoint src/api/users.ts`).

## Steps

**1. Identify the target file**

The argument is the path to a route/controller file. If no argument is given, ask the user which file to review before proceeding.

**2. Read the route file**

Read the full contents of the specified file. Note every route handler: its HTTP method, path, auth/middleware dependencies, request body/query params, and response model.

**3. Discover related files**

For each route handler, locate and read:
- The service or business-logic function(s) it calls
- The request/response schema definitions it uses
- The ORM or data-access models involved
- The corresponding test file

Use the project's conventions (see `docs/conventions.md`) to find these. Do not modify any of these files during the review.

**4. Analyze for issues across three dimensions**

**A. Error Handling**
Check each route handler for:
- Missing structured error response on operations that can fail (DB not found, permission denied, external service failure)
- Catching broad exceptions without re-raising as a typed error
- No retry logic or failure logging on external service calls (LLM agents, third-party APIs)
- Operations that can raise unhandled exceptions from the service or data layer
- Missing 404 when fetching a resource by id that may not exist
- Missing 403/401 for ownership checks (e.g. user accessing another user's resource)

**B. Input Validation**
Check each route handler and its schemas for:
- Path/query params that are raw strings instead of typed (`UUID`, `int`, enum)
- Schema definitions missing field validators (length, range, pattern, required)
- User-supplied strings passed directly into LLM prompts or shell commands without sanitization
- Missing required fields that would silently default to `None`/`undefined`
- No validation that enum-constrained fields use the actual enum type

**C. Test Coverage**
Cross-reference every route handler against the test file:
- Auth guard (401 when unauthenticated) — one test per protected route
- Happy path (200/201 with valid input)
- Not-found path (404 when resource doesn't exist)
- Forbidden path (403 when accessing another user's resource)
- Validation rejection (422/400 for malformed input)
- Downstream failure path (500 or appropriate error when service fails)

Flag any of the above that are missing.

**5. Output a structured report**

Print the report in this exact format, do not truncate findings:

```
## Endpoint Review: <filename>

### Error Handling
| Route | Issue | Severity | Suggested Fix |
|-------|-------|----------|---------------|
| GET /path | Missing 404 when resource not found | HIGH | Raise not-found error after lookup returns null |
| ...   | ...   | ...      | ...           |

### Input Validation
| Route / Schema | Issue | Severity | Suggested Fix |
|----------------|-------|----------|---------------|
| CreateUser.name | Plain string, no length constraint | MEDIUM | Enforce min/max length in schema |
| ...            | ...   | ...      | ...           |

### Test Coverage Gaps
| Route | Missing Test | Suggested Test Name |
|-------|-------------|---------------------|
| GET /users/{id} | 403 for wrong owner | test_get_user_returns_403_for_other_owner |
| ...   | ...         | ...                 |

### Summary
- Error handling issues: <N> (HIGH: X, MEDIUM: Y, LOW: Z)
- Input validation issues: <N>
- Missing tests: <N>
```

Use severity levels: **HIGH** (can cause data leakage, unhandled crash, or auth bypass), **MEDIUM** (degrades reliability or allows bad data in), **LOW** (code quality / best practice).

If a dimension has no issues, write `No issues found.` under that heading.

**6. Offer to apply fixes**

After the report, ask the user exactly:

> Would you like me to apply any of these fixes? Reply with:
> - **"all"** to apply every finding
> - **"errors"**, **"validation"**, or **"tests"** to fix one category
> - A specific route name (e.g. `GET /users/{id}`) to fix just that route
> - **"no"** to skip

## Constraints

- **Do not modify any file until the user explicitly confirms** in response to the question above.
- **Do not invent issues.** Only report findings supported by what you read in the actual files.
- **Do not rewrite working code** as part of a fix, make the minimum change that resolves the specific issue.
- When applying fixes, touch only the files necessary: the route file, its schema file, and/or its test file.
- When adding tests, follow the TDD commit convention from `docs/testing.md`: write the test in the existing test file; do not create new test files unless none exists.
- Preserve all existing imports, formatting, and code style when editing files.
