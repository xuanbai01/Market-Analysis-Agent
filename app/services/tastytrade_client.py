"""
The owner's tastytrade account, read only (ADR 0009).

A personal OAuth app's refresh token, which never expires, buys access
tokens that last 15 minutes. Every refresh asks for the ``read`` scope
alone, and an access token that comes back able to trade is refused: this
code never places, changes or cancels an order, and a token that can't
is one less thing to leak. Apart from the sign-in, every call is a GET on
a path ``_ALLOWED`` matches; order paths are not on it.

tastytrade's Open API terms (§8) limit its data to the owner's trading,
forbid showing it to any third party (an LLM provider is one) and forbid
collecting it across the market. So callers cache what they read briefly,
in memory, and never store it or put it in a prompt.

Retries: a 401 signs in again once; a 429, a 5xx or a network error backs
off exponentially with jitter, three tries in all. A refused sign-in
stops every call for an hour, since repeated failed logins get the
server's IP blocked for about 8 hours. Logs carry the path (account
numbers masked) and the status, never a header, token or secret.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.observability import log_external_call
from app.core.settings import settings

SCOPE = "read"
TOKEN_PATH = "/oauth/token"
# tastytrade rejects a request without a User-Agent of the form product/version.
USER_AGENT = "market-analysis-agent/1.0"
TIMEOUT_SECONDS = 15.0
MAX_TRIES = 3
BACKOFF_SECONDS = 1.0
# An access token is used until this long before it expires.
TOKEN_MARGIN_SECONDS = 60
DEFAULT_TOKEN_SECONDS = 900
SIGN_IN_PAUSE_SECONDS = 3600
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_SIGN_IN_REFUSED = frozenset({400, 401, 403})
_TRADE_SCOPE = "trade"

# A symbol in tastytrade's form (BRK/B), URL-encoded, as ``symbol_path`` makes it.
_SYMBOL = r"[A-Z0-9]+(?:%2F[A-Z0-9]+)?"
_ACCOUNT = r"[A-Z0-9]+"
# Every path this client may read. Orders live under other paths.
_ALLOWED = re.compile(
    rf"/option-chains/{_SYMBOL}/nested"
    r"|/market-data/by-type"
    r"|/market-metrics"
    rf"|/market-metrics/historic-corporate-events/(?:earnings-reports|dividends)/{_SYMBOL}"
    r"|/api-quote-tokens"
    r"|/customers/me/accounts"
    rf"|/accounts/{_ACCOUNT}/(?:transactions|positions|balance-snapshots)"
)
_ACCOUNT_IN_PATH = re.compile(rf"(/accounts/){_ACCOUNT}")


class TastytradeUnavailable(Exception):
    """Not configured, the sign-in was refused, or tastytrade didn't answer."""


class TastytradeNotFound(Exception):
    """tastytrade has nothing at that path (an unknown symbol, say)."""


# Swapped in tests.
_clock = time.monotonic
_sleep = asyncio.sleep
_transport: httpx.AsyncBaseTransport | None = None

_token: str | None = None
_expires_at = 0.0
_paused_until = 0.0
_lock: asyncio.Lock | None = None


def reset() -> None:
    """Forget the access token and any pause (tests; a new grant)."""
    global _token, _expires_at, _paused_until, _lock
    _token, _expires_at, _paused_until, _lock = None, 0.0, 0.0, None


def is_configured() -> bool:
    return bool(settings.TASTYTRADE_CLIENT_SECRET and settings.TASTYTRADE_REFRESH_TOKEN)


def is_allowed(path: str) -> bool:
    return _ALLOWED.fullmatch(path) is not None


def symbol_path(symbol: str) -> str:
    """Our ticker as a path segment in tastytrade's symbology: a share
    class takes a slash (BRK-B and BF.B become BRK/B and BF/B), encoded."""
    return quote(symbol.upper().replace("-", "/").replace(".", "/"), safe="")


def _masked(path: str) -> str:
    return _ACCOUNT_IN_PATH.sub(r"\1***", path)


def _summary(params: dict[str, Any] | None) -> dict[str, Any]:
    """Each parameter, with a comma-separated list shown as its length."""
    return {
        key: f"{value.count(',') + 1} values" if isinstance(value, str) and "," in value else value
        for key, value in (params or {}).items()
    }


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.TASTYTRADE_API_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        transport=_transport,
    )


