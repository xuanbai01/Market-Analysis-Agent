/**
 * /positions — the owner's open positions, live from tastytrade (ADR 0009,
 * amended), behind the owner key on top of the sign-in. Each underlying
 * gets a card; the page's totals are the cards' Greeks added up.
 *
 * tastytrade's figures live in this page's memory only: never persisted,
 * never sent to a prompt, never in the demo. Every sentence is written in
 * code, and none says what to do.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { clearOwnerKey, useOwnerKey } from "../../lib/owner";
import { useNow } from "../../lib/use-now";
import { fetchOwnerPositions, isOwnerKeyRefused } from "../../lib/owner-api";
import type { OwnerPositions, PositionGroup } from "../../lib/owner-schemas";
import { type Greeks, greeks, valuedAt } from "../../lib/positions-math";
import { signedUsd } from "../../lib/positions-text";
import { ErrorBanner } from "../ErrorBanner";
import { useSignOutOn401 } from "../options/useSignOutOn401";
import { OwnerUnlock } from "../owner/OwnerUnlock";
import { MAX_CONTEXT, PositionGroupCard } from "./PositionGroupCard";

const FIFTEEN_SECONDS = 15_000;
const FIVE_SECONDS = 5_000;

/** A total across the holdings, and the ones it leaves out for want of a
 * live figure (one unquoted holding mustn't blank the rest). */
interface Total {
  value: number | null;
  without: string[];
}

function totals(positions: OwnerPositions): { delta: Total; theta: Total; vega: Total } {
  const sum = (pick: (group: PositionGroup) => number | null): Total => {
    let value = 0;
    const without: string[] = [];
    for (const group of positions.groups) {
      const v = pick(group);
      if (v === null) without.push(group.underlying);
      else value += v;
    }
    return { value: without.length === positions.groups.length ? null : value, without };
  };
  const of = (group: PositionGroup): Greeks => greeks(group, group.quote?.mark ?? 0); // the price only scales delta
  return {
    delta: sum((group) => (group.quote?.mark ? of(group).deltaDollars : null)),
    theta: sum((group) => of(group).thetaDay),
    vega: sum((group) => of(group).vegaPoint),
  };
}

const leftOut = (total: Total, missing: string) =>
  total.without.length > 0 ? `; leaves out ${total.without.join(", ")} (no ${missing} from tastytrade)` : "";

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border border-strata-border bg-strata-surface p-3">
      <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{label}</p>
      <p className="mt-1 font-mono text-lg text-strata-hi">{value}</p>
      <p className="font-mono text-[10px] text-strata-dim">{sub}</p>
    </div>
  );
}

function Positions({ ownerKey }: { ownerKey: string }) {
  const query = useQuery({
    queryKey: ["owner-positions"],
    queryFn: () => fetchOwnerPositions(ownerKey),
    staleTime: FIFTEEN_SECONDS,
    // Read again as often as the server's copy turns over, while the tab shows
    // (TanStack pauses an interval in a background tab).
    refetchInterval: FIFTEEN_SECONDS,
    // Gone from memory as soon as nothing shows it (unmount, sign out).
    gcTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const unauthorized = useSignOutOn401(query.error);
  const refused = isOwnerKeyRefused(query.error);
  useEffect(() => {
    if (refused) clearOwnerKey(); // the page shows the unlock form again
  }, [refused]);
  const positions = query.data;
  const now = useNow(FIVE_SECONDS); // quote ages keep counting between reads
  // Outside a session the marks are the last close's: value from there.
  const valued = positions ? valuedAt(now, positions.priced_at, positions.as_of) : now;
  const t = positions ? totals(positions) : null;
  const dash = (v: number | null) => (v === null ? "—" : signedUsd(v));

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 data-testid="positions-title" className="font-mono text-xl text-strata-hi">Your positions</h1>
        <button
          type="button"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          className="rounded border border-strata-border px-2 py-1 font-mono text-[11px] text-strata-dim hover:text-strata-hi disabled:opacity-50"
        >
          {query.isFetching ? "Reading…" : "Refresh"}
        </button>
      </div>
      {positions && (
        <p data-testid="positions-asof" className="mb-6 font-mono text-[11px] text-strata-muted">
          Live · tastytrade · read {new Date(positions.as_of).toLocaleTimeString()} · {positions.accounts} account{positions.accounts === 1 ? "" : "s"}
          {positions.stale && <span className="ml-2 text-strata-neg">tastytrade isn&rsquo;t answering: this is the last copy read</span>}
          {positions.truncated && <span className="ml-2 text-strata-neg">more positions than one read takes: some are left out</span>}
        </p>
      )}
      {query.isPending && <p className="mt-6 font-mono text-sm text-strata-dim">Reading your positions from tastytrade…</p>}
      {query.error && !unauthorized && !refused && <ErrorBanner error={query.error} />}
      {positions && t && positions.groups.length > 0 && (
        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="positions-totals">
          <Tile label="For a 1% rise" value={dash(t.delta.value)} sub={`every position's delta, in dollars${leftOut(t.delta, "live price or delta")}`} />
          <Tile label="A day passing" value={dash(t.theta.value)} sub={`theta, nothing else changing${leftOut(t.theta, "live theta")}`} />
          <Tile label="IV one point higher" value={dash(t.vega.value)} sub={`vega, every expiry at once${leftOut(t.vega, "live vega")}`} />
        </div>
      )}
      {positions && positions.groups.length === 0 && positions.unanalysed.length === 0 && (
        <p data-testid="positions-empty" className="mt-6 text-sm text-strata-dim">No open positions.</p>
      )}
      {positions?.groups.map((group, i) => (
        <PositionGroupCard key={group.underlying} group={group} now={now} valuedAt={valued} withContext={i < MAX_CONTEXT} />
      ))}
      {positions && positions.unanalysed.length > 0 && (
        <section data-testid="positions-unanalysed" className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5">
          <h2 className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">Listed, not analysed</h2>
          <ul className="space-y-1 font-mono text-xs text-strata-fg">
            {positions.unanalysed.map((p, i) => (
              <li key={`${p.account}-${p.symbol}-${i}`}>
                {p.symbol || "(no symbol)"} · {p.instrument_type}
                {p.quantity === null ? " · quantity unclear" : ` · ${p.quantity}`}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p data-testid="positions-disclaimer" className="mt-4 text-xs text-strata-muted">
        Figures computed from tastytrade&rsquo;s live quotes and our own option chains. The chances are what option prices imply and what past moves show, not forecasts; nothing here is advice.
      </p>
    </>
  );
}

export default function PositionsPage() {
  const ownerKey = useOwnerKey();
  const queryClient = useQueryClient();
  useEffect(() => {
    // No key (refused, cleared in another tab, signed out): no positions in memory either.
    if (!ownerKey) queryClient.removeQueries({ queryKey: ["owner-positions"] });
  }, [ownerKey, queryClient]);
  return (
    <div className="mx-auto w-full max-w-screen-xl px-6 py-8 lg:px-8">
      {ownerKey ? <Positions ownerKey={ownerKey} /> : <OwnerUnlock />}
    </div>
  );
}
