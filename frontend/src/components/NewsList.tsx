/**
 * NewsList — Phase 4.4.A.
 *
 * The right side of the ContextBand. Shows the latest ranked news
 * items with category filter pills + sentiment dots. Default 5 items
 * with a "View N more" disclosure. Lightweight — no infinite scroll,
 * no virtualization (≤30 items per report).
 */
import { useMemo, useState } from "react";

import {
  NEWS_CATEGORIES,
  extractNewsItems,
  type NewsCategory,
  type NewsItem,
  type NewsSentiment,
} from "../lib/news-extract";
import type { Section } from "../lib/schemas";

interface Props {
  section: Section;
}

const DEFAULT_VISIBLE = 5;

const CATEGORY_LABELS: Record<NewsCategory, string> = {
  earnings: "Earnings",
  product: "Product",
  regulatory: "Regulatory",
  m_and_a: "M&A",
  supply: "Supply",
  strategy: "Strategy",
  other: "Other",
};

const SENTIMENT_COLOR: Record<NewsSentiment, string> = {
  positive: "bg-strata-pos",
  neutral: "bg-strata-dim",
  negative: "bg-strata-neg",
};

type Filter = "all" | NewsCategory;

function formatPublishedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // UTC-based date (matches LineChart's convention from 4.3.B.2 — the
  // displayed date should match the underlying timestamp regardless
  // of local TZ).
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function NewsList({ section }: Props) {
  const items = useMemo(() => extractNewsItems(section), [section]);
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState(false);

  const filtered = useMemo(
    () =>
      filter === "all" ? items : items.filter((i) => i.category === filter),
    [items, filter],
  );

  const visible = expanded ? filtered : filtered.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = filtered.length - visible.length;

  if (items.length === 0) {
    return (
      <section className="rounded-md border border-strata-border bg-strata-surface p-5">
        <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-earnings">
          News · last 7 days
        </div>
        <div className="flex h-[120px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          No recent news
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header
        data-testid="news-header"
        className="mb-3 flex items-center justify-between"
      >
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-earnings">
          News · last 7 days · {items.length} item{items.length === 1 ? "" : "s"}
        </div>
      </header>

      <div className="mb-3 flex flex-wrap gap-1.5">
        <FilterPill
          label="All"
          active={filter === "all"}
          onClick={() => setFilter("all")}
        />
        {NEWS_CATEGORIES.map((cat) => (
          <FilterPill
            key={cat}
            label={CATEGORY_LABELS[cat]}
            active={filter === cat}
            onClick={() => setFilter(cat)}
          />
        ))}
      </div>

      <ul className="divide-y divide-strata-line">
        {visible.map((item, i) => (
          <NewsItemRow key={`${item.url}-${i}`} item={item} />
        ))}
      </ul>

      {hiddenCount > 0 && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="font-mono text-[11px] uppercase tracking-kicker text-strata-dim transition hover:text-strata-fg"
          >
            View {hiddenCount} more
          </button>
        </div>
      )}
      {expanded && filtered.length > DEFAULT_VISIBLE && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="font-mono text-[11px] uppercase tracking-kicker text-strata-dim transition hover:text-strata-fg"
          >
            Show fewer
          </button>
        </div>
      )}
    </section>
  );
}

function FilterPill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-pill="news-filter"
      onClick={onClick}
      className={`rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-kicker transition ${
        active
          ? "bg-strata-highlight text-strata-canvas"
          : "bg-strata-raise text-strata-dim hover:text-strata-fg"
      }`}
    >
      {label}
    </button>
  );
}

function NewsItemRow({ item }: { item: NewsItem }) {
  return (
    <li
      data-row="news-item"
      className="flex items-start gap-3 py-2.5"
    >
      <span
        data-testid="news-sentiment"
        aria-label={`Sentiment: ${item.sentiment}`}
        className={`mt-1.5 inline-block h-1.5 w-1.5 rounded-full ${SENTIMENT_COLOR[item.sentiment]}`}
      />
      <div className="flex-1 min-w-0">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-sm leading-snug text-strata-fg hover:text-strata-hi"
        >
          {item.title}
        </a>
        <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          <span>{item.sourceLabel}</span>
          <span aria-hidden>·</span>
          <span>{formatPublishedAt(item.publishedAt)}</span>
          <span aria-hidden>·</span>
          <span className="text-strata-dim">
            {CATEGORY_LABELS[item.category]}
          </span>
        </div>
      </div>
    </li>
  );
}
