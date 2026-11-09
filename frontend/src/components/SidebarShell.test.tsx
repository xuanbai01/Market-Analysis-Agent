/**
 * SidebarShell tests — the 2026-11 rewrite.
 *
 * Pinned:
 *   1. Navigation is links with real hrefs; actions are buttons.
 *   2. Active state follows the URL (Home, Compare, the ticker row).
 *   3. Compare names the pair it opens.
 *   4. Watchlist / Recent list the tickers, with empty states, and the
 *      row actions (unstar, clear) call their handlers.
 *   5. Collapsed: labels and empty sections go, accessible names stay.
 *   6. No dead controls (the old always-disabled Export is gone).
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SidebarShell, type SidebarShellProps } from "./SidebarShell";

function renderSidebar(overrides: Partial<SidebarShellProps> = {}) {
  const props: SidebarShellProps = {
    collapsed: false,
    onToggleCollapsed: vi.fn(),
    pathname: "/",
    currentTicker: null,
    compare: { a: "AAPL", b: "MSFT" },
    compareHref: "/compare?a=AAPL&b=MSFT",
    watchlist: [],
    recent: [],
    searchShortcut: "Ctrl K",
    onSearch: vi.fn(),
    onUnwatch: vi.fn(),
    onClearRecent: vi.fn(),
    onSignOut: vi.fn(),
    ...overrides,
  };
  const utils = render(
    <MemoryRouter>
      <SidebarShell {...props} />
    </MemoryRouter>,
  );
  return { ...utils, props };
}

describe("SidebarShell — navigation", () => {
  it("links the brand mark and Home to the landing page", () => {
    renderSidebar();
    expect(
      screen.getByRole("link", { name: /market analysis agent home/i }),
    ).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });

  it("opens search from a button that shows the shortcut", () => {
    const { props } = renderSidebar();
    const search = screen.getByRole("button", { name: /search tickers/i });
    expect(search).toHaveTextContent("Ctrl K");
    expect(search).toHaveAttribute("aria-keyshortcuts", "Control+K");
    fireEvent.click(search);
    expect(props.onSearch).toHaveBeenCalledOnce();
  });

  it("Compare is a link that names the pair it opens", () => {
    renderSidebar();
    const compare = screen.getByRole("link", { name: "Compare AAPL vs MSFT" });
    expect(compare).toHaveAttribute("href", "/compare?a=AAPL&b=MSFT");
    expect(compare).toHaveTextContent("AAPL vs MSFT");
  });

  it("marks Home active on the landing page only", () => {
    renderSidebar({ pathname: "/" });
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /^compare/i })).not.toHaveAttribute("aria-current");
  });

  it("marks Compare active on the compare page", () => {
    renderSidebar({ pathname: "/compare" });
    expect(screen.getByRole("link", { name: /^compare/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("links to the lenses and marks them active on a lens page", () => {
    renderSidebar({ pathname: "/lens/megacap-capex" });
    const lenses = screen.getByRole("link", { name: "Lenses" });
    expect(lenses).toHaveAttribute("href", "/lens");
    expect(lenses).toHaveAttribute("aria-current", "page");
  });

  it("signs out from a button", () => {
    const { props } = renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(props.onSignOut).toHaveBeenCalledOnce();
  });

  it("has no disabled or placeholder controls", () => {
    const { container } = renderSidebar();
    expect(container.querySelector("button:disabled")).toBeNull();
    expect(screen.queryByRole("button", { name: /export/i })).toBeNull();
  });
});

describe("SidebarShell — ticker sections", () => {
  it("lists watchlist tickers as links to their pages", () => {
    renderSidebar({ watchlist: ["NVDA", "KO"] });
    const section = screen.getByRole("region", { name: "Watchlist" });
    expect(within(section).getByRole("link", { name: "NVDA" })).toHaveAttribute(
      "href",
      "/symbol/NVDA",
    );
    expect(within(section).getByRole("link", { name: "KO" })).toHaveAttribute(
      "href",
      "/symbol/KO",
    );
  });

  it("lists recent tickers as links", () => {
    renderSidebar({ recent: ["RIVN", "JPM"] });
    const section = screen.getByRole("region", { name: "Recent" });
    expect(within(section).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "RIVN",
      "JPM",
    ]);
  });

  it("marks the ticker on screen as the current page", () => {
    renderSidebar({
      pathname: "/symbol/KO",
      currentTicker: "KO",
      watchlist: ["NVDA", "KO"],
    });
    expect(screen.getByRole("link", { name: "KO" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NVDA" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("removes a ticker from the watchlist with its row button", () => {
    const { props } = renderSidebar({ watchlist: ["NVDA"] });
    fireEvent.click(screen.getByRole("button", { name: "Remove NVDA from watchlist" }));
    expect(props.onUnwatch).toHaveBeenCalledWith("NVDA");
  });

  it("clears recent tickers from the section header", () => {
    const { props } = renderSidebar({ recent: ["RIVN"] });
    fireEvent.click(screen.getByRole("button", { name: "Clear recent tickers" }));
    expect(props.onClearRecent).toHaveBeenCalledOnce();
  });

  it("explains empty sections instead of showing nothing", () => {
    renderSidebar();
    expect(screen.getByText(/star a ticker's page to pin it here/i)).toBeInTheDocument();
    expect(screen.getByText(/tickers you open show up here/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear recent tickers" })).toBeNull();
  });
});

describe("SidebarShell — collapsed rail", () => {
  it("drops the text labels but keeps every accessible name", () => {
    renderSidebar({ collapsed: true, watchlist: ["NVDA"] });
    expect(screen.queryByText("Home")).toBeNull();
    expect(screen.queryByText("Ctrl K")).toBeNull();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("title", "Home");
    expect(screen.getByRole("button", { name: /search tickers/i })).toHaveAttribute(
      "title",
      "Search (Ctrl K)",
    );
    // Ticker rows stay — as compact symbols.
    expect(screen.getByRole("link", { name: "NVDA" })).toBeInTheDocument();
  });

  it("hides empty sections and row actions", () => {
    renderSidebar({ collapsed: true, watchlist: ["NVDA"] });
    expect(screen.queryByRole("region", { name: "Recent" })).toBeNull();
    expect(screen.queryByRole("button", { name: /remove nvda/i })).toBeNull();
  });

  it("toggles with a button that reports its state", () => {
    const { props, container } = renderSidebar({ collapsed: true });
    expect(container.querySelector("aside")).toHaveAttribute("data-collapsed", "true");
    const toggle = screen.getByRole("button", { name: "Expand sidebar" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(props.onToggleCollapsed).toHaveBeenCalledOnce();
  });

  it("offers to collapse when expanded", () => {
    renderSidebar({ collapsed: false });
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
