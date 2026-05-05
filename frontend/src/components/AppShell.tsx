/**
 * AppShell — the persistent chrome for all authenticated routes.
 * Sidebar on the left, page content (via Outlet) on the right.
 *
 * Phase 4.7 wires:
 *   - ⌘K (Cmd+K on macOS, Ctrl+K elsewhere) opens the SearchModal
 *     from anywhere. The modal itself is lazy-loaded so the main
 *     bundle pays only the dynamic-import shim.
 *   - Sidebar Search button also opens the modal (same handler).
 *   - Sidebar Compare / Watchlist / Recent click handlers navigate
 *     via react-router. Watchlist + Recent count badges read from
 *     localStorage.
 *
 * The lazy SearchModal split keeps main bundle lean — the modal is
 * a 4.7-only UI surface and most page-loads never open it.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { listRecent } from "../lib/recent";
import { ROUTES } from "../lib/routes";
import { listWatchlist } from "../lib/watchlist";
import { SidebarShell, type SidebarKey } from "./SidebarShell";

const SearchModal = lazy(() => import("./search/SearchModal"));

function activeKeyForPath(pathname: string): SidebarKey {
  if (pathname.startsWith("/compare")) return "compare";
  // /symbol/:ticker and / both leave the sidebar in a neutral
  // "none" state — Search is reachable but not "active" the way
  // a navigated-to section would be.
  return "none";
}

/** Match Cmd+K on Mac, Ctrl+K elsewhere. */
function isOpenSearchShortcut(e: KeyboardEvent): boolean {
  if (e.key !== "k" && e.key !== "K") return false;
  return e.metaKey || e.ctrlKey;
}

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const active = activeKeyForPath(location.pathname);

  const [searchOpen, setSearchOpen] = useState(false);

  // Counts re-read whenever the route changes — visiting /symbol/:X
  // pushes onto recent, so when the user navigates back the badge
  // reflects the latest. Keeps state simple: no global pub/sub.
  const [watchlistCount, setWatchlistCount] = useState(0);
  const [recentCount, setRecentCount] = useState(0);
  useEffect(() => {
    setWatchlistCount(listWatchlist().length);
    setRecentCount(listRecent().length);
  }, [location.pathname]);

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

  function handleSearchClick() {
    setSearchOpen(true);
  }

  function handleSearchSelect(ticker: string) {
    setSearchOpen(false);
    navigate(ROUTES.symbol(ticker));
  }

  function handleCompareClick() {
    // Phase 4.6 — navigate to compare with the most-recent two
    // tickers when available, or NVDA / AVGO as a sensible default.
    const recent = listRecent();
    const a = recent[0] ?? "NVDA";
    const b = recent[1] ?? (a === "AVGO" ? "NVDA" : "AVGO");
    navigate(`${ROUTES.compare}?a=${a}&b=${b}`);
  }

  function handleWatchlistClick() {
    // No dedicated watchlist page yet — surface via search modal
    // so the user can pick a watched ticker to open. Future 4.7.B
    // can grow this into a /watchlist route if needed.
    setSearchOpen(true);
  }

  function handleRecentClick() {
    // Same posture as Watchlist — surface inside the search modal.
    setSearchOpen(true);
  }

  return (
    <div className="flex min-h-full bg-strata-canvas text-strata-fg">
      <SidebarShell
        active={active}
        onSearchClick={handleSearchClick}
        onCompareClick={handleCompareClick}
        onWatchlistClick={handleWatchlistClick}
        onRecentClick={handleRecentClick}
        watchlistCount={watchlistCount}
        recentCount={recentCount}
      />
      <main className="flex-1 overflow-y-auto">
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
