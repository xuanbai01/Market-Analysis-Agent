/**
 * InsiderCard — what officers and directors did with their own shares
 * over the last six months, from Form 4 filings (2026-11).
 *
 * Left: a sentence built from the numbers (not from the model), the
 * context that changes how it reads (how much was pre-scheduled under
 * 10b5-1 plans, and the dollars as a share of market value), four tiles,
 * and 10% holders on a line of their own: a strategic investor's stake
 * is not an executive's bet. Right: the largest traders, each with a bar
 * sized to their dollars. Buying and selling are not coloured as good or
 * bad; the words carry the direction.
 */
import type { Insiders } from "../lib/insider-extract";
import { formatClaimValue } from "../lib/format";
import { NarrativeStrip } from "./NarrativeStrip";

const usd = (v: number) => formatClaimValue(v, "usd").replace(/\.00(?=$|[KMBT])/, "");

function pct(v: number): string {
  const p = v * 100;
  if (p === 0) return "0%";
  if (p < 0.1) return `${p.toFixed(2)}%`;
  if (p < 10) return `${Math.round(p * 10) / 10}%`.replace(/\.0%$/, "%");
  return `${Math.round(p)}%`;
}

function day(iso: string, withYear = true): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
}

function headline(x: Insiders): string {
  if (x.filingCount === 0) {
    const last = x.lastFiling ? ` The most recent was filed ${day(x.lastFiling)}.` : "";
    return `No Form 4 filings about the company in the last 6 months.${last}`;
  }
  const sold = x.sold ?? 0;
  const bought = x.bought ?? 0;
  if (sold > 0 && bought > 0) return `Officers and directors sold ${usd(sold)} and bought ${usd(bought)}.`;
  if (sold > 0) return `Officers and directors sold ${usd(sold)} and bought nothing.`;
  if (bought > 0) return `Officers and directors bought ${usd(bought)} and sold nothing.`;
  return "No officer or director bought or sold.";
}

function context(x: Insiders): string {
  const parts: string[] = [];
  if ((x.sold ?? 0) > 0 && x.planShare !== null) {
    parts.push(`${pct(x.planShare)} of the selling was under pre-arranged 10b5-1 plans.`);
  }
  if (x.soldShareOfMarketCap !== null) {
    parts.push(`The sales equal ${pct(x.soldShareOfMarketCap)} of the company's market value.`);
  } else if (x.boughtShareOfMarketCap !== null) {
    parts.push(`The purchases equal ${pct(x.boughtShareOfMarketCap)} of the company's market value.`);
  }
  if ((x.sold ?? 0) === 0 && (x.bought ?? 0) === 0 && (x.routine ?? 0) > 0) {
    parts.push(`All ${x.routine} transactions were grants, option exercises, tax withholding or gifts.`);
  }
  return parts.join(" ");
}

function people(count: number | null): string {
  if (count === null) return "";
  return count === 1 ? "1 officer or director" : `${count} officers and directors`;
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div data-testid="insider-tile" className="rounded-md bg-strata-raise px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-kicker text-strata-muted">{label}</div>
      <div className="mt-0.5 font-mono text-lg text-strata-hi tabular">{value}</div>
      {sub && <div className="font-mono text-[10px] text-strata-dim">{sub}</div>}
    </div>
  );
}

interface Props {
  ticker: string;
  insiders: Insiders;
}

export function InsiderCard({ ticker, insiders: x }: Props) {
  const holders = [
    (x.holderBought ?? 0) > 0 && `bought ${usd(x.holderBought ?? 0)}`,
    (x.holderSold ?? 0) > 0 && `sold ${usd(x.holderSold ?? 0)}`,
  ].filter(Boolean);
  const largest = Math.max(1, ...x.people.map((p) => Math.abs(p.net)));
  const span =
    x.firstFiling && x.lastFiling
      ? `${day(x.firstFiling, x.firstFiling.slice(0, 4) !== x.lastFiling.slice(0, 4))} – ${day(x.lastFiling)}`
      : null;
  const contextText = context(x);

  return (
    <section
      data-testid="insider-card"
      className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <header className="mb-4 font-mono text-[10px] uppercase tracking-kicker text-strata-peers">
        Insider activity · {ticker} · last 6 months
      </header>

      <div className="grid flex-1 grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
        <div>
          <p data-testid="insider-headline" className="text-base font-medium text-strata-hi">
            {headline(x)}
          </p>
          {contextText && (
            <p data-testid="insider-context" className="mt-1 text-sm leading-relaxed text-strata-fg">
              {contextText}
            </p>
          )}

          {x.filingCount > 0 && (
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2 2xl:grid-cols-4">
              <Tile label="Bought" value={usd(x.bought ?? 0)} sub={people(x.buyers)} />
              <Tile label="Sold" value={usd(x.sold ?? 0)} sub={people(x.sellers)} />
              <Tile label="Under 10b5-1 plans" value={x.planShare !== null ? pct(x.planShare) : "—"} sub="of sales" />
              <Tile label="Routine" value={String(x.routine ?? 0)} sub="grants, exercises, withholding, gifts" />
            </div>
          )}

          {holders.length > 0 && (
            <p data-testid="insider-holders" className="mt-3 text-xs text-strata-dim">
              10% holders and other owners {holders.join(" and ")} (not counted above).
            </p>
          )}
        </div>

        {x.people.length > 0 && (
          <div>
            <div className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">Largest traders</div>
            <ul className="space-y-2.5">
              {x.people.map((p) => (
                <li key={`${p.name}-${p.role}`} data-testid="insider-person">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="text-strata-hi">{p.name}</span>
                      <span className="ml-1.5 text-xs text-strata-dim">{p.role}</span>
                    </span>
                    <span className="shrink-0 font-mono text-xs text-strata-fg tabular">
                      {p.net < 0 ? "sold" : "bought"} {usd(Math.abs(p.net))}
                    </span>
                  </div>
                  <div className="mt-1 h-1 rounded-full bg-strata-line" aria-hidden="true">
                    <div
                      className="h-1 rounded-full bg-strata-peers/70"
                      style={{ width: `${Math.max(2, (Math.abs(p.net) / largest) * 100).toFixed(1)}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <p data-testid="insider-note" className="mt-4 font-mono text-[10px] text-strata-muted">
        {x.filingCount > 0 && span ? `${x.filingCount} Form 4 filings, ${span}. ` : ""}
        Officers and directors, purchases and sales only; 10% holders shown apart.
      </p>

      <NarrativeStrip text={x.narrative} />
    </section>
  );
}
