"""The cited read of an options report (ADR 0008, PR5): what the model
is given, what is kept of what it writes, and the cache."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.options import OptionsRead, OptionsReadDraft, OptionsReport
from app.schemas.research import ThesisDraftPoint
from app.services import market_calendar as mc
from app.services import options_analysis as oa
from app.services import options_read as reader

NOW = datetime(2026, 11, 14, 17, tzinfo=UTC)
CLOSE = datetime(2026, 11, 13, 16, tzinfo=mc.ET)


def _report(symbol: str = "NVDA", *, status: str = "ok", quoted_at: datetime = CLOSE) -> OptionsReport:
    history = oa.iv_history([], 0.5946)
    claims = oa.claims(
        iv30=0.5946, iv90=0.55, rv20=0.57, rv60=0.52, skew25=0.0269, default=None, put_call_oi=0.86,
        earnings=None, history=history, at=NOW,
    )
    return OptionsReport(
        symbol=symbol, status=status, spot=162.85, quoted_at=quoted_at,  # type: ignore[arg-type]
        at_close=mc.is_close(quoted_at), rate=0.0372, rate_assumed=False, iv30=0.5946, iv30_extrapolated=False,
        iv90=0.55, skew25=0.0269, rv20=0.57, rv60=0.52, put_call_open_interest=0.86, put_call_volume=0.7,
        expiries=[], listed_expiries=[], chain=None, earnings=None, history=history,
        claims=claims if status == "ok" else [], generated_at=NOW,
    )


def _draft(*points: tuple[str, list[str]], headline: str = "Options price a little more movement than the stock has shown.") -> OptionsReadDraft:
    return OptionsReadDraft(
        headline=headline,
        points=[ThesisDraftPoint(title="A point", text=text, claim_ids=ids) for text, ids in points],
    )


ABOVE = ("IV30 is 59.46%, above realized volatility by 2.46 points: options price more movement than the stock has shown.", ["O1", "O5"])
TERM = ("IV90 is 55.00%, 4.46 points below IV30: the term structure slopes down.", ["O2", "O6"])
GOOD = _draft(ABOVE, TERM)


class _Llm:
    def __init__(self) -> None:
        self.draft: Any = GOOD
        self.prompts: list[str] = []

    async def synth_call(self, *, prompt: str, schema: Any, system: str | None = None, **_: Any) -> Any:
        self.prompts.append(prompt)
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> _Llm:
    fake = _Llm()
    monkeypatch.setattr(reader.llm, "synth_call", fake.synth_call)
    reader.clear_cache()
    return fake


def _serve(monkeypatch: pytest.MonkeyPatch, *reports: OptionsReport) -> None:
    queue = list(reports)

    async def get_report(_session: Any, _symbol: str, *, now: datetime | None = None) -> OptionsReport:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(reader.options_report, "get_report", get_report)


def test_the_ids_in_the_test_drafts_are_the_ones_meant() -> None:
    ids = {f"O{i + 1}": c.description for i, c in enumerate(_report().claims)}
    assert ids["O1"].startswith("Implied volatility, 30 days")
    assert ids["O2"].startswith("Implied volatility, 90 days")
    assert ids["O5"].startswith("IV30 above realized volatility")
    assert ids["O6"].startswith("IV90 below IV30")


async def test_a_read_cites_the_reports_claims(fake_llm: _Llm) -> None:
    read = await reader.write_read(_report(), NOW)
    assert read is not None
    assert read.symbol == "NVDA" and read.at_close and read.quoted_at == CLOSE
    assert read.claims == _report().claims
    assert [len(p.claim_refs) for p in read.points] == [2, 2]
    assert all(ref.section == reader.READ_SECTION for p in read.points for ref in p.claim_refs)


async def test_the_prompt_is_the_facts_with_ids_and_the_quote_time(fake_llm: _Llm) -> None:
    await reader.write_read(_report(), NOW)
    prompt = fake_llm.prompts[0]
    assert "[O1]" in prompt and "59.46%" in prompt
    assert "close of 2026-11-13" in prompt


def test_the_system_prompt_forbids_advice_and_forecasts() -> None:
    text = reader.READ_SYSTEM_PROMPT.lower()
    for rule in ("no advice", "no forecasts", "risk-neutral", "never compute", "only when a fact states"):
        assert rule in text


async def test_a_point_quoting_a_number_no_fact_shows_is_dropped(fake_llm: _Llm) -> None:
    fake_llm.draft = _draft(ABOVE, ("IV30 is 59.46%, on its way to 70%.", ["O1"]))
    read = await reader.write_read(_report(), NOW)
    assert read is not None and len(read.points) == 1


async def test_a_headline_with_a_made_up_number_spoils_the_read(fake_llm: _Llm) -> None:
    fake_llm.draft = _draft(ABOVE, TERM, headline="Options price a 70% move.")
    assert await reader.write_read(_report(), NOW) is None


async def test_nothing_usable_or_a_model_failure_gives_no_read(fake_llm: _Llm) -> None:
    fake_llm.draft = _draft(("IV30 is high.", []))  # cites nothing
    assert await reader.write_read(_report(), NOW) is None
    fake_llm.draft = RuntimeError("provider down")
    assert await reader.write_read(_report(), NOW) is None


async def test_one_read_per_set_of_quotes(fake_llm: _Llm, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _report(), _report(), _report(quoted_at=datetime(2026, 11, 16, 10, 45, tzinfo=mc.ET)))
    first = await reader.get_read(None, "NVDA", now=NOW)  # type: ignore[arg-type]
    again = await reader.get_read(None, "NVDA", now=NOW)  # type: ignore[arg-type]
    later = await reader.get_read(None, "NVDA", now=NOW)  # type: ignore[arg-type]
    assert again is first and later is not first
    assert len(fake_llm.prompts) == 2


async def test_no_options_means_nothing_to_read(fake_llm: _Llm, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _report("BRK-A", status="no_options"))
    with pytest.raises(reader.NothingToRead):
        await reader.get_read(None, "BRK-A", now=NOW)  # type: ignore[arg-type]
    assert fake_llm.prompts == []


async def test_a_failed_read_is_not_cached(fake_llm: _Llm, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _report())
    fake_llm.draft = RuntimeError("provider down")
    with pytest.raises(reader.ReadUnavailable):
        await reader.get_read(None, "NVDA", now=NOW)  # type: ignore[arg-type]
    fake_llm.draft = GOOD
    assert (await reader.get_read(None, "NVDA", now=NOW)).headline  # type: ignore[arg-type]
    assert len(fake_llm.prompts) == 2


async def test_has_read_follows_the_cached_report(fake_llm: _Llm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader.options_report, "fresh_report", lambda symbol: _report() if symbol == "NVDA" else None)
    assert not reader.has_read("NVDA")
    _serve(monkeypatch, _report())
    await reader.get_read(None, "NVDA", now=NOW)  # type: ignore[arg-type]
    assert reader.has_read("NVDA")
    assert not reader.has_read("SPY")


def test_a_read_round_trips_as_json() -> None:
    read = OptionsRead(symbol="NVDA", quoted_at=CLOSE, at_close=True, headline="x", points=[], claims=[], generated_at=NOW)
    assert OptionsRead.model_validate_json(read.model_dump_json()) == read
