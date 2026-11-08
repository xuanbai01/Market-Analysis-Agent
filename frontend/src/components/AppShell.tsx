/**
 * AppShell — the persistent chrome for all signed-in routes: sidebar
 * on the left, the page (via Outlet) on the right, and the ⌘K search
 * modal on top.
 *
 * This is where the sidebar's inputs come from:
 *   - the URL       → active item, the ticker on screen, the Compare pair
 *   - localStorage  → watchlist + recent (live via useWatchlist /
 *                     useRecent), the collapsed preference
 *   - its handlers  → open search, unstar, clear recent, sign out
 *
 * The search modal is lazy-loaded so the main bundle pays only the
 * dynamic-import shim.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";

import { clearStoredToken } from "../lib/auth";
import { clearRecent, useRecent } from "../lib/recent";
import { ROUTE_PATHS, ROUTES } from "../lib/routes";
import {
  comparePair,
  compareHref,
  pairFromSearch,
  readSidebarCollapsed,
  searchShortcutLabel,
  sidebarRecent,
  writeSidebarCollapsed,
} from "../lib/sidebar";
import { removeFromWatchlist, useWatchlist } from "../lib/watchlist";
import { SidebarShell } from "./SidebarShell";

const SearchModal = lazy(() => import("./search/SearchModal"));

/** Match Cmd+K on Mac, Ctrl+K elsewhere. */
function isOpenSearchShortcut(e: KeyboardEvent): boolean {
  if (e.key !== "k" && e.key !== "K") return false;
  return e.metaKey || e.ctrlKey;
}

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const symbolMatch = useMatch(ROUTE_PATHS.symbol);
  const currentTicker = symbolMatch?.params.ticker?.toUpperCase() ?? null;

  const watchlist = useWatchlist();
  const recent = useRecent();

  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [searchOpen, setSearchOpen] = useState(false);

  // Global ⌘K / Ctrl+K listener.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isOpenSearchShortcut(e)) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // On /compare the link keeps the pair on screen; elsewhere it offers
  // the ticker in view against the user's next one.
  const pairOnScreen = location.pathname.startsWith(ROUTES.compare)
    ? pairFromSearch(location.search)
    : null;
  const pair = pairOnScreen ?? comparePair(currentTicker, recent, watchlist);

  function handleToggleCollapsed() {
    setCollapsed((prev) => {
      writeSidebarCollapsed(!prev);
      return !prev;
    });
  }

  function handleSearchSelect(ticker: string) {
    setSearchOpen(false);
    navigate(ROUTES.symbol(ticker));
  }

  function handleSignOut() {
    clearStoredToken();
    queryClient.clear();
    navigate(ROUTES.login, { replace: true });
  }

  return (
    <div className="flex min-h-full bg-strata-canvas text-strata-fg">
      <SidebarShell
        collapsed={collapsed}
        onToggleCollapsed={handleToggleCollapsed}
        pathname={location.pathname}
        currentTicker={currentTicker}
        compare={pair}
        compareHref={compareHref(pair)}
        watchlist={watchlist}
        recent={sidebarRecent(recent, watchlist)}
        searchShortcut={searchShortcutLabel()}
        onSearch={() => setSearchOpen(true)}
        onUnwatch={removeFromWatchlist}
        onClearRecent={clearRecent}
        onSignOut={handleSignOut}
      />
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
      {searchOpen && (
        <Suspense fallback={null}>
          <SearchModal
            isOpen={searchOpen}
            onClose={() => setSearchOpen(false)}
            onSelect={handleSearchSelect}
          />
        </Suspense>
      )}
    </div>
  );
}
