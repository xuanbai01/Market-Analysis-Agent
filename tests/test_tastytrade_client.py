"""The read-only tastytrade client (ADR 0009): sign-in, retries, and what it
refuses to do. tastytrade is replaced by an httpx MockTransport; nothing
here touches the network."""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import re
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core import settings as settings_module
from app.services import dxlink
from app.services import tastytrade_client as tt

CLIENT_ID = "0d5f6a8e-test-client"
CLIENT_SECRET = "cs-test-7f1e2d"
REFRESH_TOKEN = "rt-test-eyJhbGciOi.refresh"
ACCESS_TOKEN = "at-test-eyJhbGciOi.access"
ACCOUNT = "5WT12345"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(tt, "_clock", fake)
    return fake


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(tt, "_sleep", fake_sleep)
    return slept


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings_module.settings
    monkeypatch.setattr(s, "TASTYTRADE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(s, "TASTYTRADE_CLIENT_SECRET", SecretStr(CLIENT_SECRET))
    monkeypatch.setattr(s, "TASTYTRADE_REFRESH_TOKEN", SecretStr(REFRESH_TOKEN))
    monkeypatch.setattr(s, "TASTYTRADE_API_URL", "https://api.tastyworks.com")
    tt.reset()
    yield
    tt.reset()


class FakeTastytrade:
    """Answers the token POST and the GETs, and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_responses: list[httpx.Response] = []
        self.get_responses: list[httpx.Response] = []
        self.token_count = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeTastytrade:
        monkeypatch.setattr(tt, "_transport", httpx.MockTransport(self.handle))
        return self

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/token":
            self.token_count += 1
            if self.token_responses:
                return self.token_responses.pop(0)
            return httpx.Response(200, json={
                "access_token": f"{ACCESS_TOKEN}-{self.token_count}", "expires_in": 900,
                "token_type": "Bearer", "scope": "read",
            })
        if self.get_responses:
            return self.get_responses.pop(0)
        return httpx.Response(200, json={"data": {"items": [{"symbol": "SPY"}]}, "context": request.url.path})

    @property
    def gets(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != "/oauth/token"]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTastytrade:
    return FakeTastytrade().install(monkeypatch)


async def test_not_configured_makes_no_request(monkeypatch: pytest.MonkeyPatch, fake: FakeTastytrade) -> None:
    monkeypatch.setattr(settings_module.settings, "TASTYTRADE_REFRESH_TOKEN", SecretStr(""))
    assert tt.is_configured() is False
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.requests == []


async def test_signs_in_with_the_read_scope_then_gets(fake: FakeTastytrade, clock: FakeClock) -> None:
    payload = await tt.get("/market-metrics", {"symbols": "SPY,QQQ"}, op="market_metrics")

    assert payload["data"]["items"] == [{"symbol": "SPY"}]
    token_request, get_request = fake.requests
    assert token_request.method == "POST"
    assert json.loads(token_request.content) == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_secret": CLIENT_SECRET,
        "client_id": CLIENT_ID,
        "scope": "read",
    }
    assert get_request.method == "GET"
    assert get_request.url.path == "/market-metrics"
    assert get_request.url.params["symbols"] == "SPY,QQQ"
    assert get_request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}-1"
    for request in fake.requests:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", request.headers["User-Agent"])


async def test_client_id_is_left_out_when_not_set(
    monkeypatch: pytest.MonkeyPatch, fake: FakeTastytrade, clock: FakeClock
) -> None:
    monkeypatch.setattr(settings_module.settings, "TASTYTRADE_CLIENT_ID", "")
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert "client_id" not in json.loads(fake.requests[0].content)


async def test_the_access_token_is_reused_until_a_minute_before_it_expires(
    fake: FakeTastytrade, clock: FakeClock
) -> None:
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    clock.now += 900 - 61
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1
    clock.now += 2
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 2
    assert fake.gets[-1].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}-2"


async def test_concurrent_calls_share_one_sign_in(fake: FakeTastytrade, clock: FakeClock) -> None:
    await asyncio.gather(*(tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics") for _ in range(5)))
    assert fake.token_count == 1
    assert len(fake.gets) == 5


async def test_a_401_signs_in_again_once(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    clock.now += tt.FRESH_TOKEN_SECONDS + 1
    fake.get_responses = [httpx.Response(401, json={"error": {"code": "token_invalid"}})]
    payload = await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert payload["data"]["items"]
    assert fake.token_count == 2
    assert fake.gets[-1].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}-2"


async def test_a_second_401_gives_up(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    clock.now += tt.FRESH_TOKEN_SECONDS + 1
    fake.get_responses = [httpx.Response(401), httpx.Response(401)]
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 2


async def test_a_401_on_a_fresh_token_is_the_paths_not_the_tokens(
    fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    fake.get_responses = [httpx.Response(401)]
    with pytest.raises(tt.TastytradeUnavailable, match="401"):
        await tt.get(f"/accounts/{ACCOUNT}/positions", op="positions")
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1  # no churn: the token still serves other paths


async def test_a_refused_sign_in_pauses_every_call_for_an_hour(fake: FakeTastytrade, clock: FakeClock) -> None:
    fake.token_responses = [httpx.Response(401, json={"error": {"code": "invalid_grant"}})]
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    clock.now += tt.SIGN_IN_PAUSE_SECONDS - 1
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1  # no second try while paused: repeated failures block the IP
    clock.now += 2
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 2


def _jwt(claims: dict[str, object]) -> str:
    def part(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    "answer",
    [
        {"scope": "read trade"},
        {"scope": ["read", "trade"]},
        {"scope": "read,trade"},
        {"scope": "READ TRADE"},
        {"access_token": _jwt({"sub": "u1", "scope": "read trade"})},  # no scope field: the claim says trade
        {"access_token": _jwt({"sub": "u1", "scp": ["read", "trade"]})},
        {"scope": "read", "access_token": _jwt({"scope": "read trade"})},  # either saying trade is enough
        {},  # nothing says what it may do
        {"access_token": _jwt({"sub": "u1"})},
    ],
)
async def test_a_token_that_can_trade_or_wont_say_is_refused(
    answer: dict[str, object], fake: FakeTastytrade, clock: FakeClock
) -> None:
    fake.token_responses = [httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 900, **answer})]
    with pytest.raises(tt.TastytradeUnavailable, match="can trade|may read"):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.gets == []
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1  # paused, not signed in again


async def test_a_jwt_that_claims_read_only_is_used(fake: FakeTastytrade, clock: FakeClock) -> None:
    token = _jwt({"sub": "u1", "scope": "read openid"})
    fake.token_responses = [httpx.Response(200, json={"access_token": token, "expires_in": 900})]
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.gets[0].headers["Authorization"] == f"Bearer {token}"


async def test_a_token_that_can_only_read_is_used(fake: FakeTastytrade, clock: FakeClock) -> None:
    fake.token_responses = [
        httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 900, "scope": "read openid"})
    ]
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.gets[0].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_throttling_backs_off_and_retries(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    fake.get_responses = [httpx.Response(429), httpx.Response(503)]
    payload = await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert payload["data"]["items"]
    assert len(fake.gets) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0] > 0


async def test_three_failures_give_up(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    fake.get_responses = [httpx.Response(503)] * 3
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert len(fake.gets) == tt.MAX_TRIES == 3


async def test_a_network_error_is_retried(
    monkeypatch: pytest.MonkeyPatch, fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/oauth/token":
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("connection reset", request=request)
        return fake.handle(request)

    monkeypatch.setattr(tt, "_transport", httpx.MockTransport(flaky))
    payload = await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert payload["data"]["items"]
    assert calls["n"] == 2


async def test_not_found_is_its_own_error(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    fake.get_responses = [httpx.Response(404, json={"error": {"code": "not_found"}})]
    with pytest.raises(tt.TastytradeNotFound):
        await tt.get(f"/option-chains/{tt.symbol_path('ZZZZ')}/nested", op="option_chain")
    assert sleeps == []


async def test_another_client_error_is_not_retried(fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]) -> None:
    fake.get_responses = [httpx.Response(403, json={"error": {"code": "not_permitted"}})]
    with pytest.raises(tt.TastytradeUnavailable, match="403"):
        await tt.get("/market-data/by-type", {"equity": "SPY"}, op="quotes")
    assert len(fake.gets) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/orders",
        f"/accounts/{ACCOUNT}/orders",
        f"/accounts/{ACCOUNT}/orders/dry-run",
        f"/accounts/{ACCOUNT}/complex-orders",
        "/watchlists",
        "/customers/me",
        "/option-chains/SPY/nested/../../orders",
        "https://evil.example/market-metrics",
    ],
)
async def test_a_path_off_the_allowlist_is_refused_before_any_request(path: str, fake: FakeTastytrade) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        await tt.get(path, op="anything")
    assert fake.requests == []


@pytest.mark.parametrize(
    "path",
    [
        "/option-chains/SPY/nested",
        "/option-chains/BRK%2FB/nested",
        "/market-data/by-type",
        "/market-metrics",
        "/market-metrics/historic-corporate-events/earnings-reports/NVDA",
        "/market-metrics/historic-corporate-events/dividends/KO",
        "/api-quote-tokens",
        "/customers/me/accounts",
        f"/accounts/{ACCOUNT}/transactions",
        f"/accounts/{ACCOUNT}/positions",
        f"/accounts/{ACCOUNT}/balance-snapshots",
    ],
)
def test_the_allowlist_holds_every_path_the_plan_reads(path: str) -> None:
    assert tt.is_allowed(path)


def test_symbol_path_matches_tastytrade_symbology() -> None:
    assert tt.symbol_path("SPY") == "SPY"
    assert tt.symbol_path("brk-b") == "BRK%2FB"
    assert tt.symbol_path("BF.B") == "BF%2FB"


async def test_logs_hold_no_secret_token_or_account_number(
    fake: FakeTastytrade, clock: FakeClock, sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    fake.get_responses = [httpx.Response(503)]
    with caplog.at_level(logging.DEBUG):
        await tt.get(f"/accounts/{ACCOUNT}/transactions", {"per-page": 1}, op="transactions")
        clock.now += tt.FRESH_TOKEN_SECONDS + 1
        fake.get_responses = [httpx.Response(401)]
        await tt.get(f"/accounts/{ACCOUNT}/balance-snapshots", op="balances")
        fake.get_responses = [httpx.Response(404)]
        with pytest.raises(tt.TastytradeNotFound):
            await tt.get(f"/accounts/{ACCOUNT}/positions", op="positions")
        with pytest.raises(ValueError):
            await tt.get(f"/accounts/{ACCOUNT}/orders", op="orders")
        fake.token_responses = [httpx.Response(401)]
        tt.reset()
        with pytest.raises(tt.TastytradeUnavailable):
            await tt.get(f"/accounts/{ACCOUNT}/positions", op="positions")
        with pytest.raises(tt.TastytradeUnavailable):
            await tt.get(f"/accounts/{ACCOUNT}/positions", op="positions")

    assert any(getattr(r, "service_id", "").startswith("tastytrade.") for r in caplog.records)
    # Only app.* prints in production (app/core/logging.py); httpx's own
    # request lines stay below the root's WARNING.
    for record in (r for r in caplog.records if r.name.startswith("app")):
        text = record.getMessage() + " " + " ".join(
            str(getattr(record, name, "")) for name in ("input_summary", "output_summary")
        )
        if record.exc_info:
            text += " " + logging.Formatter().formatException(record.exc_info)
        for secret in (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN, ACCOUNT):
            assert secret not in text


def test_the_client_writes_nothing_but_the_token_request() -> None:
    """Placing or changing an order is a write; the only write this code
    can make is the sign-in."""
    source = inspect.getsource(tt)
    assert len(re.findall(r"\.post\(", source)) == 1
    assert re.search(r"\.post\(\s*TOKEN_PATH", source)
    assert not re.search(r"\.(put|patch|delete|request|send|stream)\(", source)
    # DXLink sends only its handshake and subscriptions (tests/test_dxlink.py)
    # and makes no HTTP call of its own.
    dxlink_source = inspect.getsource(dxlink)
    assert "httpx" not in dxlink_source
    assert not re.search(r"\.(post|put|patch|delete|request|stream)\(", dxlink_source)


async def test_every_request_in_a_session_is_a_get_but_the_sign_in(
    fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    await tt.get("/market-metrics", op="any")
    for path in (f"/accounts/{ACCOUNT}/transactions", "/api-quote-tokens"):
        clock.now += tt.FRESH_TOKEN_SECONDS + 1
        fake.get_responses = [httpx.Response(401)]
        await tt.get(path, op="any")
    await tt.grant_scopes()
    methods = {(r.method, r.url.path == "/oauth/token") for r in fake.requests}
    assert methods == {("POST", True), ("GET", False)}


def test_the_scope_asked_for_is_read_only() -> None:
    assert tt.SCOPE == "read"


@pytest.mark.parametrize(
    ("answer", "pause"),
    [
        (httpx.Response(429), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(429, headers={"Retry-After": "120"}), 120),
        (httpx.Response(500), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(503, headers={"Retry-After": "999999"}), tt.SIGN_IN_PAUSE_SECONDS),
        (httpx.Response(302, headers={"Location": "https://evil.example/"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, text="<html>maintenance</html>"), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json=["access_token"]), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json={"expires_in": 900, "scope": "read"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json={"access_token": 12345, "scope": "read"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json={"access_token": "at-bad\nX-Header: 1", "scope": "read"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": "soon", "scope": "read"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": -5, "scope": "read"}), tt.SIGN_IN_RETRY_SECONDS),
        (httpx.Response(422, json={"error": {"code": "invalid_grant"}}), tt.SIGN_IN_PAUSE_SECONDS),
        (httpx.Response(404), tt.SIGN_IN_PAUSE_SECONDS),
    ],
)
async def test_every_failed_sign_in_is_remembered(
    answer: httpx.Response, pause: float, fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    fake.token_responses = [answer]
    results = await asyncio.gather(
        *(tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics") for _ in range(10)), return_exceptions=True
    )
    assert all(isinstance(r, tt.TastytradeUnavailable) for r in results)
    assert fake.token_count == 1  # the waiters saw the failure and didn't sign in
    assert fake.gets == []
    clock.now += pause - 1
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1
    clock.now += 2
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 2


async def test_a_sign_in_that_doesnt_answer_is_tried_once(
    monkeypatch: pytest.MonkeyPatch, fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(tt, "_transport", httpx.MockTransport(down))
    results = await asyncio.gather(
        *(tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics") for _ in range(10)), return_exceptions=True
    )
    assert all(isinstance(r, tt.TastytradeUnavailable) for r in results)
    assert len(fake.requests) == 1
    assert sleeps == []


async def test_a_short_lived_token_is_still_reused(fake: FakeTastytrade, clock: FakeClock) -> None:
    fake.token_responses = [httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 40, "scope": "read"})]
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    clock.now += 19
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 1


async def test_a_throttled_get_waits_as_long_as_the_server_asks_within_a_cap(
    fake: FakeTastytrade, clock: FakeClock, sleeps: list[float]
) -> None:
    fake.get_responses = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429, headers={"Retry-After": "600"}),
    ]
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert sleeps == [7.0, tt.MAX_RETRY_AFTER_SECONDS]


async def test_grant_scopes_asks_for_the_grants_own_scopes_and_keeps_no_token(
    fake: FakeTastytrade, clock: FakeClock
) -> None:
    fake.token_responses = [
        httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 900, "scope": "read trade"})
    ]
    assert await tt.grant_scopes() == frozenset({"read", "trade"})
    assert "scope" not in json.loads(fake.requests[0].content)
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.token_count == 2  # the grant check's token was dropped unused
    assert json.loads(fake.requests[1].content)["scope"] == "read"


async def test_grant_scopes_waits_out_a_pause(fake: FakeTastytrade, clock: FakeClock) -> None:
    fake.token_responses = [httpx.Response(401)]
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    with pytest.raises(tt.TastytradeUnavailable):
        await tt.grant_scopes()
    assert fake.token_count == 1


async def test_an_api_address_off_tastytrades_is_refused(monkeypatch: pytest.MonkeyPatch, fake: FakeTastytrade) -> None:
    monkeypatch.setattr(settings_module.settings, "TASTYTRADE_API_URL", "https://api.tastyworks.com.evil.example")
    with pytest.raises(tt.TastytradeUnavailable, match="TASTYTRADE_API_URL"):
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.requests == []


@pytest.mark.parametrize(
    "url", ["http://api.tastyworks.com", "https://api.tastyworks.com.evil.example", "https://localhost:8080"]
)
def test_settings_accept_only_tastytrades_addresses(url: str) -> None:
    with pytest.raises(ValidationError):
        settings_module.Settings(TASTYTRADE_API_URL=url)


def test_settings_never_print_the_secrets() -> None:
    s = settings_module.Settings(TASTYTRADE_CLIENT_SECRET=CLIENT_SECRET, TASTYTRADE_REFRESH_TOKEN=REFRESH_TOKEN)
    for text in (repr(s), str(s), str(s.model_dump())):
        assert CLIENT_SECRET not in text and REFRESH_TOKEN not in text
    assert s.TASTYTRADE_REFRESH_TOKEN.get_secret_value() == REFRESH_TOKEN


def test_the_whole_account_segment_is_masked() -> None:
    for path in ("/accounts/5WT12345/positions", "/accounts/ab-12.x/positions", "/accounts/5wt12345"):
        masked = tt._masked(path)
        assert masked.startswith("/accounts/***")
        assert "12345" not in masked and "ab-12" not in masked


async def test_a_paused_sign_in_says_so_in_the_logs(
    fake: FakeTastytrade, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    fake.token_responses = [httpx.Response(401)]
    with caplog.at_level(logging.WARNING, logger="app"):
        for _ in range(3):
            with pytest.raises(tt.TastytradeUnavailable):
                await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and r.name.startswith("app")]
    assert any("paused" in w and "refused the sign-in (401)" in w for w in warnings)
    assert sum("refused while the sign-in is paused" in w for w in warnings) == 1  # once per pause



@pytest.mark.parametrize(
    "scope", ["read accounts:5wt12345:owner", "read openid accounts:5wt12345:owner accounts:5wt99999:trade-only"]
)
async def test_account_scopes_beside_read_are_accepted(scope: str, fake: FakeTastytrade, clock: FakeClock) -> None:
    fake.token_responses = [httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 900, "scope": scope})]
    await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.gets[0].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


@pytest.mark.parametrize(
    ("scope", "reason"),
    [
        ("read accounts:5wt12345:owner trade", "can trade"),
        ("accounts:5wt12345:owner", "may read"),
        ("read admin", "doesn't know"),
        ("read accounts:5wt12345", "doesn't know"),
        ("read accounts:../x:owner", "doesn't know"),
    ],
)
async def test_other_scopes_are_refused_and_named_without_the_account(
    scope: str, reason: str, fake: FakeTastytrade, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    fake.token_responses = [httpx.Response(200, json={"access_token": ACCESS_TOKEN, "expires_in": 900, "scope": scope})]
    with caplog.at_level(logging.WARNING, logger="app"), pytest.raises(tt.TastytradeUnavailable, match=reason) as raised:
        await tt.get("/market-metrics", {"symbols": "SPY"}, op="market_metrics")
    assert fake.gets == []
    assert "5wt12345" not in str(raised.value)
    assert all("5wt12345" not in r.getMessage() for r in caplog.records)
