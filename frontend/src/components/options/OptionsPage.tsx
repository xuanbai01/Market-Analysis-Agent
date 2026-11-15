/**
 * OptionsPage — /options/:ticker (ADR 0008). What the option prices say:
 * headline figures, the expected-move cone, the term structure, the next
 * report's implied move against past ones, and one expiry at a time (smile,
 * open interest, chain). Signed in only; not in the public demo.
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../lib/api";
import { clearStoredToken } from "../../lib/auth";
import { fetchOptionsReport } from "../../lib/options-api";
import type { OptionsReport } from "../../lib/options-schemas";
import { ROUTES } from "../../lib/routes";
import { ErrorBanner } from "../ErrorBanner";
import { money, pct, shortDate } from "./chart-kit";
import { EarningsMoves } from "./EarningsMoves";
import { ExpectedMoveCone } from "./ExpectedMoveCone";
import { ExpirySection } from "./ExpirySection";
import { TermStructureChart } from "./TermStructureChart";

const PERCENTILE_SESSIONS = 63;

function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

function asOf(quotedAt: string): string {
  const when = new Date(quotedAt);
  const time = when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  const day = when.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
  return time === "4:00 PM"
    ? `Quotes from the last close (${day}, 4:00 PM ET)`
    : `Quotes about 15 minutes delayed (${day}, ${time} ET)`;
}

function daysBetween(fromIso: string, toIso: string): number {
  return (Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000;
}

function Panel({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section data-testid={testId} className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5">
      <h2 className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{title}</h2>
      {children}
    </section>
  );
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

function Tiles({ report }: { report: OptionsReport }) {
  const { history, chain } = report;
  const nearest = report.expiries.find((e) => e.expiry === chain?.expiry);
  const ivRank =
    history.percentile !== null
      ? `${ordinal(Math.round(history.percentile))} percentile over ${Math.min(history.sessions, 252)} sessions`
      : `Collecting: ${history.sessions} of ${PERCENTILE_SESSIONS} sessions`;
  return (
    <div data-testid="options-tiles" className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile label="Spot" value={report.spot !== null ? money(report.spot) : "—"} />
      <Tile label="IV30" value={report.iv30 !== null ? pct(report.iv30) : "—"} sub={report.rv20 !== null ? `RV20 ${pct(report.rv20)}` : undefined} />
      <Tile label="IV history" value={history.percentile !== null ? `${Math.round(history.percentile)}` : "—"} sub={ivRank} />
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
  const navigate = useNavigate();
  const symbol = (ticker ?? "").toUpperCase();
  const query = useQuery({
    queryKey: ["options", symbol],
    queryFn: () => fetchOptionsReport(symbol),
    enabled: symbol.length > 0,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (query.error instanceof ApiError && query.error.status === 401) {
      clearStoredToken();
      navigate(ROUTES.login, { replace: true });
    }
  }, [query.error, navigate]);

  const report = query.data;
  const unauthorized = query.error instanceof ApiError && query.error.status === 401;
  const eventDays =
    report?.earnings?.reaction_date ? daysBetween(report.quoted_at, report.earnings.reaction_date) : null;

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
          {asOf(report.quoted_at)}
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
          <div className="grid gap-6 xl:grid-cols-2">
            {report.spot !== null && (
              <Panel title="Expected move, one standard deviation">
                <ExpectedMoveCone expiries={report.expiries} spot={report.spot} eventDays={eventDays} />
              </Panel>
            )}
            <Panel title="Term structure: at-the-money IV">
              <TermStructureChart expiries={report.expiries} rv20={report.rv20} />
            </Panel>
          </div>
          {report.earnings && (
            <Panel title="Earnings">
              <EarningsMoves earnings={report.earnings} />
            </Panel>
          )}
          {report.chain && (
            <Panel title="One expiry">
              <ExpirySection symbol={symbol} listed={report.listed_expiries} initial={report.chain} spot={report.spot} />
            </Panel>
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
