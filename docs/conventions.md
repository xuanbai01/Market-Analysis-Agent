# Coding Conventions

## Universal

- **Imports:** absolute (`from app.services.news_repository import ...`). No relative imports (`from .foo`).
- **No magic values:** named constants or enums for anything that repeats.
- **No dead code:** unused imports, commented-out blocks, unreachable branches — delete them.
- **Small files:** if a module is over 400 lines, challenge why. Split by responsibility, not line count.
- **Small functions:** one thing per function. If you need "and" in the name (`fetch_and_parse_bar`), it's probably two functions.

## Python / FastAPI (this project's only stack today)

- **Naming:** `snake_case` for files, functions, variables, DB columns. `PascalCase` for Pydantic/SQLAlchemy classes.
- **Async by default:** any function that touches the DB, HTTP, or an external service is `async`. Routers use `async def`.
- **Schemas:** every endpoint has a dedicated Pydantic request and response schema in `app/schemas/`. **Never return a SQLAlchemy model directly from a route.** Convert via a `*Out` schema.
- **Services / repositories:** one file per domain in `app/services/` (`news_repository.py`, `market_repository.py`, `data_ingestion.py`). Services take an `AsyncSession` injected from the router.
- **Routers:** thin. Parse input → call service → return schema. No business logic, no raw SQL, no external HTTP.
- **Errors:** raise `fastapi.HTTPException` with the right status code. Unhandled exceptions are rendered as RFC 7807 problem+json by [app/core/errors.py](../app/core/errors.py) — don't reinvent this.
- **DB:**
  - Use SQLAlchemy 2.0 typed ORM (`Mapped[...]`, `mapped_column`).
  - Use `select()` + `session.execute()`. No `session.query()` (1.x style).
  - Never construct SQL strings from user input.
- **Settings:** all config via `app/core/settings.py` (pydantic-settings). Read from `.env` in dev, env vars in prod. **Never hardcode DB URLs, API keys, or secrets.**
- **LLM agents (when added):** one async function per agent, typed inputs and outputs. No DB writes inside agent functions — the calling service handles persistence.
- **Time:** store as `timestamptz` in DB; use `datetime.now(timezone.utc)` (never naive `datetime.utcnow()` when writing new code) — see [news_repository.py](../app/services/news_repository.py) for the pattern.

## Schemas and validation

- Validate every external input at the boundary (router, queue consumer). Never trust upstream data.
- Use Pydantic v2 models for request/response schemas. Use `Field(...)` constraints (min_length, ge, regex) where applicable.
- Error messages should name the field and what was wrong, not just "invalid input".

## Frontend (future: web dashboard / Discord bot)

When a frontend lands in this repo:
- **Naming:** `camelCase` variables/functions, `PascalCase` components/types.
- **Components:** one per file. Filename matches component name.
- **API calls:** all fetch logic in `lib/api/` (or equivalent). Components never call `fetch` directly.
- **Types:** in `lib/types/`. No `any`, no implicit `any`.
- **State:** prefer local state + context. No global store library unless simpler options are exhausted.

## Git

- **Branch naming:** `feature/`, `fix/`, `chore/`, `docs/`, `test/` prefixes.
- **Commit messages:** imperative mood, specific. "Add news ingestion job" not "news stuff". Type prefix (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `refactor:`) for a scannable history.
- **Every feature branch merges via PR.** Never push directly to `main`.
- **One concern per commit.** Easier to review, easier to revert.
