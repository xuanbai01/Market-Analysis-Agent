# Security

Active mitigations for the OWASP Top 10, scoped to this project's stack (FastAPI + async SQLAlchemy + Postgres + external market/news/LLM APIs). Only relax a default when you have a concrete reason and write it into an ADR.

## A01 — Broken Access Control

- **Today: one shared secret.** [`app/core/auth.py::require_shared_secret`](../app/core/auth.py) checks `Authorization: Bearer <BACKEND_SHARED_SECRET>` (constant-time compare) on **every route except `/`, `/v1/health` and the three demo routes below**. That includes plain reads of stored data (market snapshot and history, news, symbols): until 2026-11 those were open, and each told an anonymous caller which tickers had been researched. Production sets the secret; with it unset (local dev) the dependency is a pass-through. [`tests/test_route_auth.py`](../tests/test_route_auth.py) asserts that the set of ungated routes is exactly that short list, so a new route is gated or the test fails.
- The dashboard asks for the secret at sign-in and keeps it in `localStorage`; a 401 on a report clears it and returns to sign-in.
- **One deliberate exception: the read-only demo.** `GET /v1/demo`, `/v1/demo/research/{symbol}` and `/v1/demo/market/{symbol}/prices` answer without the secret ([`app/services/demo.py`](../app/services/demo.py)). They return only what is already stored (the latest report and the stored prices) for the tickers in `DEMO_SYMBOLS`; they never generate a report, call the LLM or reach a data provider, so a visitor cannot spend money or quota. A ticker off the list is a 404 whether or not anything is stored for it. They are built to be hammered: responses are cached for five minutes as serialized bytes (no per-request validation or serialization of a large report), the cache can only hold keys for listed tickers and the three allowed ranges, responses carry `Cache-Control: public, max-age=300`, and one IP is limited to `DEMO_RATE_LIMIT_PER_MINUTE` requests (120 by default). `DEMO_SYMBOLS` empty turns all three off. `tests/test_route_auth.py` pins the set to exactly these three GET routes; `tests/test_demo.py` fails if any path from them reaches the orchestrator or the price ingest. The reports hold public market data and AI prose about it, nothing about the owner.
- **When real users arrive:** per-user auth through a dependency that returns `current_user`, and every user-owned query scoped to `current_user.id` unless the route is explicitly cross-user.

## A02 — Cryptographic Failures

- When auth lands: JWTs signed with HS256 (or stronger); secret lives in `DATABASE_URL`-style env vars only.
- Passwords (if we go that route): hash with bcrypt or argon2. Never log or store plaintext.
- TLS everywhere in staging and prod. Local dev over http is fine.

## A03 — Injection

- **No raw SQL strings constructed from user input.** Use SQLAlchemy 2.0 `select()` with bound params.
- **No user input passed directly into LLM prompts.** Once agents land: structure and sanitize input into a template with typed slots, never f-string interpolation of raw user strings.
- No shell commands built from user input. If ingestion calls a subprocess, use an allowlist.
- **A source link is a web address or nothing.** `Source.url` is rendered as `<a href>`; both the Pydantic model and the Zod schema keep only `http(s)` and drop anything else (a `javascript:` address would run in the page that holds the owner's token).

## A04 — Insecure Design

- Router → Service → (Agent / DB) separation. Business logic never lives in route handlers where it can be bypassed.
- Immutable audit records: ingested market bars and news items should be append-only (use a ts-indexed table; supersede, don't update).
- Rate-limit LLM-backed endpoints. `/v1/research/{symbol}` has a per-IP limit on fresh reports (default 3/h; 30/h in production while the owner is the only user — lower it before sharing the URL).

## A05 — Security Misconfiguration

- All secrets loaded via `app/core/settings.py` from environment variables. The `.env` file is `.gitignored` — never commit real values.
- `APP_ENV=prod` must disable FastAPI debug / docs routes unless deliberately public (currently `/docs` is always on — revisit before public launch).
- CORS allows exactly one origin, `FRONTEND_ORIGIN` ([`app/core/cors.py`](../app/core/cors.py)); production sets it to the Vercel dashboard in `fly.toml`. Never `*`.

## A06 — Vulnerable and Outdated Components

- Dependencies pinned in `pyproject.toml`. Renovate / Dependabot should be enabled when the repo goes public.
- Gitleaks runs on every PR via `.github/workflows/ci.yml`. Critical CVEs block merge.

## A07 — Identification and Authentication Failures

- Shared secret only (see A01): validated on every protected request; failures return 401 with `WWW-Authenticate: Bearer` and never log the token. No expiry or rotation beyond replacing the Fly secret.
- When per-user auth lands: token expiry enforced (24h default), failed logins return a generic error and are logged with an anonymized identifier.

## A08 — Software and Data Integrity Failures

- Gitleaks in CI catches committed secrets.
- Schema changes go through migrations (Alembic, once wired). No manual `ALTER TABLE` in prod.
- **External service outputs (LLM, Polygon, NewsAPI) are parsed and validated with Pydantic before any DB write.** A malformed upstream response must not poison our DB.

## A09 — Security Logging and Monitoring Failures — **this is non-negotiable for this project**

- **Every external service invocation is logged:** service id (`polygon.aggregates`, `openai.chat`, `newsapi.everything`), input payload shape, output payload shape (not full body unless needed), latency ms, timestamp. This is what keeps LLM and ingestion systems debuggable.
- Auth failures (when auth lands) logged with timestamp and anonymized identifier.
- **Never log** raw passwords, tokens, API keys, or full PII. Redact headers when logging HTTP requests.
- **An unhandled error tells the caller nothing about the server.** The 500 body carries a reference id; the exception goes to the log under that id (`app/core/errors.py`). It used to carry `str(exc)`, which on an open route can hand a stranger a SQL fragment or a hostname.

## A10 — Server-Side Request Forgery (SSRF)

- The backend does not make HTTP requests to user-supplied URLs. All external calls go to hardcoded, vetted endpoints (yfinance, Polygon, NewsAPI, Reddit, LLM providers).
- If that ever changes (e.g. "fetch this user-provided RSS feed"), add an allowlist and block internal IP ranges.

## CI Security Gates

See `.github/workflows/ci.yml`:

1. **Gitleaks** — secrets detection on every push and PR.
2. **Claude AI PR review** — flags suspicious patterns in the diff on every PR.
3. **`security-review` skill** — run manually via `/security-review` before merging anything that touches a new route, service, or external call.

## Do / Don't Cheat Sheet

**Do**
- Log every external call (LLM, market API, news API): service id, input, output, latency, timestamp.
- Validate every request with Pydantic at the router boundary.
- Store ingested data immutably. Supersede, never overwrite.
- Run `/security-review` on any branch that adds a new route or external call before merging.

**Don't**
- Pass raw user input into LLM prompts.
- Construct SQL from user input, ever.
- Hardcode secrets, even in "just for dev" code paths.
- Return SQLAlchemy models directly from route handlers.
- Skip TDD for auth/authorization code when it lands. This is where mocks lie and regressions hide.
