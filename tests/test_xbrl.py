"""SEC XBRL annual series (app/services/xbrl.py). SEC is never called."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core import settings as settings_module
from app.services import sec_registrants, xbrl


def fact(frame: str | None, val: float) -> dict[str, Any]:
    out: dict[str, Any] = {"val": val, "form": "10-K"}
    if frame:
        out["frame"] = frame
    return out


def payload(*facts: dict[str, Any]) -> dict[str, Any]:
    return {"units": {"USD": list(facts)}}


def test_annual_values_keep_only_calendar_year_frames() -> None:
    values = xbrl.annual_values(
        payload(fact("CY2024", 10.0), fact("CY2024Q3", 3.0), fact(None, 99.0), fact("CY2025", 12.0))
    )
    assert values == {2024: 10.0, 2025: 12.0}


def test_annual_values_handle_an_empty_payload() -> None:
    assert xbrl.annual_values({}) == {}


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings_module.settings, "EDGAR_CACHE_DIR", str(tmp_path))
    return tmp_path


class FakeSec:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> httpx.Response:
        self.calls.append(url)
        tag = url.rsplit("/", 1)[-1].removesuffix(".json")
        request = httpx.Request("GET", url)
        if tag not in self.responses:
            return httpx.Response(404, request=request).raise_for_status()  # type: ignore[return-value]
        status, body = self.responses[tag]
        response = httpx.Response(status, json=body, request=request)
        response.raise_for_status()
        return response


def test_series_merge_tags_year_by_year_preferring_the_first(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Amazon: the old capex tag until 2016, the new one after."""
    fake = FakeSec({
        "OldTag": (200, payload(fact("CY2015", 4.6), fact("CY2016", 6.7))),
        "NewTag": (200, payload(fact("CY2016", 7.0), fact("CY2017", 12.0))),
    })
    monkeypatch.setattr(xbrl.edgar, "_sec_get", fake)
    assert xbrl.annual_series("0001018724", ["OldTag", "NewTag"]) == {2015: 4.6, 2016: 6.7, 2017: 12.0}


