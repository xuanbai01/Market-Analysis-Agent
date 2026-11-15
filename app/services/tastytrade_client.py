"""
The owner's tastytrade account, read only (ADR 0009).

A personal OAuth app's refresh token, which never expires, buys access
tokens that last 15 minutes. Every refresh asks for the ``read`` scope,
and the access token is used only if what it may do (the answer's
``scope``, else the token's own claim) is known and holds nothing beyond
``read`` and ``openid``: this code never places, changes or cancels an
order. Apart from the sign-in, every call is a GET on a path ``_ALLOWED``
matches; order paths are not on it. ``grant_scopes`` asks what the stored
grant itself may do, for the probe: a grant that can trade should be
replaced by a read-only one, because the refresh token is the credential
that could leak.

tastytrade's Open API terms (§8) limit its data to the owner's trading,
forbid showing it to any third party (an LLM provider is one) and forbid
collecting it across the market. So callers cache what they read briefly,
in memory, and never store it or put it in a prompt.

Sign-in failures are remembered, so neither waiting callers nor later
ones try again at once: repeated failed logins get the server's IP
blocked for about 8 hours. A refusal (a 4xx other than 429) pauses every
call for an hour; a throttled, failed or garbled sign-in for a minute (or
the server's Retry-After). A data call that gets a 401 signs in again
once, unless its token is less than a minute old (then the path is
refused, not the token); a 429, a 5xx or a network error backs off with
jitter, three tries in all. Logs carry the path (account numbers masked)
and the status, never a header, token or secret.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import math
import random
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.observability import log_external_call
from app.core.settings import settings

logger = logging.getLogger(__name__)

SCOPE = "read"
TOKEN_PATH = "/oauth/token"
API_URLS = frozenset({"https://api.tastyworks.com", "https://api.cert.tastyworks.com"})
# tastytrade rejects a request without a User-Agent of the form product/version.
USER_AGENT = "market-analysis-agent/1.0"
TIMEOUT_SECONDS = 15.0
MAX_TRIES = 3
BACKOFF_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 30.0
# An access token is used until this long before it expires (at most half its life).
TOKEN_MARGIN_SECONDS = 60
DEFAULT_TOKEN_SECONDS = 900
# A 401 on a token younger than this is about the path, not the token.
FRESH_TOKEN_SECONDS = 60
SIGN_IN_PAUSE_SECONDS = 3600  # refused: a revoked or wrong grant
SIGN_IN_RETRY_SECONDS = 60  # throttled, down, or a garbled answer
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_READ_ONLY_SCOPES = frozenset({"read", "openid"})
# What a bearer token may hold: anything else could break a header and
# end up quoted in a transport error's message.
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9._~+/=-]+")

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
_ACCOUNT_IN_PATH = re.compile(r"(/accounts/)[^/?#]+")


class TastytradeUnavailable(Exception):
    """Not configured, the sign-in was refused, or tastytrade didn't answer."""


class TastytradeNotFound(Exception):
    """tastytrade has nothing at that path (an unknown symbol, say)."""


# Swapped in tests.
_clock = time.monotonic
_sleep = asyncio.sleep
_transport: httpx.AsyncBaseTransport | None = None

_token: str | None = None
_issued_at = 0.0
_expires_at = 0.0
_paused_until = 0.0
_pause_reason = ""
_pause_noted = False
_lock: asyncio.Lock | None = None


def reset() -> None:
    """Forget the access token and any pause (tests; a new grant)."""
    global _token, _issued_at, _expires_at, _paused_until, _pause_reason, _pause_noted, _lock
    _token, _issued_at, _expires_at, _lock = None, 0.0, 0.0, None
    _paused_until, _pause_reason, _pause_noted = 0.0, "", False


def is_configured() -> bool:
    return bool(settings.TASTYTRADE_CLIENT_SECRET.get_secret_value() and settings.TASTYTRADE_REFRESH_TOKEN.get_secret_value())


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
    if settings.TASTYTRADE_API_URL not in API_URLS:
        raise TastytradeUnavailable("TASTYTRADE_API_URL is not one of tastytrade's addresses")
    return httpx.AsyncClient(
        base_url=settings.TASTYTRADE_API_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        transport=_transport,
    )


def _pause(seconds: float, reason: str) -> TastytradeUnavailable:
    """Stop signing in for ``seconds``; the error to raise."""
    global _paused_until, _pause_reason, _pause_noted
    _paused_until, _pause_reason, _pause_noted = _clock() + seconds, reason, False
    logger.warning("tastytrade sign-in paused for %d s: %s", seconds, reason)
    return TastytradeUnavailable(reason)


def _check_pause() -> None:
    global _pause_noted
    if _paused_until > _clock():
        if not _pause_noted:
            _pause_noted = True
            logger.warning("tastytrade calls refused while the sign-in is paused: %s", _pause_reason)
        raise TastytradeUnavailable(_pause_reason)


def _retry_after(response: httpx.Response, default: float, cap: float) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return default
    return min(max(seconds, 0.0), cap) if math.isfinite(seconds) else default


def _scopes(value: Any) -> set[str]:
    """Scopes as a set, from a space- or comma-separated string or a list."""
    if isinstance(value, str):
        return {part.lower() for part in re.split(r"[\s,]+", value) if part}
    if isinstance(value, list | tuple):
        return {str(part).lower() for part in value}
    return set()


def _claimed_scopes(token: str) -> set[str]:
    """The ``scope`` (or ``scp``) claim of a JWT, read without verifying it:
    only to learn what tastytrade says the token may do."""
    parts = token.split(".")
    if len(parts) != 3:
        return set()
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, binascii.Error):
        return set()
    if not isinstance(claims, dict):
        return set()
    return _scopes(claims.get("scope", claims.get("scp")))


