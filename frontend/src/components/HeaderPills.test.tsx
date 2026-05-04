/**
 * HeaderPills — Phase 4.5.A primitive tests.
 *
 * Renders one or more diagnostic pills at the page top-right when
 * ``layout_signals`` flags distress. Each pill maps deterministically
 * from a single signal:
 *
 *   - is_unprofitable_ttm OR gross_margin_negative → "● UNPROFITABLE · TTM"
 *   - cash_runway_quarters !== null AND < 6           → "⚠ LIQUIDITY WATCH"
 *   - beat_rate_below_30pct                          → "● BOTTOM DECILE BEAT RATE"
 *   - debt_rising_cash_falling                       → "▲ DEBT RISING · CASH FALLING"
 *
 * Returns null when every signal is healthy so the page header stays
 * clean for healthy mature names.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { HeaderPills } from "./HeaderPills";
import type { LayoutSignals } from "../lib/schemas";

function signals(overrides: Partial<LayoutSignals> = {}): LayoutSignals {
  return {
    is_unprofitable_ttm: false,
    beat_rate_below_30pct: false,
    cash_runway_quarters: null,
    gross_margin_negative: false,
    debt_rising_cash_falling: false,
    ...overrides,
  };
}

describe("HeaderPills", () => {
  it("renders nothing when every signal is healthy", () => {
    const { container } = render(<HeaderPills signals={signals()} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the UNPROFITABLE pill when is_unprofitable_ttm", () => {
    const { getByText, container } = render(
      <HeaderPills signals={signals({ is_unprofitable_ttm: true })} />,
    );
    expect(getByText(/unprofitable/i)).not.toBeNull();
    expect(
      container.querySelectorAll("[data-pill='header-pill']").length,
    ).toBe(1);
  });

  it("renders the UNPROFITABLE pill when gross_margin_negative (without dupe)", () => {
    // Both signals collapse to one pill — the user sees one
    // "UNPROFITABLE · TTM" indicator regardless of which condition
    // tripped it. Avoids visual noise on Rivian-class names where both
    // fire simultaneously.
    const { getByText, container } = render(
      <HeaderPills
        signals={signals({
          is_unprofitable_ttm: true,
          gross_margin_negative: true,
        })}
      />,
    );
    expect(getByText(/unprofitable/i)).not.toBeNull();
    const unprofitablePills = Array.from(
      container.querySelectorAll("[data-pill='header-pill']"),
    ).filter((p) => /unprofitable/i.test(p.textContent ?? ""));
    expect(unprofitablePills.length).toBe(1);
  });

  it("renders LIQUIDITY WATCH when cash_runway_quarters < 6", () => {
    const { getByText } = render(
      <HeaderPills signals={signals({ cash_runway_quarters: 4.5 })} />,
    );
    expect(getByText(/liquidity watch/i)).not.toBeNull();
  });

  it("does not render LIQUIDITY WATCH when cash_runway_quarters >= 6", () => {
    const { queryByText } = render(
      <HeaderPills signals={signals({ cash_runway_quarters: 8.0 })} />,
    );
    expect(queryByText(/liquidity watch/i)).toBeNull();
  });

  it("does not render LIQUIDITY WATCH when cash_runway_quarters is null", () => {
    const { container } = render(
      <HeaderPills signals={signals({ cash_runway_quarters: null })} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders BOTTOM DECILE BEAT RATE pill when beat_rate_below_30pct", () => {
    const { getByText } = render(
      <HeaderPills signals={signals({ beat_rate_below_30pct: true })} />,
    );
    expect(getByText(/bottom decile/i)).not.toBeNull();
  });

  it("renders DEBT RISING pill when debt_rising_cash_falling", () => {
    const { getByText } = render(
      <HeaderPills signals={signals({ debt_rising_cash_falling: true })} />,
    );
    expect(getByText(/debt rising/i)).not.toBeNull();
  });

  it("stacks multiple pills when several signals fire simultaneously", () => {
    const { container } = render(
      <HeaderPills
        signals={signals({
          is_unprofitable_ttm: true,
          cash_runway_quarters: 4.5,
          beat_rate_below_30pct: true,
        })}
      />,
    );
    const pills = container.querySelectorAll("[data-pill='header-pill']");
    expect(pills.length).toBe(3);
  });
});
