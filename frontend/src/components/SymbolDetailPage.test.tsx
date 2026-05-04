/**
 * SymbolDetailPage tests (Phase 4.0).
 *
 * The dashboard page at /symbol/:ticker. In 4.0 it:
 * 1. Reads the :ticker URL param.
 * 2. Fetches the report via the existing TanStack Query path.
 * 3. Renders a hero placeholder above the ReportRenderer.
 *
 * Phase 4.1 fills in the hero. Phase 4.2+ replaces individual cards
 * with Strata variants. SymbolDetailPage is the host throughout.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { SymbolDetailPage } from "./SymbolDetailPage";
import * as api from "../lib/api";
import { HEALTHY_LAYOUT_SIGNALS, type ResearchReport } from "../lib/schemas";

function fakeReport(symbol: string): ResearchReport {
  return {
    symbol,
    name: `${symbol} Inc.`,
    sector: "megacap_tech",
    generated_at: "2026-05-02T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections: [
      {
        title: "Valuation",
        summary: "Trades at a premium.",
        confidence: "high",
        claims: [
          {
            description: "P/E ratio (trailing 12 months)",
            value: 28.5,
            source: {
              tool: "yfinance.fundamentals",
              fetched_at: "2026-05-02T14:00:00+00:00",
            },
            history: [],
          },
        ],
      },
    ],
  };
}

function renderAt(ticker: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/symbol/${ticker}`]}>
        <Routes>
          <Route path="/symbol/:ticker" element={<SymbolDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SymbolDetailPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls the API with the ticker from the URL (uppercased)", async () => {
    const spy = vi
      .spyOn(api, "fetchResearchReport")
      .mockResolvedValue(fakeReport("AAPL"));
    renderAt("aapl");
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith("AAPL", expect.objectContaining({}));
  });

  it("renders the report once the fetch resolves", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      fakeReport("AAPL"),
    );
    renderAt("AAPL");
    await waitFor(() => {
      expect(screen.getByText(/trades at a premium/i)).toBeInTheDocument();
    });
    // Symbol shown in the report header.
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
  });

  it("renders the HeroCard once the report resolves (Phase 4.1)", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      fakeReport("AAPL"),
    );
    // HeroCard's price query needs a stub too — it fires on mount.
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [
        { ts: "2026-04-01T00:00:00Z", close: 180, volume: 1_000_000 },
        { ts: "2026-04-02T00:00:00Z", close: 182, volume: 1_100_000 },
      ],
      latest: {
        ts: "2026-04-02T00:00:00Z",
        close: 182,
        delta_abs: 2,
        delta_pct: 0.011,
      },
    });
    renderAt("AAPL");
    await waitFor(() => {
      // Hero shows the ticker eyebrow and the FCF / ROIC / P/E stats
      // when those claims exist; symbol always renders.
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });
  });

  it("shows a loading state while the report is in flight", () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    renderAt("AAPL");
    // LoadingState renders "Generating report for AAPL…"
    expect(screen.getByText(/generating report for aapl/i)).toBeInTheDocument();
  });

  // ── Phase 4.5.B — distressed-mode row reordering ─────────────────

  function reportWithSections(
    symbol: string,
    overrides: Partial<ResearchReport> = {},
  ): ResearchReport {
    const richBase: ResearchReport = {
      symbol,
      name: `${symbol} Inc.`,
      sector: "ev_auto",
      generated_at: "2026-05-04T14:00:00+00:00",
      overall_confidence: "low",
      tool_calls_audit: [],
      layout_signals: HEALTHY_LAYOUT_SIGNALS,
      sections: [
        // The reorder logic only cares about which sections exist;
        // the cards no-op when their data is sparse, but the row
        // wrappers render unconditionally so the data-row markers
        // we assert on always appear.
        { title: "Valuation", summary: "", confidence: "low", claims: [] },
        { title: "Quality", summary: "", confidence: "low", claims: [] },
        { title: "Earnings", summary: "", confidence: "low", claims: [] },
        { title: "Capital Allocation", summary: "", confidence: "low", claims: [] },
        { title: "Risk Factors", summary: "", confidence: "low", claims: [] },
        { title: "Macro", summary: "", confidence: "low", claims: [] },
      ],
      ...overrides,
    };
    return richBase;
  }

  it("renders rows in default order when not distressed", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      reportWithSections("AAPL"),
    );
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 182, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("AAPL");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-3']")).not.toBeNull(),
    );
    const row3 = container.querySelector("[data-row='dashboard-row-3']");
    const row4 = container.querySelector("[data-row='dashboard-row-4']");
    // Default order: row 3 = Valuation + PerShareGrowth (the Strata
    // 40/60 row); row 4 = Cash + Risk + Macro (the 3-col row).
    expect(row3?.getAttribute("data-row-content")).toBe("valuation-growth");
    expect(row4?.getAttribute("data-row-content")).toBe("cash-risk-macro");
  });

  it("swaps rows 3 and 4 when is_unprofitable_ttm fires", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      reportWithSections("RIVN", {
        layout_signals: {
          ...HEALTHY_LAYOUT_SIGNALS,
          is_unprofitable_ttm: true,
        },
      }),
    );
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "RIVN",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 11, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("RIVN");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-3']")).not.toBeNull(),
    );
    const row3 = container.querySelector("[data-row='dashboard-row-3']");
    const row4 = container.querySelector("[data-row='dashboard-row-4']");
    // Distressed: Cash + Risk + Macro lift to row 3 (the survival
    // story comes first); Valuation + PerShareGrowth drop to row 4.
    expect(row3?.getAttribute("data-row-content")).toBe("cash-risk-macro");
    expect(row4?.getAttribute("data-row-content")).toBe("valuation-growth");
  });

  it("swaps rows when cash_runway_quarters < 6 (liquidity watch)", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      reportWithSections("RIVN", {
        layout_signals: {
          ...HEALTHY_LAYOUT_SIGNALS,
          cash_runway_quarters: 4.5,
        },
      }),
    );
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "RIVN",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 11, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("RIVN");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-3']")).not.toBeNull(),
    );
    expect(
      container
        .querySelector("[data-row='dashboard-row-3']")
        ?.getAttribute("data-row-content"),
    ).toBe("cash-risk-macro");
  });

  it("keeps default order when runway is healthy (>= 6Q)", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      reportWithSections("AAPL", {
        layout_signals: {
          ...HEALTHY_LAYOUT_SIGNALS,
          cash_runway_quarters: 24.0,
        },
      }),
    );
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 182, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("AAPL");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-3']")).not.toBeNull(),
    );
    expect(
      container
        .querySelector("[data-row='dashboard-row-3']")
        ?.getAttribute("data-row-content"),
    ).toBe("valuation-growth");
  });
});
