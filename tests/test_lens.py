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
    companies=(
        lens.LensCompanySpec("AAA", "Alpha", "1"),
        lens.LensCompanySpec("BBB", "Beta", "2"),
        lens.LensCompanySpec("CCC", "Gamma", "3"),
    ),
)

# AAA heavy spender, BBB light, CCC only reports from 2024 (like NVDA).
RAW = {
    "AAA": {"capex": {2023: 20.0, 2024: 30.0, 2025: 40.0}, "revenue": {2023: 100.0, 2024: 120.0, 2025: 160.0},
            "ocf": {2023: 40.0, 2024: 50.0, 2025: 50.0}},
    "BBB": {"capex": {2023: 2.0, 2024: 2.0, 2025: 3.0}, "revenue": {2023: 100.0, 2024: 100.0, 2025: 100.0},
            "ocf": {2023: 30.0, 2024: 30.0, 2025: -5.0}},
    "CCC": {"capex": {2024: 5.0, 2025: 10.0}, "revenue": {2024: 50.0, 2025: 100.0}, "ocf": {2025: 20.0}},
}


def built() -> tuple[list[int], list[Any], list[Any]]:
    years = lens.window(RAW, size=3)
    companies = [
        lens.LensCompany(ticker=c.ticker, name=c.name, points=lens.company_points(RAW[c.ticker], years))
        for c in SPEC.companies
    ]
    return years, companies, lens.year_stats(companies, years)


def test_window_ends_at_the_latest_year_everyone_reported() -> None:
    partial = {**RAW, "BBB": {**RAW["BBB"], "capex": {2023: 2.0, 2024: 2.0}}}
    assert lens.window(RAW, size=3) == [2023, 2024, 2025]
    assert lens.window(partial, size=2) == [2023, 2024]
    assert lens.window({"X": {"capex": {}, "revenue": {}, "ocf": {}}}) == []


def test_points_compute_intensity_and_capex_to_ocf() -> None:
    _, companies, _ = built()
    aaa = companies[0].points[-1]
    assert aaa.capex_intensity == pytest.approx(0.25)
    assert aaa.capex_to_ocf == pytest.approx(0.8)
    # Negative operating cash flow: the ratio means nothing, so it's left out.
    assert companies[1].points[-1].capex_to_ocf is None
    # A year a company didn't report stays empty.
    assert companies[2].points[0].capex_intensity is None


def test_percentile_interpolates() -> None:
    assert lens.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert lens.percentile([10], 0.75) == 10


def test_year_stats_cover_only_the_companies_reporting() -> None:
    _, _, stats = built()
    first, last = stats[0], stats[-1]
    assert first.companies == 2 and last.companies == 3
    assert last.median == pytest.approx(0.10)  # [0.03, 0.10, 0.25]
    assert (last.high_ticker, last.low_ticker) == ("AAA", "BBB")
    assert last.total_capex == pytest.approx(53.0)


def test_facts_describe_the_distribution_growth_and_positions() -> None:
    _, companies, stats = built()
    facts = {f.description: f for f in lens.lens_facts(companies, stats)}
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


async def test_narrative_keeps_points_citing_facts_they_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    _, companies, stats = built()
    facts = lens.lens_facts(companies, stats)

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
    assert await lens.write_narrative(SPEC, lens.lens_facts(companies, stats)) is None


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
