/**
 * WatchlistButton tests (Phase 4.7).
 *
 * Star-toggle button rendered next to the HeaderPills on
 * /symbol/:ticker. Reads from + writes to localStorage via the
 * watchlist helpers. State is local-mirrored so a click immediately
 * flips the visual state without a parent re-render.
 *
 * Behaviors pinned:
 *   1. Renders unfilled star when ticker is not in watchlist.
 *   2. Renders filled star when ticker is in watchlist.
 *   3. Click toggles the state (visual + persistence both flip).
 *   4. aria-pressed reflects current state.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { WatchlistButton } from "./WatchlistButton";
import { addToWatchlist, isWatched } from "../lib/watchlist";

beforeEach(() => {
  window.localStorage.clear();
});

describe("WatchlistButton", () => {
  it("renders unfilled when ticker is not watchlisted", () => {
    render(<WatchlistButton ticker="NVDA" />);
    const button = screen.getByRole("button", { name: /watchlist/i });
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders filled when ticker is already watchlisted", () => {
    addToWatchlist("NVDA");
    render(<WatchlistButton ticker="NVDA" />);
    const button = screen.getByRole("button", { name: /watchlist/i });
    expect(button.getAttribute("aria-pressed")).toBe("true");
  });

  it("click toggles the watchlist persistence", () => {
    render(<WatchlistButton ticker="NVDA" />);
    const button = screen.getByRole("button", { name: /watchlist/i });
    fireEvent.click(button);
    expect(isWatched("NVDA")).toBe(true);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(isWatched("NVDA")).toBe(false);
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("uppercases the ticker prop before persisting", () => {
    render(<WatchlistButton ticker="nvda" />);
    fireEvent.click(screen.getByRole("button", { name: /watchlist/i }));
    expect(isWatched("NVDA")).toBe(true);
  });
});
