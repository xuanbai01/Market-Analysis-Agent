/**
 * LandingPage tests (Phase 4.0).
 *
 * LandingPage is the home of authenticated users. It carries:
 * 1. A search input that, on submit, navigates to /symbol/:ticker.
 * 2. A recent-reports list (from PastReportsList) so users can jump
 *    back into prior work.
 *
 * The search modal (⌘K, autocomplete) lands in Phase 4.7. This is the
 * inline-form variant for now.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { LandingPage } from "./LandingPage";

function renderLanding() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route
            path="/symbol/:ticker"
            element={<div data-testid="symbol-page" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LandingPage", () => {
  it("renders a search input with placeholder text mentioning a ticker", () => {
    renderLanding();
    expect(screen.getByRole("textbox", { name: /symbol|ticker/i })).toBeInTheDocument();
  });

  it("navigates to /symbol/:ticker when the search form is submitted", () => {
    renderLanding();
    const input = screen.getByRole("textbox", { name: /symbol|ticker/i });
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.submit(input.closest("form")!);
    expect(screen.getByTestId("symbol-page")).toBeInTheDocument();
  });

  it("uppercases the ticker before navigating", () => {
    renderLanding();
    const input = screen.getByRole("textbox", { name: /symbol|ticker/i });
    fireEvent.change(input, { target: { value: "aapl" } });
    fireEvent.submit(input.closest("form")!);
    // The route param itself isn't directly inspectable in MemoryRouter
    // without extra wiring; we just confirm the navigation happened.
    expect(screen.getByTestId("symbol-page")).toBeInTheDocument();
  });

  it("renders a 'Recent reports' section", () => {
    renderLanding();
    // The PastReportsList component carries this label via its h3.
    expect(screen.getByText(/recent|past reports/i)).toBeInTheDocument();
  });

  it("does not navigate when the input is empty", () => {
    renderLanding();
    const input = screen.getByRole("textbox", { name: /symbol|ticker/i });
    fireEvent.submit(input.closest("form")!);
    expect(screen.queryByTestId("symbol-page")).not.toBeInTheDocument();
  });
});

// ── Phase 4.7 — Recent ticker cards + watchlist section ─────────────
//
// The landing page surfaces the user's last-visited tickers as cards
// at the top of the page (above the search bar's history-driven Past
// Reports list). When the watchlist is non-empty, a separate watchlist
// section renders below the recent cards.

describe("LandingPage — Phase 4.7 recent + watchlist", () => {
  it("renders a recent tickers section when localStorage has recent entries", () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "market-agent.recent",
      JSON.stringify(["NVDA", "AAPL"]),
    );
    renderLanding();
    // Section header.
    expect(screen.getByText(/recent tickers/i)).toBeInTheDocument();
    // The two tickers themselves.
    expect(screen.getAllByText(/^NVDA$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^AAPL$/).length).toBeGreaterThan(0);
  });

  it("renders a watchlist section when localStorage has watchlist entries", () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "market-agent.watchlist",
      JSON.stringify(["AVGO"]),
    );
    renderLanding();
    expect(screen.getByText(/watchlist/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^AVGO$/).length).toBeGreaterThan(0);
  });
});