async def _sign_in(client: httpx.AsyncClient, scope: str | None) -> tuple[str, float, set[str]]:
    """(access token, lifetime in seconds, what it may do). Every failure
    pauses the sign-in before it raises. Call with the lock held."""
    body = {
        "grant_type": "refresh_token",
        "refresh_token": settings.TASTYTRADE_REFRESH_TOKEN.get_secret_value(),
        "client_secret": settings.TASTYTRADE_CLIENT_SECRET.get_secret_value(),
    }
    if scope is not None:
        body["scope"] = scope
    if settings.TASTYTRADE_CLIENT_ID:
        body["client_id"] = settings.TASTYTRADE_CLIENT_ID
    try:
        with log_external_call("tastytrade.sign_in", {"scope": scope or "the grant's"}) as call:
            response = await client.post(TOKEN_PATH, json=body)
            call.record_output({"status": response.status_code})
    except httpx.TransportError:
        raise _pause(SIGN_IN_RETRY_SECONDS, "tastytrade's sign-in didn't answer") from None
    status = response.status_code
    if status in _RETRY_STATUSES:
        wait = _retry_after(response, SIGN_IN_RETRY_SECONDS, SIGN_IN_PAUSE_SECONDS)
        raise _pause(wait, f"tastytrade's sign-in answered {status}")
    if 400 <= status < 500:
        raise _pause(SIGN_IN_PAUSE_SECONDS, f"tastytrade refused the sign-in ({status})")
    if status != 200:
        raise _pause(SIGN_IN_RETRY_SECONDS, f"tastytrade's sign-in answered {status}")
    try:
        payload = response.json()
        token = payload["access_token"]
        lifetime = float(payload.get("expires_in") or DEFAULT_TOKEN_SECONDS)
        granted = payload.get("scope")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise _pause(SIGN_IN_RETRY_SECONDS, "tastytrade's sign-in answer was garbled") from None
    if not isinstance(token, str) or not _TOKEN_CHARS.fullmatch(token) or not (math.isfinite(lifetime) and lifetime > 0):
        raise _pause(SIGN_IN_RETRY_SECONDS, "tastytrade's sign-in answer was garbled")
    return token, lifetime, _scopes(granted) | _claimed_scopes(token)


async def _access_token(client: httpx.AsyncClient) -> str:
    """The cached access token, or a new one from the refresh token. One
    sign-in at a time: concurrent callers wait for it, and see its failure."""
    global _token, _issued_at, _expires_at
    async with _get_lock():
        _check_pause()
        if _token is not None and _expires_at > _clock():
            return _token
        token, lifetime, scopes = await _sign_in(client, SCOPE)
        if not scopes:
            raise _pause(SIGN_IN_PAUSE_SECONDS, "tastytrade didn't say what the token may do; refusing it")
        if not scopes <= _READ_ONLY_SCOPES:
            raise _pause(SIGN_IN_PAUSE_SECONDS, "tastytrade granted a token that can trade; make a grant with the read scope only")
        _token, _issued_at = token, _clock()
        _expires_at = _issued_at + lifetime - min(TOKEN_MARGIN_SECONDS, lifetime / 2)
        return token


async def grant_scopes() -> frozenset[str]:
    """What the stored grant itself may do: one sign-in that doesn't ask
    for a narrower scope. Its token is dropped unused. For the probe only."""
    if not is_configured():
        raise TastytradeUnavailable("tastytrade is not configured")
    async with _client() as client, _get_lock():
        _check_pause()
        _, _, scopes = await _sign_in(client, None)
    return frozenset(scopes)


def _stale(token: str) -> bool:
    """After a 401: whether to sign in again. Not when the token is the
    current one and less than a minute old; then the path is refused."""
    global _token
    if token != _token:
        return True  # another call has signed in since
    if _clock() - _issued_at < FRESH_TOKEN_SECONDS:
        return False
    _token = None
    return True


async def _get_once(
    client: httpx.AsyncClient, path: str, params: dict[str, Any] | None, token: str, op: str
) -> httpx.Response:
    with log_external_call(f"tastytrade.{op}", {"path": _masked(path), "params": _summary(params)}) as call:
        response = await client.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        call.record_output({"status": response.status_code, "bytes": len(response.content)})
    return response


def _backoff(attempt: int, response: httpx.Response | None) -> float:
    """Seconds before try ``attempt + 1``: the server's Retry-After (capped),
    else doubling with up to as much again of jitter."""
    jittered = BACKOFF_SECONDS * 2 ** (attempt - 1) * (1 + random.random())
    return jittered if response is None else _retry_after(response, jittered, MAX_RETRY_AFTER_SECONDS)


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
            token = await _access_token(client)  # raises; a sign-in is never retried here
            response: httpx.Response | None
            try:
                response = await _get_once(client, path, params, token, op)
            except httpx.TransportError:  # timeouts included
                response = None
            if response is not None and response.status_code == 401 and not signed_in_again:
                signed_in_again = True
                if _stale(token):
                    continue
            if response is not None and response.status_code not in _RETRY_STATUSES:
                break
            attempt += 1
            if attempt >= MAX_TRIES:
                status = "no answer" if response is None else str(response.status_code)
                raise TastytradeUnavailable(f"tastytrade failed {MAX_TRIES} times ({status})")
            await _sleep(_backoff(attempt, response))
    if response.status_code == 404:
        raise TastytradeNotFound(_masked(path))
    if response.status_code >= 400:
        raise TastytradeUnavailable(f"tastytrade answered {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise TastytradeUnavailable("tastytrade answered something that isn't JSON") from None
