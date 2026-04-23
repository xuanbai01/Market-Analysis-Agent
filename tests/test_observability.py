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
