import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptionsReportSchema } from "../../lib/options-schemas";
import { dayTicks } from "./chart-kit";
import { EarningsMoves } from "./EarningsMoves";
import { ExpectedMoveCone } from "./ExpectedMoveCone";
import { RAW_OPTIONS_REPORT } from "./fixture";
import { OpenInterestChart } from "./OpenInterestChart";
import { SmileChart } from "./SmileChart";
import { TermStructureChart } from "./TermStructureChart";

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const CHAIN = REPORT.chain!;
const EARNINGS = REPORT.earnings!;

describe("ExpectedMoveCone", () => {
  it("draws the one-sigma band out to about six months, with the report marked", () => {
    render(<ExpectedMoveCone expiries={REPORT.expiries} spot={REPORT.spot!} eventDays={5} />);
    expect(screen.getByTestId("options-cone-band")).toBeInTheDocument();
    expect(screen.getAllByTestId("options-cone-hit")).toHaveLength(10); // the 399-day expiry is left off
    expect(screen.getByTestId("options-cone-event")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", expect.stringMatching(/^Expected move by expiry/));
  });

  it("tells the range of an expiry on hover", () => {
    render(<ExpectedMoveCone expiries={REPORT.expiries} spot={REPORT.spot!} eventDays={null} />);
    fireEvent.mouseEnter(screen.getAllByTestId("options-cone-hit")[4]);
    const tip = screen.getByTestId("options-cone-tooltip");
    expect(tip).toHaveTextContent("28 days");
    expect(tip).toHaveTextContent("±16.7%");
    expect(tip).toHaveTextContent("IV 60.4%");
  });

  it("draws nothing for fewer than two expiries", () => {
    const { container } = render(<ExpectedMoveCone expiries={REPORT.expiries.slice(0, 1)} spot={100} eventDays={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TermStructureChart", () => {
  it("plots each expiry's ATM IV with realized vol as a reference", () => {
    render(<TermStructureChart expiries={REPORT.expiries} rv20={REPORT.rv20} />);
    expect(screen.getAllByTestId("options-term-dot")).toHaveLength(11);
    expect(screen.getAllByTestId("options-term-dot").filter((d) => d.getAttribute("data-earnings") === "true")).toHaveLength(10);
    expect(screen.getByTestId("options-term-rv")).toHaveTextContent("RV20");
  });

  it("tells an expiry's IV on hover", () => {
    render(<TermStructureChart expiries={REPORT.expiries} rv20={null} />);
    fireEvent.mouseEnter(screen.getAllByTestId("options-term-hit")[1]);
    expect(screen.getByTestId("options-term-tooltip")).toHaveTextContent("5 days");
    expect(screen.queryByTestId("options-term-rv")).toBeNull();
  });

  it("draws nothing for fewer than two expiries", () => {
    const { container } = render(<TermStructureChart expiries={[]} rv20={0.2} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SmileChart", () => {
  it("draws puts and calls with the forward marked and a legend", () => {
    render(<SmileChart chain={CHAIN} />);
    expect(screen.getAllByTestId("options-smile-dot")).toHaveLength(CHAIN.smile.length);
    expect(screen.getByTestId("options-smile-forward")).toBeInTheDocument();
    expect(screen.getByText("Puts")).toBeInTheDocument();
    expect(screen.getByText("Calls")).toBeInTheDocument();
  });

  it("draws nothing with fewer than three points", () => {
    const { container } = render(<SmileChart chain={{ ...CHAIN, smile: CHAIN.smile.slice(0, 2) }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("OpenInterestChart", () => {
  it("mirrors call and put open interest by strike", () => {
    render(<OpenInterestChart chain={CHAIN} spot={REPORT.spot} />);
    const calls = CHAIN.open_interest.filter((p) => p.call > 0).length;
    const puts = CHAIN.open_interest.filter((p) => p.put > 0).length;
    expect(screen.getAllByTestId("options-oi-call")).toHaveLength(calls);
    expect(screen.getAllByTestId("options-oi-put")).toHaveLength(puts);
    fireEvent.mouseEnter(screen.getAllByTestId("options-oi-hit")[0]);
    expect(screen.getByTestId("options-oi-tooltip")).toHaveTextContent("Calls");
  });

  it("draws nothing without open interest", () => {
    const { container } = render(<OpenInterestChart chain={{ ...CHAIN, open_interest: [] }} spot={100} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("EarningsMoves", () => {
  it("sets past reports' moves against the move the options price", () => {
    render(<EarningsMoves earnings={EARNINGS} />);
    expect(screen.getAllByTestId("options-earnings-bar")).toHaveLength(8);
    expect(screen.getByTestId("options-earnings-band")).toBeInTheDocument();
    // The average size of the move, not a one-sigma band like the cone's.
    expect(screen.getByTestId("options-earnings-summary")).toHaveTextContent("an average move of 7.1%");
    expect(screen.getByTestId("options-earnings-summary").textContent).not.toContain("±");
    expect(screen.getByTestId("options-earnings-summary")).toHaveTextContent("$11.59");
    expect(screen.getByTestId("options-earnings-summary")).toHaveTextContent("4.0%");
  });

  it("says why there's no implied move, and still shows the past ones", () => {
    render(<EarningsMoves earnings={{ ...EARNINGS, implied_move: null, implied_move_usd: null, refused: "the first expiry after the report is 98 days out" }} />);
    expect(screen.queryByTestId("options-earnings-band")).toBeNull();
    expect(screen.getByTestId("options-earnings-summary")).toHaveTextContent("98 days out");
    expect(screen.getAllByTestId("options-earnings-bar")).toHaveLength(8);
  });

  it("draws nothing with no report and no history", () => {
    const { container } = render(
      <EarningsMoves earnings={{ ...EARNINGS, next_date: null, implied_move: null, past: [], refused: "no earnings date" }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("dayTicks", () => {
  it("labels the standard horizons the expiries reach", () => {
    expect(dayTicks(100)).toEqual([7, 30, 90]);
  });

  it("labels the farthest expiry when it is nearer than a week", () => {
    expect(dayTicks(4.6)).toEqual([5]);
  });
});
