/**
 * Display rules for cross-company lenses (ADR 0007 layer 3).
 *
 * Colors: the dataviz reference categorical palette for dark surfaces,
 * in its validated order, assigned by the company's position in the lens
 * (never by rank, so a company keeps its color everywhere). Validated on
 * the Strata surface #0e1116: lightness band, chroma, adjacent CVD ΔE ≥ 8.4
 * and normal-vision ΔE ≥ 19.3 all pass. Seven series is past the
 * all-pairs-safe three, so every chart also labels companies directly
 * and the table repeats the numbers.
 */
import type { LensCompany, LensReport } from "./schemas";

export const LENS_COLORS = [
  "#3987e5", // blue
  "#d95926", // orange
  "#199e70", // aqua
  "#c98500", // yellow
  "#d55181", // magenta
  "#008300", // green
  "#9085e9", // violet
] as const;

export function companyColor(index: number): string {
  return LENS_COLORS[index % LENS_COLORS.length];
}

/** "$384.8B", "$9.0B", "$740M". */
export function usdBillions(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  return `${sign}$${(abs / 1e6).toFixed(0)}M`;
}

/** 0.1839 → "18.4%". */
export function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export interface CompanyYear {
  ticker: string;
  color: string;
  capex: number | null;
  intensity: number | null;
  capexToOcf: number | null;
}

/** Every company's numbers for one year of the lens, highest intensity
 *  first; companies that didn't report that year come last. */
export function companiesInYear(report: Pick<LensReport, "companies" | "years">, year: number): CompanyYear[] {
  const i = report.years.indexOf(year);
  const rows = report.companies.map((c, index) => {
    const point = i >= 0 ? c.points[i] : undefined;
    return {
      ticker: c.ticker,
      color: companyColor(index),
      capex: point?.capex ?? null,
      intensity: point?.capex_intensity ?? null,
      capexToOcf: point?.capex_to_ocf ?? null,
    };
  });
  return rows.sort((a, b) => (b.intensity ?? -Infinity) - (a.intensity ?? -Infinity));
}

/** The first year a company has an intensity value, and that value. */
export function firstReported(company: LensCompany, years: readonly number[]): { year: number; intensity: number } | null {
  for (let i = 0; i < company.points.length; i++) {
    const v = company.points[i].capex_intensity;
    if (v !== null) return { year: years[i], intensity: v };
  }
  return null;
}
