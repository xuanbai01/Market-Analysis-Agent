/**
 * SearchModal tests (Phase 4.7).
 *
 * Triggered by ⌘K from anywhere in the app. Filterable input over the
 * union of (recent ∪ watchlist ∪ POPULAR_TICKERS, deduped). Submitting
 * any text uppercases → calls onSelect with the ticker. Esc closes.
 *
 * Behaviors pinned:
 *   1. Renders nothing when isOpen=false.
 *   2. Renders dialog with input when isOpen=true.
 *   3. Filters the suggestion list as the user types.
 *   4. Recent + watchlist tickers appear in the list.
 *   5. Submit (Enter on input) calls onSelect with the typed ticker uppercased.
 *   6. Clicking a suggestion calls onSelect with that ticker.
 *   7. Esc closes (calls onClose).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SearchModal } from "./SearchModal";
import { addToWatchlist } from "../../lib/watchlist";
import { pushRecent } from "../../lib/recent";

beforeEach(() => {
  window.localStorage.clear();
});

describe("SearchModal", () => {
  it("renders nothing when isOpen=false", () => {
    const { container } = render(
      <SearchModal isOpen={false} onClose={() => {}} onSelect={() => {}} />,
    );
    // No dialog rendered.
    expect(container.querySelector("[role='dialog']")).toBeNull();
  });

  it("renders dialog with autofocused input when isOpen=true", () => {
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={() => {}} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it("includes popular tickers in the suggestion list", () => {
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={() => {}} />);
    // NVDA is in POPULAR_TICKERS.
    expect(screen.getAllByText(/^NVDA$/i).length).toBeGreaterThan(0);
  });

  it("surfaces recent + watchlist tickers inline", () => {
    addToWatchlist("AVGO");
    pushRecent("HOOD");
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={() => {}} />);
    expect(screen.getAllByText(/^AVGO$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^HOOD$/i).length).toBeGreaterThan(0);
  });

  it("filters the list as the user types", () => {
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={() => {}} />);
    const input = screen.getByPlaceholderText(/search/i);
    fireEvent.change(input, { target: { value: "AAPL" } });
    // AAPL should be in the filtered list (it's in POPULAR_TICKERS); other
    // popular tickers like NVDA should not.
    expect(screen.getAllByText(/^AAPL$/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/^NVDA$/i)).toHaveLength(0);
  });

  it("submitting the input via Enter calls onSelect with uppercased ticker", () => {
    const onSelect = vi.fn();
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={onSelect} />);
    const input = screen.getByPlaceholderText(/search/i);
    fireEvent.change(input, { target: { value: "tsla" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("TSLA");
  });

  it("clicking a suggestion calls onSelect with that ticker", () => {
    const onSelect = vi.fn();
    render(<SearchModal isOpen={true} onClose={() => {}} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByText(/^NVDA$/i)[0]);
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("Esc keydown calls onClose", () => {
    const onClose = vi.fn();
    render(<SearchModal isOpen={true} onClose={onClose} onSelect={() => {}} />);
    const input = screen.getByPlaceholderText(/search/i);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
