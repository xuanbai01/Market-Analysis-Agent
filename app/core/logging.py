"""
Logging setup: the app's own loggers (``app.*``) print INFO and above to
stderr, which is what ``fly logs`` shows.

Until 2026-11-14 nothing called this (the module set up the root logger
and was never imported), so ``log_external_call``'s INFO records, each
tool's and LLM call's latency (docs/security.md A09), were dropped. Only
errors got out, through Python's last-resort handler and without their
fields, and a RIVN build that took minutes on Fly left no trace of where
the time went.

Only ``app.*`` is raised to INFO. Every other logger stays at the root's
WARNING: httpx logs each request URL at INFO, and FRED's carries the API
key. The URL also reaches the log inside an error: httpx puts it in an
``HTTPStatusError``'s message, which a failed external call's traceback
prints, so a key in a query string is masked on every line this prints.

``app`` keeps propagating, so pytest's ``caplog`` (a root handler) sees
its records. Under uvicorn the root has no handler, so nothing prints
twice; ``tests/test_observability.py`` checks that in a fresh process.
"""
import logging
import re
import sys
from typing import TextIO

_APP_LOGGER = "app"
_HANDLER_NAME = "app-stream"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# What log_external_call attaches to its records (app/core/observability.py).
_EXTERNAL_CALL_FIELDS = (
    "service_id",
    "outcome",
    "latency_ms",
    "exception_class",
    "input_summary",
    "output_summary",
)
# A key passed in a query string: FRED's ``api_key``, NewsAPI's ``apiKey``.
_KEY_IN_QUERY = re.compile(r"\b(api_?key|access_token|token)=[^&\s'\"]+", re.IGNORECASE)
# A bearer token quoted in an error: h11 puts an illegal header's value,
# "Bearer <token>", in its message (tastytrade_client, ADR 0009).
_BEARER = re.compile(r"\b(Bearer)\s+[^\s'\"]+", re.IGNORECASE)


class _AppFormatter(logging.Formatter):
    """The usual line, then an external call's fields as ``name=value``
    (a traceback, if any, follows), with keys in URLs and bearer tokens masked."""

    def format(self, record: logging.LogRecord) -> str:
        text = _KEY_IN_QUERY.sub(r"\1=[REDACTED]", super().format(record))
        return _BEARER.sub(r"\1 [REDACTED]", text)

    def formatMessage(self, record: logging.LogRecord) -> str:
        fields = [
            f"{name}={getattr(record, name)}"
            for name in _EXTERNAL_CALL_FIELDS
            if hasattr(record, name)
        ]
        return " ".join([super().formatMessage(record), *fields])


def configure_logging(stream: TextIO | None = None) -> None:
    """Send ``app.*`` records at INFO and above to ``stream`` (stderr by
    default). Calling it again replaces the handler instead of adding one."""
    logger = logging.getLogger(_APP_LOGGER)
    for handler in [h for h in logger.handlers if h.get_name() == _HANDLER_NAME]:
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(_AppFormatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
