import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { type ExpiryChain, ExpiryChainSchema, OptionsReportSchema, type Positioning } from "../../lib/options-schemas";
import {
  acrossSentence,
  compactUsd,
  contractLabel,
  deltaSentence,
  gammaSentence,
  maxPainSentence,
  positioningSentence,
  strikeLabel,
  type Sentence,
} from "../../lib/options-text";
import { AcrossExpiries } from "./AcrossExpiries";
import { ExpirySection } from "./ExpirySection";
import { ExposureChart } from "./ExposureChart";
import { RAW_OPTIONS_REPORT } from "./fixture";
import { OpenInterestChart } from "./OpenInterestChart";
import { TopOpenInterest } from "./TopOpenInterest";

vi.mock("../../lib/options-api", () => ({ fetchOptionsChain: vi.fn() }));

const text = (s: Sentence | null) => (s === null ? null : s.map((p) => (typeof p === "string" ? p : `**${p.strong}**`)).join(""));

// NVDA's Nov 16 expiry as our code computed it from Yahoo on 2026-11-15.
const POSITIONING: Positioning = {
  call_open_interest: 175164,
  put_open_interest: 121003,
  put_call: 0.6908,
  top: [
    { strike: 200, side: "call", open_interest: 17272 },
    { strike: 150, side: "put", open_interest: 13924 },
    { strike: 180, side: "call", open_interest: 13562 },
  ],
  max_pain: 167.5,
  exposure: [
    { strike: 155, gex: -3_100_000, dex: -900_000 },
    { strike: 160, gex: -9_800_000, dex: -1_400_000 },
    { strike: 165, gex: 7_200_000, dex: 600_000 },
    { strike: 170, gex: 2_400_000, dex: 300_000 },
    { strike: 175, gex: 0, dex: 0 },
  ],
  call_gex: 48_870_000,
  put_gex: -65_820_000,
  net_gex: -16_960_000,
  call_dex: 1_760_000,
  put_dex: -4_160_000,
  net_dex: -2_400_000,
  call_wall: 165,
  put_wall: 160,
  gamma_flip: 165.29,
  assumption: "Gamma and delta exposure assume dealers are long the calls and short the puts customers hold opposite them.",
};

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const CHAIN = { ...REPORT.chain!, positioning: POSITIONING };

describe("positioning words", () => {
  it("formats dollars, strikes and contracts", () => {
    expect(compactUsd(-16_960_000)).toBe("−$17.0M");
    expect(compactUsd(48_870_000)).toBe("$48.9M");
    expect(compactUsd(2_400_000_000)).toBe("$2.40B");
    expect(compactUsd(950_400)).toBe("$950K");
    expect(compactUsd(12)).toBe("$12");
    expect(strikeLabel(200)).toBe("$200");
    expect(strikeLabel(162.5)).toBe("$162.5");
    expect(contractLabel("2026-11-16", POSITIONING.top[0])).toBe("Nov 16 $200 call");
  });

  it("says where open interest sits and where max pain is against the price", () => {
    expect(text(positioningSentence(POSITIONING, "2026-11-16"))).toBe(
      "Nov 16: **175,164 calls** and **121,003 puts** open (put/call **0.69**); the largest is the **$200 call (17,272)**.",
    );
    expect(text(maxPainSentence(POSITIONING, 162.85))).toBe(
      "Max pain is **$167.50**, **2.9% above** the price: the settle that would leave the most open contracts worthless.",
    );
    expect(text(maxPainSentence({ ...POSITIONING, max_pain: 160 }, 162.85))).toContain("**1.8% below**");
    expect(text(maxPainSentence({ ...POSITIONING, max_pain: 162.85 }, 162.85))).toContain("**at** the price");
    expect(maxPainSentence({ ...POSITIONING, max_pain: null }, 162.85)).toBeNull();
  });

  it("names what gamma's sign means only under the stated assumption", () => {
    expect(text(gammaSentence(POSITIONING))).toBe(
      "Net gamma exposure is **−$17.0M per 1% move**: if dealers hold the other side as assumed, their hedging would add to moves; it changes sign near **$165.29**.",
    );
    expect(text(gammaSentence({ ...POSITIONING, net_gex: 5_000_000, gamma_flip: null }))).toBe(
      "Net gamma exposure is **$5.0M per 1% move**: if dealers hold the other side as assumed, their hedging would damp moves.",
    );
    expect(text(deltaSentence(POSITIONING))).toBe("Net delta exposure is **−$2.4M per 1% move**: puts' delta outweighs calls'.");
    expect(gammaSentence({ ...POSITIONING, call_open_interest: 0, put_open_interest: 0 })).toBeNull();
  });

  it("gives max pain's range across expiries", () => {
    const e = REPORT.expiries;
    const priced = [
      { ...e[0], max_pain: 167.5 },
      { ...e[1], max_pain: 190 },
      { ...e[2], max_pain: 160 },
    ];
    expect(text(acrossSentence(priced))).toMatch(/^Max pain runs from \*\*\$160\.00\*\* \(.+\) to \*\*\$190\.00\*\* \(.+\) across the 3 expiries read\.$/);
    expect(acrossSentence([{ ...e[0], max_pain: null }])).toBeNull();
  });
});

