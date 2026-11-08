/**
 * SidebarShell — the left sidebar on every signed-in page.
 *
 * Rewritten 2026-11. It answers two questions and nothing else:
 *
 *   Where can I go?        Search (opens the ⌘K modal), Home, Compare
 *   What was I looking at? Watchlist (starred tickers), Recent (opened
 *                          tickers not already starred)
 *
 * plus Sign out and a collapse toggle in the footer.
 *
 * Rules:
 *   - Navigation is a link (real href: middle-click, copy link work);
 *     an action (search, remove, clear, sign out, collapse) is a button.
 *   - Active state comes from the URL: Home on "/", Compare on
 *     "/compare", a ticker row on "/symbol/<it>".
 *   - Compare shows the pair it will open ("AAPL vs MSFT"), so the
 *     click is never a surprise.
 *   - Expanded (224 px) on md+ screens unless the user collapsed it;
 *     always the 64 px rail below md. The rail keeps every item —
 *     icons get tooltips, ticker rows stay as compact symbols.
 *
 * Presentational: AppShell owns the URL, storage and modal wiring and
 * passes plain values in, so this component renders the same in tests.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { ComparePair } from "../lib/sidebar";
import { ROUTES } from "../lib/routes";
import {
  BrandMark,
  IconClock,
  IconClose,
  IconCollapse,
  IconCompare,
  IconExpand,
  IconHome,
  IconSearch,
  IconSignOut,
  IconStar,
} from "./icons";

export interface SidebarShellProps {
  /** User chose the rail. Below md the rail shows regardless. */
  collapsed: boolean;
  onToggleCollapsed: () => void;
  pathname: string;
  /** Ticker of the symbol page on screen, else null. */
  currentTicker: string | null;
  compare: ComparePair;
  compareHref: string;
  watchlist: readonly string[];
  /** Recent tickers to list — already capped and without starred ones. */
  recent: readonly string[];
  searchShortcut: string;
  onSearch: () => void;
  onUnwatch: (ticker: string) => void;
  onClearRecent: () => void;
  onSignOut: () => void;
}

export function SidebarShell(props: SidebarShellProps) {
  const {
    collapsed,
    onToggleCollapsed,
    pathname,
    currentTicker,
    compare,
    compareHref,
    watchlist,
    recent,
    searchShortcut,
    onSearch,
    onUnwatch,
    onClearRecent,
    onSignOut,
  } = props;
  const layout = layoutClasses(collapsed);
  const compareLabel = `${compare.a} vs ${compare.b}`;

  return (
    <aside
      id="app-sidebar"
      data-sidebar="strata"
      data-collapsed={collapsed ? "true" : "false"}
      className={[
        "sticky top-0 flex h-screen flex-shrink-0 flex-col border-r border-strata-line bg-strata-canvas transition-[width] duration-150",
        layout.width,
      ].join(" ")}
    >
      <div className="px-2 pb-3 pt-5">
        <Link
          to={ROUTES.landing}
          aria-label="Market Analysis Agent home"
          title={collapsed ? "Market Analysis Agent" : undefined}
          className={`flex h-9 items-center gap-2.5 rounded-md px-1.5 ${layout.align} focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight`}
        >
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-strata-highlight text-strata-canvas">
            <BrandMark />
          </span>
          {layout.label && (
            <span className={`${layout.label} truncate text-sm font-semibold tracking-tight text-strata-hi`}>
              Market Agent
            </span>
          )}
        </Link>
      </div>

      <nav aria-label="Main" className="flex flex-col gap-0.5 px-2">
        <button
          type="button"
          onClick={onSearch}
          aria-label="Search tickers"
          aria-keyshortcuts={searchShortcut === "⌘K" ? "Meta+K" : "Control+K"}
          title={collapsed ? `Search (${searchShortcut})` : undefined}
          className={itemClass(false, layout.align)}
        >
          <IconSearch />
          {layout.label && (
            <>
              <span className={`${layout.label} flex-1 text-left`}>Search</span>
              <kbd className={`${layout.label} rounded border border-strata-border px-1.5 font-mono text-[10px] leading-4 text-strata-muted`}>
                {searchShortcut}
              </kbd>
            </>
          )}
        </button>
        <NavItem
          to={ROUTES.landing}
          label="Home"
          icon={<IconHome />}
          active={pathname === ROUTES.landing}
          collapsed={collapsed}
        />
        <NavItem
          to={compareHref}
          label="Compare"
          ariaLabel={`Compare ${compareLabel}`}
          detail={compareLabel}
          icon={<IconCompare />}
          active={pathname.startsWith(ROUTES.compare)}
          collapsed={collapsed}
        />
      </nav>

      <div className="mt-5 flex flex-1 flex-col gap-5 overflow-y-auto px-2 pb-4">
        <TickerSection
          title="Watchlist"
          icon={<IconStar />}
          tickers={watchlist}
          currentTicker={currentTicker}
          collapsed={collapsed}
          emptyText="Star a ticker's page to pin it here."
          rowAction={(ticker) => (
            <button
              type="button"
              onClick={() => onUnwatch(ticker)}
              aria-label={`Remove ${ticker} from watchlist`}
              title="Remove from watchlist"
              className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-strata-muted opacity-0 transition hover:bg-strata-line hover:text-strata-fg focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight group-hover:opacity-100"
            >
              <IconClose />
            </button>
          )}
        />
        <TickerSection
          title="Recent"
          icon={<IconClock />}
          tickers={recent}
          currentTicker={currentTicker}
          collapsed={collapsed}
          emptyText="Tickers you open show up here."
          headerAction={
            recent.length > 0 ? (
              <button
                type="button"
                onClick={onClearRecent}
                aria-label="Clear recent tickers"
                className="rounded px-1 font-mono text-[10px] uppercase tracking-kicker text-strata-muted transition hover:text-strata-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
              >
                Clear
              </button>
            ) : null
          }
        />
      </div>

      <div className="flex flex-col gap-0.5 border-t border-strata-line px-2 py-3">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-controls="app-sidebar"
          aria-expanded={!collapsed}
          title={collapsed ? "Expand sidebar" : undefined}
          // Below md the rail is forced, so the toggle would do nothing.
          className={`${itemClass(false, layout.align)} hidden md:flex`}
        >
          {collapsed ? <IconExpand /> : <IconCollapse />}
          {layout.label && <span className={layout.label}>Collapse</span>}
        </button>
        <button
          type="button"
          onClick={onSignOut}
          aria-label="Sign out"
          title={collapsed ? "Sign out" : undefined}
          className={itemClass(false, layout.align)}
        >
          <IconSignOut />
          {layout.label && <span className={layout.label}>Sign out</span>}
        </button>
      </div>
    </aside>
  );
}

