/**
 * MarketStrip — one row of headline markets across the top of every
 * signed-in page: S&P 500, Nasdaq 100, Dow, VIX, our fear & greed
 * estimate, then Russell 2000, the 10-year yield, the dollar, gold,
 * crude and bitcoin (order set by the backend; the estimate sits after
 * VIX, its closest relative).
 *
 * Each quote shows the last close and the day's move (▲/▼ plus color,
 * so direction never rests on color alone). The fear & greed chip opens
 * a panel with its four parts and how the score is built — it is our
 * estimate, not CNN's index, and says so.
 *
 * Data: GET /v1/market/overview, refreshed every 5 minutes. The strip
 * is a convenience, so a failed request hides it rather than erroring.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchMarketOverview } from "../lib/api";
import {
  formatQuoteChange,
  formatQuotePrice,
  formatSessionDate,
  RATING_BANDS,
  RATING_LABEL,
  type Direction,
} from "../lib/market-format";
import type { MarketQuote, SentimentEstimate, SentimentRating } from "../lib/schemas";

const REFRESH_MS = 5 * 60_000;
const SKELETON_CHIPS = 6;
const CNN_INDEX_URL = "https://www.cnn.com/markets/fear-and-greed";
const PANEL_WIDTH = 340;

const DIRECTION_CLASS: Record<Direction, string> = {
  up: "text-strata-pos",
  down: "text-strata-neg",
  flat: "text-strata-muted",
};
const DIRECTION_GLYPH: Record<Direction, string> = { up: "▲", down: "▼", flat: "■" };

// Meter fill per band: fear in the loss hue, greed in the gain hue,
// neutral gray between — a diverging scale with a gray midpoint.
const BAND_CLASS: Record<SentimentRating, string> = {
  extreme_fear: "bg-strata-neg/70",
  fear: "bg-strata-neg/35",
  neutral: "bg-strata-neutral/40",
  greed: "bg-strata-pos/35",
  extreme_greed: "bg-strata-pos/70",
};

export function MarketStrip() {
  const query = useQuery({
    queryKey: ["market-overview"],
    queryFn: fetchMarketOverview,
    staleTime: 60_000,
    refetchInterval: REFRESH_MS,
  });

  if (query.isError) return null;
  if (query.isPending) {
    return (
      <StripFrame busy>
        {Array.from({ length: SKELETON_CHIPS }, (_, i) => (
          <li key={i} className="flex h-[52px] w-28 flex-shrink-0 flex-col justify-center gap-1.5 px-3">
            <span className="h-2 w-14 rounded bg-strata-raise" />
            <span className="h-3 w-20 rounded bg-strata-raise" />
          </li>
        ))}
      </StripFrame>
    );
  }

  const { quotes, sentiment } = query.data;
  if (quotes.length === 0 && !sentiment) return null;

  const vix = quotes.findIndex((q) => q.kind === "volatility");
  const splitAt = vix >= 0 ? vix + 1 : quotes.length;
  return (
    <StripFrame
      after={sentiment ?? undefined}
      head={quotes.slice(0, splitAt)}
      tail={quotes.slice(splitAt)}
    />
  );
}

interface StripFrameProps {
  busy?: boolean;
  head?: MarketQuote[];
  after?: SentimentEstimate;
  tail?: MarketQuote[];
  children?: ReactNode;
}

function StripFrame({ busy = false, head = [], after, tail = [], children }: StripFrameProps) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelLeft, setPanelLeft] = useState(0);
  const sectionRef = useRef<HTMLElement | null>(null);

  // Close the panel on Escape or a click elsewhere.
  useEffect(() => {
    if (!panelOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPanelOpen(false);
    }
    function onPointer(e: PointerEvent) {
      if (!sectionRef.current?.contains(e.target as Node)) setPanelOpen(false);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onPointer);
    };
  }, [panelOpen]);

  function togglePanel(chip: HTMLElement) {
    // The row scrolls sideways, so the panel lives outside it and is
    // placed under the chip, kept inside the strip's width.
    const section = sectionRef.current?.getBoundingClientRect();
    const rect = chip.getBoundingClientRect();
    if (section) {
      const max = Math.max(0, section.width - PANEL_WIDTH - 8);
      setPanelLeft(Math.min(Math.max(0, rect.left - section.left), max));
    }
    setPanelOpen((open) => !open);
  }

  return (
    <section
      ref={sectionRef}
      aria-label="Markets"
      aria-busy={busy || undefined}
      data-testid="market-strip"
      className="relative border-b border-strata-line bg-strata-canvas"
    >
      {/* md+: chips wrap so every market is visible. Phones: one row to
          swipe, without a scrollbar eating the strip's height. */}
      <ul className="flex overflow-x-auto px-3 [scrollbar-width:none] md:flex-wrap md:overflow-visible [&::-webkit-scrollbar]:hidden">
        {children}
        {head.map((q) => (
          <QuoteChip key={q.symbol} quote={q} />
        ))}
        {after && (
          <SentimentChip
            sentiment={after}
            expanded={panelOpen}
            onToggle={togglePanel}
          />
        )}
        {tail.map((q) => (
          <QuoteChip key={q.symbol} quote={q} />
        ))}
      </ul>
      {after && panelOpen && <SentimentPanel sentiment={after} left={panelLeft} />}
    </section>
  );
}

