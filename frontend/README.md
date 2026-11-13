# Market Analysis Agent — Frontend

React 18 + Vite + TypeScript dashboard for the [Market Analysis Agent](../) backend. Live at <https://market-analysis-agent-red.vercel.app> (sign in with the backend's shared secret).

## Screens

| Route | What |
|---|---|
| `/login` | Paste the shared secret; it's probed against `GET /v1/research?limit=1` and kept in `localStorage`. |
| `/` | Search + past reports. |
| `/symbol/:ticker` | The dashboard: section nav, hero, analyst view, Quality / Earnings / Valuation / Per-share growth, Cash & capital · Capital returns · Risk · Macro, Business + News. Adapts to distressed names (pills, hero metric swap, survival cards first). |
| `/compare?a=X&b=Y` | Two tickers side by side. |
| `/lens`, `/lens/:id` | Cross-company lenses (megacap tech capex). |

Every signed-in page has the sidebar (Search ⌘K, Home, Compare, Lenses, Watchlist, Recent) and the market strip.

## Local dev

```bash
cd frontend
npm install
cp .env.example .env.local     # VITE_BACKEND_URL=http://localhost:8000 (or the Fly URL)
npm run dev                    # http://localhost:5173
```

The backend must allow the dev origin: `FRONTEND_ORIGIN=http://localhost:5173` in the root `.env`. With `BACKEND_SHARED_SECRET` unset (the local default) any value works at sign-in.

## Scripts

| Command | What |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | `tsc -b && vite build` → `dist/` (prints each chunk's gzip size) |
| `npm run preview` | Serve the production build locally |
| `npm run test` / `npm run test:watch` | Vitest (happy-dom; count in [docs/testing.md](../docs/testing.md)) |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | ESLint, zero warnings allowed |

CI runs lint, typecheck, test and build on every PR.

## Bundle budget

The main chunk must stay under **100 KB gzipped**; it is 89.85 KB (2026-11-13). Every route except `/` and `/login` is lazy-loaded into its own chunk: dashboard 26.8 KB, demo shell + index 1.8 KB, compare 6.6 KB, lens 4.4 KB (+ 0.7 KB index), search modal 1.3 KB. There is no charting library; charts are hand-rolled SVG. These sizes are kept only here. Check them with `npm run build` before adding a dependency.

## Layout

```
src/
├── App.tsx                 # router + auth guard; lazy routes
├── components/
│   ├── AppShell.tsx        # sidebar + market strip + outlet; global ⌘K
│   ├── SidebarShell.tsx    # navigation + live Watchlist / Recent; collapses to a rail
│   ├── MarketStrip.tsx     # headline quotes + fear & greed (est.) panel
│   ├── SymbolDetailPage.tsx# the dashboard (lazy) and its cards: HeroCard,
│   │                       #   AnalystViewCard, QualityCard, EarningsCard, ValuationCard,
│   │                       #   PerShareGrowthCard, CashAndCapitalCard, CapitalReturnsCard,
│   │                       #   RiskDiffCard, MacroPanel, BusinessCard, NewsList …
│   ├── SectionNav.tsx      # sticky in-page nav built from data-section-* anchors
│   ├── ErrorBoundary.tsx   # per card, per page, silent for the strip
│   ├── LineChart / MultiLine / EpsChart / PeerScatterV2 / Sparkline
│   │                       # hand-rolled SVG primitives
│   ├── compare/            # ComparePage (lazy) and its rows
│   ├── lens/               # LensPage, LensIndexPage, DistributionChart, CapexBars (lazy)
│   └── search/             # SearchModal (lazy)
└── lib/
    ├── api.ts              # the only fetch caller — typed ApiError, Zod validation
    ├── schemas.ts          # Zod mirrors of the backend Pydantic models (tolerant of new units)
    ├── *-extract.ts        # one pure extractor per card: report → what the card draws
    ├── format.ts           # unit-aware claim formatting (mirrors the backend's display units)
    ├── stored-list.ts      # watchlist / recent in localStorage via useSyncExternalStore
    └── thesis.ts, lens.ts, sidebar.ts, routes.ts …
```

Conventions: components never call `fetch` (go through `lib/api.ts`); cards take a `Section` and run an extractor, so the parsing logic is unit-tested without rendering; a card with nothing to show returns `null` and the layout counts only cards that render.

## Deploying to Vercel

The project is already connected: a push to `main` builds `frontend/` (Root Directory `frontend`, Vite preset, settings from `vercel.json`, which also rewrites every path to `index.html` for client-side routes). The only environment variable is `VITE_BACKEND_URL=https://market-analysis-agent.fly.dev`; the shared secret is typed at sign-in, never baked into the build.

The backend must list the Vercel origin: `FRONTEND_ORIGIN` in `fly.toml` (exact match, no trailing slash). Full runbook in [docs/deployment.md](../docs/deployment.md).

## Why these choices

- **Vite over Next.js:** a static SPA against a separate API; SSR adds nothing here.
- **TanStack Query** owns server state (reports, prices, overview, lenses); local state + `useSyncExternalStore` for the small localStorage lists. No global store.
- **Zod** validates every response before a component sees it, so backend drift fails loudly in one place — and unknown claim units degrade to a heuristic format instead of failing the report.
- **Hand-rolled SVG charts:** each chart is small and specific (axes, baselines, hover, direct labels), and it keeps a ~100 KB charting library out of the bundle (Recharts was removed in 2026-11).
- **Tailwind with Strata tokens** (`tailwind.config`): one dark theme, named colors per section.
- **`localStorage` for the token:** simple and persistent; the XSS surface is small (no third-party scripts, no user HTML).