describe("positioning schema", () => {
  it("reads a chain with positioning, and one cached before it", () => {
    const raw = RAW_OPTIONS_REPORT.chain as Record<string, unknown>;
    expect(ExpiryChainSchema.parse({ ...raw, positioning: POSITIONING }).positioning?.max_pain).toBe(167.5);
    expect(ExpiryChainSchema.parse(raw).positioning).toBeNull();
    expect(OptionsReportSchema.parse(RAW_OPTIONS_REPORT).expiries[0].max_pain).toBeNull();
  });
});

describe("positioning charts", () => {
  it("ranks the largest contracts, and draws nothing with none", () => {
    const { unmount } = render(<TopOpenInterest expiry="2026-11-16" top={POSITIONING.top} />);
    const rows = screen.getAllByTestId("options-top-oi-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Nov 16 $200 call17,272");
    unmount();
    const { container } = render(<TopOpenInterest expiry="2026-11-16" top={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws a bar per strike with exposure, the price and the flip", () => {
    render(<ExposureChart positioning={POSITIONING} field="gex" price={162.85} testId="gex" />);
    expect(screen.getAllByTestId("gex-bar")).toHaveLength(4); // the zero strike draws no bar
    expect(screen.getByTestId("gex-price")).toHaveTextContent("price $162.85");
    expect(screen.getByTestId("gex-flip")).toHaveTextContent("flip $165.29");
  });

  it("marks no flip on the delta chart, and draws nothing when every strike is zero", () => {
    const { unmount } = render(<ExposureChart positioning={POSITIONING} field="dex" price={162.85} testId="dex" />);
    expect(screen.queryByTestId("dex-flip")).toBeNull();
    unmount();
    const flat = { ...POSITIONING, exposure: POSITIONING.exposure.map((e) => ({ ...e, gex: 0 })) };
    const { container } = render(<ExposureChart positioning={flat} field="gex" price={162.85} testId="flat" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("marks max pain on the open interest chart", () => {
    render(<OpenInterestChart chain={CHAIN} spot={162.85} />);
    expect(screen.getByTestId("options-oi-max-pain")).toHaveTextContent("max pain $167.50");
  });

  it("lists each expiry read with its max pain against the price", () => {
    const expiries = REPORT.expiries.map((e, i) => ({ ...e, max_pain: i === 0 ? 167.5 : null, net_gex: i === 0 ? -16_960_000 : null }));
    render(<AcrossExpiries expiries={expiries} price={162.85} />);
    const rows = screen.getAllByTestId("options-across-row");
    expect(rows).toHaveLength(expiries.length);
    const first = rows.find((r) => r.textContent?.includes("$167.50"));
    expect(first).toHaveTextContent("+$4.65 (+2.9%)");
    expect(first).toHaveTextContent("−$17.0M");
  });

  it("hides the table when no expiry has max pain", () => {
    const { container } = render(<AcrossExpiries expiries={REPORT.expiries} price={162.85} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the expiry panel's positioning block", () => {
  function renderSection(chain: ExpiryChain = CHAIN) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ExpirySection
            symbol="NVDA"
            listed={REPORT.listed_expiries}
            initial={chain}
            spot={162.85}
            quotedAt={REPORT.quoted_at}
            skew25={REPORT.skew25}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("shows the largest contracts, gamma and delta with their stats and the assumption", () => {
    renderSection();
    const block = screen.getByTestId("options-positioning");
    expect(within(block).getByTestId("options-top-oi-block-summary")).toHaveTextContent(/175,164 calls/);
    expect(within(block).getByTestId("options-gex-block-stats")).toHaveTextContent("Call wall$165.00");
    expect(within(block).getByTestId("options-gex-block-stats")).toHaveTextContent("Gamma flip$165.29");
    expect(within(block).getByTestId("options-dex-block-summary")).toHaveTextContent(/puts' delta outweighs/);
    expect(screen.getByTestId("options-positioning-assumption")).toHaveTextContent(/dealers/);
    // The open interest chart's sentence is now max pain's.
    expect(screen.getByTestId("options-oi-block-summary")).toHaveTextContent(/^Max pain is \$167\.50/);
  });

  it("leaves the block out for a chain cached before positioning", () => {
    renderSection({ ...CHAIN, positioning: null });
    expect(screen.queryByTestId("options-positioning")).toBeNull();
    expect(screen.getByTestId("options-oi-block-summary")).toHaveTextContent(/^Most open near the money/);
  });
});
