/**
 * The public read-only demo (2026-11): what a visitor without the
 * shared secret sees, and what they must not be offered.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "../../lib/api";
import { HEALTHY_LAYOUT_SIGNALS, type ResearchReport } from "../../lib/schemas";
import { LoginScreen } from "../LoginScreen";
import { SymbolDetailPage } from "../SymbolDetailPage";
import DemoIndexPage from "./DemoIndexPage";
import DemoShell from "./DemoShell";

const INDEX = {
  symbols: [
    { symbol: "KO", name: "The Coca-Cola Company", generated_at: "2026-11-13T17:00:00Z" },
    { symbol: "NVDA", name: null, generated_at: "2026-11-12T09:00:00Z" },
  ],
};

function report(symbol: string): ResearchReport {
  const source = { tool: "yfinance.fundamentals", fetched_at: "2026-11-13T17:00:00+00:00" };
  return {
    symbol,
    name: "The Coca-Cola Company",
    sector: "consumer_staples",
    generated_at: "2026-11-13T17:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    thesis: null,
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections: [
      {
        title: "Valuation",
        summary: "Trades at a premium.",
        confidence: "high",
        claims: [{ description: "P/E ratio (trailing 12 months)", value: 29.2, source, history: [] }],
      },
      {
        title: "Business",
        summary: "",
        confidence: "high",
        claims: [{ description: "Business description (from 10-K filing)", value: "Sells beverages.", source, history: [] }],
      },
      {
        title: "Peers",
        summary: "",
        confidence: "high",
        claims: [{ description: "Peers selected for comparison", value: "PEP, PG", source, history: [] }],
      },
    ],
  };
}

function renderDemo(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<DemoShell />}>
            <Route path="/demo" element={<DemoIndexPage />} />
            <Route path="/demo/:ticker" element={<SymbolDetailPage />} />
          </Route>
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "fetchDemoIndex").mockResolvedValue(INDEX);
  vi.spyOn(api, "fetchDemoPrices").mockResolvedValue({
    ticker: "KO",
    range: "60D",
    prices: [],
    latest: { ts: "2026-11-13T00:00:00+00:00", close: 0, delta_abs: 0, delta_pct: 0 },
  });
});

describe("the demo index", () => {
  it("lists each demo ticker as a link to its report", async () => {
    renderDemo("/demo");
    const links = await screen.findAllByTestId("demo-ticker");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/demo/KO", "/demo/NVDA"]);
    expect(links[0]).toHaveTextContent("The Coca-Cola Company");
  });

  it("says so when there is nothing to show", async () => {
    vi.spyOn(api, "fetchDemoIndex").mockResolvedValue({ symbols: [] });
    renderDemo("/demo");
    expect(await screen.findByTestId("demo-empty")).toBeInTheDocument();
  });

  it("offers sign-in from the top bar", async () => {
    renderDemo("/demo");
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});

describe("a report in the demo", () => {
  it("reads through the open demo routes and never the signed-in ones", async () => {
    const demoReport = vi.spyOn(api, "fetchDemoReport").mockResolvedValue(report("KO"));
    const realReport = vi.spyOn(api, "fetchResearchReport");
    const realPrices = vi.spyOn(api, "fetchMarketPrices");

    renderDemo("/demo/ko");

    await waitFor(() => expect(demoReport).toHaveBeenCalledWith("KO"));
    await screen.findByText("The Coca-Cola Company");
    await waitFor(() => expect(api.fetchDemoPrices).toHaveBeenCalled());
    expect(realReport).not.toHaveBeenCalled();
    expect(realPrices).not.toHaveBeenCalled();
  });

  it("shows the report's age without offering to regenerate it or star it", async () => {
    vi.spyOn(api, "fetchDemoReport").mockResolvedValue(report("KO"));
    renderDemo("/demo/KO");

    const freshness = await screen.findByTestId("report-freshness");
    expect(freshness).toHaveTextContent("Generated");
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /watchlist/i })).toBeNull();
    expect(screen.queryByTestId("analyst-view-missing")).toBeNull();
  });

  it("names peers without linking to pages the demo can't open", async () => {
    vi.spyOn(api, "fetchDemoReport").mockResolvedValue(report("KO"));
    renderDemo("/demo/KO");

    const peers = await screen.findByTestId("business-peers");
    expect(peers).toHaveTextContent("PEP");
    expect(peers.querySelectorAll("a")).toHaveLength(0);
  });

  it("does not record the visit in the signed-in recent list", async () => {
    window.localStorage.clear();
    vi.spyOn(api, "fetchDemoReport").mockResolvedValue(report("KO"));
    renderDemo("/demo/KO");
    await screen.findByTestId("report-freshness");
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("KO");
  });

  it("shows the server's message for a ticker that isn't in the demo", async () => {
    vi.spyOn(api, "fetchDemoReport").mockRejectedValue(
      new api.ApiError({ status: 404, title: "Not part of the demo." }),
    );
    renderDemo("/demo/AAPL");
    expect(await screen.findByText(/Not part of the demo/)).toBeInTheDocument();
  });
});

describe("the sign-in page", () => {
  function renderLogin() {
    return render(
      <MemoryRouter>
        <LoginScreen onAuthenticated={() => undefined} />
      </MemoryRouter>,
    );
  }

  it("links to the demo when there is one", async () => {
    renderLogin();
    expect(await screen.findByRole("link", { name: /read-only demo/i })).toHaveAttribute("href", "/demo");
  });

  it("shows no demo link when the demo is off or can't be reached", async () => {
    vi.spyOn(api, "fetchDemoIndex").mockResolvedValue({ symbols: [] });
    renderLogin();
    await waitFor(() => expect(api.fetchDemoIndex).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /read-only demo/i })).toBeNull();

    vi.spyOn(api, "fetchDemoIndex").mockRejectedValue(new Error("offline"));
    renderLogin();
    await waitFor(() => expect(api.fetchDemoIndex).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /read-only demo/i })).toBeNull();
  });
});
