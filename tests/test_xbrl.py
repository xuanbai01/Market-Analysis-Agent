"""SEC XBRL annual series (app/services/xbrl.py). SEC is never called."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core import settings as settings_module
from app.services import xbrl


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
