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
import { HEALTHY_LAYOUT_SIGNALS, type ResearchReport } from "../lib/schemas";

function fakeReport(opts: Partial<ResearchReport> = {}): ResearchReport {
  return {
    symbol: "NVDA",
    name: "NVIDIA Corporation",
    sector: "megacap_tech",
    generated_at: "2026-05-02T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
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

  // Phase 4.3.X / cosmetic backlog from PR #50: design calls for an
  // exchange chip near the ticker eyebrow ("NVDA · NASDAQ · SEMIS").
  // The chip is sourced from the Resolved sector tag claim (already
  // shipped as ``sector_tag`` since 4.1) — no backend work required,
  // just a presentation-layer chip render adjacent to the ticker.
  it("renders an exchange chip combining ticker + sector tag", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    const chip = container.querySelector("[data-testid='hero-exchange-chip']");
    expect(chip).not.toBeNull();
    // The chip should reference both the ticker and a sector token —
    // exact prose is the implementation's call, but both must appear.
    const text = chip!.textContent ?? "";
    expect(text).toMatch(/NVDA/);
    expect(text.toLowerCase()).toMatch(/megacap_tech|tech/);
  });

  // Phase 4.3.B.1 — sub-3M range pills (1D / 5D / 1M / 3M) all backed
  // by the same /v1/market/:ticker/prices?range=60D fetch. Pre-4.3.B.1
  // they all rendered the same 60-bar chart because the LineChart
  // received the unsliced data. The fix slices client-side: each pill
  // produces a visibly different chart and the range subtitle updates
  // to reflect the actual span shown.

  it("renders the 60D price chart with all 60 points by default (3M range)", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    // Default range is 3M → entire 60D dataset rendered.
    const chart = container.querySelector("[data-testid='line-chart']");
    const path = chart!.querySelector("path[data-line-stroke]");
    const d = path!.getAttribute("d") ?? "";
    // 60 points = 1 "M" + 59 "L" commands. Match either L or C
    // segments since the LineChart's path command isn't pinned here.
    const segmentCount = (d.match(/[ML]/g) ?? []).length;
    expect(segmentCount).toBe(60);
  });

  it("slices to 22 points when 1M range is selected", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    fireEvent.click(screen.getByText("1M"));
    await waitFor(() => {
      const d =
        container
          .querySelector("[data-testid='line-chart'] path[data-line-stroke]")
          ?.getAttribute("d") ?? "";
      const segmentCount = (d.match(/[ML]/g) ?? []).length;
      expect(segmentCount).toBe(22);
    });
  });

  it("slices to 5 points when 5D range is selected", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    fireEvent.click(screen.getByText("5D"));
    await waitFor(() => {
      const d =
        container
          .querySelector("[data-testid='line-chart'] path[data-line-stroke]")
          ?.getAttribute("d") ?? "";
      const segmentCount = (d.match(/[ML]/g) ?? []).length;
      expect(segmentCount).toBe(5);
    });
  });

  it("slices to 2 points when 1D range is selected", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    fireEvent.click(screen.getByText("1D"));
    await waitFor(() => {
      const d =
        container
          .querySelector("[data-testid='line-chart'] path[data-line-stroke]")
          ?.getAttribute("d") ?? "";
      const segmentCount = (d.match(/[ML]/g) ?? []).length;
      expect(segmentCount).toBe(2);
    });
  });

  // Phase 4.3.B.2 — HeroCard enables LineChart's axes + hover tooltip
  // so the price chart is no longer decorative. The user can see the
  // price range (min/max y-axis labels) + time span (first/last date
  // x-axis labels) at a glance, and read exact price + date by hover.

  it("renders y-axis price labels on the hero price chart", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    expect(
      container.querySelector("[data-testid='line-chart-y-axis-max']"),
    ).not.toBeNull();
    expect(
      container.querySelector("[data-testid='line-chart-y-axis-min']"),
    ).not.toBeNull();
  });

  it("renders x-axis date labels on the hero price chart", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    expect(
      container.querySelector("[data-testid='line-chart-x-axis-start']"),
    ).not.toBeNull();
    expect(
      container.querySelector("[data-testid='line-chart-x-axis-end']"),
    ).not.toBeNull();
  });

  it("shows a hover tooltip when the cursor moves over the hero price chart", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const { container } = renderHero(fakeReport());
    await waitFor(() =>
      expect(
        container.querySelector("[data-testid='line-chart']"),
      ).not.toBeNull(),
    );
    const svg = container.querySelector("[data-testid='line-chart']");
    fireEvent.mouseMove(svg!, { clientX: 100, clientY: 60 });
    expect(
      container.querySelector("[data-testid='line-chart-hover-tooltip']"),
    ).not.toBeNull();
  });

  // ── Phase 4.5.A — distressed-name metric swap ─────────────────────

  function distressedReport(): ResearchReport {
    const report = fakeReport({
      symbol: "RIVN",
      name: "Rivian Automotive",
      sector: "ev_auto",
      layout_signals: {
        is_unprofitable_ttm: true,
        beat_rate_below_30pct: true,
        cash_runway_quarters: 4.5,
        gross_margin_negative: true,
        debt_rising_cash_falling: true,
      },
    });
    // Add a P/S claim so the swap has something to render.
    report.sections = [
      ...report.sections,
      {
        title: "Valuation",
        summary: "",
        confidence: "medium",
        claims: [
          {
            description: "Price-to-sales ratio (trailing 12 months)",
            value: 1.84,
            source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-02T14:00:00+00:00" },
            history: [],
          },
        ],
      },
    ];
    return report;
  }

  it("swaps Forward P/E to P/Sales when is_unprofitable_ttm", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(distressedReport());
    await waitFor(() =>
      expect(screen.getByText(/p\/sales/i)).toBeInTheDocument(),
    );
    // Forward P/E label is gone in distressed mode.
    expect(screen.queryByText(/forward p\/e/i)).toBeNull();
    // P/S value renders verbatim.
    expect(screen.getByText(/1\.84/)).toBeInTheDocument();
  });

  it("swaps ROIC to Cash Runway when is_unprofitable_ttm", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(distressedReport());
    await waitFor(() =>
      expect(screen.getByText(/cash runway/i)).toBeInTheDocument(),
    );
    // ROIC label is gone in distressed mode.
    expect(screen.queryByText(/roic ttm/i)).toBeNull();
    // Runway formats as "~4.5 quarters" (or similar quarterly framing).
    const runwayValue = screen.getByText(/4\.5/);
    expect(runwayValue).toBeInTheDocument();
  });

  it("colors FCF margin red when fcf_margin is negative on distressed report", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    const report = distressedReport();
    // Override FCF margin to negative.
    const qualitySection = report.sections.find((s) => s.title === "Quality");
    const fcfClaim = qualitySection?.claims.find(
      (c) => c.description === "Free cash flow margin",
    );
    if (fcfClaim) fcfClaim.value = -0.52;
    const { container } = renderHero(report);
    await waitFor(() =>
      expect(screen.getByText(/fcf margin/i)).toBeInTheDocument(),
    );
    // The FCF stat tile carries the strata-neg accent class on the
    // value when the underlying value is negative.
    const fcfStat = container.querySelector("[data-stat='hero-fcf-margin']");
    expect(fcfStat).not.toBeNull();
    const valueClass =
      fcfStat?.querySelector("[data-stat-value]")?.className ?? "";
    expect(valueClass).toMatch(/text-strata-neg/);
  });

  it("keeps the default Forward P/E + ROIC trio when not distressed", async () => {
    vi.spyOn(api, "fetchMarketPrices").mockResolvedValue(fakePrices());
    renderHero(fakeReport()); // no layout_signals on healthy fixture
    await waitFor(() =>
      expect(screen.getByText(/forward p\/e/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/forward p\/e/i)).toBeInTheDocument();
    expect(screen.getByText(/roic/i)).toBeInTheDocument();
    expect(screen.queryByText(/p\/sales/i)).toBeNull();
    expect(screen.queryByText(/cash runway/i)).toBeNull();
  });
});
