# Security

Active mitigations for the OWASP Top 10, scoped to this project's stack (FastAPI + async SQLAlchemy + Postgres + external market/news/LLM APIs). Only relax a default when you have a concrete reason and write it into an ADR.

## A01 — Broken Access Control

- **Today: one shared secret.** [`app/core/auth.py::require_shared_secret`](../app/core/auth.py) checks `Authorization: Bearer <BACKEND_SHARED_SECRET>` (constant-time compare) on **every route except `/`, `/v1/health` and the three demo routes below**. That includes plain reads of stored data (market snapshot and history, news, symbols): until 2026-11 those were open, and each told an anonymous caller which tickers had been researched. Production sets the secret; with it unset (local dev) the dependency is a pass-through. [`tests/test_route_auth.py`](../tests/test_route_auth.py) asserts that the set of ungated routes is exactly that short list, so a new route is gated or the test fails. The daily IV snapshot cron (ADR 0008) calls a gated route with the same secret, stored as the `BACKEND_SHARED_SECRET` GitHub Actions secret; the workflow has no permissions, checks out no code, uses no third-party actions and never prints it.
- The dashboard asks for the secret at sign-in and keeps it in `localStorage`; a 401 on a report clears it and returns to sign-in.
- **The owner's account data needs a second key** (ADR 0009, amended 2026-11-15). Routes under `/v1/owner` take `require_owner` ([`app/api/v1/dependencies.py`](../app/api/v1/dependencies.py)): the shared secret, then `X-Owner-Key: <OWNER_KEY>`, compared in constant time on bytes.
  - **Why a second key:** the shared secret is also a GitHub Actions secret, so it alone must not open the owner's account.
  - **Fail closed:** with `OWNER_KEY` unset the routes answer 404 to a caller past the shared secret, local dev included. A missing or wrong key is a 403.
  - **A strong key:** set, it must be at least 32 characters and differ from the shared secret, or the app won't start (`Settings._owner_key_is_strong`). Past the shared secret, the key's strength is the real defence.
  - **Lockout:** every request takes one of the caller's `OWNER_KEY_FAILURES_PER_HOUR` tries (10, from 1 to 100) before its key is compared, and a right key gives it back.
    - A burst of guesses gets no more than the tries left.
    - With none left every request is a 429, the right key included.
    - An IPv6 caller counts by its /64.
    - The counts are in memory, so they're per machine and a restart clears them. That's also the way out if someone holding the shared secret locks the owner out from a shared address: `fly apps restart`.
  - **Logging:** a refusal is logged as missing or wrong, and a lockout as one warning. The caller is named by a keyed hash, with a key that's new each boot, never by address, and the owner key never appears.
  - **Not advertised:** the owner routes are left out of the public OpenAPI schema.
  - [`tests/test_owner_auth.py`](../tests/test_owner_auth.py) pins the owner's routes.
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
- Rate-limit LLM-backed endpoints, and anything that fans out to a provider: an options page build (about a dozen Yahoo calls) is limited per IP on cache misses (`OPTIONS_RATE_LIMIT_PER_HOUR`, 60); cached reports are free. The options read is a model call, limited per IP when no read of the same quotes is cached (`OPTIONS_READ_RATE_LIMIT_PER_HOUR`, 20); its prompt holds the validated ticker, the quote time and computed claims, nothing a caller typed.
- Rate-limit LLM-backed endpoints. `/v1/research/{symbol}` has a per-IP limit on fresh reports (default 3/h; 30/h in production while the owner is the only user — lower it before sharing the URL).
- **Every per-IP limit keys on `Fly-Client-IP`,** which Fly's proxy sets to the address it accepted the connection from, and only when it parses as an IP (`dependencies._client_ip`; off Fly, the socket's peer). Not `X-Forwarded-For`: Fly appends to it and keeps whatever the client wrote first, so keying on that let a caller mint a new bucket per request, on the open demo routes too (security review, #114). Buckets that have refilled are dropped once there are 1,024 keys (`TokenBucket.PRUNE_AT`), so memory follows recent callers. This assumes Fly's proxy: behind another proxy that sets only `X-Forwarded-For`, every caller would share the proxy's address.
- **Workflow secrets live on the steps that use them,** not the job: install steps run third-party code (`live-eval.yml`).

## A05 — Security Misconfiguration

- All secrets loaded via `app/core/settings.py` from environment variables. The `.env` file is `.gitignored` — never commit real values.
- `APP_ENV=prod` must disable FastAPI debug / docs routes unless deliberately public (currently `/docs` is always on — revisit before public launch).
- CORS allows exactly one origin, `FRONTEND_ORIGIN` ([`app/core/cors.py`](../app/core/cors.py)); production sets it to the Vercel dashboard in `fly.toml`. Never `*`. Allowed headers: `Authorization`, `Content-Type` and `X-Owner-Key`.

## A06 — Vulnerable and Outdated Components

- Dependencies pinned in `pyproject.toml`. Renovate / Dependabot should be enabled when the repo goes public.
- Gitleaks runs on every PR via `.github/workflows/ci.yml`. Critical CVEs block merge.

## A07 — Identification and Authentication Failures

- Shared secret only (see A01): validated on every protected request; failures return 401 with `WWW-Authenticate: Bearer` and never log the token. No expiry or rotation beyond replacing the secret, which now lives in three places: the Fly secret, the GitHub Actions secret (the IV snapshot cron) and each browser's sign-in. A narrower token for the cron waits until there are collaborators (ADR 0008).
- **The owner key** (A01) lives as a Fly secret and in the owner's password manager, which syncs it to their PCs. The sign-in form carries a fixed hidden username, so a manager can save the secret under a name, and posts (so a stray native submit can't put it in a URL). The owner pages' unlock form will do the same. Rotate it by importing a new `OWNER_KEY` (docs/deployment.md §10).
- When per-user auth lands: token expiry enforced (24h default), failed logins return a generic error and are logged with an anonymized identifier.
- **The owner's tastytrade credential** (ADR 0009) is a personal OAuth app's client ID and secret and its grant's refresh token. The refresh token never expires and opens a brokerage account.
  - **Storage:** they are Fly secrets only (`TASTYTRADE_*`, docs/deployment.md §9), never in GitHub or a browser.
  - **Read only:** every refresh asks for `scope=read`.
    - `tastytrade_client` uses an access token only when the answer's `scope` field, or else the token's own claim, holds `read` and nothing beyond `openid` and tastytrade's per-account scopes (`accounts:<number>:<authority>`). `trade` or an unknown scope is refused without being printed (a scope can name an account). A missing or garbled scope counts as a refusal.
    - Apart from the sign-in POST, it can only GET, and only paths on its allowlist, none of them an order path. `tests/test_tastytrade_client.py` checks the source and every request.
    - The probe checks that the stored grant itself can't trade (`grant_scopes`). A read-only access token proves nothing about the refresh token, which is the credential that could leak.
  - **Failed sign-in:** every failure is remembered, so waiting and later callers don't sign in again. Repeated failed logins block the server's IP for about 8 hours.
    - A refusal (a 4xx other than 429) pauses all calls for an hour.
    - A throttled, failed or garbled answer pauses them for a minute, or for the server's Retry-After.
    - A 401 on a token less than a minute old doesn't trigger another sign-in.
    - Each pause logs a warning.
  - **Settings:** the secrets are `SecretStr`, so printing the settings shows asterisks. `TASTYTRADE_API_URL` is one of tastytrade's two addresses (production, sandbox), so a typo can't send the refresh token elsewhere. `.env.*` and `*.env` are ignored by git and Docker.
  - **Revoking:** delete the grant on my.tastytrade.com and create a new one.

