/**
 * WatchlistButton — star toggle on /symbol/:ticker. Phase 4.7.
 *
 * Reads the live watchlist (useWatchlist), so it stays in step with
 * the sidebar: unstarring a ticker from the sidebar empties this star,
 * and starring here adds the sidebar row on the same render.
 */
import { toggleWatchlist, useWatchlist } from "../lib/watchlist";

interface Props {
  ticker: string;
}

export function WatchlistButton({ ticker }: Props) {
  const watched = useWatchlist().includes(ticker.toUpperCase());
  const label = watched ? "Remove from watchlist" : "Add to watchlist";

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={watched}
      title={label}
      onClick={() => toggleWatchlist(ticker)}
      className={`flex h-8 w-8 items-center justify-center rounded-md border transition ${
        watched
          ? "border-strata-highlight/40 bg-strata-highlight/10 text-strata-highlight"
          : "border-strata-border bg-strata-surface text-strata-dim hover:border-strata-highlight/40 hover:text-strata-highlight"
      }`}
    >
      {watched ? "★" : "☆"}
    </button>
  );
}
