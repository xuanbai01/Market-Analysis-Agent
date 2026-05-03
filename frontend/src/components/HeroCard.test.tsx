/**
 * HeroCard tests (Phase 4.1).
 *
 * The headline card on /symbol/:ticker. Three columns:
 *   left: ticker meta (logo placeholder, ticker eyebrow, name, big
 *     price, delta, MCAP/VOL/52W meta line)
 *   center: 60-day price chart with range pills
 *   right: 3 featured stats (Forward P/E, ROIC TTM, FCF Margin)
 *
 * Behaviors pinned:
 * 1. Ticker, name, sector tag visible.
 * 2. Latest price and delta render with correct sign coloring.
 * 3. Range pills render; clicking one re-fetches via the prices query.
 * 4. Featured stat block renders 3 stats with eyebrow + value (sub-
 *    context omitted when peer data unavailable).
 * 5. LineChart renders inside the card when prices loaded.
 * 6. Falls back to skeleton when prices in flight.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { HeroCard } from "./HeroCard";
import * as api from "../lib/api";
import type { ResearchReport } from "../lib/schemas";

function fakeReport(opts: Partial<ResearchReport> = {}): ResearchReport {
  return {
    symbol: "NVDA",
    name: "NVIDIA Corporation",
    sector: "megacap_tech",
    generated_at: "2026-05-02T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    sections: [
      {
        title: "Valuation",
        summary: "",
        confidence: "high",
        claims: [
          {
            description: "P/E ratio (forward, analyst consensus)",
            value: 32.1,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
        ],
      },
      {
        title: "Quality",
        summary: "",
        confidence: "high",
        claims: [
          {
            description: "Return on invested capital (TTM)",
            value: 0.61,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
          {
            description: "Free cash flow margin",
            value: 0.421,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
        ],
      },
      {
        title: "Capital Allocation",
        summary: "",
        confidence: "high",
        claims: [
          {
            description: "52-week high",
            value: 921.04,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
          {
            description: "52-week low",
            value: 410.18,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
          {
            description: "Market capitalization",
            value: 2.19e12,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
        ],
      },
    ],
    ...opts,
  };
}

function fakePrices() {
  return {
    ticker: "NVDA",
    range: "60D",
    prices: Array.from({ length: 60 }, (_, i) => ({
      ts: `2026-03-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z`,
      close: 800 + i * 1.5,
      volume: 40_000_000,
    })),
    latest: {
      close: 892.41,
      ts: "2026-05-01T20:00:00Z",
      delta_abs: 14.22,
      delta_pct: 0.0162,
    },
  };
}

function renderHero(report: ResearchReport) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <HeroCard report={report} />
    </QueryClientProvider>,
  );
}

describe("HeroCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders ticker, name, sector tag", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport());
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    expect(screen.getByText("NVIDIA Corporation")).toBeInTheDocument();
    // Sector tag rendered (case-insensitive — design uppercases).
    expect(screen.getByText(/megacap_tech/i)).toBeInTheDocument();
  });

  it("renders the latest price with positive delta in pos color", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() => {
      expect(screen.getByText(/892\.41/)).toBeInTheDocument();
    });
    // Positive delta should render with the pos color class somewhere.
    const positives = container.querySelectorAll(".text-strata-pos");
    expect(positives.length).toBeGreaterThan(0);
  });

  it("renders 6 range pills (1D / 5D / 1M / 3M / 1Y / 5Y)", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport());
    await waitFor(() => expect(screen.getByText("3M")).toBeInTheDocument());
    for (const pill of ["1D", "5D", "1M", "3M", "1Y", "5Y"]) {
      expect(screen.getByText(pill)).toBeInTheDocument();
    }
  });

  it("re-fetches prices when a different range pill is clicked", async () => {
    const spy = vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport());
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const callsBefore = spy.mock.calls.length;
    fireEvent.click(screen.getByText("1Y"));
    await waitFor(() =>
      expect(spy.mock.calls.length).toBeGreaterThan(callsBefore),
    );
    // Latest call should have used range=1Y.
    const lastCall = spy.mock.calls[spy.mock.calls.length - 1];
    expect(lastCall[1]).toBe("1Y");
  });

  it("renders 3 featured stats", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport());
    await waitFor(() =>
      expect(screen.getByText(/forward p\/e/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/forward p\/e/i)).toBeInTheDocument();
    expect(screen.getByText(/roic/i)).toBeInTheDocument();
    expect(screen.getByText(/fcf margin/i)).toBeInTheDocument();
  });

  it("renders the LineChart once prices arrive", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
  });

  it("falls back to a skeleton when prices fetch is in flight", () => {
    vi.spyOn(api, "fetchMarketPrices").mockImplementation(
      () => new Promise(() => {}), // pending forever
    );
    const { container } = renderHero(fakeReport());
    // No line chart yet
    expect(
      container.querySelector("[data-testid='line-chart']"),
    ).toBeNull();
    // Some kind of placeholder/loading marker for the chart region
    expect(
      container.querySelector("[data-testid='line-chart-loading']"),
    ).not.toBeNull();
  });

  it("renders meta line with MCAP, VOL, 52W band", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport());
    await waitFor(() =>
      expect(screen.getByText(/MCAP/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/52W/i)).toBeInTheDocument();
  });
});
