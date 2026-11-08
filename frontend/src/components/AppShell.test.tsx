/**
 * AppShell tests — the wiring between the URL, the stored ticker lists
 * and the sidebar. The sidebar's own rendering is pinned in
 * SidebarShell.test.tsx; these cover what only the whole shell shows.
 */
import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";

import { AppShell } from "./AppShell";
import { WatchlistButton } from "./WatchlistButton";
import { getStoredToken, setStoredToken } from "../lib/auth";
import { pushRecent } from "../lib/recent";
import { readSidebarCollapsed } from "../lib/sidebar";
import { addToWatchlist, listWatchlist } from "../lib/watchlist";

function SymbolStub() {
  const { ticker = "" } = useParams();
  return (
    <div data-testid="symbol-page">
      {ticker}
      <WatchlistButton ticker={ticker} />
    </div>
  );
}

function CompareStub() {
  const { search } = useLocation();
  return <div data-testid="compare-page">{search}</div>;
}

function renderShell(path: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<div data-testid="login-page" />} />
          <Route element={<AppShell />}>
            <Route path="/" element={<div data-testid="landing-page" />} />
            <Route path="/symbol/:ticker" element={<SymbolStub />} />
            <Route path="/compare" element={<CompareStub />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const watchlistSection = () => screen.getByRole("region", { name: "Watchlist" });
const recentSection = () => screen.getByRole("region", { name: "Recent" });

describe("AppShell — sidebar stays in step with the page", () => {
  it("shows a ticker under Watchlist the moment its star is clicked", () => {
    renderShell("/symbol/KO");
    expect(within(watchlistSection()).queryByRole("link", { name: "KO" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    expect(within(watchlistSection()).getByRole("link", { name: "KO" })).toBeInTheDocument();
  });

  it("empties the page's star when the ticker is removed from the sidebar", () => {
    addToWatchlist("KO");
    renderShell("/symbol/KO");
    expect(screen.getByRole("button", { name: "Remove from watchlist" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove KO from watchlist" }));
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(listWatchlist()).toEqual([]);
  });

  it("adds a ticker to Recent when a page records it", () => {
    renderShell("/");
    act(() => {
      pushRecent("RIVN");
    });
    expect(within(recentSection()).getByRole("link", { name: "RIVN" })).toBeInTheDocument();
  });

  it("lists a starred ticker once — under Watchlist, not Recent too", () => {
    pushRecent("JPM");
    pushRecent("KO");
    addToWatchlist("KO");
    renderShell("/");
    expect(within(watchlistSection()).getByRole("link", { name: "KO" })).toBeInTheDocument();
    expect(within(recentSection()).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "JPM",
    ]);
  });

  it("clears Recent from its header", () => {
    pushRecent("JPM");
    renderShell("/");
    fireEvent.click(screen.getByRole("button", { name: "Clear recent tickers" }));
    expect(within(recentSection()).queryAllByRole("link")).toHaveLength(0);
  });
});

describe("AppShell — navigation", () => {
  it("opens a ticker from the sidebar and marks it current", () => {
    pushRecent("JPM");
    renderShell("/");
    fireEvent.click(within(recentSection()).getByRole("link", { name: "JPM" }));
    expect(screen.getByTestId("symbol-page")).toHaveTextContent("JPM");
    expect(screen.getByRole("link", { name: "JPM" })).toHaveAttribute("aria-current", "page");
  });

  it("offers the ticker on screen against the user's previous one", () => {
    pushRecent("JPM");
    pushRecent("KO");
    renderShell("/symbol/KO");
    const compare = screen.getByRole("link", { name: "Compare KO vs JPM" });
    fireEvent.click(compare);
    expect(screen.getByTestId("compare-page")).toHaveTextContent("?a=KO&b=JPM");
  });

  it("keeps the pair on screen while on the compare page", () => {
    pushRecent("NVDA");
    renderShell("/compare?a=AAPL&b=MSFT");
    expect(screen.getByRole("link", { name: "Compare AAPL vs MSFT" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("signs out: forgets the token and goes to the login page", () => {
    setStoredToken("secret");
    renderShell("/");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(getStoredToken()).toBeNull();
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
  });

  it("remembers the collapsed choice", () => {
    renderShell("/");
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    expect(readSidebarCollapsed()).toBe(true);
  });

  it("opens the search modal with Ctrl+K", async () => {
    renderShell("/");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByRole("dialog", { name: /ticker search/i })).toBeInTheDocument();
  });
});
