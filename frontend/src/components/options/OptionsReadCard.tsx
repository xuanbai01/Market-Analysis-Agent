/**
 * OptionsReadCard — the cited AI read of the page's figures (ADR 0008,
 * PR5): a headline and a few points, each citing the figures it quotes.
 * Written server-side once per set of quotes; while it's written the card
 * says so, and when the read limit or the model stops it, it says that.
 * Quiet when the symbol has nothing to read.
 */
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "../../lib/api";
import { fetchOptionsRead } from "../../lib/options-api";
import type { OptionsRead } from "../../lib/options-schemas";
import { CitedPoints } from "../CitedPoints";
import { useSignOutOn401 } from "./useSignOutOn401";

const MINUTE = 60;

function quotesOf(read: OptionsRead): string {
  const when = new Date(read.quoted_at);
  const day = when.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
  const time = when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  return `${day}, ${time} ET`;
}

function Shell({ children, testId }: { children: React.ReactNode; testId: string }) {
  return (
    <section data-testid={testId} className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5">
      {children}
    </section>
  );
}

export function OptionsReadCard({ symbol, quotedAt }: { symbol: string; quotedAt: string }) {
  const query = useQuery({
    // Keyed on the quote time: new quotes, a new read.
    queryKey: ["options-read", symbol, quotedAt],
    queryFn: () => fetchOptionsRead(symbol),
    staleTime: Infinity,
    retry: false,
  });
  const unauthorized = useSignOutOn401(query.error);

  if (query.isPending) {
    return (
      <Shell testId="options-read-loading">
        <p className="font-mono text-[11px] text-strata-muted">Writing a read of these figures…</p>
      </Shell>
    );
  }
  if (query.error) {
    const error = query.error instanceof ApiError ? query.error : null;
    if (unauthorized || error?.status === 404) return null;
    const minutes = error?.retryAfterSeconds ? Math.max(1, Math.ceil(error.retryAfterSeconds / MINUTE)) : null;
    return (
      <Shell testId="options-read-unavailable">
        <p className="font-mono text-[11px] text-strata-muted">
          {error?.status === 429
            ? `An hourly limit on option lookups or written reads is reached; try again ${minutes ? `in about ${minutes} minutes` : "later"}.`
            : "No read could be written just now; the figures below stand on their own."}
        </p>
      </Shell>
    );
  }

  const read = query.data;
  return (
    <Shell testId="options-read">
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">What the prices say</p>
        <p className="font-mono text-[10px] text-strata-muted">
          AI-written from the figures on this page · each point lists its sources · not advice
        </p>
      </header>
      <p className="text-lg font-medium leading-snug text-strata-hi">{read.headline}</p>
      <CitedPoints points={read.points} facts={read.claims} evidenceTestId="options-read-evidence" collapsed />
      {read.quoted_at !== quotedAt && (
        <p data-testid="options-read-stale" className="mt-3 font-mono text-[10px] text-strata-muted">
          Read of the quotes from {quotesOf(read)}.
        </p>
      )}
    </Shell>
  );
}
