/**
 * ComparePage tests (Phase 4.6.A).
 *
 * /compare?a=NVDA&b=AVGO — two-ticker side-by-side dashboard.
 *
 * Behaviors pinned (mirrors the Compare mockup at
 * docs/screenshots/image-1777831012413.png):
 *
 *   1. Reads ?a + ?b from the URL, uppercases both, fires two report
 *      fetches in parallel via TanStack Query.
 *   2. Renders both ticker heroes (CompareHero) with name + price +
 *      mini area chart.
 *   3. Renders the Valuation row (3 metrics) and Quality row (4 metrics).
 *   4. Renders the operating-margin overlay + growth overlay + risk
 *      diff side-by-side.
 *   5. Swap button mutates the URL: /compare?a=NVDA&b=AVGO →
 *      /compare?a=AVGO&b=NVDA.
 *   6. Missing query params (?a only, ?b only, neither) redirect to /.
 *   7. Per-side distress chrome: when ticker A is distressed but B is
 *      healthy, the UNPROFITABLE pill renders only above the A column.
 *
 * Note on lazy-loading: the App.tsx lazy() wrapper isn't tested here
 * directly — Suspense + lazy is verified by the bundle output (the
 * compare/ chunk is separate from the main entry). These tests render
 * ComparePage directly without the lazy wrapper.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import { ComparePage } from "./ComparePage";
import * as api from "../../lib/api";
import {
  HEALTHY_LAYOUT_SIGNALS,
  type ResearchReport,
  type LayoutSignals,
} from "../../lib/schemas";

const SOURCE = {
  tool: "yfinance.fundamentals",
  fetched_at: "2026-05-04T14:00:00+00:00",
} as const;

function num(description: string, value: number) {
  return { description, value, source: { ...SOURCE }, history: [] };
}

function fakeReport(symbol: string, name: string, opts: Partial<{ sector: string; layout_signals: LayoutSignals }> = {}): ResearchReport {
  return {
    symbol,
    name,
    sector: opts.sector ?? "semiconductors",
    generated_at: "2026-05-04T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    layout_signals: opts.layout_signals ?? HEALTHY_LAYOUT_SIGNALS,
    sections: [
      {
        title: "Valuation",
        summary: "",
        confidence: "high",
        claims: [
          num("P/E ratio (forward, analyst consensus)", symbol === "NVDA" ? 32.1 : 26.8),
          num("Price-to-sales ratio (trailing 12 months)", symbol === "NVDA" ? 24.4 : 14.2),
          num("Enterprise value to EBITDA", symbol === "NVDA" ? 41.2 : 24.8),
        ],
      },
      {
        title: "Quality",
        summary: "",
        confidence: "high",
        claims: [
          num("Gross margin", symbol === "NVDA" ? 0.748 : 0.738),
          num("Operating margin", symbol === "NVDA" ? 0.612 : 0.421),
          num("Free cash flow margin", symbol === "NVDA" ? 0.421 : 0.412),
          num("Return on invested capital (TTM)", symbol === "NVDA" ? 0.61 : 0.21),
        ],
      },
      {
        title: "Capital Allocation",
        summary: "",
        confidence: "high",
        claims: [
          num("Market capitalization", symbol === "NVDA" ? 2.19e12 : 8.58e11),
        ],
      },
    ],
  };
}

function fakePrices(symbol: string) {
  return {
    ticker: symbol,
    range: "60D",
    prices: Array.from({ length: 60 }, (_, i) => ({
      ts: `2026-03-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z`,
      close: (symbol === "NVDA" ? 800 : 1700) + i * 1.5,
      volume: 40_000_000,
    })),
    latest: {
      close: symbol === "NVDA" ? 892.41 : 1842.1,
      ts: "2026-05-01T20:00:00Z",
      delta_abs: symbol === "NVDA" ? 14.22 : 18.4,
      delta_pct: symbol === "NVDA" ? 0.0162 : 0.0101,
    },
  };
}

function renderAt(initialUrl: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <Routes>
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/" element={<div data-testid="landing-stub">landing</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ComparePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "fetchMarketPrices").mockImplementation((ticker) =>
      Promise.resolve(fakePrices(ticker)),
    );
  });

  it("fetches both reports in parallel using uppercased tickers", async () => {
    const spy = vi
      .spyOn(api, "fetchResearchReport")
      .mockImplementation((symbol) =>
        Promise.resolve(fakeReport(symbol, symbol === "NVDA" ? "NVIDIA" : "Broadcom")),
      );
    renderAt("/compare?a=nvda&b=avgo");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    const tickers = spy.mock.calls.map((c) => c[0]).sort();
    expect(tickers).toEqual(["AVGO", "NVDA"]);
  });

  it("renders both ticker names once the reports resolve", async () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation((symbol) =>
      Promise.resolve(fakeReport(symbol, symbol === "NVDA" ? "NVIDIA" : "Broadcom")),
    );
    renderAt("/compare?a=NVDA&b=AVGO");
    await waitFor(() => expect(screen.getByText("NVIDIA")).toBeInTheDocument());
    expect(screen.getByText("Broadcom")).toBeInTheDocument();
  });

  it("renders the 3-metric Valuation row + 4-metric Quality row", async () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation((symbol) =>
      Promise.resolve(fakeReport(symbol, symbol === "NVDA" ? "NVIDIA" : "Broadcom")),
    );
    const { container } = renderAt("/compare?a=NVDA&b=AVGO");
    await waitFor(() => expect(screen.getByText("NVIDIA")).toBeInTheDocument());

    // Both rows render. Each metric row exposes data-row="compare-metric"
    // so the test doesn't depend on label string spelling.
    const rows = container.querySelectorAll("[data-row='compare-metric']");
    expect(rows.length).toBe(3 + 4);
  });

  it("Swap button mutates the URL — A and B exchange positions", async () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation((symbol) =>
      Promise.resolve(fakeReport(symbol, symbol === "NVDA" ? "NVIDIA" : "Broadcom")),
    );
    const { container } = renderAt("/compare?a=NVDA&b=AVGO");
    await waitFor(() => expect(screen.getByText("NVIDIA")).toBeInTheDocument());

    const swap = screen.getByRole("button", { name: /swap/i });
    fireEvent.click(swap);
    // After swap, the left column ticker is AVGO, not NVDA.
    await waitFor(() => {
      const heroes = container.querySelectorAll("[data-card='compare-hero']");
      expect(heroes[0]?.getAttribute("data-ticker")).toBe("AVGO");
      expect(heroes[1]?.getAttribute("data-ticker")).toBe("NVDA");
    });
  });

  it("redirects to landing when ?a is missing", async () => {
    renderAt("/compare?b=AVGO");
    await waitFor(() =>
      expect(screen.getByTestId("landing-stub")).toBeInTheDocument(),
    );
  });

  it("redirects to landing when ?b is missing", async () => {
    renderAt("/compare?a=NVDA");
    await waitFor(() =>
      expect(screen.getByTestId("landing-stub")).toBeInTheDocument(),
    );
  });

  it("renders distress pill on the distressed side only", async () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation((symbol) =>
      Promise.resolve(
        fakeReport(symbol, symbol === "RIVN" ? "Rivian" : "Ford", {
          // Only RIVN is distressed.
          layout_signals:
            symbol === "RIVN"
              ? { ...HEALTHY_LAYOUT_SIGNALS, is_unprofitable_ttm: true }
              : HEALTHY_LAYOUT_SIGNALS,
        }),
      ),
    );
    const { container } = renderAt("/compare?a=RIVN&b=F");
    await waitFor(() => expect(screen.getByText("Rivian")).toBeInTheDocument());

    // The header pills container is scoped per side via a column wrapper
    // marked with data-side="a" / "b". The distressed pill must appear
    // only inside the A column.
    const aCol = container.querySelector("[data-side='a']");
    const bCol = container.querySelector("[data-side='b']");
    expect(aCol?.querySelector("[data-pill='header-pill']")).not.toBeNull();
    expect(bCol?.querySelector("[data-pill='header-pill']")).toBeNull();
  });

  it("renders the 'What survives / What's cut' footer strip", async () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation((symbol) =>
      Promise.resolve(fakeReport(symbol, symbol === "NVDA" ? "NVIDIA" : "Broadcom")),
    );
    renderAt("/compare?a=NVDA&b=AVGO");
    await waitFor(() => expect(screen.getByText("NVIDIA")).toBeInTheDocument());

    expect(screen.getByText(/what survives/i)).toBeInTheDocument();
    expect(screen.getByText(/what'?s cut/i)).toBeInTheDocument();
  });
});
