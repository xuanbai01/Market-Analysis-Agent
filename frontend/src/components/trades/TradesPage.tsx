/**
 * /trades — the owner's tastytrade transactions from the encrypted copy
 * (ADR 0009, amended), behind the owner key. Each visit syncs the copy
 * first; when tastytrade can't be reached the copy is shown as it stands,
 * saying why. A CSV of the copy downloads from here.
 *
 * The trades live in this page's memory only (never persisted, gone when
 * the page or the key goes) and never reach a prompt.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../lib/api";
import { clearOwnerKey, useOwnerKey } from "../../lib/owner";
import { fetchOwnerTrades, fetchOwnerTradesCsv, isOwnerKeyRefused } from "../../lib/owner-api";
import type { OwnerTrade } from "../../lib/owner-schemas";
import { signedUsd } from "../../lib/positions-text";
import { ErrorBanner } from "../ErrorBanner";
import { useSignOutOn401 } from "../options/useSignOutOn401";
import { OwnerUnlock } from "../owner/OwnerUnlock";

const ALL = "";

function when(trade: OwnerTrade): string {
  if (trade.executed_at) return new Date(trade.executed_at).toLocaleString();
  return trade.date ?? "—";
}

const num = (v: number | null, digits = 2) => (v === null ? "—" : v.toFixed(digits));

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function Trades({ ownerKey }: { ownerKey: string }) {
  const query = useQuery({
    queryKey: ["owner-trades"],
    queryFn: () => fetchOwnerTrades(ownerKey),
    gcTime: 0, // gone from memory as soon as nothing shows it
    retry: false,
  });
  const unauthorized = useSignOutOn401(query.error);
  const refused = isOwnerKeyRefused(query.error);
  useEffect(() => {
    if (refused) clearOwnerKey();
  }, [refused]);
  const [underlying, setUnderlying] = useState(ALL);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const trades = useMemo(() => query.data?.trades ?? [], [query.data]);
  const underlyings = useMemo(() => [...new Set(trades.map((t) => t.underlying).filter((u): u is string => !!u))].sort(), [trades]);
  const shown = underlying === ALL ? trades : trades.filter((t) => t.underlying === underlying);
  const vaultMissing = query.error instanceof ApiError && query.error.status === 503;

  async function download() {
    setDownloading(true);
    setDownloadError(null);
    try {
      saveBlob(await fetchOwnerTradesCsv(ownerKey), "trades.csv");
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.title : "Couldn't download the CSV.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 data-testid="trades-title" className="font-mono text-xl text-strata-hi">Your trades</h1>
        {query.data && (
          <button
            type="button"
            onClick={() => void download()}
            disabled={downloading}
            className="rounded border border-strata-border px-2 py-1 font-mono text-[11px] text-strata-dim hover:text-strata-hi disabled:opacity-50"
          >
            {downloading ? "Preparing…" : "Download CSV"}
          </button>
        )}
      </div>
      {query.data && (
        <p data-testid="trades-status" className="mb-4 font-mono text-[11px] text-strata-muted">
          {query.data.trades.length} trades · a copy stored encrypted, read from tastytrade
          {!query.data.synced && (
            <span className="ml-2 text-strata-neg">not updated this visit: {query.data.reason ?? "tastytrade didn't answer"}</span>
          )}
        </p>
      )}
      {downloadError && <p role="alert" className="mb-3 text-sm text-strata-neg">{downloadError}</p>}
      {query.isPending && <p className="mt-6 font-mono text-sm text-strata-dim">Reading your trades…</p>}
      {vaultMissing && (
        <p data-testid="trades-no-vault" className="mt-6 text-sm text-strata-dim">
          The trade copy isn&rsquo;t set up on the server yet: its key (OWNER_VAULT_KEY) comes first, in docs/deployment.md §11.
        </p>
      )}
      {query.error && !unauthorized && !refused && !vaultMissing && <ErrorBanner error={query.error} />}
      {query.data && trades.length === 0 && <p data-testid="trades-empty" className="mt-6 text-sm text-strata-dim">No trades yet.</p>}
      {underlyings.length > 1 && (
        <label className="mb-3 flex items-center gap-2 font-mono text-[11px] text-strata-dim">
          Underlying
          <select
            value={underlying}
            onChange={(e) => setUnderlying(e.target.value)}
            className="rounded border border-strata-border bg-strata-raise px-2 py-1 text-strata-hi"
          >
            <option value={ALL}>All</option>
            {underlyings.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </label>
      )}
      {shown.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-strata-border bg-strata-surface">
          <table className="w-full min-w-[720px] font-mono text-xs" data-testid="trades-table">
            <thead className="text-left text-[10px] uppercase tracking-kicker text-strata-muted">
              <tr>
                <th className="px-3 py-2 font-normal">When</th>
                <th className="px-3 py-2 font-normal">Action</th>
                <th className="px-3 py-2 font-normal">Symbol</th>
                <th className="px-3 py-2 text-right font-normal">Qty</th>
                <th className="px-3 py-2 text-right font-normal">Price</th>
                <th className="px-3 py-2 text-right font-normal">Fees</th>
                <th className="px-3 py-2 text-right font-normal">Net</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.id} className="border-t border-strata-line text-strata-fg" title={t.description ?? undefined}>
                  <td className="px-3 py-1.5 text-strata-dim">{when(t)}</td>
                  <td className="px-3 py-1.5">{t.action ?? t.sub_type ?? t.type ?? "—"}</td>
                  <td className="px-3 py-1.5">{t.symbol ?? t.underlying ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right">{num(t.quantity, 0)}</td>
                  <td className="px-3 py-1.5 text-right">{num(t.price)}</td>
                  <td className="px-3 py-1.5 text-right text-strata-dim">{t.fees ? t.fees.toFixed(2) : "—"}</td>
                  <td className={`px-3 py-1.5 text-right ${t.net_value === null ? "" : t.net_value >= 0 ? "text-strata-pos" : "text-strata-neg"}`}>
                    {t.net_value === null ? "—" : signedUsd(t.net_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function TradesPage() {
  const ownerKey = useOwnerKey();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!ownerKey) queryClient.removeQueries({ queryKey: ["owner-trades"] });
  }, [ownerKey, queryClient]);
  return (
    <div className="mx-auto w-full max-w-screen-xl px-6 py-8 lg:px-8">
      {ownerKey ? <Trades ownerKey={ownerKey} /> : <OwnerUnlock />}
    </div>
  );
}
