/**
 * AppShell — the persistent chrome for all authenticated routes.
 * Sidebar on the left, page content (via Outlet) on the right.
 *
 * The active sidebar key is derived from the current URL so the
 * sidebar highlight stays in sync with navigation. Search is the
 * default-active state on every route in 4.0 since the modal isn't
 * implemented yet (it just opens a stub on click).
 */
import { Outlet, useLocation } from "react-router-dom";

import { SidebarShell, type SidebarKey } from "./SidebarShell";

function activeKeyForPath(pathname: string): SidebarKey {
  if (pathname.startsWith("/compare")) return "compare";
  // /symbol/:ticker and / both leave the sidebar in a neutral
  // "none" state — Search is reachable but not "active" the way
  // a navigated-to section would be.
  return "none";
}

export function AppShell() {
  const location = useLocation();
  const active = activeKeyForPath(location.pathname);

  function handleSearch() {
    // Phase 4.7 replaces this with a real modal. For now, focus the
    // search bar on the landing page if the user is there, or no-op
    // (a small visual hint could land in 4.1 — TBD).
    const input = document.querySelector<HTMLInputElement>(
      "input[name='symbol-search']",
    );
    input?.focus();
  }

  return (
    <div className="flex min-h-full bg-strata-canvas text-strata-fg">
      <SidebarShell active={active} onSearchClick={handleSearch} />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