interface Layout {
  width: string;
  align: string;
  /** Class for text that shows only when expanded; null = don't render. */
  label: string | null;
  /** Same, for a label that lays out its own children in a row. */
  labelRow: string | null;
}

/**
 * Collapsed → rail everywhere. Expanded → rail below md, full width
 * from md up; labels exist in the DOM but show from md up.
 */
function layoutClasses(collapsed: boolean): Layout {
  if (collapsed) {
    return { width: "w-16", align: "justify-center", label: null, labelRow: null };
  }
  return {
    width: "w-16 md:w-56",
    align: "justify-center md:justify-start",
    label: "hidden md:inline",
    labelRow: "hidden md:flex",
  };
}

function itemClass(active: boolean, align: string): string {
  return [
    "flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm transition-colors",
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight",
    align,
    active
      ? "bg-strata-raise text-strata-hi"
      : "text-strata-dim hover:bg-strata-raise hover:text-strata-fg",
  ].join(" ");
}

interface NavItemProps {
  to: string;
  label: string;
  ariaLabel?: string;
  /** Muted second line, e.g. the pair Compare will open. */
  detail?: string;
  icon: ReactNode;
  active: boolean;
  collapsed: boolean;
}

function NavItem({ to, label, ariaLabel, detail, icon, active, collapsed }: NavItemProps) {
  const layout = layoutClasses(collapsed);
  return (
    <Link
      to={to}
      aria-label={ariaLabel ?? label}
      aria-current={active ? "page" : undefined}
      title={collapsed ? (ariaLabel ?? label) : undefined}
      className={itemClass(active, layout.align)}
    >
      <span className={active ? "text-strata-highlight" : undefined}>{icon}</span>
      {layout.labelRow && (
        <span className={`${layout.labelRow} min-w-0 flex-1 items-baseline justify-between gap-2`}>
          <span>{label}</span>
          {detail && (
            <span className="truncate font-mono text-[10px] text-strata-muted">{detail}</span>
          )}
        </span>
      )}
    </Link>
  );
}

interface TickerSectionProps {
  title: string;
  icon: ReactNode;
  tickers: readonly string[];
  currentTicker: string | null;
  collapsed: boolean;
  emptyText: string;
  headerAction?: ReactNode;
  rowAction?: (ticker: string) => ReactNode;
}

function TickerSection({
  title,
  icon,
  tickers,
  currentTicker,
  collapsed,
  emptyText,
  headerAction,
  rowAction,
}: TickerSectionProps) {
  const isEmpty = tickers.length === 0;
  // The rail has no room for an empty-state sentence: hide the section.
  if (isEmpty && collapsed) return null;
  const layout = layoutClasses(collapsed);

  return (
    <section
      aria-label={title}
      data-section={title.toLowerCase()}
      className={isEmpty ? "hidden md:block" : undefined}
    >
      <div className={`mb-1 flex h-6 items-center px-2.5 ${layout.align}`}>
        {/* Rail: the icon names the section (tooltip on hover). */}
        <span
          title={title}
          className={`text-strata-muted ${collapsed ? "" : "md:hidden"}`}
        >
          {icon}
        </span>
        {layout.label && (
          <>
            <h2 className="hidden flex-1 font-mono text-[10px] uppercase tracking-kicker text-strata-muted md:block">
              {title}
            </h2>
            {headerAction && <span className="hidden md:block">{headerAction}</span>}
          </>
        )}
      </div>
      {isEmpty ? (
        <p className="px-2.5 text-xs leading-relaxed text-strata-muted">{emptyText}</p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {tickers.map((ticker) => {
            const active = ticker === currentTicker;
            return (
              <li key={ticker} className="group relative">
                <Link
                  to={ROUTES.symbol(ticker)}
                  aria-current={active ? "page" : undefined}
                  className={[
                    "flex h-8 w-full items-center rounded-md px-2.5 font-mono transition-colors",
                    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight",
                    collapsed ? "justify-center text-[11px]" : "justify-center text-[11px] md:justify-start md:text-[13px]",
                    active
                      ? "bg-strata-raise text-strata-hi"
                      : "text-strata-dim hover:bg-strata-raise hover:text-strata-fg",
                  ].join(" ")}
                >
                  <span className="truncate">{ticker}</span>
                </Link>
                {/* Row actions need the expanded width. */}
                {rowAction && layout.label && (
                  <span className="hidden md:block">{rowAction(ticker)}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
