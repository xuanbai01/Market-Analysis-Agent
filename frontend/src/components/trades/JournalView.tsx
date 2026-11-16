/**
 * The /trades page's Journal tab (tastytrade PR D): the owner's trades read
 * as positions by the server (``trade_journal``). A sentence on what closed,
 * realized P&L by month, then each position (newest opened first) with how
 * it stands or ended; a row opens to its legs and the fills behind it.
 * Facts about past trades, nothing about what to do next.
 */
import { Fragment, useMemo, useState } from "react";

import { endingLabel, heldLabel, positionName, summarySentence } from "../../lib/journal-text";
import { dateLabel, type Sentence } from "../../lib/options-text";
import type { JournalPosition, OwnerTrade, TradeJournal } from "../../lib/owner-schemas";
import { legLabel, signedUsd } from "../../lib/positions-text";
import { cents, quantity, tradeTime } from "../../lib/trades-format";
import { RealizedByMonth } from "./RealizedByMonth";

type StatusFilter = "all" | "open" | "closed";

function Words({ sentence }: { sentence: Sentence }) {
  return (
    <>
      {sentence.map((part, i) =>
        typeof part === "string" ? <Fragment key={i}>{part}</Fragment> : <strong key={i} className="text-strata-hi">{part.strong}</strong>,
      )}
    </>
  );
}

function opened(position: JournalPosition): string {
  return position.opened_at ? dateLabel(position.opened_at.slice(0, 10), true) : "—";
}

