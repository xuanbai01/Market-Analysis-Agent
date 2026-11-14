# Testing Strategy

## Philosophy: TDD for all core logic

Write failing tests first. Implement minimum code to pass. Refactor. This is not optional for services, agents, and anything with business logic. The discipline pays back the first time a mock-based test passes incorrectly and a regression test that inspects real behavior catches the bug.

## State today

- **Backend:** 1006 tests in `tests/` (flat, one `test_<module>.py` per service or router), plus `tests/evals/` — the factuality rubric's unit tests (run on every PR) and 6 live golden cases (AAPL, NVDA, RIVN, JPM, KO, XOM) that call the real LLM and run only with `-m live_llm`. `tests/conftest.py` provides the async client and the rollback-per-test DB session.
- **Frontend:** 667 vitest + Testing Library tests under `frontend/src`, next to the component or helper they cover (`HeroCard.test.tsx`, `lib/format.test.ts`), on happy-dom.
- **CI** runs both suites, lint and typecheck, and boots the production image (see "When to run tests").
- These two counts are the only place the numbers are kept; other docs link here.

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
- **Pre-push:** full suite + `ruff check app tests`.
- **CI on PR:** backend `ruff` + `pytest`; frontend lint, typecheck, vitest and build; a production-image job that builds the Dockerfile and boots it against Postgres (alembic upgrade + `/v1/health`); Gitleaks; an AI review of the diff by DeepSeek, posted as a PR comment (`scripts/ai_review.py`).
- **Before merging a change to report content** (prompts, claims, tools, the thesis): the live golden eval, locally (`uv run pytest -m live_llm tests/evals -s`) or with the **Live Eval** workflow (`gh workflow run live-eval.yml -f provider=deepseek`). It is started by hand because it costs money and calls live providers.

## Fixtures and test data

- Prefer factory functions over JSON fixture files. Explicit, fast, each test declares what it needs.
- Do not share mutable state between tests. Rollback per test or fresh DB per test module.
- Use realistic values (`uuid4()`, real-looking ticker symbols like `"NVDA"`, real-shape timestamps). Hardcoding `"abc"` as an id lets cast bugs slip by.
