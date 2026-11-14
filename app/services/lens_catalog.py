"""
The lenses on offer: which metric, read from which XBRL tags, across
which companies (ADR 0007 layer 3; computed in ``lens``).

Every lens reports the same three numbers per company-year: the metric in
dollars, the metric ÷ revenue ("intensity") and the metric ÷ operating
cash flow. A new lens over the same group is a new ``LensMetric`` and one
entry in ``LENSES``.

Checked against SEC on 2026-11-14 for the megacap group, 2015–2025: capex
and stock-based compensation are tagged by all seven companies every year.
R&D by all but Amazon, which reports "technology and infrastructure"
spending instead (a broader cost), so the R&D lens leaves it out rather
than mix definitions. Buybacks and dividends were not added: Amazon and
Tesla tag neither, and a missing value can't be told apart from a zero.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas.lens import LensMetricInfo, LensSummary
from app.services import xbrl


@dataclass(frozen=True)
class LensMetric:
    key: str
    label: str  # starts a heading: "Capex", "SBC", "R&D"
    short: str  # inside a sentence: "capex", "SBC", "R&D"
    tags: tuple[str, ...]  # ordered us-gaap preferences, merged year by year
    definition: str  # one sentence, shown under the lens and given to the model

    def info(self) -> LensMetricInfo:
        return LensMetricInfo(key=self.key, label=self.label, short=self.short, definition=self.definition)


@dataclass(frozen=True)
class LensCompanySpec:
    ticker: str
    name: str
    cik: str


@dataclass(frozen=True)
class LensSpec:
    id: str
    title: str
    description: str
    metric: LensMetric
    companies: tuple[LensCompanySpec, ...]

    def summary(self) -> LensSummary:
        return LensSummary(
            id=self.id,
            title=self.title,
            description=self.description,
            tickers=[c.ticker for c in self.companies],
            metric=self.metric.info(),
        )


CAPEX = LensMetric(
    key="capex",
    label="Capex",
    short="capex",
    tags=xbrl.CAPEX_TAGS,
    definition="Capex is purchases of property and equipment.",
)
SBC = LensMetric(
    key="sbc",
    label="SBC",
    short="SBC",
    tags=("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
    definition=(
        "SBC is stock-based compensation: the non-cash cost of paying employees "
        "in shares, as added back in the cash flow statement."
    ),
)
RND = LensMetric(
    key="rnd",
    label="R&D",
    short="R&D",
    tags=("ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
    definition="R&D is research and development expense as reported on the income statement.",
)

MEGACAPS = (
    LensCompanySpec("AAPL", "Apple", "0000320193"),
    LensCompanySpec("MSFT", "Microsoft", "0000789019"),
    LensCompanySpec("GOOGL", "Alphabet", "0001652044"),
    LensCompanySpec("AMZN", "Amazon", "0001018724"),
    LensCompanySpec("META", "Meta Platforms", "0001326801"),
    LensCompanySpec("NVDA", "Nvidia", "0001045810"),
    LensCompanySpec("TSLA", "Tesla", "0001318605"),
)

LENSES: dict[str, LensSpec] = {
    "megacap-capex": LensSpec(
        id="megacap-capex",
        title="Megacap tech capex",
        description=(
            "How much of their revenue the seven largest US tech companies "
            "put into capital spending, and how that spending is spread "
            "across the group."
        ),
        metric=CAPEX,
        companies=MEGACAPS,
    ),
    "megacap-sbc": LensSpec(
        id="megacap-sbc",
        title="Megacap stock-based compensation",
        description=(
            "How much of their revenue the seven largest US tech companies "
            "pay their employees in stock, and how that cost is spread "
            "across the group."
        ),
        metric=SBC,
        companies=MEGACAPS,
    ),
    "megacap-rnd": LensSpec(
        id="megacap-rnd",
        title="Megacap R&D intensity",
        description=(
            "How much of their revenue the largest US tech companies spend "
            "on research and development, and how that spending is spread "
            "across the group."
        ),
        metric=RND,
        companies=MEGACAPS,
    ),
}
