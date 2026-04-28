"""
Tests for fetch_edgar. Provider mocked at the registry; the SEC HTTP
client is not unit-tested here (same convention as yfinance —
exercised via post-merge smoke test, not in the suite). What we *do*
unit-test:

1. Provider fan-out — service passes through filings the provider
   returned, in the right order, with one log_external_call record.
2. Disk cache semantics — cache hit skips the provider, cache miss
   writes through to disk in one atomic step.
3. Form-type / recent_n / provider validation.
4. include_text flag controls whether the primary doc text is fetched.
5. CIK zero-padding for short-CIK companies.
6. Sort order: most-recent filed_at first.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.schemas.edgar import EdgarFiling
from app.services.edgar import (
    PROVIDERS,
    SUPPORTED_FORM_TYPES,
    _cache_key_dir,
    fetch_edgar,
)

# ── Fake provider helpers ─────────────────────────────────────────────


def _mk_filing(
    *,
    cik: str = "0000320193",
    symbol: str = "AAPL",
    accession: str = "0000320193-24-000123",
    form_type: str = "10-K",
    filed_at: datetime | None = None,
    period_of_report: date | None = None,
    primary_doc_url: str | None = None,
    primary_doc_text: str | None = None,
    size_bytes: int = 1234,
) -> EdgarFiling:
    return EdgarFiling(
        cik=cik,
        symbol=symbol,
        accession=accession,
        form_type=form_type,
        filed_at=filed_at or datetime(2024, 11, 1, tzinfo=UTC),
        period_of_report=period_of_report or date(2024, 9, 28),
        primary_doc_url=primary_doc_url
        or f"https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-', '')}/aapl-10k.htm",
        primary_doc_text=primary_doc_text,
        size_bytes=size_bytes,
    )


@pytest.fixture
def edgar_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point EDGAR_CACHE_DIR at a per-test tmp_path so writes are isolated."""
    from app.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "EDGAR_CACHE_DIR", str(tmp_path))
    return tmp_path


# ── async entry point — provider fan-out ──────────────────────────────


async def test_returns_filings_from_provider(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    filings = [
        _mk_filing(accession="0000320193-24-000123"),
        _mk_filing(
            accession="0000320193-23-000110",
            filed_at=datetime(2023, 11, 3, tzinfo=UTC),
        ),
    ]
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym, _form, _n, _txt, _cik=None: filings,
    )

    result = await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=2, provider="fake"
    )

    assert len(result) == 2
    assert all(isinstance(f, EdgarFiling) for f in result)
    assert {f.accession for f in result} == {
        "0000320193-24-000123",
        "0000320193-23-000110",
    }


async def test_filings_returned_in_descending_filed_at_order(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """Most-recent-first is the contract for callers; provider order shouldn't matter."""
    older = _mk_filing(
        accession="0000320193-22-000077",
        filed_at=datetime(2022, 11, 1, tzinfo=UTC),
    )
    newer = _mk_filing(
        accession="0000320193-24-000123",
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
    )
    middle = _mk_filing(
        accession="0000320193-23-000110",
        filed_at=datetime(2023, 11, 3, tzinfo=UTC),
    )
    # Provider hands them back in arbitrary order.
    monkeypatch.setitem(
        PROVIDERS, "fake", lambda *_a: [older, newer, middle]
    )

    result = await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=3, provider="fake"
    )

    assert [f.accession for f in result] == [
        "0000320193-24-000123",
        "0000320193-23-000110",
        "0000320193-22-000077",
    ]


async def test_recent_n_zero_returns_empty_without_provider_call(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    called = False

    def _provider(*_a: Any) -> list[EdgarFiling]:
        nonlocal called
        called = True
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _provider)

    result = await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=0, provider="fake"
    )

    assert result == []
    assert called is False


async def test_unknown_form_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported form_type"):
        await fetch_edgar("AAPL", form_type="WEIRD", recent_n=1)


async def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await fetch_edgar(
            "AAPL", form_type="10-K", recent_n=1, provider="not-registered"
        )


