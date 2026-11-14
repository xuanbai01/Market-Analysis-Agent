"""
Cross-company lens (app/services/lens.py + /v1/lens). SEC and the LLM are
replaced by fakes; the numbers are small enough to check by hand.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import settings as settings_module
from app.main import app
from app.schemas.lens import LensDraft, LensReport
from app.schemas.research import ThesisDraftPoint
from app.services import lens

SPEC = lens.LensSpec(
    id="test-lens",
    title="Test capex",
    description="Three companies.",
    metric=lens.CAPEX,
    companies=(
        lens.LensCompanySpec("AAA", "Alpha", "1"),
        lens.LensCompanySpec("BBB", "Beta", "2"),
        lens.LensCompanySpec("CCC", "Gamma", "3"),
    ),
)

# AAA heavy spender, BBB light, CCC only reports from 2024 (like NVDA).
RAW = {
    "AAA": {"value": {2023: 20.0, 2024: 30.0, 2025: 40.0}, "revenue": {2023: 100.0, 2024: 120.0, 2025: 160.0},
            "ocf": {2023: 40.0, 2024: 50.0, 2025: 50.0}},
    "BBB": {"value": {2023: 2.0, 2024: 2.0, 2025: 3.0}, "revenue": {2023: 100.0, 2024: 100.0, 2025: 100.0},
            "ocf": {2023: 30.0, 2024: 30.0, 2025: -5.0}},
    "CCC": {"value": {2024: 5.0, 2025: 10.0}, "revenue": {2024: 50.0, 2025: 100.0}, "ocf": {2025: 20.0}},
}


def built() -> tuple[list[int], list[Any], list[Any]]:
    years = lens.window(RAW, size=3)
    companies = [
        lens.LensCompany(ticker=c.ticker, name=c.name, points=lens.company_points(RAW[c.ticker], years))
        for c in SPEC.companies
    ]
    return years, companies, lens.year_stats(companies, years)


def test_window_ends_at_the_latest_year_everyone_reported() -> None:
    partial = {**RAW, "BBB": {**RAW["BBB"], "value": {2023: 2.0, 2024: 2.0}}}
    assert lens.window(RAW, size=3) == [2023, 2024, 2025]
    assert lens.window(partial, size=2) == [2023, 2024]
    assert lens.window({"X": {"value": {}, "revenue": {}, "ocf": {}}}) == []


def test_points_compute_intensity_and_the_share_of_operating_cash_flow() -> None:
    _, companies, _ = built()
    aaa = companies[0].points[-1]
    assert aaa.value == pytest.approx(40.0)
    assert aaa.intensity == pytest.approx(0.25)
    assert aaa.to_ocf == pytest.approx(0.8)
    # Negative operating cash flow: the ratio means nothing, so it's left out.
    assert companies[1].points[-1].to_ocf is None
    # A year a company didn't report stays empty.
    assert companies[2].points[0].intensity is None


def test_percentile_interpolates() -> None:
    assert lens.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert lens.percentile([10], 0.75) == 10


def test_year_stats_cover_only_the_companies_reporting() -> None:
    _, _, stats = built()
    first, last = stats[0], stats[-1]
    assert first.companies == 2 and last.companies == 3
    assert last.median == pytest.approx(0.10)  # [0.03, 0.10, 0.25]
    assert (last.high_ticker, last.low_ticker) == ("AAA", "BBB")
    assert last.total == pytest.approx(53.0)


def test_facts_describe_the_distribution_growth_and_positions() -> None:
    _, companies, stats = built()
    facts = {f.description: f for f in lens.lens_facts(lens.CAPEX, companies, stats)}
    assert facts["Median capex intensity (capex ÷ revenue), CY2025, 3 companies"].value == pytest.approx(0.10)
    assert facts["Highest capex intensity, CY2025: AAA"].value == pytest.approx(0.25)
    # Growth only over companies reporting both ends (CCC joined later).
    growth = facts["Total capex growth, CY2023 → CY2025 (multiple; AAA, BBB)"]
    assert growth.value == pytest.approx(43 / 22)
    assert facts["AAA capex ÷ operating cash flow, CY2025"].value == pytest.approx(0.8)
    assert "BBB capex ÷ operating cash flow, CY2025" not in facts
    assert facts["CCC capex intensity change, CY2024 → CY2025"].value == pytest.approx(0.0)
    # Fewer than five spenders: no top-four concentration fact.
    assert not any(d.startswith("Share of CY2025 capex") for d in facts)
    sources = {f.source.tool for f in facts.values()}
    assert sources == {"computed.analytics", "sec.xbrl"}


def test_facts_name_the_lens_metric() -> None:
    """The same computation reads as SBC (or R&D) when the lens is about
    SBC: the descriptions are what the narrative quotes and cites."""
    _, companies, stats = built()
    facts = {f.description for f in lens.lens_facts(lens.SBC, companies, stats)}
    assert "Median SBC intensity (SBC ÷ revenue), CY2025, 3 companies" in facts
    assert "AAA SBC ÷ operating cash flow, CY2025" in facts
    assert "Total SBC, 3 companies, CY2025" in facts
    assert not any("capex" in d for d in facts)


def test_a_company_with_no_figure_for_the_metric_is_left_out_of_the_window() -> None:
    """Amazon tags no R&D expense: it must not empty the R&D lens's window
    (the latest year *every* company reported)."""
    no_rnd = {**RAW, "DDD": {"value": {}, "revenue": {2025: 500.0}, "ocf": {2025: 50.0}}}
    assert lens.window(no_rnd, size=3) == [2023, 2024, 2025]
    assert lens.without_figures(no_rnd) == ["DDD"]


async def test_a_lens_names_the_companies_it_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = lens.LensSpec(
        id="test-rnd",
        title="Test R&D",
        description="Four companies.",
        metric=lens.RND,
        companies=(*SPEC.companies, lens.LensCompanySpec("DDD", "Delta", "4")),
    )
    raw = {**RAW, "DDD": {"value": {}, "revenue": {2025: 500.0}, "ocf": {2025: 50.0}}}

    async def no_narrative(*_a: Any) -> None:
        return None

    monkeypatch.setattr(lens, "fetch_raw", lambda _spec: raw)
    monkeypatch.setattr(lens, "write_narrative", no_narrative)
    report = await lens.build_lens(spec)

    assert [c.ticker for c in report.companies] == ["AAA", "BBB", "CCC"]
    assert report.excluded == ["DDD"]
    assert "DDD" in report.method
    assert report.metric.label == "R&D"
    assert report.stats[-1].companies == 3


def test_the_megacap_lenses_share_one_group() -> None:
    megacaps = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]
    assert set(lens.LENSES) == {"megacap-capex", "megacap-sbc", "megacap-rnd"}
    for spec in lens.LENSES.values():
        assert [c.ticker for c in spec.companies] == megacaps
    assert lens.LENSES["megacap-sbc"].metric is lens.SBC
    assert lens.LENSES["megacap-rnd"].metric is lens.RND


async def test_the_narrative_prompt_says_what_the_metric_is(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    async def capture(**kw: Any) -> LensDraft:
        prompts.append(kw["prompt"])
        return LensDraft(headline="", points=[])

    monkeypatch.setattr(lens.llm, "synth_call", capture)
    _, companies, stats = built()
    spec = lens.LensSpec(id="x", title="X", description="", metric=lens.SBC, companies=SPEC.companies)
    await lens.write_narrative(spec, lens.lens_facts(lens.SBC, companies, stats))
    assert lens.SBC.definition in prompts[0]


async def test_narrative_keeps_points_citing_facts_they_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    _, companies, stats = built()
    facts = lens.lens_facts(lens.CAPEX, companies, stats)

    async def fake(**_kw: Any) -> LensDraft:
        return LensDraft(
            headline="Spending is uneven.",
            points=[
                # L6 = highest intensity (quoted); L1 = the median (not quoted, dropped).
                ThesisDraftPoint(text="AAA spends 25.00% of revenue.", claim_ids=["L6", "L1"]),
                ThesisDraftPoint(text="Cites nothing real.", claim_ids=["L999"]),
            ],
        )

    monkeypatch.setattr(lens.llm, "synth_call", fake)
    narrative = await lens.write_narrative(SPEC, facts)
    assert narrative is not None
    assert [p.text for p in narrative.points] == ["AAA spends 25.00% of revenue."]
    cited = [facts[r.index].description for r in narrative.points[0].claim_refs]
    assert cited == ["Highest capex intensity, CY2025: AAA"]


async def test_narrative_failure_leaves_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_kw: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(lens.llm, "synth_call", boom)
    _, companies, stats = built()
    assert await lens.write_narrative(SPEC, lens.lens_facts(lens.CAPEX, companies, stats)) is None


@pytest.fixture
def fake_sources(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake_fetch(spec: lens.LensSpec) -> dict[str, Any]:
        calls.append(spec.id)
        return RAW

    async def no_narrative(*_a: Any) -> None:
        return None

    lens.clear_cache()
    monkeypatch.setitem(lens.LENSES, SPEC.id, SPEC)
    monkeypatch.setattr(lens, "fetch_raw", fake_fetch)
    monkeypatch.setattr(lens, "write_narrative", no_narrative)
    yield calls
    lens.clear_cache()


async def test_get_lens_builds_once_then_serves_the_cache(fake_sources: list[str]) -> None:
    first = await lens.get_lens(SPEC.id)
    second = await lens.get_lens(SPEC.id)
    assert isinstance(first, LensReport) and first is second
    assert fake_sources == [SPEC.id]
    assert first.tickers == ["AAA", "BBB", "CCC"]


async def test_get_lens_serves_the_stale_copy_when_a_rebuild_fails(
    fake_sources: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await lens.get_lens(SPEC.id)

    def broken(_spec: Any) -> Any:
        raise RuntimeError("SEC down")

    monkeypatch.setattr(lens, "fetch_raw", broken)
    monkeypatch.setattr(lens, "CACHE_TTL_SECONDS", -1)
    lens._cache[SPEC.id].expires_at = 0
    assert await lens.get_lens(SPEC.id) is first


async def test_unknown_lens_is_none() -> None:
    assert await lens.get_lens("no-such-lens") is None


@pytest_asyncio.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_route_lists_and_returns_lenses(api: AsyncClient, fake_sources: list[str]) -> None:
    index = (await api.get("/v1/lens")).json()
    assert {"id": "megacap-capex"}.items() <= next(i for i in index if i["id"] == "megacap-capex").items()
    resp = await api.get(f"/v1/lens/{SPEC.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["years"]) == lens.WINDOW_YEARS and body["years"][-1] == 2025
    assert body["stats"][-1]["high_ticker"] == "AAA"


async def test_route_404s_an_unknown_lens(api: AsyncClient) -> None:
    resp = await api.get("/v1/lens/no-such-lens")
    assert resp.status_code == 404


async def test_route_503s_when_the_data_is_unavailable(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(_lens_id: str) -> Any:
        raise RuntimeError("SEC down")

    monkeypatch.setattr("app.api.v1.routers.lens.get_lens", down)
    resp = await api.get("/v1/lens/megacap-capex")
    assert resp.status_code == 503
