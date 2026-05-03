/**
 * ReportRenderer tests (Phase 3.3.A onwards).
 *
 * Pre-3.3 the renderer was uncovered; these tests pin the structural
 * contract — the bits we'd notice breaking immediately while dogfooding
 * — and the Phase 3.3.A "Trend column" behavior:
 *
 * 1. Symbol, generated_at, overall confidence are visible in the header.
 * 2. Each section becomes a card with title + summary + claims table.
 * 3. **Trend column header** is added to the claims table.
 * 4. Claims with ``history.length >= 2`` render a Sparkline in the trend
 *    cell.
 * 5. Claims with empty / single-point history render an empty trend cell
 *    (no layout shift, no error placeholder).
 *
 * We don't lock pixel-perfect Recharts SVG output — that's brittle to
 * version drift. We assert on the ``data-testid='sparkline'`` marker
 * the Sparkline component sets.
 */
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { ResearchReport } from "../lib/schemas";
import { ReportRenderer } from "./ReportRenderer";

function buildReport(
  overrides: Partial<ResearchReport> = {},
): ResearchReport {
  return {
    symbol: "AAPL",
    generated_at: "2026-04-29T14:05:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    name: null,
    sector: null,
    sections: [
      {
        title: "Earnings",
        summary: "Latest EPS came in above consensus.",
        confidence: "high",
        claims: [
          {
            description: "Reported EPS (latest quarter)",
            value: 2.18,
            source: {
              tool: "yfinance.earnings",
              fetched_at: "2026-04-29T14:00:00+00:00",
            },
            history: [
              { period: "2024-Q1", value: 1.4 },
              { period: "2024-Q2", value: 1.53 },
              { period: "2024-Q3", value: 2.05 },
              { period: "2024-Q4", value: 2.18 },
            ],
          },
          {
            description: "Next earnings report date",
            value: "2026-05-01",
            source: {
              tool: "yfinance.earnings",
              fetched_at: "2026-04-29T14:00:00+00:00",
            },
            history: [], // Non-history-bearing claim.
          },
        ],
      },
    ],
    ...overrides,
  };
}

