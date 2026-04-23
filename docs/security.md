# Security

Active mitigations for the OWASP Top 10, scoped to this project's stack (FastAPI + async SQLAlchemy + Postgres + external market/news/LLM APIs). Only relax a default when you have a concrete reason and write it into an ADR.

## A01 — Broken Access Control

- There is **no auth yet**. Every public-internet deployment must sit behind an auth dependency before launch.
- When added: every protected route uses a FastAPI dependency that validates the token and returns `current_user`.
- Scope all user-owned DB queries to `current_user.id` unless the route is explicitly cross-user (admin, public read).

## A02 — Cryptographic Failures

- When auth lands: JWTs signed with HS256 (or stronger); secret lives in `DATABASE_URL`-style env vars only.
- Passwords (if we go that route): hash with bcrypt or argon2. Never log or store plaintext.
- TLS everywhere in staging and prod. Local dev over http is fine.

## A03 — Injection

- **No raw SQL strings constructed from user input.** Use SQLAlchemy 2.0 `select()` with bound params.
- **No user input passed directly into LLM prompts.** Once agents land: structure and sanitize input into a template with typed slots, never f-string interpolation of raw user strings.
- No shell commands built from user input. If ingestion calls a subprocess, use an allowlist.

## A04 — Insecure Design

- Router → Service → (Agent / DB) separation. Business logic never lives in route handlers where it can be bypassed.
- Immutable audit records: ingested market bars and news items should be append-only (use a ts-indexed table; supersede, don't update).
- Rate-limit external-facing endpoints once exposed publicly. Especially relevant for `/v1/analysis` and `/v1/forecasts/*` (LLM-backed, expensive).

## A05 — Security Misconfiguration

- All secrets loaded via `app/core/settings.py` from environment variables. The `.env` file is `.gitignored` — never commit real values.
- `APP_ENV=prod` must disable FastAPI debug / docs routes unless deliberately public (currently `/docs` is always on — revisit before public launch).
- CORS (not yet configured): when added, allowlist origins explicitly. Never `*` in production.

## A06 — Vulnerable and Outdated Components

- Dependencies pinned in `pyproject.toml`. Renovate / Dependabot should be enabled when the repo goes public.
- Gitleaks runs on every PR via `.github/workflows/ci.yml`. Critical CVEs block merge.

## A07 — Identification and Authentication Failures

- Deferred — no auth yet. When added: token expiry enforced (24h default), tokens validated on every protected request, failed logins return a generic error and are logged with an anonymized identifier.

## A08 — Software and Data Integrity Failures

- Gitleaks in CI catches committed secrets.
- Schema changes go through migrations (Alembic, once wired). No manual `ALTER TABLE` in prod.
- **External service outputs (LLM, Polygon, NewsAPI) are parsed and validated with Pydantic before any DB write.** A malformed upstream response must not poison our DB.

## A09 — Security Logging and Monitoring Failures — **this is non-negotiable for this project**

- **Every external service invocation is logged:** service id (`polygon.aggregates`, `openai.chat`, `newsapi.everything`), input payload shape, output payload shape (not full body unless needed), latency ms, timestamp. This is what keeps LLM and ingestion systems debuggable.
- Auth failures (when auth lands) logged with timestamp and anonymized identifier.
- **Never log** raw passwords, tokens, API keys, or full PII. Redact headers when logging HTTP requests.

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