def test_concepts_are_cached_on_disk_including_misses(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSec({"Capex": (200, payload(fact("CY2025", 1.0)))})
    monkeypatch.setattr(xbrl.edgar, "_sec_get", fake)
    assert xbrl.fetch_concept("0000320193", "Capex") == payload(fact("CY2025", 1.0))
    assert xbrl.fetch_concept("0000320193", "NeverFiled") == {}
    xbrl.fetch_concept("0000320193", "Capex")
    xbrl.fetch_concept("0000320193", "NeverFiled")
    assert len(fake.calls) == 2  # second round served from disk
    assert (cache_dir / "xbrl" / "0000320193" / "Capex.json").exists()


def test_an_expired_cache_entry_is_refetched(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSec({"Capex": (200, payload(fact("CY2025", 1.0)))})
    monkeypatch.setattr(xbrl.edgar, "_sec_get", fake)
    xbrl.fetch_concept("0000320193", "Capex")
    monkeypatch.setattr(xbrl, "CACHE_TTL_SECONDS", -1)
    xbrl.fetch_concept("0000320193", "Capex")
    assert len(fake.calls) == 2


def test_server_errors_raise_instead_of_caching_an_empty_series(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSec({"Capex": (503, {})}))
    with pytest.raises(httpx.HTTPStatusError):
        xbrl.fetch_concept("0000320193", "Capex")
    assert not (cache_dir / "xbrl" / "0000320193" / "Capex.json").exists()


# ── Facts with their filing date (2026-11, per-share history) ────────


def test_annual_facts_read_any_unit_and_keep_the_filing_date() -> None:
    """Share counts come in "shares" and EPS in "USD/shares"; the filing
    date says which stock splits a number already reflects."""
    body = {
        "units": {
            "shares": [
                {"val": 625_000_000, "frame": "CY2018", "filed": "2021-02-26"},
                {"val": 24_514_000_000, "frame": "CY2025", "filed": "2026-02-25"},
                {"val": 6_000_000_000, "frame": "CY2025Q3", "filed": "2025-11-19"},
            ]
        }
    }
    assert xbrl.annual_facts(body, "shares") == {
        2018: (625_000_000.0, "2021-02-26"),
        2025: (24_514_000_000.0, "2026-02-25"),
    }
    assert xbrl.annual_facts(body, "USD") == {}


def test_annual_series_with_filed_merges_tags_like_annual_series(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSec({
        "OldTag": (200, {"units": {"USD": [{"val": 1.0, "frame": "CY2015", "filed": "2016-02-01"}]}}),
        "NewTag": (200, {"units": {"USD": [
            {"val": 9.0, "frame": "CY2015", "filed": "2017-02-01"},
            {"val": 2.0, "frame": "CY2016", "filed": "2017-02-01"},
        ]}}),
    })
    monkeypatch.setattr(xbrl.edgar, "_sec_get", fake)
    assert xbrl.annual_series_with_filed("0000000001", ["OldTag", "NewTag"]) == {
        2015: (1.0, "2016-02-01"),
        2016: (2.0, "2017-02-01"),
    }


# ── Successor registrants (2026-11, dogfood #18) ─────────────────────


class FakeSecByCik:
    """Like ``FakeSec`` but keyed by (cik, tag): two registrants, one tag."""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses

    def __call__(self, url: str) -> httpx.Response:
        parts = url.split("/")
        cik, tag = parts[-3].removeprefix("CIK"), parts[-1].removesuffix(".json")
        request = httpx.Request("GET", url)
        if (cik, tag) not in self.responses:
            return httpx.Response(404, request=request).raise_for_status()  # type: ignore[return-value]
        return httpx.Response(200, json=self.responses[(cik, tag)], request=request)


def test_a_successor_registrants_series_continue_into_its_predecessors(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exxon, 2026: the ticker moved to a new holding company whose own
    filings hold no ten-year history. Years it has filed win; the
    registrant before it fills the rest."""
    new, old = "0000000002", "0000000001"
    monkeypatch.setattr(sec_registrants, "PREDECESSOR_CIKS", {new: (old,)})
    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSecByCik({
        (new, "Revenues"): payload(fact("CY2025", 21.0), fact("CY2026", 30.0)),
        (old, "Revenues"): payload(fact("CY2024", 10.0), fact("CY2025", 20.0)),
    }))
    assert xbrl.annual_series(new, ["Revenues"]) == {2024: 10.0, 2025: 21.0, 2026: 30.0}
    # Asked for directly, the old registrant is just itself.
    assert xbrl.annual_series(old, ["Revenues"]) == {2024: 10.0, 2025: 20.0}


def test_a_successor_with_no_annual_facts_yet_reads_entirely_from_its_predecessor(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    new, old = "0000000002", "0000000001"
    monkeypatch.setattr(sec_registrants, "PREDECESSOR_CIKS", {new: (old,)})
    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSecByCik({
        (old, "Shares"): {"units": {"shares": [
            {"val": 4_000.0, "frame": "CY2024", "filed": "2025-02-19"},
            {"val": 3_900.0, "frame": "CY2025", "filed": "2026-02-18"},
        ]}},
    }))
    assert xbrl.annual_series_with_filed(new, ["Shares"], "shares") == {
        2024: (4_000.0, "2025-02-19"),
        2025: (3_900.0, "2026-02-18"),
    }


def test_share_counts_fall_back_to_basic_in_years_with_no_diluted_count(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exxon has no dilutive securities and stopped tagging a diluted
    count after 2013; every later year carries only the basic one. A
    year that has a diluted count keeps it."""

    def shares(*points: tuple[str, float]) -> dict[str, Any]:
        return {"units": {"shares": [{"val": v, "frame": f, "filed": "2026-02-18"} for f, v in points]}}

    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSecByCik({
        ("0000034088", "WeightedAverageNumberOfDilutedSharesOutstanding"): shares(("CY2013", 4_419.0)),
        ("0000034088", "WeightedAverageNumberOfSharesOutstandingBasic"): shares(
            ("CY2013", 4_400.0), ("CY2024", 4_298.0), ("CY2025", 4_305.0)
        ),
    }))
    series = xbrl.annual_series_with_filed("0000034088", xbrl.DILUTED_SHARES_TAGS, "shares")
    assert {year: value for year, (value, _filed) in series.items()} == {
        2013: 4_419.0,
        2024: 4_298.0,
        2025: 4_305.0,
    }


# ── Period ends (2026-11, valuation history) ─────────────────────────


def test_period_ends_come_from_the_annual_frames(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fiscal year is priced on its own last day: Apple's ends in late
    September, so the calendar frame alone does not say when."""
    body = {"units": {"USD": [
        {"val": 1.0, "frame": "CY2024", "end": "2024-09-28", "filed": "2024-11-01"},
        {"val": 2.0, "frame": "CY2025", "end": "2025-09-27", "filed": "2025-10-31"},
        {"val": 0.5, "frame": "CY2025Q3", "end": "2025-06-28", "filed": "2025-08-01"},
        {"val": 3.0, "end": "2023-09-30", "filed": "2023-11-03"},  # no frame: superseded
    ]}}
    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSecByCik({("0000320193", "Revenues"): body}))

    assert xbrl.annual_period_ends("0000320193", ["Revenues"]) == {2024: "2024-09-28", 2025: "2025-09-27"}


def test_period_ends_follow_a_successor_registrant_too(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new, old = "0000000002", "0000000001"
    monkeypatch.setattr(sec_registrants, "PREDECESSOR_CIKS", {new: (old,)})
    monkeypatch.setattr(xbrl.edgar, "_sec_get", FakeSecByCik({
        (old, "Revenues"): {"units": {"USD": [{"val": 1.0, "frame": "CY2025", "end": "2025-12-31", "filed": "2026-02-18"}]}},
    }))

    assert xbrl.annual_period_ends(new, ["Revenues"]) == {2025: "2025-12-31"}
