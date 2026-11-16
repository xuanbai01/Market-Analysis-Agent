/**
 * WholeChainPanel — every expiry out to four months at tastytrade's live
 * quotes, for the owner (options PR 5, ADR 0009; /v1/owner/options/{symbol}/chain):
 * the chain's open interest and walls, gamma exposure by strike added up
 * across the expiries, and each expiry's row in the across-expiries table.
 *
 * Read on demand: a read asks tastytrade for thousands of contracts, so it
 * waits for the button, and the figures leave memory with the page.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api";
import { GLOSSARY, gammaSentence } from "../../lib/options-text";
import { clearOwnerKey, useOwnerKey } from "../../lib/owner";
import { fetchWholeChain } from "../../lib/owner-api";
import type { WholeChain } from "../../lib/owner-schemas";
import { wholeChainNotes, wholeChainSentence } from "../../lib/whole-chain-text";
import { AcrossExpiries } from "./AcrossExpiries";
import { SentenceText } from "./chart-kit";
import { ExposureChart } from "./ExposureChart";
import { Panel } from "./Panel";
import { useSignOutOn401 } from "./useSignOutOn401";

const A_MINUTE = 60_000; // the server keeps a read as long

export function WholeChainPanel({ symbol }: { symbol: string }) {
  const ownerKey = useOwnerKey();
  return ownerKey === null ? null : <Loaded symbol={symbol} ownerKey={ownerKey} />;
}

function Loaded({ symbol, ownerKey }: { symbol: string; ownerKey: string }) {
  const [asked, setAsked] = useState(false);
  const query = useQuery({
    queryKey: ["owner-whole-chain", symbol],
    queryFn: () => fetchWholeChain(ownerKey, symbol),
    enabled: asked,
    staleTime: A_MINUTE,
    gcTime: 0, // tastytrade's figures leave memory with the page
    retry: false,
  });
  const unauthorized = useSignOutOn401(query.error);
  // Only a 403 says the key is wrong (a 404 may be a deploy in flight).
  const refused = query.error instanceof ApiError && query.error.status === 403;
  useEffect(() => {
    if (refused) clearOwnerKey();
  }, [refused]);
  if (unauthorized || refused) return null;

  const whole = query.data;
  return (
    <Panel
      title="Every expiry · tastytrade live"
      testId="options-whole-chain-panel"
      info={GLOSSARY.wholeChain}
      summary={whole ? wholeChainSentence(whole) : null}
    >
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          data-testid="options-whole-chain-read"
          onClick={() => (asked ? void query.refetch() : setAsked(true))}
          disabled={query.isFetching}
          className="rounded border border-strata-border px-2 py-1 font-mono text-[11px] text-strata-dim hover:text-strata-hi disabled:opacity-50"
        >
          {query.isFetching ? "Reading every expiry…" : whole ? "Read again" : "Read every expiry from tastytrade"}
        </button>
        {!asked && (
          <span className="font-mono text-[10px] text-strata-muted">
            Four months of expiries, strikes within 15% of the price, at live quotes: a few seconds.
          </span>
        )}
      </div>
      {query.error && <p className="font-mono text-xs text-strata-dim">{errorText(query.error)}</p>}
      {whole && <Body whole={whole} />}
    </Panel>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return error.title;
  const reason = error instanceof ApiError ? error.title.replace(/\.$/, "") : "tastytrade didn't answer";
  return `The whole chain is unavailable: ${reason}.`;
}

function Body({ whole }: { whole: WholeChain }) {
  const gamma = gammaSentence(whole.positioning);
  const notes = wholeChainNotes(whole);
  return (
    <div className="w-full">
      {gamma && (
        <p data-testid="options-whole-chain-gamma" className="mb-3 text-sm leading-relaxed text-strata-fg">
          <SentenceText sentence={gamma} />
        </p>
      )}
      <ExposureChart positioning={whole.positioning} field="gex" price={whole.spot} testId="options-whole-chain-gex" />
      <p className="mt-1 mb-4 font-mono text-[10px] text-strata-muted">{whole.positioning.assumption}</p>
      <AcrossExpiries expiries={whole.expiries} price={whole.spot} />
      {notes.map((note) => (
        <p key={note} className="mt-2 font-mono text-[10px] text-strata-muted">
          {note}
        </p>
      ))}
      <p data-testid="options-whole-chain-source" className="mt-2 font-mono text-[10px] text-strata-muted">
        Live · tastytrade · read {new Date(whole.as_of).toLocaleTimeString()} · {whole.options_quoted.toLocaleString("en-US")}{" "}
        contracts · shown to you only, never stored
      </p>
    </div>
  );
}
