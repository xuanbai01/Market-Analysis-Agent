/**
 * watchlist tests (Phase 4.7).
 *
 * Pure localStorage CRUD — no React, no fetch. Each test isolates by
 * clearing localStorage in beforeEach.
 *
 * Behaviors pinned:
 *   1. listWatchlist returns [] on empty / corrupted storage.
 *   2. addToWatchlist persists and dedupes on a second add.
 *   3. removeFromWatchlist removes the ticker; no-op when absent.
 *   4. toggleWatchlist flips state and returns the new isWatched value.
 *   5. isWatched is case-insensitive about the queried ticker.
 *   6. Round-trip: write → read returns the same list.
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  addToWatchlist,
  isWatched,
  listWatchlist,
  removeFromWatchlist,
  toggleWatchlist,
} from "./watchlist";

beforeEach(() => {
  window.localStorage.clear();
});

describe("watchlist", () => {
  it("returns an empty list when storage is empty", () => {
    expect(listWatchlist()).toEqual([]);
    expect(isWatched("NVDA")).toBe(false);
  });

  it("addToWatchlist persists and uppercases the ticker", () => {
    addToWatchlist("nvda");
    expect(listWatchlist()).toEqual(["NVDA"]);
    expect(isWatched("NVDA")).toBe(true);
    expect(isWatched("nvda")).toBe(true);
  });

  it("addToWatchlist dedupes — adding the same ticker twice keeps one entry", () => {
    addToWatchlist("NVDA");
    addToWatchlist("NVDA");
    expect(listWatchlist()).toEqual(["NVDA"]);
  });

  it("removeFromWatchlist removes the entry; no-op when absent", () => {
    addToWatchlist("NVDA");
    addToWatchlist("AAPL");
    removeFromWatchlist("NVDA");
    expect(listWatchlist()).toEqual(["AAPL"]);
    // Removing again is a no-op, no throw.
    removeFromWatchlist("NVDA");
    expect(listWatchlist()).toEqual(["AAPL"]);
  });

  it("toggleWatchlist flips state and returns the new isWatched value", () => {
    expect(toggleWatchlist("NVDA")).toBe(true);
    expect(isWatched("NVDA")).toBe(true);
    expect(toggleWatchlist("NVDA")).toBe(false);
    expect(isWatched("NVDA")).toBe(false);
  });

  it("survives a corrupted storage payload (returns [] rather than throwing)", () => {
    window.localStorage.setItem("market-agent.watchlist", "{not-json");
    expect(listWatchlist()).toEqual([]);
    // And a subsequent add overwrites cleanly.
    addToWatchlist("NVDA");
    expect(listWatchlist()).toEqual(["NVDA"]);
  });
});
