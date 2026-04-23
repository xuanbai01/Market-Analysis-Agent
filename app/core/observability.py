"""
Observability helpers. Keep this module small and dependency-free — every
service touches it.

`log_external_call` is the one non-negotiable pattern from docs/security.md
A09: every LLM, market-data, news, webhook, or third-party HTTP call must
be logged with service id, input summary, output summary, latency ms, and
timestamp. Using this helper consistently is what keeps the system
debuggable once real providers are in the mix.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any

logger = logging.getLogger("app.external")


@dataclass
class ExternalCall:
    """Mutable handle a caller uses to attach an output summary."""

    service_id: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any] = field(default_factory=dict)

    def record_output(self, summary: dict[str, Any]) -> None:
        self.output_summary = summary


@contextmanager
def log_external_call(
    service_id: str,
    input_summary: dict[str, Any] | None = None,
):
    """
    Context manager that logs exactly one external service call.

    The context yields an `ExternalCall` handle the caller can use to
    attach an `output_summary` before the block exits. Whether the block
    succeeds or raises, one log record is emitted with:

      - service_id            — short stable id, e.g. ``yfinance.history``
      - input_summary         — shape of the request, not the full payload
      - output_summary        — shape of the response (row count, etc.)
      - latency_ms            — wall time in milliseconds (2-decimal rounded)
      - timestamp             — ISO 8601 UTC string, emitted even though
                                stdlib logging has its own timestamp, so
                                log aggregators don't have to parse the
                                logger-added asctime.
      - outcome               — ``"ok"`` or ``"error"``
      - exception_class       — only on failure

    Never put full raw payloads (PII, tokens, full prompts, full article
    bodies) into the summaries — size and privacy both bite.

    Example
    -------
    >>> with log_external_call("yfinance.history", {"symbol": "NVDA", "period": "1y"}) as call:
    ...     bars = fetch_bars(...)
    ...     call.record_output({"bar_count": len(bars)})
    """
    call = ExternalCall(service_id=service_id, input_summary=input_summary or {})
    started_at = monotonic()
    try:
        yield call
    except Exception as exc:
        latency_ms = round((monotonic() - started_at) * 1000, 2)
        logger.exception(
            "external_call",
            extra={
                "service_id": service_id,
                "input_summary": call.input_summary,
                "output_summary": call.output_summary,
                "latency_ms": latency_ms,
                "timestamp": datetime.now(UTC).isoformat(),
                "outcome": "error",
                "exception_class": exc.__class__.__name__,
            },
        )
        raise
    latency_ms = round((monotonic() - started_at) * 1000, 2)
    logger.info(
        "external_call",
        extra={
            "service_id": service_id,
            "input_summary": call.input_summary,
            "output_summary": call.output_summary,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(UTC).isoformat(),
            "outcome": "ok",
        },
    )