## A08 — Software and Data Integrity Failures

- Gitleaks in CI catches committed secrets.
- Schema changes go through migrations (Alembic, once wired). No manual `ALTER TABLE` in prod.
- **External service outputs (LLM, Polygon, NewsAPI) are parsed and validated with Pydantic before any DB write.** A malformed upstream response must not poison our DB.

## A09 — Security Logging and Monitoring Failures — **this is non-negotiable for this project**

- **Every external service invocation is logged:** service id (`polygon.aggregates`, `openai.chat`, `newsapi.everything`), input payload shape, output payload shape (not full body unless needed), latency ms, timestamp. This is what keeps LLM and ingestion systems debuggable.
- Auth failures (when auth lands) logged with timestamp and anonymized identifier.
- **Never log** raw passwords, tokens, API keys, or full PII. Redact headers when logging HTTP requests.
- **tastytrade calls log the path and the status,** never a header, token, quote token or response body.
  - The whole account segment is masked (`/accounts/***/…`).
  - An access token must be header-safe before it's used: h11 quotes an illegal header value in its error. As a backstop, the log formatter masks `Bearer <token>`.
  - websockets' frame log, which would print the DXLink AUTH frame, is held at WARNING.
  - Tests feed distinctive secrets through every path and fail if one reaches an `app.*` log line.
- **tastytrade's data is shown to no third party** (its Open API terms §8(4) and §8(6)), and a Claude Code session is one. So `tastytrade_probe` and any check by Claude print metadata only: ages, counts, field names, yes/no comparisons. The owner compares values in tastytrade's own app.
- **An unhandled error tells the caller nothing about the server.** The 500 body carries a reference id; the exception goes to the log under that id (`app/core/errors.py`). It used to carry `str(exc)`, which on an open route can hand a stranger a SQL fragment or a hostname.

## A10 — Server-Side Request Forgery (SSRF)

- The backend does not make HTTP requests to user-supplied URLs. All external calls go to hardcoded, vetted endpoints (yfinance, Polygon, NewsAPI, Reddit, LLM providers).
- If that ever changes (e.g. "fetch this user-provided RSS feed"), add an allowlist and block internal IP ranges.
- **One address comes from a provider's answer:** DXLink's websocket URL arrives with tastytrade's quote token.
  - `dxlink` connects only to tastytrade's two feed hosts (`dxlink.FEED_HOSTS`) over `wss://` on port 443, with no credentials, query or fragment in the address. A new host is added only after a probe shows the account being given it.
  - It follows no redirect: websockets would follow a cross-host `wss://` one.
  - Messages are capped at 4 MiB with compression off, so there's no decompression bomb, and the events a fetch keeps are capped too.

## CI Security Gates

See `.github/workflows/ci.yml`:

1. **Gitleaks** — secrets detection on every push and PR.
2. **AI PR review (DeepSeek)** — reads the diff of every PR from a branch of this repo and posts one comment: bugs, security holes, broken project rules ([`scripts/ai_review.py`](../scripts/ai_review.py)). A different model family from the one that writes the code. Advisory; it never blocks a merge. It sees the diff only, so it is no substitute for `/security-review`. It runs the PR's own copy of the script with the DeepSeek key, which is fine while only the owner can push branches: anyone who can push could already change `ci.yml` in a PR and print any secret. Revisit before adding collaborators (the comment on the job in `ci.yml` says how).
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
- Store tastytrade's data, send it to an LLM, show it in the demo, or ask its API for the `trade` scope (ADR 0009).