function QuoteChip({ quote }: { quote: MarketQuote }) {
  const change = formatQuoteChange(quote);
  return (
    <li
      data-testid="market-quote"
      data-symbol={quote.symbol}
      title={`${quote.label} · as of ${formatSessionDate(quote.as_of)}`}
      className="flex h-[52px] flex-shrink-0 flex-col justify-center whitespace-nowrap px-3"
    >
      <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        {quote.label}
      </span>
      <span className="flex items-baseline gap-2 font-mono tabular">
        <span className="text-[13px] text-strata-hi">{formatQuotePrice(quote)}</span>
        <span className={`text-[11px] ${DIRECTION_CLASS[change.direction]}`}>
          <span aria-hidden="true">{DIRECTION_GLYPH[change.direction]} </span>
          {change.text}
        </span>
      </span>
    </li>
  );
}

interface SentimentChipProps {
  sentiment: SentimentEstimate;
  expanded: boolean;
  onToggle: (chip: HTMLElement) => void;
}

function SentimentChip({ sentiment, expanded, onToggle }: SentimentChipProps) {
  const score = Math.round(sentiment.score);
  const rating = RATING_LABEL[sentiment.rating];
  return (
    <li className="flex flex-shrink-0">
      <button
        type="button"
        data-testid="sentiment-chip"
        aria-expanded={expanded}
        aria-controls="sentiment-panel"
        aria-label={`Fear and greed, our estimate: ${score}, ${rating}. Show how it's built`}
        onClick={(e) => onToggle(e.currentTarget)}
        className={[
          "my-1.5 flex flex-col justify-center whitespace-nowrap rounded-md px-3 text-left transition-colors",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight",
          expanded ? "bg-strata-raise" : "hover:bg-strata-raise",
        ].join(" ")}
      >
        <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Fear &amp; Greed
          <span className="rounded border border-strata-border px-1 text-[9px] normal-case tracking-normal">
            est.
          </span>
        </span>
        <span className="flex items-center gap-2 font-mono tabular">
          <span className="text-[13px] text-strata-hi">{score}</span>
          <span className="text-[11px] text-strata-dim">{rating}</span>
          <Meter score={sentiment.score} className="w-12" />
        </span>
      </button>
    </li>
  );
}

function Meter({ score, className = "" }: { score: number; className?: string }) {
  const clamped = Math.min(100, Math.max(0, score));
  return (
    <span
      aria-hidden="true"
      className={`relative flex h-1.5 overflow-hidden rounded-full ${className}`}
    >
      {RATING_BANDS.map((band) => (
        <span
          key={band.rating}
          className={BAND_CLASS[band.rating]}
          style={{ width: `${band.to - band.from}%` }}
        />
      ))}
      <span
        data-testid="meter-marker"
        className="absolute top-0 h-full w-0.5 -translate-x-1/2 bg-strata-hi"
        style={{ left: `${clamped}%` }}
      />
    </span>
  );
}

function SentimentPanel({ sentiment, left }: { sentiment: SentimentEstimate; left: number }) {
  return (
    <div
      id="sentiment-panel"
      role="region"
      aria-label="How the fear and greed estimate is built"
      style={{ left, width: PANEL_WIDTH }}
      className="absolute top-full z-30 mt-1 max-w-[calc(100vw-6rem)] rounded-lg border border-strata-border bg-strata-surface p-4 shadow-[0_24px_48px_-16px_rgba(0,0,0,0.7)]"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Fear &amp; Greed · our estimate
        </p>
        <p className="font-mono text-[10px] text-strata-muted">
          as of {formatSessionDate(sentiment.as_of)}
        </p>
      </div>
      <p className="mt-1 flex items-baseline gap-2">
        <span className="font-mono text-2xl text-strata-hi tabular">{Math.round(sentiment.score)}</span>
        <span className="text-sm text-strata-fg">{RATING_LABEL[sentiment.rating]}</span>
      </p>
      <Meter score={sentiment.score} className="mt-2 w-full" />
      <div className="mt-1 flex justify-between font-mono text-[9px] text-strata-muted">
        <span>Extreme fear</span>
        <span>Neutral</span>
        <span>Extreme greed</span>
      </div>

      <ul className="mt-4 space-y-3">
        {sentiment.components.map((c) => (
          <li key={c.key} data-testid="sentiment-component">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-strata-fg">{c.label}</span>
              <span className="font-mono text-strata-hi tabular">{Math.round(c.score)}</span>
            </div>
            <Meter score={c.score} className="mt-1 w-full" />
            <p className="mt-1 text-[11px] leading-snug text-strata-dim">{c.description}</p>
          </li>
        ))}
      </ul>

      <p className="mt-4 border-t border-strata-line pt-3 text-[11px] leading-snug text-strata-muted">
        {sentiment.methodology}{" "}
        <a
          href={CNN_INDEX_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="text-strata-highlight hover:underline"
        >
          CNN&apos;s index ↗
        </a>
      </p>
    </div>
  );
}
