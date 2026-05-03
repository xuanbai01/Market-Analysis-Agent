/**
 * SidebarShell — 72px-wide left rail visible across authenticated
 * routes. Brand logo at the top, 5 vertical nav buttons (Search,
 * Compare, Watchlist, Recent, Export).
 *
 * Phase 4.0 wires only Search; the others are visually present but
 * disabled. They activate as features land:
 *
 *   - Search    — activated 4.0 (modal lands in 4.7)
 *   - Compare   — activated 4.6
 *   - Watchlist — activated 4.7
 *   - Recent    — activated 4.7
 *   - Export    — TBD
 *
 * Router-agnostic by design: the parent passes ``active`` so this
 * component is testable without MemoryRouter and reusable across
 * routes (`/` highlights none, `/symbol/:ticker` highlights nothing
 * yet, `/compare` will highlight Compare).
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
}

interface NavItem {
  key: Exclude<SidebarKey, "none">;
  label: string;
  /** Inline SVG path or unicode glyph. Single-character glyphs OK
   *  for now; replace with proper icon set in 4.7+. */
  icon: string;
  enabled: boolean;
}

const NAV: NavItem[] = [
  { key: "search", label: "Search", icon: "⌕", enabled: true },
  { key: "compare", label: "Compare", icon: "◫", enabled: false },
  { key: "watchlist", label: "Watchlist", icon: "★", enabled: false },
  { key: "recent", label: "Recent", icon: "◷", enabled: false },
  { key: "export", label: "Export", icon: "⎙", enabled: false },
];

export function SidebarShell({ active, onSearchClick }: Props) {
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
        const isActive = active === item.key;
        const isClickable = item.enabled;
        return (
          <button
            key={item.key}
            type="button"
            aria-current={isActive ? "page" : undefined}
            aria-label={item.label}
            disabled={!isClickable}
            onClick={item.key === "search" ? onSearchClick : undefined}
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
        );
      })}
    </aside>
  );
}
