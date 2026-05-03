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
import type { ResearchReport } from "../lib/schemas";

function fakeReport(symbol: string): ResearchReport {
  return {
    symbol,
    generated_at: "2026-05-02T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
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

  it("renders a hero placeholder reserving space for Phase 4.1", async () => {
    vi.spyOn(api, "fetchResearchReport").mockResolvedValue(
      fakeReport("AAPL"),
    );
    const { container } = renderAt("AAPL");
    await waitFor(() => {
      expect(
        container.querySelector("[data-testid='hero-placeholder']"),
      ).not.toBeNull();
    });
  });

  it("shows a loading state while the report is in flight", () => {
    vi.spyOn(api, "fetchResearchReport").mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    renderAt("AAPL");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
