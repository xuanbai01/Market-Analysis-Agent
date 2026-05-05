/**
 * SidebarShell tests (Phase 4.0).
 *
 * The sidebar is a 72px-wide left rail visible on every authenticated
 * route. It carries the brand logo and 5 nav icons (Search, Compare,
 * Watch, Recent, Export). The "active" state is passed in via prop —
 * SidebarShell stays router-agnostic so it's testable in isolation.
 *
 * Behavior pinned here:
 *
 * 1. Renders with the documented width (72px) so layout is predictable.
 * 2. Renders all five nav icons + the logo.
 * 3. Active prop highlights the matching nav button.
 * 4. Disabled nav buttons (Compare/Watch/Recent/Export — those land in
 *    later phases) are visually present but not clickable.
 * 5. Search button fires its onClick handler.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SidebarShell } from "./SidebarShell";

describe("SidebarShell", () => {
  it("renders the brand logo", () => {
    render(<SidebarShell active="search" onSearchClick={() => {}} />);
    expect(screen.getByLabelText(/logo|brand/i)).toBeInTheDocument();
  });

  it("renders 5 nav buttons (Search / Compare / Watch / Recent / Export)", () => {
    render(<SidebarShell active="search" onSearchClick={() => {}} />);
    for (const label of ["Search", "Compare", "Watchlist", "Recent", "Export"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("highlights the active nav button via aria-current", () => {
    render(<SidebarShell active="search" onSearchClick={() => {}} />);
    expect(screen.getByRole("button", { name: "Search" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // Other buttons should NOT carry aria-current.
    expect(screen.getByRole("button", { name: "Compare" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("calls onSearchClick when Search is clicked", () => {
    const onSearch = vi.fn();
    render(<SidebarShell active="search" onSearchClick={onSearch} />);
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch).toHaveBeenCalledOnce();
  });

  it("disables Compare / Watch / Recent / Export until later phases", () => {
    render(<SidebarShell active="search" onSearchClick={() => {}} />);
    for (const label of ["Compare", "Watchlist", "Recent", "Export"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "Search" })).not.toBeDisabled();
  });

  it("uses a 72px width via the strata-sidebar class marker", () => {
    const { container } = render(
      <SidebarShell active="search" onSearchClick={() => {}} />,
    );
    // The width is enforced via Tailwind class; we test the marker
    // attribute that the component sets so the test isn't tied to
    // the specific Tailwind classname.
    const aside = container.querySelector("aside[data-sidebar='strata']");
    expect(aside).not.toBeNull();
  });
});

// ── Phase 4.7 — count badges + new click handlers ────────────────────
//
// Each Nav button (Compare / Watchlist / Recent) becomes enabled when
// the corresponding optional onClick handler is passed. Watchlist and
// Recent additionally render a count badge when the corresponding
// numeric prop is > 0. Export stays permanently disabled until that
// phase lands (TBD).

describe("SidebarShell — Phase 4.7 count badges + click handlers", () => {
  it("Compare becomes enabled and clickable when onCompareClick is provided", () => {
    const onCompare = vi.fn();
    render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onCompareClick={onCompare}
      />,
    );
    const button = screen.getByRole("button", { name: "Compare" });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onCompare).toHaveBeenCalledOnce();
  });

  it("Watchlist becomes enabled when onWatchlistClick is provided", () => {
    const onWatchlist = vi.fn();
    render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onWatchlistClick={onWatchlist}
      />,
    );
    const button = screen.getByRole("button", { name: /watchlist/i });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onWatchlist).toHaveBeenCalledOnce();
  });

  it("Recent becomes enabled when onRecentClick is provided", () => {
    const onRecent = vi.fn();
    render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onRecentClick={onRecent}
      />,
    );
    const button = screen.getByRole("button", { name: /recent/i });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onRecent).toHaveBeenCalledOnce();
  });

  it("Watchlist count badge renders when watchlistCount > 0", () => {
    const { container } = render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onWatchlistClick={() => {}}
        watchlistCount={3}
      />,
    );
    const badge = container.querySelector("[data-badge='watchlist-count']");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toContain("3");
  });

  it("Watchlist count badge is hidden when watchlistCount is 0 or undefined", () => {
    const { container, rerender } = render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onWatchlistClick={() => {}}
        watchlistCount={0}
      />,
    );
    expect(
      container.querySelector("[data-badge='watchlist-count']"),
    ).toBeNull();

    rerender(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onWatchlistClick={() => {}}
      />,
    );
    expect(
      container.querySelector("[data-badge='watchlist-count']"),
    ).toBeNull();
  });

  it("Recent count badge renders when recentCount > 0", () => {
    const { container } = render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onRecentClick={() => {}}
        recentCount={5}
      />,
    );
    const badge = container.querySelector("[data-badge='recent-count']");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toContain("5");
  });

  it("Export stays disabled regardless of other props (TBD phase)", () => {
    render(
      <SidebarShell
        active="none"
        onSearchClick={() => {}}
        onCompareClick={() => {}}
        onWatchlistClick={() => {}}
        onRecentClick={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });
});