describe("ReportRenderer header", () => {
  it("shows symbol and overall-confidence badge", () => {
    render(<ReportRenderer report={buildReport()} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    // Confidence is rendered uppercase via a Tailwind class; the text
    // node still says "high".
    expect(screen.getAllByText(/high/i).length).toBeGreaterThan(0);
  });

  it("renders one card per section with title + summary", () => {
    render(<ReportRenderer report={buildReport()} />);
    expect(
      screen.getByRole("heading", { level: 3, name: "Earnings" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Latest EPS came in above consensus."),
    ).toBeInTheDocument();
  });

  it("renders 'No sections returned.' on empty sections", () => {
    render(<ReportRenderer report={buildReport({ sections: [] })} />);
    expect(screen.getByText(/no sections returned/i)).toBeInTheDocument();
  });
});

describe("ReportRenderer Trend column (Phase 3.3.A)", () => {
  it("includes a Trend column header in the claims table", () => {
    render(<ReportRenderer report={buildReport()} />);
    expect(
      screen.getByRole("columnheader", { name: /trend/i }),
    ).toBeInTheDocument();
  });

  it("renders a Sparkline in the trend cell when history has 2+ points", () => {
    const { container } = render(<ReportRenderer report={buildReport()} />);
    const sparklines = container.querySelectorAll(
      "[data-testid='sparkline']",
    );
    // Only the EPS row has populated history; the report-date row is
    // history-less.
    expect(sparklines).toHaveLength(1);
  });

  it("renders no Sparkline for a claim with empty history", () => {
    // A report with one claim, no history → zero sparklines, but
    // the Trend column header is still present (stable layout).
    const noHistory = buildReport({
      sections: [
        {
          title: "Risk Factors",
          summary: "",
          confidence: "low",
          claims: [
            {
              description: "Risk paragraphs added",
              value: 3,
              source: {
                tool: "sec.ten_k_risks_diff",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
              history: [],
            },
          ],
        },
      ],
    });
    const { container } = render(<ReportRenderer report={noHistory} />);
    expect(container.querySelectorAll("[data-testid='sparkline']")).toHaveLength(
      0,
    );
    expect(
      screen.getByRole("columnheader", { name: /trend/i }),
    ).toBeInTheDocument();
  });

  it("renders the existing Metric / Value / Source columns alongside Trend", () => {
    render(<ReportRenderer report={buildReport()} />);
    expect(
      screen.getByRole("columnheader", { name: /metric/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /value/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /source/i }),
    ).toBeInTheDocument();
  });

  it("formats numeric value alongside the sparkline (anti-regression on existing ClaimsTable behavior)", () => {
    render(<ReportRenderer report={buildReport()} />);
    // formatClaimValue renders 2.18 as the string "2.18".
    expect(screen.getByText("2.18")).toBeInTheDocument();
  });
});

// ── Phase 3.3.B — SectionChart wiring ───────────────────────────────

describe("ReportRenderer SectionChart wiring (Phase 3.3.B)", () => {
  // SectionChart is lazy-loaded (React.lazy + Suspense) so the
  // recharts dep stays out of the main bundle. Tests for "did the
  // chart render" need waitFor() because the chunk resolves async.
  // Tests for "the chart did NOT render" can be synchronous —
  // featuredClaim() returns null synchronously and the lazy import
  // never fires, so the fallback / chart never appears.

  it(
    "renders a SectionChart for an Earnings section with EPS history",
    async () => {
      // The default buildReport() has an Earnings section with a
      // 4-point eps_actual history → the SectionChart should appear.
      // Recharts is a 100 KB chunk; the first lazy() resolution per
      // worker pays the dynamic-import cost. Under full-suite load
      // (33 test files post-4.3) the dynamic import has been observed
      // to take 6+ seconds. Generous timeouts here keep the test
      // deterministic across machine loads.
      const { container } = render(<ReportRenderer report={buildReport()} />);
      await waitFor(
        () =>
          expect(
            container.querySelector("[data-testid='section-chart']"),
          ).not.toBeNull(),
        { timeout: 15000 },
      );
    },
    20000,
  );

  it("renders no SectionChart for Risk Factors (no featured-claim spec)", () => {
    const riskOnly: ResearchReport = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      overall_confidence: "low",
      tool_calls_audit: [],
    name: null,
    sector: null,
      sections: [
        {
          title: "Risk Factors",
          summary: "",
          confidence: "low",
          claims: [
            {
              description: "Newly added risk paragraphs vs prior 10-K",
              value: 3,
              source: {
                tool: "sec.ten_k_risks_diff",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
              history: [],
            },
          ],
        },
      ],
    };
    const { container } = render(<ReportRenderer report={riskOnly} />);
    expect(
      container.querySelector("[data-testid='section-chart']"),
    ).toBeNull();
  });

  it("renders no SectionChart when Earnings EPS history is empty (graceful pre-3.2 degrade)", () => {
    const noEpsHistory: ResearchReport = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      overall_confidence: "medium",
      tool_calls_audit: [],
    name: null,
    sector: null,
      sections: [
        {
          title: "Earnings",
          summary: "Pre-3.2 cached report.",
          confidence: "medium",
          claims: [
            {
              description: "Reported EPS (latest quarter)",
              value: 2.18,
              source: {
                tool: "yfinance.earnings",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
              history: [], // empty — pre-3.2 cache
            },
          ],
        },
      ],
    };
    const { container } = render(<ReportRenderer report={noEpsHistory} />);
    expect(
      container.querySelector("[data-testid='section-chart']"),
    ).toBeNull();
  });

  it("renders a SectionChart for Quality with ROE history", async () => {
    // Same lazy-load timeout consideration as the Earnings test above —
    // bumped via the explicit 10s test timeout at the bottom of this it().
    const qualityReport: ResearchReport = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      overall_confidence: "high",
      tool_calls_audit: [],
    name: null,
    sector: null,
      sections: [
        {
          title: "Quality",
          summary: "ROE has trended up over four quarters.",
          confidence: "high",
          claims: [
            {
              description: "Return on equity",
              value: 0.18,
              source: {
                tool: "yfinance.fundamentals",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
              history: [
                { period: "2024-Q1", value: 0.15 },
                { period: "2024-Q2", value: 0.16 },
                { period: "2024-Q3", value: 0.17 },
                { period: "2024-Q4", value: 0.18 },
              ],
            },
          ],
        },
      ],
    };
    const { container } = render(<ReportRenderer report={qualityReport} />);
    await waitFor(
      () =>
        expect(
          container.querySelector("[data-testid='section-chart']"),
        ).not.toBeNull(),
      { timeout: 15000 },
    );
  }, 20000);
});

// Phase 4.2 note: the previous "PeerScatter wiring" describe block was
// removed alongside ReportRenderer's lazy PeerScatter import. Peers is
// now rendered by ValuationCard → PeerScatterV2 outside this component;
// see PeerScatterV2.test.tsx + ValuationCard.test.tsx for the
// equivalent coverage.
