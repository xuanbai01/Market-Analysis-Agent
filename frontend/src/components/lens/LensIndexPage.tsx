/**
 * LensIndexPage — /lens. The cross-company lenses on offer; each card
 * opens its lens.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listLenses } from "../../lib/api";
import { ROUTES } from "../../lib/routes";
import { ErrorBanner } from "../ErrorBanner";

export function LensIndexPage() {
  const query = useQuery({ queryKey: ["lenses"], queryFn: listLenses, staleTime: 60 * 60_000 });
  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-10">
      <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">Lenses</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-strata-hi">One metric, across a group of companies</h1>
      <p className="mt-1 text-sm text-strata-dim">
        Ten years of SEC filings: how the group is distributed, who sits at each end, and what it implies.
      </p>
      {query.error && <div className="mt-6"><ErrorBanner error={query.error} /></div>}
      <ul className="mt-6 grid gap-3 sm:grid-cols-2">
        {(query.data ?? []).map((lens) => (
          <li key={lens.id}>
            <Link
              to={ROUTES.lens(lens.id)}
              data-testid="lens-card"
              className="block rounded-md border border-strata-border bg-strata-surface p-4 transition hover:border-strata-highlight/50 hover:bg-strata-raise focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
            >
              <p className="text-sm font-medium text-strata-hi">{lens.title}</p>
              <p className="mt-1 text-xs leading-relaxed text-strata-dim">{lens.description}</p>
              <p className="mt-2 font-mono text-[10px] text-strata-muted">{lens.tickers.join(" · ")}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default LensIndexPage;
