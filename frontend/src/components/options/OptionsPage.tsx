/**
 * OptionsPage — /options/:ticker (ADR 0008). What the option prices say:
 * headline figures, the expected-move cone, the term structure, the next
 * report's implied move against past ones, one expiry at a time (smile,
 * open interest, chain), a strategy builder on that expiry, and a cited AI
 * read of the figures. Signed in only; not in the public demo.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { fetchOptionsReport } from "../../lib/options-api";
import type { OptionsReport } from "../../lib/options-schemas";
import { ROUTES } from "../../lib/routes";
import { ErrorBanner } from "../ErrorBanner";
import { money, pct, shortDate } from "./chart-kit";
import { drawsCone, drawsEarnings, drawsTerm } from "./draws";
import { EarningsMoves } from "./EarningsMoves";
import { ExpectedMoveCone } from "./ExpectedMoveCone";
import { ExpirySection } from "./ExpirySection";
import { OptionsReadCard } from "./OptionsReadCard";
import { Panel } from "./Panel";
import { TermStructureChart } from "./TermStructureChart";
import { useSignOutOn401 } from "./useSignOutOn401";

// The backend's rules (options_analysis): a percentile from 63 stored
// sessions, over the last 252.
const PERCENTILE_SESSIONS = 63;
const HISTORY_WINDOW = 252;

function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

function asOf(report: OptionsReport): string {
  const when = new Date(report.quoted_at);
  const time = when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  const day = when.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
  return report.at_close
    ? `Quotes from the last close (${day}, ${time} ET)`
    : `Quotes about 15 minutes delayed (${day}, ${time} ET)`;
}

function daysBetween(fromIso: string, toIso: string): number {
  return (Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000;
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-strata-border bg-strata-surface p-4">
      <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{label}</p>
      <p className="mt-1 font-mono text-lg text-strata-hi">{value}</p>
      {sub && <p className="mt-0.5 font-mono text-[11px] text-strata-dim">{sub}</p>}
    </div>
  );
}

function ivSub(report: OptionsReport): string | undefined {
  const parts = [
    report.rv20 !== null ? `RV20 ${pct(report.rv20)}` : null,
    report.iv30 !== null && report.iv30_extrapolated ? "extrapolated" : null,
  ].filter((s) => s !== null);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

function Tiles({ report }: { report: OptionsReport }) {
  const { history, chain } = report;
  const nearest = report.expiries.find((e) => e.expiry === chain?.expiry);
  const ivRank =
    history.percentile !== null
      ? `percentile over ${Math.min(history.sessions, HISTORY_WINDOW)} sessions`
      : history.sessions < PERCENTILE_SESSIONS
        ? `Collecting: ${history.sessions} of ${PERCENTILE_SESSIONS} sessions`
        : "No IV30 today to rank";
  return (
    <div data-testid="options-tiles" className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile label="Spot" value={report.spot !== null ? money(report.spot) : "—"} />
      <Tile label="IV30" value={report.iv30 !== null ? pct(report.iv30) : "—"} sub={ivSub(report)} />
      <Tile label="IV history" value={history.percentile !== null ? ordinal(Math.round(history.percentile)) : "—"} sub={ivRank} />
      <Tile
        label="Expected move"
        value={nearest ? `±${pct(nearest.expected_move)}` : "—"}
        sub={nearest ? `by ${shortDate(nearest.expiry)}` : undefined}
      />
      <Tile label="25Δ skew" value={report.skew25 !== null ? `${(report.skew25 * 100).toFixed(1)} pts` : "—"} sub="put IV − call IV" />
      <Tile label="Put/call OI" value={report.put_call_open_interest !== null ? report.put_call_open_interest.toFixed(2) : "—"} />
    </div>
  );
}

export default function OptionsPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const symbol = (ticker ?? "").toUpperCase();
  const query = useQuery({
    queryKey: ["options", symbol],
    queryFn: () => fetchOptionsReport(symbol),
    enabled: symbol.length > 0,
    staleTime: 5 * 60_000,
  });

  const report = query.data;
  const unauthorized = useSignOutOn401(query.error);
  const eventDays =
    report?.earnings?.reaction_date ? daysBetween(report.quoted_at, report.earnings.reaction_date) : null;
  // A panel only for a chart that will draw (each chart's own check).
  const cone = report && report.spot !== null && drawsCone(report.expiries) ? report.spot : null;
  const term = report !== undefined && drawsTerm(report.expiries);

  return (
    <div className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8 xl:px-10">
      <Link to={ROUTES.symbol(symbol)} className="font-mono text-[11px] text-strata-dim hover:text-strata-hi">
        ← {symbol} dashboard
      </Link>
      <h1 data-testid="options-title" className="mt-2 font-mono text-xl text-strata-hi">
        {symbol} options
      </h1>
      {report?.name && <p className="text-sm text-strata-dim">{report.name}</p>}
      {report && (
        <p data-testid="options-asof" className="mb-6 font-mono text-[11px] text-strata-muted">
          {asOf(report)}
        </p>
      )}

      {query.isPending && (
        <p data-testid="options-loading" className="mt-6 font-mono text-sm text-strata-dim">
          Reading the option chains for {symbol}…
        </p>
      )}
      {query.error && !unauthorized && <ErrorBanner error={query.error} />}

      {report && report.status !== "ok" && (
        <p data-testid="options-empty" className="mt-6 text-sm text-strata-dim">
          {report.status === "no_options"
            ? `${symbol} lists no options.`
            : `No two-sided quotes to price for ${symbol}: its options trade too thinly.`}
        </p>
      )}

      {report && report.status === "ok" && (
        <>
          <Tiles report={report} />
          <OptionsReadCard symbol={symbol} quotedAt={report.quoted_at} />
          <div className={`grid gap-6 ${cone !== null && term ? "xl:grid-cols-2" : ""}`}>
            {cone !== null && (
              <Panel title="Expected move, one standard deviation">
                <ExpectedMoveCone expiries={report.expiries} spot={cone} eventDays={eventDays} />
              </Panel>
            )}
            {term && (
              <Panel title="Term structure: at-the-money IV">
                <TermStructureChart expiries={report.expiries} rv20={report.rv20} />
              </Panel>
            )}
          </div>
          {report.earnings && drawsEarnings(report.earnings) && (
            <Panel title="Earnings">
              <EarningsMoves earnings={report.earnings} />
            </Panel>
          )}
          {report.chain && (
            <ExpirySection symbol={symbol} listed={report.listed_expiries} initial={report.chain} spot={report.spot} />
          )}
        </>
      )}

      {report && (
        <p data-testid="options-disclaimer" className="mt-4 font-mono text-[10px] text-strata-muted">
          Figures come from option prices about 15 minutes delayed (the last close outside market hours); IVs are ours
          (Black-76 on the forward), and any probability is risk-neutral. Analysis, not advice.
        </p>
      )}
    </div>
  );
}
