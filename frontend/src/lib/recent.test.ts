/**
 * recent tests (Phase 4.7).
 *
 * MRU list of last-visited tickers, capped at 10. Same localStorage
 * pattern as watchlist.ts; same per-test isolation via beforeEach
 * clear.
 *
 * Behaviors pinned:
 *   1. listRecent returns [] on empty / corrupted storage.
 *   2. pushRecent prepends the ticker (MRU = front).
 *   3. pushRecent dedupes — re-pushing an existing ticker moves it to front.
 *   4. pushRecent caps the list at 10 (oldest drops off).
 *   5. pushRecent uppercases the ticker on the way in.
 *   6. Round-trip: write → read returns the same list.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { listRecent, pushRecent, RECENT_MAX } from "./recent";

beforeEach(() => {
  window.localStorage.clear();
});

describe("recent", () => {
  it("returns an empty list when storage is empty", () => {
    expect(listRecent()).toEqual([]);
  });

  it("pushRecent prepends new tickers (MRU front)", () => {
    pushRecent("NVDA");
    pushRecent("AAPL");
    pushRecent("MSFT");
    expect(listRecent()).toEqual(["MSFT", "AAPL", "NVDA"]);
  });

  it("pushRecent dedupes — re-pushing moves to front, doesn't duplicate", () => {
    pushRecent("NVDA");
    pushRecent("AAPL");
    pushRecent("NVDA");
    expect(listRecent()).toEqual(["NVDA", "AAPL"]);
  });

  it("caps the list at RECENT_MAX (oldest drops off)", () => {
    // Push more than the cap.
    for (let i = 0; i < RECENT_MAX + 5; i++) {
      pushRecent(`T${i}`);
    }
    const list = listRecent();
    expect(list.length).toBe(RECENT_MAX);
    // Front is the most recent push.
    expect(list[0]).toBe(`T${RECENT_MAX + 4}`);
    // The earliest pushes have aged out.
    expect(list).not.toContain("T0");
  });

  it("uppercases the ticker", () => {
    pushRecent("nvda");
    expect(listRecent()).toEqual(["NVDA"]);
  });

  it("survives a corrupted storage payload (returns [])", () => {
    window.localStorage.setItem("market-agent.recent", "{not-json");
    expect(listRecent()).toEqual([]);
  });
});
