# Deployment

Runbook for deploying the Market Analysis Agent to Fly.io with a Neon Postgres backend. Architectural rationale is in [ADR 0002](adr/0002-deployment.md); this document is purely operational.

## First-time setup (~20 minutes, done once)

### 1. Create the Neon project (5 min)

1. Sign up at <https://neon.tech> (free tier is fine).
2. Create a new project. Pick a region near your Fly region — `US East (Ohio)` or `US East (N. Virginia)` pair well with Fly's `iad`.
3. On the project dashboard, under **Connection details**:
   - Set the endpoint dropdown to **Direct** (not Pooled — see warning below).
   - Set the role to your `*_owner` user (or whatever you'll connect as).
   - Copy the **Connection string**. Neon's default copy looks like:
     ```
     postgres://USER:PASSWORD@ep-xxxxx.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
     ```
4. **Three substitutions** turn the libpq-flavoured Neon string into one asyncpg accepts:
   - Scheme: `postgres://` → `postgresql+asyncpg://`
   - `sslmode=require` → `ssl=require`
   - Drop `&channel_binding=require` entirely
   - Drop any other libpq-only params you see (`gssencmode`, `application_name`, `options`, …) — asyncpg rejects them with `TypeError: connect() got an unexpected keyword argument '<name>'`
   Final form:
   ```
   postgresql+asyncpg://USER:PASSWORD@ep-xxxxx.us-east-1.aws.neon.tech/neondb?ssl=require
   ```
   Hang on to this string — you'll paste it into both `.env` (locally) and Fly secrets below.

> **Use the Direct endpoint, not the Pooled one, for MVP.** Neon's pooled endpoint is `-pooler.<region>.aws.neon.tech`; the direct endpoint drops the `-pooler` segment. asyncpg + Neon's transaction-mode pooler requires `statement_cache_size=0` on the engine, otherwise concurrent requests hit `prepared statement "__asyncpg_stmt_X__" already exists`. ADR 0002 calls this out; we default to the direct endpoint until a single Fly machine bumps the connection cap.

### 2. Install the Fly CLI (2 min)

```bash
# macOS / Linux
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

Then authenticate:

```bash
fly auth login
```

### 3. Create the Fly app (3 min)

From the repo root:

```bash
fly launch --no-deploy --copy-config --name market-analysis-agent --region iad
```

`--copy-config` makes Fly read our existing [`fly.toml`](../fly.toml) rather than prompting to generate a fresh one. `--no-deploy` means: create the app, skip the first deploy — we still need to set secrets. If the name is taken, pick another (Fly app names are global).

### 4. Set secrets (2 min)

```bash
# bash/zsh
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@ep-xxxxx.us-east-1.aws.neon.tech/neondb?ssl=require"
```

```powershell
# PowerShell — note the SINGLE quotes. Double quotes let PowerShell see the
# `=` inside `ssl=require` as its own delimiter, splitting the URL in half
# and producing "is not a valid secret name". Single quotes are literal.
fly secrets set 'DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@ep-xxxxx.us-east-1.aws.neon.tech/neondb?ssl=require'
```

`APP_ENV`, `TZ`, and `PORT` are set as plain env vars in `fly.toml`, so you don't need to pass them as secrets.

### 5. First deploy (5 min)

```bash
fly deploy
```

The first build pulls Python + pandas + numpy + yfinance, so allow ~3 minutes. Subsequent deploys use the layer cache and finish in under a minute.

When it completes:

```bash
fly open
```

Verify:
- `https://<your-app>.fly.dev/v1/health` → `{"status":"ok","db":true}`
- `https://<your-app>.fly.dev/v1/symbols` → seeded NVDA + SPY rows (from the baseline migration)
- `https://<your-app>.fly.dev/docs` → Swagger UI

### 6. Wire up push-to-deploy (3 min)

Generate a deploy token:

```bash
fly tokens create deploy --name github-actions --expiry 8760h
```

The output is a `FlyV1 fm2_...` string. Copy it, then on GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

- Name: `FLY_API_TOKEN`
- Value: the `FlyV1 fm2_...` string

Now `git push origin main` runs [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), which calls `flyctl deploy --remote-only`. The workflow skips when only docs / tasks / markdown changed (see the `paths-ignore` list).

## Ongoing operations

### Rolling out a change

```bash
git push origin main
```

That's it. GitHub Actions runs `flyctl deploy --remote-only`; Fly does a rolling replacement of the machine; the new container runs `alembic upgrade head && uvicorn ...` on startup.

For a manual redeploy without pushing new code:

```bash
# GitHub Actions UI → Deploy → Run workflow
# or locally:
flyctl deploy --remote-only
```

### Rollback

```bash
fly releases                      # find the previous version number
fly releases rollback <version>   # revert to it
```

Rollback does **not** downgrade the database. If the rolled-back code can't read the current schema, you need to either roll the schema back too (`alembic downgrade <rev>`, via `fly ssh console -C 'alembic downgrade <rev>'`) or hotfix forward.

### Running a one-off command in the app container

```bash
fly ssh console                                       # interactive shell
fly ssh console -C "alembic current"                  # one-off
fly ssh console -C "alembic downgrade -1"             # emergency schema rollback
```

### Tail logs

```bash
fly logs
```

Structured records from the `app.external` logger (A09 external-call logging — see [`docs/security.md`](security.md#a09)) surface here as JSON. Filter with `fly logs | grep external_call`.

### Scale

```bash
fly scale count 2 --region iad          # two machines, auto-load-balanced
fly scale memory 1024                   # upgrade RAM
fly scale show                          # current counts / sizes
```

If you ever scale past one machine, move the Alembic step out of the container `CMD` into a one-shot release command — otherwise two machines will race on `alembic upgrade head` at deploy time. ADR 0002 flags this.

### Inspect / query the DB

Use the Neon dashboard's SQL editor or connect with `psql`:

```bash
psql "postgres://USER:PASSWORD@ep-xxxxx.us-east-1.aws.neon.tech/neondb?sslmode=require"
```

Note: `psql` wants `postgres://` (libpq) and `sslmode=require` — the *opposite* of asyncpg's `postgresql+asyncpg://` and `ssl=require`. Each driver speaks its own connection-string dialect.

## Troubleshooting

### `TypeError: connect() got an unexpected keyword argument 'sslmode'`

Your `DATABASE_URL` uses libpq's `sslmode=require` syntax. asyncpg uses `ssl=require`. Edit your `.env` (or `fly secrets set` again) and replace the parameter name. Same TLS, different spelling.

### `TypeError: connect() got an unexpected keyword argument 'channel_binding'` (or `gssencmode`, `application_name`, etc.)

Same family of bug — Neon's default copy-paste string includes libpq-only query params asyncpg doesn't understand. Strip everything from the URL except `?ssl=require`. See step 1 above for the canonical form.

### `fly secrets set` fails with `"... is not a valid secret name"`

PowerShell ate the `=` inside `ssl=require`. Use single quotes around the whole `KEY=VALUE` argument:

```powershell
fly secrets set 'DATABASE_URL=postgresql+asyncpg://...?ssl=require'
```

### `POST /v1/market/ingest` returns `200` with `"ingested": 0`

yfinance returned an empty DataFrame. yfinance has been brittle against Yahoo's API for years; if the version pinned in `pyproject.toml` is more than a few months old, bump it. Quick sanity check locally:

```powershell
uv run python -c "import yfinance as yf; print(len(yf.Ticker('NVDA').history(period='1y')))"
```

Expect ~250. If you see 0 + a `possibly delisted` message, your pin is stale: `uv add "yfinance>=1.0"` and update the Dockerfile to match.

### Health check fails immediately after deploy

`fly logs` usually shows the cause. Most common: `DATABASE_URL` is missing or malformed. Check with `fly secrets list`; re-set with `fly secrets set 'DATABASE_URL=...'` (single quotes).

### `prepared statement "__asyncpg_stmt_X__" already exists`

You set `DATABASE_URL` to Neon's `-pooler` endpoint. Either:
- Switch to the direct endpoint (drop `-pooler` from the hostname), or
- Edit [`app/db/session.py`](../app/db/session.py) to pass `connect_args={"statement_cache_size": 0}` to `create_async_engine`.

### First request after idle takes 2–3 seconds

Expected. Fly machine was stopped + Neon compute was suspended; both wake on the first request. Either warm with a cron that hits `/v1/health` every minute, or flip `auto_stop_machines = "off"` + `min_machines_running = 1` in `fly.toml` (~$1.94/mo always-on).

### GitHub Actions deploy fails with "no such app"

Name mismatch between `fly.toml` (`app = "..."`) and the app you created with `fly launch`. Either rename the app or edit `fly.toml` to match.

### Deploy succeeded but the endpoint 502s

Usually the container is still running `alembic upgrade head` when Fly's first health check hits. Grace period in `fly.toml` is 30 s — if migrations take longer than that (unlikely at this schema size), increase `grace_period`.

## Cost watch

- **Neon free:** 500 MB storage, 100 compute hours / month. Dashboard shows usage under *Billing*.
- **Fly:** `fly dashboard` → *Billing*. With `auto_stop_machines = "stop"` and low traffic, expect $0–3/mo.
- Set a monthly spend alert on Fly at $10 until real traffic. Same on Neon when you upgrade to a paid plan.
