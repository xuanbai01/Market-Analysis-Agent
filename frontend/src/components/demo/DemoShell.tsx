/**
 * DemoShell — the frame around the public demo pages.
 *
 * No sidebar, search, watchlist or market strip: those need the signed-in
 * API. A top bar names what this is, links the demo tickers and offers
 * sign-in. Everything inside reads through the open demo routes.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { fetchDemoIndex } from "../../lib/api";
import { DemoContext } from "../../lib/demo";
import { ROUTES } from "../../lib/routes";
import { ErrorBoundary } from "../ErrorBoundary";

export default function DemoShell() {
  const location = useLocation();
  const index = useQuery({ queryKey: ["demo-index"], queryFn: fetchDemoIndex, staleTime: 300_000 });
  const symbols = index.data?.symbols ?? [];

  return (
    <DemoContext.Provider value={true}>
      <div className="min-h-full bg-strata-canvas">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-strata-line px-4 py-3 sm:px-6">
          <Link to={ROUTES.demo} className="text-sm font-semibold text-strata-hi">
            Market Analysis Agent
          </Link>
          <span className="rounded border border-strata-border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
            Read-only demo
          </span>
          <nav aria-label="Demo tickers" className="flex flex-wrap items-center gap-1.5">
            {symbols.map(({ symbol }) => (
              <NavLink
                key={symbol}
                to={ROUTES.demoSymbol(symbol)}
                className={({ isActive }) =>
                  `rounded px-2 py-0.5 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight ${
                    isActive ? "bg-strata-raise text-strata-hi" : "text-strata-dim hover:text-strata-hi"
                  }`
                }
              >
                {symbol}
              </NavLink>
            ))}
          </nav>
          <Link
            to={ROUTES.login}
            className="ml-auto font-mono text-[11px] text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
          >
            Sign in
          </Link>
        </header>
        <main>
          <ErrorBoundary label="This page" variant="page" resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </DemoContext.Provider>
  );
}