def _refuse_sign_in(reason: str) -> TastytradeUnavailable:
    global _paused_until
    _paused_until = _clock() + SIGN_IN_PAUSE_SECONDS
    return TastytradeUnavailable(reason)


async def _access_token(client: httpx.AsyncClient) -> str:
    """The cached access token, or a new one from the refresh token. One
    sign-in at a time: concurrent callers wait for it."""
    global _token, _expires_at
    async with _get_lock():
        if _paused_until > _clock():
            raise TastytradeUnavailable("tastytrade refused the sign-in within the last hour")
        if _token is not None and _expires_at > _clock():
            return _token
        body = {
            "grant_type": "refresh_token",
            "refresh_token": settings.TASTYTRADE_REFRESH_TOKEN,
            "client_secret": settings.TASTYTRADE_CLIENT_SECRET,
            "scope": SCOPE,
        }
        if settings.TASTYTRADE_CLIENT_ID:
            body["client_id"] = settings.TASTYTRADE_CLIENT_ID
        with log_external_call("tastytrade.sign_in", {"scope": SCOPE}) as call:
            response = await client.post(TOKEN_PATH, json=body)
            call.record_output({"status": response.status_code})
        if response.status_code in _SIGN_IN_REFUSED:
            raise _refuse_sign_in(f"tastytrade refused the sign-in ({response.status_code})")
        if response.status_code >= 400:
            raise TastytradeUnavailable(f"tastytrade's sign-in answered {response.status_code}")
        payload = response.json()
        if _TRADE_SCOPE in str(payload.get("scope") or "").split():
            raise _refuse_sign_in("tastytrade granted a token that can trade; make a grant with the read scope only")
        lifetime = float(payload.get("expires_in") or DEFAULT_TOKEN_SECONDS)
        _token = str(payload["access_token"])
        _expires_at = _clock() + lifetime - TOKEN_MARGIN_SECONDS
        return _token


def _forget(token: str) -> None:
    global _token
    if _token == token:
        _token = None


async def _get_once(
    client: httpx.AsyncClient, path: str, params: dict[str, Any] | None, token: str, op: str
) -> httpx.Response:
    with log_external_call(f"tastytrade.{op}", {"path": _masked(path), **_summary(params)}) as call:
        response = await client.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        call.record_output({"status": response.status_code, "bytes": len(response.content)})
    return response


def _backoff(attempt: int) -> float:
    """Seconds before try ``attempt + 1``: doubling, with up to as much again of jitter."""
    return BACKOFF_SECONDS * 2 ** (attempt - 1) * (1 + random.random())


async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
    """The JSON tastytrade answers for GET ``path``. ``op`` names the call
    in the logs (``tastytrade.<op>``). Raises ``ValueError`` for a path off
    the allowlist, ``TastytradeNotFound`` for a 404, and
    ``TastytradeUnavailable`` for everything else that isn't an answer."""
    if not is_configured():
        raise TastytradeUnavailable("tastytrade is not configured")
    if not is_allowed(path):
        raise ValueError(f"tastytrade path not allowed: {_masked(path)}")
    async with _client() as client:
        signed_in_again = False
        attempt = 0
        while True:
            response: httpx.Response | None
            try:
                token = await _access_token(client)
                response = await _get_once(client, path, params, token, op)
            except httpx.TransportError:  # timeouts included
                response = None
            if response is not None and response.status_code == 401 and not signed_in_again:
                _forget(token)
                signed_in_again = True
                continue
            if response is not None and response.status_code not in _RETRY_STATUSES:
                break
            attempt += 1
            if attempt >= MAX_TRIES:
                status = "no answer" if response is None else str(response.status_code)
                raise TastytradeUnavailable(f"tastytrade failed {MAX_TRIES} times ({status})")
            await _sleep(_backoff(attempt))
    if response.status_code == 404:
        raise TastytradeNotFound(_masked(path))
    if response.status_code >= 400:
        raise TastytradeUnavailable(f"tastytrade answered {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise TastytradeUnavailable("tastytrade answered something that isn't JSON") from None
