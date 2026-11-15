"""The cited read of an options report (ADR 0008, PR5): what the model
is given, what is kept of what it writes, and the cache."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.options import OptionsRead, OptionsReadDraft, OptionsReport
from app.schemas.research import Claim, Source, ThesisDraftPoint
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
        await asyncio.sleep(0)  # a real call yields: concurrent visits interleave here
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> _Llm:
    fake = _Llm()
    monkeypatch.setattr(reader.llm, "synth_call", fake.synth_call)
    reader.clear_cache()
    return fake


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


async def test_a_point_quoting_a_figure_it_does_not_cite_is_dropped(fake_llm: _Llm) -> None:
    """Every number on the card has its chip: 55.00% is IV90 (O2), not cited here."""
    fake_llm.draft = _draft(ABOVE, ("IV30 is 59.46% and IV90 is 55.00%.", ["O1"]))
    read = await reader.write_read(_report(), NOW)
    assert read is not None and len(read.points) == 1


@pytest.mark.parametrize(
    "text",
    [
        "IV30 is 59.46%, below realized volatility by 2.46 points.",  # the claim says above
        "IV90 is 55.00%, 4.46 points under IV30: the term structure slopes up.",  # it slopes down
    ],
)
async def test_a_point_that_turns_its_claims_direction_round_is_dropped(fake_llm: _Llm, text: str) -> None:
    ids = ["O1", "O5"] if "realized" in text else ["O2", "O6"]
    fake_llm.draft = _draft(ABOVE, (text, ids))
    read = await reader.write_read(_report(), NOW)
    assert read is not None and len(read.points) == 1


async def test_a_point_may_name_both_directions(fake_llm: _Llm) -> None:
    both = ("IV30 is 59.46%, above realized volatility by 2.46 points, not below it.", ["O1", "O5"])
    fake_llm.draft = _draft(ABOVE, both)
    read = await reader.write_read(_report(), NOW)
    assert read is not None and len(read.points) == 2


async def test_a_headline_with_a_made_up_number_spoils_the_read(fake_llm: _Llm) -> None:
    fake_llm.draft = _draft(ABOVE, TERM, headline="Options price a 70% move.")
    assert await reader.write_read(_report(), NOW) is None


async def test_nothing_usable_or_a_model_failure_gives_no_read(fake_llm: _Llm) -> None:
    fake_llm.draft = _draft(("IV30 is high.", []))  # cites nothing
    assert await reader.write_read(_report(), NOW) is None
    fake_llm.draft = RuntimeError("provider down")
    assert await reader.write_read(_report(), NOW) is None


async def test_one_read_per_set_of_quotes(fake_llm: _Llm) -> None:
    first = await reader.get_read(_report(), now=NOW)
    again = await reader.get_read(_report(), now=NOW)
    later = await reader.get_read(_report(quoted_at=datetime(2026, 11, 16, 10, 45, tzinfo=mc.ET)), now=NOW)
    assert again is first and later is not first
    assert len(fake_llm.prompts) == 2


async def test_no_options_means_nothing_to_read(fake_llm: _Llm) -> None:
    with pytest.raises(reader.NothingToRead):
        await reader.get_read(_report("BRK-A", status="no_options"), now=NOW)
    assert fake_llm.prompts == []


async def test_a_failed_read_is_not_cached(fake_llm: _Llm) -> None:
    fake_llm.draft = RuntimeError("provider down")
    with pytest.raises(reader.ReadUnavailable):
        await reader.get_read(_report(), now=NOW)
    fake_llm.draft = GOOD
    assert (await reader.get_read(_report(), now=NOW)).headline
    assert len(fake_llm.prompts) == 2


async def test_has_read_is_about_these_quotes(fake_llm: _Llm) -> None:
    assert not reader.has_read(_report())
    await reader.get_read(_report(), now=NOW)
    assert reader.has_read(_report())
    assert not reader.has_read(_report(quoted_at=datetime(2026, 11, 16, 10, 45, tzinfo=mc.ET)))
    assert not reader.has_read(_report("SPY"))


def test_a_read_round_trips_as_json() -> None:
    read = OptionsRead(symbol="NVDA", quoted_at=CLOSE, at_close=True, headline="x", points=[], claims=[], generated_at=NOW)
    assert OptionsRead.model_validate_json(read.model_dump_json()) == read


async def test_a_point_can_quote_the_reason_a_move_is_not_priced(fake_llm: _Llm) -> None:
    """The refusal is a claim whose value is text; the number in it ("98
    days") is the claim's own, not a stray figure."""
    refusal = Claim(
        description="Implied earnings move, report on 2027-02-09: not priced",
        value="the first expiry after the report is 98 days out",
        unit="string",
        source=Source(tool="computed.options", fetched_at=NOW),
    )
    report = _report()
    report = report.model_copy(update={"claims": [*report.claims, refusal]})
    ref = f"O{len(report.claims)}"
    fake_llm.draft = _draft(ABOVE, ("No earnings move is priced: the first expiry after the report is 98 days out.", [ref]))
    read = await reader.write_read(report, NOW)
    assert read is not None and len(read.points) == 2


async def test_concurrent_visits_share_one_model_call_and_leave_no_lock(fake_llm: _Llm) -> None:
    import asyncio

    reads = await asyncio.gather(*(reader.get_read(_report(), now=NOW) for _ in range(3)))
    assert len(fake_llm.prompts) == 1 and all(r is reads[0] for r in reads)
    assert reader._locks == {} and reader._waiting == {}


async def test_after_a_failure_waiting_visits_try_one_at_a_time(fake_llm: _Llm, monkeypatch: pytest.MonkeyPatch) -> None:
    """Security review (#114): the holder used to drop the lock while
    others waited, so a new visit could call the model alongside them."""
    import asyncio

    fake_llm.draft = RuntimeError("provider down")
    running = [0]
    most = [0]
    real = fake_llm.synth_call

    async def counted(**kwargs: Any) -> Any:
        running[0] += 1
        most[0] = max(most[0], running[0])
        await asyncio.sleep(0)
        try:
            return await real(**kwargs)
        finally:
            running[0] -= 1

    monkeypatch.setattr(reader.llm, "synth_call", counted)
    results = await asyncio.gather(*(reader.get_read(_report(), now=NOW) for _ in range(3)), return_exceptions=True)
    assert all(isinstance(r, reader.ReadUnavailable) for r in results)
    assert most[0] == 1
    assert reader._locks == {} and reader._waiting == {}
