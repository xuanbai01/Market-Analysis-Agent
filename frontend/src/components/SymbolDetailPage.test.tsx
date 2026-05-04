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

  // ── Phase 4.5.C — layout polish ──────────────────────────────────

  it("renders ContextBand AFTER row 4, not between hero and row 2", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue({
      ...reportWithSections("AAPL"),
      sections: [
        ...reportWithSections("AAPL").sections,
        { title: "Business", summary: "", confidence: "low", claims: [] },
        { title: "News", summary: "", confidence: "low", claims: [] },
      ],
    });
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 182, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("AAPL");
    await waitFor(() =>
      expect(container.querySelector("[data-testid='context-band']")).not.toBeNull(),
    );
    // ContextBand's DOM position must come AFTER row 4 in source order.
    const all = Array.from(
      container.querySelectorAll(
        "[data-row='dashboard-row-4'], [data-testid='context-band']",
      ),
    );
    const row4Index = all.findIndex(
      (el) => el.getAttribute("data-row") === "dashboard-row-4",
    );
    const ctxIndex = all.findIndex(
      (el) => el.getAttribute("data-testid") === "context-band",
    );
    expect(row4Index).toBeGreaterThanOrEqual(0);
    expect(ctxIndex).toBeGreaterThan(row4Index);
  });

  it("collapses row 4 to a single column when only Cash & Capital is populated", async () => {
    // Sections WITHOUT Risk Factors / Macro — Cash & Capital
    // (cross-section) still renders because Quality is present.
    const minimalReport = reportWithSections("AAPL", {
      sections: [
        { title: "Valuation", summary: "", confidence: "low", claims: [] },
        { title: "Quality", summary: "", confidence: "low", claims: [] },
        { title: "Earnings", summary: "", confidence: "low", claims: [] },
        { title: "Capital Allocation", summary: "", confidence: "low", claims: [] },
        // No Risk Factors, no Macro — both should yield null cards.
      ],
    });
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(minimalReport);
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 182, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("AAPL");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-4']")).not.toBeNull(),
    );
    const row4 = container.querySelector("[data-row='dashboard-row-4']");
    // Card count attribute: 1 = single-column collapse.
    expect(row4?.getAttribute("data-card-count")).toBe("1");
  });

  it("renders row 4 as 3-col grid when all three cards are populated", async () => {
    // The reportWithSections fixture includes Risk Factors + Macro
    // sections, but with empty claims — for this test we want the
    // cards to actually render, so add some minimal claims.
    const richReport = reportWithSections("AAPL");
    const riskSection = richReport.sections.find((s) => s.title === "Risk Factors");
    if (riskSection) {
      riskSection.claims = [
        {
          description: "Newly added risk paragraphs vs prior 10-K",
          value: 4,
          source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-04T14:00:00+00:00" },
          history: [],
        },
        {
          description: "Risk paragraphs dropped vs prior 10-K",
          value: 1,
          source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-04T14:00:00+00:00" },
          history: [],
        },
        {
          description: "Risk paragraphs kept (carryover)",
          value: 80,
          source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-04T14:00:00+00:00" },
          history: [],
        },
        {
          description: "Item 1A char delta vs prior 10-K",
          value: 200,
          source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-04T14:00:00+00:00" },
          history: [],
        },
      ];
    }
    const macroSection = richReport.sections.find((s) => s.title === "Macro");
    if (macroSection) {
      macroSection.claims = [
        {
          description: "10Y Treasury yield (latest observation)",
          value: 4.1,
          source: { tool: "fred.macro", fetched_at: "2026-05-04T14:00:00+00:00" },
          history: [
            { period: "2024-01", value: 4.5 },
            { period: "2024-02", value: 4.3 },
            { period: "2024-03", value: 4.2 },
            { period: "2024-04", value: 4.1 },
          ],
        },
      ];
    }
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(richReport);
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue({
      ticker: "AAPL",
      range: "60D",
      prices: [],
      latest: { ts: "2026-04-02T00:00:00Z", close: 182, delta_abs: 0, delta_pct: 0 },
    });
    const { container } = renderAt("AAPL");
    await waitFor(() =>
      expect(container.querySelector("[data-row='dashboard-row-4']")).not.toBeNull(),
    );
    const row4 = container.querySelector("[data-row='dashboard-row-4']");
    expect(row4?.getAttribute("data-card-count")).toBe("3");
  });

  it("uses items-start on every multi-column row for honest height alignment", async () => {
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
    // Every row's grid wrapper carries ``items-start`` so cards align
    // top instead of stretching to row height — 4.5.C layout polish.
    const rows = container.querySelectorAll("[data-row^='dashboard-row-']");
    expect(rows.length).toBeGreaterThan(0);
    rows.forEach((row) => {
      const gridChild = row.querySelector(".grid");
      expect(gridChild?.className ?? "").toMatch(/items-start/);
    });
  });

  it("uses a wider container (max-w-screen-2xl) so dashboards breathe on big monitors", async () => {
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
      expect(container.querySelector("[data-testid='dashboard-container']")).not.toBeNull(),
    );
    const wrapper = container.querySelector("[data-testid='dashboard-container']");
    expect(wrapper?.className ?? "").toMatch(/max-w-screen-2xl/);
  });
});
