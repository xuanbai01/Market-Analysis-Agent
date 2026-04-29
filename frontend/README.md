# Market Analysis Agent — Frontend

React + Vite + TypeScript dashboard for the [Market Analysis Agent](../) backend.

Two screens:

- **Login** — paste the shared secret, probe `GET /v1/research?limit=1`, persist the token in `localStorage` on 200, kick the user back here on any subsequent 401.
- **Dashboard** — symbol input + focus dropdown + refresh toggle. Submit → loading state with the "first synth takes ~30s" copy → rendered report. Past-reports sidebar reads `GET /v1/research?limit=20`; clicks re-fetch the full report (cache hit, sub-second).

## Local dev

```bash
cd frontend
npm install
cp .env.example .env.local
# edit .env.local: VITE_BACKEND_URL=http://localhost:8000  (or your Fly URL)

npm run dev          # http://localhost:5173
```

If your backend has `BACKEND_SHARED_SECRET` set, the login screen will demand it. If unset (local dev default), paste anything — `probeAuth` will still 200 because the dep is a pass-through.

## Scripts

| Command            | What                                                      |
|--------------------|-----------------------------------------------------------|
| `npm run dev`      | Vite dev server with HMR                                  |
| `npm run build`    | `tsc -b && vite build` → `dist/`                          |
| `npm run preview`  | Serve the production build locally                        |
| `npm run test`     | Vitest one-shot                                           |
| `npm run test:watch` | Vitest watch                                            |
| `npm run typecheck`| `tsc -b --noEmit`                                         |
| `npm run lint`     | ESLint                                                    |

## Deploying to Vercel

One-time setup:

1. Push the repo to GitHub if you haven't.
2. Vercel → "Add New Project" → import the GitHub repo.
3. **Root Directory:** `frontend`. (This is the key step.)
4. **Framework Preset:** Vite (auto-detected).
5. **Build / output / install commands:** auto-detected from `vercel.json`.
6. **Environment variables:**
   - `VITE_BACKEND_URL=https://market-analysis-agent.fly.dev` (or your Fly app's URL).
   That's the only one — the shared secret is entered by the user at the login screen, not baked in.
7. Deploy.

After the first deploy, set the backend's CORS allowlist:

```bash
fly secrets set FRONTEND_ORIGIN=https://your-app.vercel.app
fly secrets set BACKEND_SHARED_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Then visit your Vercel URL, paste the same `BACKEND_SHARED_SECRET` at the login screen.

## Architecture

```
src/
├── App.tsx                 # 2-state machine: login | dashboard
├── main.tsx                # entry; QueryClientProvider
├── index.css               # tailwind directives + base body styles
├── components/
│   ├── LoginScreen.tsx     # password field, probeAuth, persist token
│   ├── Dashboard.tsx       # form + report + past-reports list, owns 401 handling
│   ├── ReportForm.tsx      # symbol/focus/refresh form
│   ├── ReportRenderer.tsx  # cards: section title, summary prose, claims table
│   ├── PastReportsList.tsx # sidebar
│   ├── ConfidenceBadge.tsx # high/medium/low pill
│   ├── ErrorBanner.tsx     # status-code-aware messaging (401/429/503)
│   └── LoadingState.tsx    # "~30s on first synth" copy
└── lib/
    ├── api.ts              # the only fetch caller — typed errors, Zod validation
    ├── schemas.ts          # Zod mirrors of backend Pydantic models
    ├── auth.ts             # localStorage helpers
    └── format.ts           # display rules for ClaimValue (mirrors backend rubric)
```

## Why these choices

- **Vite over Next.js**: this is a static SPA against a separate backend; Next adds SSR/RSC complexity we don't need.
- **TanStack Query** handles the only stateful surface (server state). No Redux / Zustand.
- **Zod** validates every API response before it hits a component, so backend drift fails loudly here, not three layers deep.
- **localStorage for the token**: simple, persists across tab close, no cookie+CORS gymnastics. XSS surface is small (no third-party scripts, no user-generated HTML).
- **No router**: 2 screens, conditional render. Add `react-router` if/when deep-linkable views land (e.g. `/symbol/AAPL`).
- **Tailwind**: 0 design system, fast iteration, easy to rip out later.

## Test coverage

| File                          | What                                             |
|-------------------------------|--------------------------------------------------|
| `src/lib/schemas.test.ts`     | Zod parses realistic backend payloads; rejects bad shapes (unknown confidence, malformed dates) |
| `src/lib/format.test.ts`      | `formatClaimValue` matches backend rubric display rules (% for fractions, T/B/M abbreviation, etc.) |
| `src/lib/auth.test.ts`        | Token round-trip, graceful localStorage failure |

Component tests (LoginScreen / Dashboard) deferred — the schemas + format tests cover the highest-drift surface; component-render bugs surface immediately on any local refresh.
