import logging

import pytest

from app.core.observability import log_external_call


def test_success_emits_single_ok_record(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        with log_external_call("test.service", {"symbol": "NVDA"}) as call:
            call.record_output({"bar_count": 3})

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.message == "external_call"
    assert r.service_id == "test.service"
    assert r.input_summary == {"symbol": "NVDA"}
    assert r.output_summary == {"bar_count": 3}
    assert r.outcome == "ok"
    assert isinstance(r.latency_ms, float)
    assert r.latency_ms >= 0
    assert r.timestamp  # ISO 8601 string


def test_exception_emits_error_record_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="app.external"):
        with pytest.raises(RuntimeError, match="boom"):
            with log_external_call("test.service", {"symbol": "NVDA"}):
                raise RuntimeError("boom")

    error_records = [
        r for r in caplog.records if r.name == "app.external" and r.levelno >= logging.ERROR
    ]
    assert len(error_records) == 1
    r = error_records[0]
    assert r.outcome == "error"
    assert r.exception_class == "RuntimeError"
    assert r.service_id == "test.service"
    assert isinstance(r.latency_ms, float)


def test_output_summary_defaults_to_empty_if_not_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        with log_external_call("test.service"):
            pass  # caller never calls record_output

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].input_summary == {}
    assert records[0].output_summary == {}


def test_latency_reflects_block_duration(caplog: pytest.LogCaptureFixture) -> None:
    import time

    with caplog.at_level(logging.INFO, logger="app.external"):
        with log_external_call("test.service"):
            time.sleep(0.02)

    r = [r for r in caplog.records if r.name == "app.external"][0]
    # Give generous slack for sleep granularity on Windows CI.
    assert r.latency_ms >= 10, f"expected >=10ms, got {r.latency_ms}"


# ── Reaching the process log (what `fly logs` shows) ───────────────────


def test_an_external_call_reaches_the_log_with_its_fields() -> None:
    """2026-11-14: nothing set up the app's loggers, so these INFO records
    (each tool's latency) were dropped, and a RIVN build that took minutes
    on Fly left no trace of where the time went."""
    import io

    from app.core.logging import configure_logging

    stream = io.StringIO()
    configure_logging(stream)
    try:
        with log_external_call("sec.ten_k_risks_diff", {"symbol": "RIVN"}) as call:
            call.record_output({"added_count": 117})
    finally:
        configure_logging()

    line = stream.getvalue()
    assert "INFO app.external: external_call service_id=sec.ten_k_risks_diff" in line
    assert "outcome=ok latency_ms=" in line
    assert "input_summary={'symbol': 'RIVN'}" in line
    assert "output_summary={'added_count': 117}" in line


def test_a_failed_external_call_reaches_the_log_with_its_traceback() -> None:
    import io

    from app.core.logging import configure_logging

    stream = io.StringIO()
    configure_logging(stream)
    try:
        with pytest.raises(RuntimeError):
            with log_external_call("deepseek.structured_call"):
                raise RuntimeError("boom")
    finally:
        configure_logging()

    text = stream.getvalue()
    assert "ERROR app.external: external_call service_id=deepseek.structured_call" in text
    assert "outcome=error" in text and "exception_class=RuntimeError" in text
    assert "Traceback" in text and "RuntimeError: boom" in text


def test_configuring_twice_does_not_print_twice() -> None:
    import io

    from app.core.logging import configure_logging

    stream = io.StringIO()
    configure_logging(stream)
    configure_logging(stream)
    try:
        with log_external_call("test.service"):
            pass
    finally:
        configure_logging()

    assert stream.getvalue().count("external_call") == 1


def test_an_api_key_in_a_failed_calls_url_is_not_printed() -> None:
    """NewsAPI and FRED take their keys in the query string, and httpx puts
    the whole URL in an HTTPStatusError's message, which the traceback of a
    failed external call prints."""
    import io

    import httpx

    from app.core.logging import configure_logging

    request = httpx.Request(
        "GET",
        "https://newsapi.org/v2/everything",
        params={"q": "RIVN", "apiKey": "news-secret-1", "api_key": "fred-secret-2"},
    )
    stream = io.StringIO()
    configure_logging(stream)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            with log_external_call("newsapi.everything"):
                httpx.Response(401, request=request).raise_for_status()
    finally:
        configure_logging()

    text = stream.getvalue()
    assert "HTTPStatusError" in text and "newsapi.org/v2/everything?q=RIVN" in text
    assert "news-secret-1" not in text and "fred-secret-2" not in text
    assert "apiKey=[REDACTED]" in text and "api_key=[REDACTED]" in text


_FRESH_APP = """
import logging
import app.main
from app.core.observability import log_external_call
with log_external_call("sec.ten_k_risks_diff", {"symbol": "RIVN"}):
    pass
print(logging.getLogger("httpx").isEnabledFor(logging.INFO))
"""


def test_a_fresh_app_prints_each_external_call_once() -> None:
    """In a new interpreter, as uvicorn loads it. Here conftest has already
    imported app.main and earlier tests leave a handler on ``app``, so only
    a fresh process shows that importing the app sets up the log. Once: a
    root handler from anything the app imports would print it twice. And
    httpx stays below INFO, where it logs request URLs."""
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-c", _FRESH_APP],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
        check=True,
    )

    assert result.stderr.count("external_call service_id=sec.ten_k_risks_diff") == 1
    assert result.stdout.strip() == "False"
