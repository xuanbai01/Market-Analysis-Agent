/**
 * IvHistoryPanel — the stock's IV and 20-session realized volatility over
 * a year, three years or everything, from the owner's tastytrade account
 * (ADR 0009, PR C; /v1/owner/options/{symbol}/history). Only with the owner
 * key; tastytrade's figures stay in memory (gcTime 0) and are never stored.
 *
 * The sentence places today's IV among the past year's sessions (our
 * arithmetic on tastytrade's series); the table gives tastytrade's own
 * rank and percentile, labelled as its own.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api";
import { type IvRange, IV_RANGES, inRange, ivHistorySentence, ivHistoryStats } from "../../lib/iv-history-text";
import { GLOSSARY, dateLabel } from "../../lib/options-text";
import { clearOwnerKey, useOwnerKey } from "../../lib/owner";
import { fetchIvHistory } from "../../lib/owner-api";
import type { IvHistory } from "../../lib/owner-schemas";
import { MultiLine } from "../MultiLine";
import { COLOR } from "./chart-kit";
import { Panel } from "./Panel";
import { useSignOutOn401 } from "./useSignOutOn401";

const FIFTEEN_MINUTES = 15 * 60_000; // the server keeps it as long
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function IvHistoryPanel({ symbol }: { symbol: string }) {
  const ownerKey = useOwnerKey();
  return ownerKey === null ? null : <Loaded symbol={symbol} ownerKey={ownerKey} />;
}

function Loaded({ symbol, ownerKey }: { symbol: string; ownerKey: string }) {
  const [range, setRange] = useState<IvRange>("1Y");
  const query = useQuery({
    queryKey: ["owner-iv-history", symbol],
    queryFn: () => fetchIvHistory(ownerKey, symbol),
    staleTime: FIFTEEN_MINUTES,
    gcTime: 0, // tastytrade's figures leave memory with the page
    retry: false,
  });
  const unauthorized = useSignOutOn401(query.error);
  // Only a 403 says the key is wrong: a 404 can't be told from a backend
  // without this route yet (a deploy in flight), as on the Live switch.
  const refused = query.error instanceof ApiError && query.error.status === 403;
  useEffect(() => {
    if (refused) clearOwnerKey();
  }, [refused]);
  if (unauthorized || refused) return null;

  const history = query.data;
  return (
    <Panel
      title="IV history · tastytrade"
      testId="options-iv-history-panel"
      info={GLOSSARY.tastytradeIvHistory}
      summary={history ? ivHistorySentence(history) : null}
      stats={history ? ivHistoryStats(history) : undefined}
    >
      {query.isPending && <p className="font-mono text-xs text-strata-dim">Reading tastytrade&rsquo;s history…</p>}
      {query.error && <p className="font-mono text-xs text-strata-dim">{errorText(query.error)}</p>}
      {history && <Chart history={history} range={range} onRange={setRange} />}
    </Panel>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return error.title;
  const reason = error instanceof ApiError ? error.title.replace(/\.$/, "") : "tastytrade didn't answer";
  return `IV history unavailable: ${reason}.`;
}

function Chart({ history, range, onRange }: { history: IvHistory; range: IvRange; onRange: (r: IvRange) => void }) {
  const shown = inRange(history.points, range);
  const series = [
    { label: "IV", color: COLOR.band, history: shown.flatMap((p) => (p.iv === null ? [] : [{ period: p.date, value: p.iv }])) },
    {
      label: "RV20",
      color: COLOR.neutral,
      history: shown.flatMap((p) => (p.rv20 === null ? [] : [{ period: p.date, value: p.rv20 }])),
    },
  ];
  return (
    <div className="w-full">
      <div role="group" aria-label="IV history span" className="mb-2 flex gap-1 font-mono text-xs">
        {IV_RANGES.map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={r === range}
            onClick={() => onRange(r)}
            className={`rounded px-2 py-0.5 transition ${
              r === range ? "bg-strata-highlight text-strata-canvas" : "text-strata-dim hover:text-strata-fg"
            }`}
          >
            {r}
          </button>
        ))}
      </div>
      <MultiLine
        series={series}
        showLegend
        showEndLabels
        formatValue={pct}
        formatPeriod={(p) => dateLabel(p, true)}
        ariaLabel={`IV and 20-session realized volatility, ${shown.length} sessions, from tastytrade.`}
      />
      <p data-testid="options-iv-history-source" className="mt-2 font-mono text-[10px] text-strata-muted">
        Live · tastytrade · read {new Date(history.as_of).toLocaleTimeString()} · shown to you only, never stored
        {!history.complete && " · tastytrade sent less history than asked"}
      </p>
    </div>
  );
}
