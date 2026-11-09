/** A small lens report shared by the lens tests: three companies, three years. */
import type { LensReport } from "../../lib/schemas";

const SRC = { tool: "computed.analytics", fetched_at: "2026-11-09T00:00:00+00:00" };

function point(year: number, capex: number | null, revenue: number | null, ocf: number | null) {
  return {
    year,
    capex,
    revenue,
    ocf,
    capex_intensity: capex !== null && revenue ? capex / revenue : null,
    capex_to_ocf: capex !== null && ocf && ocf > 0 ? capex / ocf : null,
  };
}

export const LENS: LensReport = {
  id: "megacap-capex",
  title: "Megacap tech capex",
  description: "How much of their revenue they reinvest.",
  tickers: ["AAA", "BBB", "CCC"],
  method: "SEC XBRL annual filings.",
  years: [2023, 2024, 2025],
  companies: [
    {
      ticker: "AAA",
      name: "Alpha",
      points: [point(2023, 20e9, 100e9, 40e9), point(2024, 30e9, 120e9, 50e9), point(2025, 40e9, 160e9, 50e9)],
    },
    {
      ticker: "BBB",
      name: "Beta",
      points: [point(2023, 2e9, 100e9, 30e9), point(2024, 2e9, 100e9, 30e9), point(2025, 3e9, 100e9, -5e9)],
    },
    {
      ticker: "CCC",
      name: "Gamma",
      points: [point(2023, null, null, null), point(2024, 5e9, 50e9, null), point(2025, 10e9, 100e9, 20e9)],
    },
  ],
  stats: [
    { year: 2023, companies: 2, median: 0.11, p25: 0.065, p75: 0.155, low: 0.02, low_ticker: "BBB", high: 0.2, high_ticker: "AAA", total_capex: 22e9 },
    { year: 2024, companies: 3, median: 0.1, p25: 0.06, p75: 0.175, low: 0.02, low_ticker: "BBB", high: 0.25, high_ticker: "AAA", total_capex: 37e9 },
    { year: 2025, companies: 3, median: 0.1, p25: 0.065, p75: 0.175, low: 0.03, low_ticker: "BBB", high: 0.25, high_ticker: "AAA", total_capex: 53e9 },
  ],
  facts: [
    { description: "Highest capex intensity, CY2025: AAA", value: 0.25, unit: "fraction", source: SRC, history: [] },
    { description: "Total capex, 3 companies, CY2025", value: 53e9, unit: "usd", source: SRC, history: [] },
  ],
  narrative: {
    headline: "Spending is concentrated in one heavy investor.",
    points: [{ text: "AAA spends 25.00% of revenue.", claim_refs: [{ section: "Lens", index: 0 }] }],
  },
  generated_at: "2026-11-09T00:00:00+00:00",
};
