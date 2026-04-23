# Testing Strategy

## Philosophy: TDD for all core logic

Write failing tests first. Implement minimum code to pass. Refactor. This is not optional for services, agents, and anything with business logic. The discipline pays back the first time a mock-based test passes incorrectly and a regression test that inspects real behavior catches the bug.

## State today

There is **no test suite yet**. The first task that touches a service (market repo, ingestion, technicals) should introduce `tests/` and write the failing test first.

Suggested layout:

```
tests/
├── conftest.py              # pytest-asyncio config, db fixtures, httpx AsyncClient
├── test_health.py
├── test_symbols.py
├── test_news.py
├── test_market.py
└── services/
    ├── test_market_repository.py
    └── test_news_repository.py
```

Install deps (once): `uv add --dev pytest pytest-asyncio httpx` (or add to `[tool.uv]` dev-dependencies and `uv sync`).

## What to test (by layer)

| Layer | What the tests should cover |
|---|---|
| **Services / repositories** (`app/services/`) | Every branch, including error paths. Use a real test DB or rollback-per-test fixture. Mock external HTTP (yfinance, NewsAPI, LLM). |
| **Agents / external calls** (when they exist) | Mock the external API response. Test that the agent correctly parses structured outputs and handles malformed responses. |
| **Routers** (`app/api/v1/routers/`) | Happy path (200/201), 404 on unknown id, 422 on malformed input, 500 → RFC 7807 problem+json, auth when added. Use `httpx.AsyncClient` + FastAPI's `lifespan`. |
| **Utilities** | Every input class. Boundaries, empty inputs, expected errors. Especially relevant for future technical-indicator code. |

## Async patterns

- Mark tests `@pytest.mark.asyncio` (or enable `asyncio_mode = "auto"` in `pyproject.toml`).
- For DB tests: wrap each test in a transaction that rolls back, or use a function-scoped DB fixture.
- For router tests: use `httpx.AsyncClient(app=app, base_url="http://test")` — do not spin up a real uvicorn.

## Coverage target

>80% on everything under `app/services/` and (future) `app/agents/`. Do not chase 100%; focus on behavior coverage, not line coverage.

## Commit pattern for TDD

```
test: add failing tests for news symbol tagging     ← RED
feat: implement news symbol tagger                   ← GREEN
refactor: extract tagger into service helper         ← REFACTOR
```

The separation makes code review dramatically easier and gives you git history that proves the tests came first.

## Two test-quality traps to avoid

**1. Mock-tautology tests.** If a test mocks the thing it's supposed to verify, it will pass even when the code is wrong. Guard rule: if your test can be deleted without breaking anything, it was never testing the thing. This matters most for ingestion and agent code, where mocking the external provider is tempting but hides bugs in the real-response parsing.

**2. No end-to-end exercise.** Unit tests cannot catch broken router mounting, schema drift, or missing DB columns. After every feature, hit the actual endpoint with `curl` or the `/docs` UI against a freshly-started stack. Better: add a smoke-test script that hits the core endpoints after `docker compose up`.

## When to run tests

- **Pre-commit:** tests for the layer you touched.
- **Pre-push:** full suite + `ruff check app`.
- **CI on PR:** everything above + Gitleaks + Claude AI PR review.

## Fixtures and test data

- Prefer factory functions over JSON fixture files. Explicit, fast, each test declares what it needs.
- Do not share mutable state between tests. Rollback per test or fresh DB per test module.
- Use realistic values (`uuid4()`, real-looking ticker symbols like `"NVDA"`, real-shape timestamps). Hardcoding `"abc"` as an id lets cast bugs slip by.
