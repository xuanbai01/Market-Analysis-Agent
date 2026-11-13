/**
 * DemoIndexPage — ``/demo``. Says what the demo is and lists the
 * tickers that have a report to open.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchDemoIndex } from "../../lib/api";
import { formatAge } from "../../lib/format";
import { ROUTES } from "../../lib/routes";

export default function DemoIndexPage() {
  const index = useQuery({ queryKey: ["demo-index"], queryFn: fetchDemoIndex, staleTime: 300_000 });
  const symbols = index.data?.symbols ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight text-strata-hi">Equity research, cited end to end</h1>
      <p className="mt-3 text-sm leading-relaxed text-strata-fg">
        Each report is a dashboard for one company: price, quality, earnings, valuation against peers and against
        its own history, cash and capital returns, changes in its 10-K risk factors, and an analyst view that argues
        the bull and bear case. Every number, including the ones in the AI-written prose, traces to the data it came
        from.
      </p>
      <p className="mt-2 text-sm leading-relaxed text-strata-dim">
        This demo shows reports that were already built. It can&apos;t generate new ones or look up other tickers.
      </p>

      {index.isPending && <p className="mt-8 text-sm text-strata-dim">Loading…</p>}
      {index.isError && (
        <p role="alert" className="mt-8 text-sm text-strata-neg">
          The demo couldn&apos;t be loaded. Try again in a moment.
        </p>
      )}
      {index.isSuccess && symbols.length === 0 && (
        <p data-testid="demo-empty" className="mt-8 text-sm text-strata-dim">
          No demo reports are available right now.
        </p>
      )}

      {symbols.length > 0 && (
        <ul className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {symbols.map((entry) => (
            <li key={entry.symbol}>
              <Link
                to={ROUTES.demoSymbol(entry.symbol)}
                data-testid="demo-ticker"
                className="block rounded-md border border-strata-border bg-strata-surface p-4 transition hover:border-strata-highlight/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
              >
                <div className="font-mono text-sm font-medium text-strata-hi">{entry.symbol}</div>
                {entry.name && <div className="mt-0.5 text-sm text-strata-fg">{entry.name}</div>}
                <div className="mt-2 font-mono text-[11px] text-strata-muted">
                  Report built {formatAge(entry.generated_at)}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
