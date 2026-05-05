/**
 * SidebarShell — 72px-wide left rail visible across authenticated
 * routes. Brand logo at the top, 5 vertical nav buttons (Search,
 * Compare, Watchlist, Recent, Export).
 *
 * Phase 4.0 wired only Search. Phase 4.6.A enabled Compare. Phase 4.7
 * activates Watchlist + Recent and lights up the count badges.
 *
 *   - Search    — activated 4.0 (modal lands in 4.7)
 *   - Compare   — activated 4.6 (when onCompareClick is provided)
 *   - Watchlist — activated 4.7 (when onWatchlistClick is provided;
 *                badge shows when watchlistCount > 0)
 *   - Recent    — activated 4.7 (when onRecentClick is provided;
 *                badge shows when recentCount > 0)
 *   - Export    — TBD (always disabled)
 *
 * Each non-Search button's enabled state derives from the presence of
 * its onClick handler — keeps the component backward-compatible with
 * pre-4.6 callers that only passed ``onSearchClick``.
 *
 * Router-agnostic by design: the parent passes ``active`` so this
 * component is testable without MemoryRouter.
 */

export type SidebarKey =
  | "search"
  | "compare"
  | "watchlist"
  | "recent"
  | "export"
  | "none";

interface Props {
  active: SidebarKey;
  onSearchClick: () => void;
  // Phase 4.6 / 4.7 — optional click handlers. Presence enables the
  // corresponding nav button.
  onCompareClick?: () => void;
  onWatchlistClick?: () => void;
  onRecentClick?: () => void;
  // Phase 4.7 — count badges. > 0 → render badge; 0 / undefined →
  // hide.
  watchlistCount?: number;
  recentCount?: number;
}

interface NavItem {
  key: Exclude<SidebarKey, "none">;
  label: string;
  /** Inline SVG path or unicode glyph. */
  icon: string;
}

const NAV: NavItem[] = [
  { key: "search", label: "Search", icon: "⌕" },
  { key: "compare", label: "Compare", icon: "◫" },
  { key: "watchlist", label: "Watchlist", icon: "★" },
  { key: "recent", label: "Recent", icon: "◷" },
  { key: "export", label: "Export", icon: "⎙" },
];

export function SidebarShell({
  active,
  onSearchClick,
  onCompareClick,
  onWatchlistClick,
  onRecentClick,
  watchlistCount,
  recentCount,
}: Props) {
  // Map each nav key to (handler, enabled, badgeCount).
  const wiring: Record<
    Exclude<SidebarKey, "none">,
    { handler: (() => void) | undefined; enabled: boolean; badgeCount?: number }
  > = {
    search: { handler: onSearchClick, enabled: true },
    compare: { handler: onCompareClick, enabled: Boolean(onCompareClick) },
    watchlist: {
      handler: onWatchlistClick,
      enabled: Boolean(onWatchlistClick),
      badgeCount: watchlistCount,
    },
    recent: {
      handler: onRecentClick,
      enabled: Boolean(onRecentClick),
      badgeCount: recentCount,
    },
    export: { handler: undefined, enabled: false },
  };
  return (
    <aside
      data-sidebar="strata"
      className="flex w-[72px] flex-shrink-0 flex-col items-center gap-4 border-r border-strata-line bg-strata-canvas/60 py-6"
    >
      {/* Brand mark — placeholder square until proper logo lands */}
      <div
        aria-label="Brand logo"
        className="flex h-9 w-9 items-center justify-center rounded-lg bg-strata-highlight font-mono text-sm font-bold text-strata-canvas shadow-[0_8px_24px_-8px_rgba(126,154,212,0.5)]"
      >
        R
      </div>
      <div className="my-1 h-px w-6 bg-strata-line" />

      {NAV.map((item) => {
        const wire = wiring[item.key];
        const isActive = active === item.key;
        const isClickable = wire.enabled;
        const badgeCount = wire.badgeCount;
        const showBadge = typeof badgeCount === "number" && badgeCount > 0;
        return (
          <div key={item.key} className="relative">
            <button
              type="button"
              aria-current={isActive ? "page" : undefined}
              aria-label={item.label}
              disabled={!isClickable}
              onClick={wire.handler}
              className={[
                "flex h-9 w-9 items-center justify-center rounded-lg text-base transition",
                isActive
                  ? "border border-strata-highlight/40 bg-strata-highlight/10 text-strata-highlight"
                  : "border border-transparent text-strata-dim",
                isClickable
                  ? "hover:bg-strata-raise hover:text-strata-fg"
                  : "cursor-not-allowed opacity-50",
              ].join(" ")}
            >
              {item.icon}
            </button>
            {showBadge && (
              <span
                data-badge={`${item.key}-count`}
                className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-strata-highlight px-1 font-mono text-[9px] font-bold text-strata-canvas"
              >
                {badgeCount}
              </span>
            )}
          </div>
        );
      })}
    </aside>
  );
}
