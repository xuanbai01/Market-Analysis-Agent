/**
 * WatchlistButton — Phase 4.7 star toggle on /symbol/:ticker.
 *
 * Mounted next to the HeaderPills. Click flips the localStorage
 * watchlist entry for the ticker. Visual state is local-mirrored so
 * the click feels instant — no parent re-render needed.
 *
 * Outside this button, the watchlist is read by the sidebar (count
 * badge), the search modal (inline suggestion), and the landing
 * page (watchlist section). All those readers re-read from
 * localStorage on mount; the button doesn't need to broadcast.
 */
import { useState } from "react";

import { isWatched as readIsWatched, toggleWatchlist } from "../lib/watchlist";

interface Props {
  ticker: string;
}

export function WatchlistButton({ ticker }: Props) {
  // Initial mirror — read once on mount.
  const [watched, setWatched] = useState<boolean>(() => readIsWatched(ticker));

  function handleClick() {
    const nextState = toggleWatchlist(ticker);
    setWatched(nextState);
  }

  const label = watched ? "Remove from watchlist" : "Add to watchlist";

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={watched}
      onClick={handleClick}
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