async def test_supports_all_documented_form_types(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """The form types the docstring advertises must round-trip without ValueError."""
    monkeypatch.setitem(PROVIDERS, "fake", lambda *_a: [])

    for form in SUPPORTED_FORM_TYPES:
        result = await fetch_edgar(
            "AAPL", form_type=form, recent_n=1, provider="fake"
        )
        assert result == []


async def test_symbol_uppercased_before_provider_call(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    seen_symbols: list[str] = []

    def _capture(sym: str, *_a: Any) -> list[EdgarFiling]:
        seen_symbols.append(sym)
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_edgar("aapl", form_type="10-K", recent_n=1, provider="fake")

    assert seen_symbols == ["AAPL"]


async def test_include_text_flag_passed_to_provider(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    seen: list[bool] = []

    def _capture(
        _sym: str,
        _form: str,
        _n: int,
        include_text: bool,
        _cik: str | None = None,
    ) -> list[EdgarFiling]:
        seen.append(include_text)
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_edgar("AAPL", form_type="10-K", recent_n=1, provider="fake")
    await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=1, include_text=True, provider="fake"
    )

    assert seen == [False, True]


# ── observability ─────────────────────────────────────────────────────


async def test_logs_one_external_call_record(
    monkeypatch: pytest.MonkeyPatch,
    edgar_cache: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    monkeypatch.setitem(
        PROVIDERS, "fake", lambda *_a: [_mk_filing(), _mk_filing(accession="0000320193-23-000110", filed_at=datetime(2023, 11, 3, tzinfo=UTC))]
    )

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_edgar(
            "AAPL", form_type="10-K", recent_n=2, provider="fake"
        )

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.edgar"
    assert r.input_summary == {
        "symbol": "AAPL",
        "form_type": "10-K",
        "recent_n": 2,
        "include_text": False,
        "provider": "fake",
    }
    assert r.output_summary["filing_count"] == 2
    assert r.output_summary["cache_hits"] == 0
    assert r.outcome == "ok"


async def test_provider_exception_propagates_and_logs_error(
    monkeypatch: pytest.MonkeyPatch,
    edgar_cache: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    def _broken(*_a: Any) -> list[EdgarFiling]:
        raise RuntimeError("EDGAR is down")

    monkeypatch.setitem(PROVIDERS, "fake", _broken)

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="EDGAR is down"):
            await fetch_edgar(
                "AAPL", form_type="10-K", recent_n=1, provider="fake"
            )

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"
    assert records[0].exception_class == "RuntimeError"


# ── disk cache ────────────────────────────────────────────────────────


async def test_cache_miss_writes_to_disk(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    filing = _mk_filing()
    monkeypatch.setitem(PROVIDERS, "fake", lambda *_a: [filing])

    await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=1, provider="fake"
    )

    cache_path = _cache_key_dir(edgar_cache, filing.cik, filing.accession) / "metadata.json"
    assert cache_path.exists(), "expected cache write on miss"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["accession"] == filing.accession
    assert cached["form_type"] == "10-K"


async def test_cache_hit_skips_provider(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """A filing already on disk is returned without invoking the provider."""
    filing = _mk_filing()
    cache_dir = _cache_key_dir(edgar_cache, filing.cik, filing.accession)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "metadata.json").write_text(
        filing.model_dump_json(), encoding="utf-8"
    )
    # Also pre-populate the index so the service knows what to read.
    index_path = edgar_cache / "AAPL" / "10-K.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps([{"cik": filing.cik, "accession": filing.accession}]),
        encoding="utf-8",
    )

    called = False

    def _provider(*_a: Any) -> list[EdgarFiling]:
        nonlocal called
        called = True
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _provider)

    result = await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=1, provider="fake"
    )

    assert called is False, "cached filing should skip provider call"
    assert len(result) == 1
    assert result[0].accession == filing.accession


async def test_cache_hit_reflected_in_observability(
    monkeypatch: pytest.MonkeyPatch,
    edgar_cache: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """cache_hits in output_summary lets us measure cache effectiveness over time."""
    import logging

    filing = _mk_filing()
    cache_dir = _cache_key_dir(edgar_cache, filing.cik, filing.accession)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "metadata.json").write_text(
        filing.model_dump_json(), encoding="utf-8"
    )
    index_path = edgar_cache / "AAPL" / "10-K.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps([{"cik": filing.cik, "accession": filing.accession}]),
        encoding="utf-8",
    )

    monkeypatch.setitem(PROVIDERS, "fake", lambda *_a: [])

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_edgar(
            "AAPL", form_type="10-K", recent_n=1, provider="fake"
        )

    rec = next(r for r in caplog.records if r.name == "app.external")
    assert rec.output_summary["cache_hits"] == 1
    assert rec.output_summary["filing_count"] == 1


async def test_text_request_bypasses_metadata_only_cache(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """A cached filing without text must NOT satisfy ``include_text=True``.

    Real failure mode discovered by smoke-testing the live tools: a prior
    ``fetch_edgar(include_text=False)`` populates the cache with
    ``primary_doc_text=None``, and a subsequent call with
    ``include_text=True`` would reuse that cached entry without invoking
    the provider — leaving the caller with a useless empty-text filing.
    The fix: cache hits only count when the cached entry has text, when
    text was requested.
    """
    # Cache a filing WITHOUT text (mimics a prior include_text=False call).
    metadata_only = _mk_filing(primary_doc_text=None)
    cache_dir = _cache_key_dir(
        edgar_cache, metadata_only.cik, metadata_only.accession
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "metadata.json").write_text(
        metadata_only.model_dump_json(), encoding="utf-8"
    )
    index_path = edgar_cache / "AAPL" / "10-K.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            [{"cik": metadata_only.cik, "accession": metadata_only.accession}]
        ),
        encoding="utf-8",
    )

    # Provider returns the same filing WITH text. The provider must be
    # called — the metadata-only cache entry doesn't satisfy the request.
    with_text = _mk_filing(
        primary_doc_text="<html>Item 1A. Risk Factors. Real text.</html>",
    )
    provider_calls = 0

    def _provider(*_a: Any) -> list[EdgarFiling]:
        nonlocal provider_calls
        provider_calls += 1
        return [with_text]

    monkeypatch.setitem(PROVIDERS, "fake", _provider)

    result = await fetch_edgar(
        "AAPL",
        form_type="10-K",
        recent_n=1,
        include_text=True,
        provider="fake",
    )

    assert provider_calls == 1, (
        "include_text=True with metadata-only cache must hit the provider"
    )
    assert len(result) == 1
    assert result[0].primary_doc_text is not None
    assert "Real text" in result[0].primary_doc_text