function Detail({ position, byId, fills }: { position: JournalPosition; byId: Map<string, JournalPosition>; fills: OwnerTrade[] }) {
  const origin = position.origin_position ? byId.get(position.origin_position) : undefined;
  const from = position.rolled_from ? byId.get(position.rolled_from) : undefined;
  const to = position.rolled_to ? byId.get(position.rolled_to) : undefined;
  return (
    <div data-testid="journal-detail" className="space-y-2 px-3 py-3 text-strata-fg">
      <ul className="space-y-0.5">
        {position.legs.map((leg) => (
          <li key={leg.symbol}>
            {legLabel(leg)}
            {leg.closed > 0 && leg.closed < Math.abs(leg.quantity) && (
              <span className="text-strata-dim"> · {quantity(leg.closed)} closed</span>
            )}
          </li>
        ))}
      </ul>
      {position.origin && (
        <p className="text-strata-dim">
          Delivered by {position.origin === "assignment" ? "an assignment" : "an exercise"}
          {origin ? ` of ${positionName(origin)}` : ""}.
        </p>
      )}
      {from && <p className="text-strata-dim">Rolled from {positionName(from)}.</p>}
      {to && <p className="text-strata-dim">Rolled into {positionName(to)}.</p>}
      {position.note && <p className="text-strata-dim">{position.note}</p>}
      {fills.length > 0 && (
        <table className="w-full text-[11px]">
          <tbody>
            {fills.map((t) => (
              <tr key={t.id} className="border-t border-strata-line">
                <td className="py-1 pr-3 text-strata-dim">{tradeTime(t)}</td>
                <td className="py-1 pr-3">{t.action ?? t.sub_type ?? "—"}</td>
                <td className="py-1 pr-3">{t.symbol ?? "—"}</td>
                <td className="py-1 pr-3 text-right">{quantity(t.quantity)}</td>
                <td className="py-1 text-right">{t.net_value === null ? "—" : cents(t.net_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function JournalView({ journal, trades, underlying }: { journal: TradeJournal; trades: OwnerTrade[]; underlying: string }) {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [open, setOpen] = useState<string | null>(null);
  const byId = useMemo(() => new Map(journal.positions.map((p) => [p.id, p])), [journal]);
  const tradeById = useMemo(() => new Map(trades.map((t) => [t.id, t])), [trades]);
  const shown = journal.positions
    .filter((p) => !underlying || p.underlying === underlying)
    .filter((p) => status === "all" || (status === "closed" ? p.status === "closed" : p.status !== "closed"))
    .sort((a, b) => (b.opened_at ?? "").localeCompare(a.opened_at ?? ""));
  const unmatched = journal.unmatched.length;
  const pickedRealized = journal.underlyings.find((u) => u.underlying === underlying)?.realized;

  return (
    <section data-testid="journal">
      {underlying && (
        <p data-testid="journal-underlying-total" className="mb-1 text-sm text-strata-hi">
          {underlying}: {pickedRealized === undefined ? "nothing realized yet" : `${signedUsd(pickedRealized)} realized`}
        </p>
      )}
      <p data-testid="journal-summary" className="mb-4 text-sm text-strata-fg">
        {/* The filter narrows the table only: say what the sentence covers. */}
        {underlying && <span className="text-strata-dim">All underlyings: </span>}
        <Words sentence={summarySentence(journal.totals)} />
      </p>
      {journal.months.length > 0 && (
        <div className="mb-6 rounded-md border border-strata-border bg-strata-surface p-4">
          <h2 className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
            Realized P&amp;L by month closed{underlying ? ", all underlyings" : ""}
          </h2>
          <RealizedByMonth months={journal.months} />
        </div>
      )}
      <label className="mb-3 flex items-center gap-2 font-mono text-[11px] text-strata-dim">
        Show
        <select
          data-testid="journal-status-filter"
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}
          className="rounded border border-strata-border bg-strata-raise px-2 py-1 text-strata-hi"
        >
          <option value="all">All positions</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
        </select>
      </label>
      {shown.length === 0 ? (
        <p className="text-sm text-strata-dim">No positions to show.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-strata-border bg-strata-surface">
          <table className="w-full min-w-[640px] font-mono text-xs">
            <thead className="text-left text-[10px] uppercase tracking-kicker text-strata-muted">
              <tr>
                <th className="px-3 py-2 font-normal">Opened</th>
                <th className="px-3 py-2 font-normal">Position</th>
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-3 py-2 text-right font-normal">Held</th>
                <th className="px-3 py-2 text-right font-normal">Realized</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <Fragment key={p.id}>
                  <tr data-testid="journal-row" className="border-t border-strata-line text-strata-fg">
                    <td className="px-3 py-1.5 text-strata-dim">{opened(p)}</td>
                    <td className="px-3 py-1.5">
                      <button
                        type="button"
                        aria-expanded={open === p.id}
                        onClick={() => setOpen(open === p.id ? null : p.id)}
                        className="text-left hover:text-strata-hi"
                      >
                        {open === p.id ? "▾" : "▸"} {p.underlying} {p.structure}
                      </button>
                    </td>
                    <td className="px-3 py-1.5">{endingLabel(p)}</td>
                    <td className="px-3 py-1.5 text-right">{heldLabel(p.days_held)}</td>
                    <td className={`px-3 py-1.5 text-right ${p.realized === null ? "" : p.realized >= 0 ? "text-strata-pos" : "text-strata-neg"}`}>
                      {p.realized === null ? "—" : cents(p.realized)}
                    </td>
                  </tr>
                  {open === p.id && (
                    <tr className="bg-strata-raise">
                      <td colSpan={5}>
                        <Detail
                          position={p}
                          byId={byId}
                          fills={p.transactions.map((id) => tradeById.get(id)).filter((t): t is OwnerTrade => t !== undefined)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {unmatched > 0 && (
        <div data-testid="journal-unmatched" className="mt-4 text-xs text-strata-dim">
          <p>
            {unmatched} transaction{unmatched === 1 ? " isn't" : "s aren't"} in the journal; each is in the Transactions tab:
          </p>
          <ul className="mt-1 list-inside list-disc">
            {journal.unmatched.map((u) => (
              <li key={u.id}>
                {u.date ?? "—"} · {u.symbol ?? "—"}: {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
