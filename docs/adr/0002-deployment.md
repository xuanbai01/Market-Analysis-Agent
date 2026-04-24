# ADR 0002: Deploy to Fly.io, Postgres on Neon

**Status:** Accepted
**Date:** 2026-04-24
**Deciders:** xuanbai01
**Related:** [ADR 0001](0001-stack-choice.md) (stack choice, explicitly deferred deployment)

## Context

[ADR 0001](0001-stack-choice.md) picked FastAPI + async SQLAlchemy + Postgres but deferred the deployment target. We're now at the Phase 1 exit criterion — "MVP deploy" — and need a live URL before starting Phase 2 (agents + RAG).

Two non-negotiables for Phase 1 MVP:

1. **Cost floor near $0** while traffic is zero. This is a portfolio project; it should stay cheap until real users force the issue.
2. **Works with the existing Dockerfile and Alembic migration flow.** No rewriting deploy artifacts.

Three nice-to-haves:

3. pgvector extension available for when Phase 2 RAG lands.
4. No surprise hard pauses on the DB (a paused DB at demo time is a portfolio-killer).
5. Push-to-deploy from GitHub — the project already runs `ruff + pytest + gitleaks` in CI; add a deploy job on main.

## Options considered

### Option 1: Fly.io (API) + Neon (DB) *(chosen)*
- **Pros:**
  - Fly: native Docker deploys, `auto_stop_machines` scales the API to zero when idle (~1s cold start on the next request), pay-as-you-go at very low numbers for a 512 MB shared-cpu machine.
  - Neon: free tier has no *project pause* — compute autosuspends after ~5 min idle and wakes on connect (~1–2 s). Native pgvector. Separate pgbouncer pooler endpoint when we need it.
  - Both have usable free tiers. Realistic idle cost: **$0–3/mo.**
  - Neon's serverless-style cold start pairs nicely with Fly's scale-to-zero — neither has to be warm when nobody is using the app.
- **Cons:**
  - Two vendors to manage instead of one (two dashboards, two sets of secrets).
  - asyncpg + Neon pooler needs `statement_cache_size=0` to disable prepared statements. We default to Neon's direct endpoint for MVP (no pooler) to dodge this entirely; revisit if a single Fly machine starts bumping the connection cap.

### Option 2: Fly.io (API) + Supabase (DB)
- **Pros:** One vendor for DB + auth + realtime + storage if we ever need them; design_doc originally named Supabase.
- **Cons:** **Supabase free tier pauses the project after 7 days of inactivity** — manual unpause, not compatible with "portfolio link you can send recruiters any time." Paid tier fixes it at **$25/mo flat**, which eats most of the $50–80 design-doc budget before any LLM tokens are spent. We don't currently use Supabase Auth / Realtime / Storage / RLS, so we're paying $25 for Postgres.

### Option 3: Fly.io (API) + Fly Postgres (co-located)
- **Pros:** One vendor. Postgres lives in the same region with private-network latency (sub-ms). No egress cost.
- **Cons:** Fly Postgres is "managed by us, operated by you" — we'd do our own backups and upgrades. No free tier worth naming; smallest instance is $1.94/mo and you pay for disk separately. pgvector needs a manual extension install. Fine for a team, awkward for a solo portfolio project.

### Option 4: Render (single platform)
- **Pros:** Simplest mental model — one dashboard, one deploy button. `render.yaml` auto-provisions the API and Postgres together.
- **Cons:** Free web tier spins down with ~30–60 s cold start; paid tier is $7/mo web + $7/mo Postgres = $14/mo with no scale-to-zero. More expensive than Fly + Neon at idle, not cheaper at any load, and the cold start is user-visible.

### Option 5: Cloud Run + Cloud SQL (GCP)
- **Pros:** True scale-to-zero on compute, generous free tier.
- **Cons:** Cloud SQL's cheapest Postgres is ~$9/mo minimum always-on, undoing the scale-to-zero savings. GCP setup is the most complex of the five options. Not worth it for this stage.

## Decision

**Fly.io for the API, Neon for Postgres.** Both on their free tiers to start.

Deploy flow:

1. `fly launch` once to create the app (reads [`fly.toml`](../../fly.toml) at the repo root).
2. `flyctl secrets set DATABASE_URL=...` pointing at Neon.
3. `git push origin main` triggers the GitHub Actions deploy workflow ([`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml)).
4. The Fly build reuses our existing [Dockerfile](../../Dockerfile), which runs `alembic upgrade head` before `uvicorn` so the schema stays in sync.

## Consequences

### Easier

- **Cost stays at or below $5/mo** until we outgrow either free tier. Comfortably under the design-doc budget.
- pgvector available on Neon free tier — Phase 2 RAG work doesn't need an infra migration.
- Existing Dockerfile + Alembic flow works without modification. The only code change in this PR is adding `pool_pre_ping=True` to the async engine so SQLAlchemy auto-recycles connections that Neon dropped during autosuspend.
- Push-to-deploy from `main` via GitHub Actions — matches the existing CI trigger; one `FLY_API_TOKEN` secret is all the extra configuration.
- `/docs` stays public — deliberate for a portfolio project (recruiters can click through the live OpenAPI). Flip `APP_ENV=prod` + guard it behind auth later.

### Harder

- **Cold starts.** First request after idle pays both Neon's ~1–2s wake + Fly's ~1s machine-start = up to ~3s. Subsequent requests are warm. For a portfolio demo that's fine; for a real SLA, set `min_machines_running = 1` on Fly (~$1.94/mo always-on) and use Neon Pro for always-on compute.
- **Two vendors.** Two dashboards, two sets of secrets, two blast radii. `docs/deployment.md` has the runbook.
- **Migration racing.** `alembic upgrade head` runs in the container CMD. With `min_machines_running = 0` and at most one machine during a deploy, no race. If we ever scale to N > 1 machines, move migrations out of the container CMD into a one-shot release command.
- **Neon free tier caps.** 500 MB storage, 100 hours of compute per month. Plenty for Phase 1; revisit when ingest backfills start eating storage or agent traffic warms the compute hours.

### Locked-in

- **Fly.io as the compute target.** Switching to Render / Cloud Run is a half-day — `fly.toml` has no exotic features — but the deploy workflow would need rewriting.
- **Postgres specifically** (already locked by ADR 0001). Any "Postgres on X" is a drop-in for this project.
- **Push-to-main = deploy.** Anyone with merge rights deploys. Acceptable for a single-maintainer project; add a staging env + manual promotion if that changes.

## Open questions / revisit when

- We start approaching Neon's 100 compute-hour cap, or the DB grows past ~300 MB. Upgrade to Neon Launch ($19/mo) or Pro ($25/mo) at that point — same codebase.
- A single Fly machine can't cover request load. Turn on `min_machines_running = 2`, move migrations out of CMD, consider switching to the Neon pooler endpoint with `statement_cache_size=0`.
- We need Supabase-exclusive features (Auth, RLS, Realtime) for the product. Revisit Option 2; the existing Neon schema migrates over cleanly.
- We need a staging environment. Create a second Fly app + a second Neon branch; configure a `staging` GitHub Actions job.