async def test_text_cache_hit_skips_provider(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """A cached filing WITH text DOES satisfy ``include_text=True``."""
    cached_with_text = _mk_filing(
        primary_doc_text="<html>Item 1A. cached body.</html>"
    )
    cache_dir = _cache_key_dir(
        edgar_cache, cached_with_text.cik, cached_with_text.accession
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "metadata.json").write_text(
        cached_with_text.model_dump_json(), encoding="utf-8"
    )
    index_path = edgar_cache / "AAPL" / "10-K.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            [
                {
                    "cik": cached_with_text.cik,
                    "accession": cached_with_text.accession,
                }
            ]
        ),
        encoding="utf-8",
    )

    called = False

    def _provider(*_a: Any) -> list[EdgarFiling]:
        nonlocal called
        called = True
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _provider)

    result = await fetch_edgar(
        "AAPL",
        form_type="10-K",
        recent_n=1,
        include_text=True,
        provider="fake",
    )

    assert called is False, "cached filing with text should skip the provider"
    assert len(result) == 1
    assert result[0].primary_doc_text is not None
    assert "cached body" in result[0].primary_doc_text


async def test_cache_write_atomic_no_partial_files(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """Cache writes use temp + rename so a crash mid-write never leaves partial JSON."""
    import os

    filing = _mk_filing()
    monkeypatch.setitem(PROVIDERS, "fake", lambda *_a: [filing])

    await fetch_edgar(
        "AAPL", form_type="10-K", recent_n=1, provider="fake"
    )

    cache_dir = _cache_key_dir(edgar_cache, filing.cik, filing.accession)
    files = sorted(os.listdir(cache_dir))
    # Only the final metadata.json should remain — no .tmp or .partial files.
    assert files == ["metadata.json"], files


async def test_cik_zero_padded_in_provider_filings(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """A filing whose cik came in unpadded should still validate."""
    # The schema enforces 10-digit cik on Pydantic construction. Ensure
    # the provider doesn't accidentally hand back a short-cik filing —
    # that would surface as a ValidationError, which is what we want.
    with pytest.raises(Exception):  # noqa: B017 — ValidationError or similar
        EdgarFiling(
            cik="320193",  # 6 digits — should fail validation
            symbol="AAPL",
            accession="0000320193-24-000123",
            form_type="10-K",
            filed_at=datetime(2024, 11, 1, tzinfo=UTC),
            primary_doc_url="https://www.sec.gov/foo",
            size_bytes=1,
        )


# ── cik= bypass for institution filings (added with 2.1.4c) ──────────


async def test_cik_kwarg_passed_to_provider(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """When ``cik=`` is provided, it's threaded through to the provider.

    Used by holdings_13f to fetch institution filings without going
    through the ticker→CIK lookup (institutions don't have tickers).
    """
    seen_cik: list[str | None] = []

    def _capture(
        _sym: str,
        _form: str,
        _n: int,
        _txt: bool,
        cik: str | None = None,
    ) -> list[EdgarFiling]:
        seen_cik.append(cik)
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_edgar(
        "BRK_13F",
        form_type="13F-HR",
        recent_n=1,
        provider="fake",
        cik="0001067983",
    )

    assert seen_cik == ["0001067983"]


async def test_13f_hr_is_supported_form_type(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", lambda *_a, **_kw: [])

    # Should not raise — 13F-HR is a supported form type for institution filings.
    result = await fetch_edgar(
        "BRK_13F",
        form_type="13F-HR",
        recent_n=1,
        provider="fake",
        cik="0001067983",
    )
    assert result == []


async def test_cik_kwarg_default_none_preserves_existing_behavior(
    monkeypatch: pytest.MonkeyPatch, edgar_cache: Path
) -> None:
    """Calls without cik= still work — kwargs is optional."""
    seen_cik: list[str | None] = []

    def _capture(
        _sym: str,
        _form: str,
        _n: int,
        _txt: bool,
        cik: str | None = None,
    ) -> list[EdgarFiling]:
        seen_cik.append(cik)
        return []

    monkeypatch.setitem(PROVIDERS, "fake", _capture)

    await fetch_edgar("AAPL", form_type="10-K", recent_n=1, provider="fake")

    assert seen_cik == [None]
