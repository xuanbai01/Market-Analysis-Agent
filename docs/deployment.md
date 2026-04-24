# Deployment

Runbook for deploying the Market Analysis Agent to Fly.io with a Neon Postgres backend. Architectural rationale is in [ADR 0002](adr/0002-deployment.md); this document is purely operational.

## First-time setup (~20 minutes, done once)

### 1. Create the Neon project (5 min)

1. Sign up at <https://neon.tech> (free tier is fine).
2. Create a new project. Pick a region near your Fly region — `US East (Ohio)` pairs well with Fly's `iad`.
3. On the project dashboard, under **Connection details**, copy the **Connection string** (not the direct host, the one already formatted as a URI). It looks like:
   ```
   postgres://USER:PASSWORD@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. **Convert the scheme** from `postgres://` to `postgresql+asyncpg://` for async SQLAlchemy. Final form:
   ```
   postgresql+asyncpg://USER:PASSWORD@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
   Hang on to this string — you'll paste it into Fly secrets below.

> **Don't use the `-pooler` endpoint for MVP.** asyncpg + Neon's transaction-mode pooler requires `statement_cache_size=0` on the engine. ADR 0002 calls this out; we default to the direct endpoint until a single Fly machine bumps the connection cap.

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
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require"
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
psql "postgres://USER:PASSWORD@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require"
```

(Note: `psql` wants `postgres://`, not `postgresql+asyncpg://` — strip the driver suffix.)

## Troubleshooting

### Health check fails immediately after deploy

`fly logs` usually shows the cause. Most common: `DATABASE_URL` is missing or malformed. Check with `fly secrets list`; re-set with `fly secrets set DATABASE_URL=...`.

### "prepared statement \"__asyncpg_stmt_X__\" already exists"

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
