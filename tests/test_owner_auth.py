"""The owner key (ADR 0009, amended 2026-11-15).

Routes under ``/v1/owner`` hold the owner's own account data. The shared
secret is also a GitHub Actions secret (the IV snapshot cron), so a leak
there must not open them: they take a second key, ``X-Owner-Key``, on top
of the shared secret. With no owner key configured they don't exist (404),
and an address that keeps sending a wrong one is locked out for a while,
the right key included.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1 import dependencies as deps
from app.api.v1.dependencies import OWNER_HEADER, require_owner
from app.core import settings as settings_module
from app.main import app
from app.services import tastytrade_client

_SHARED = "the-shared-secret"
_OWNER = "owner-key-7f3a9c41d2"  # distinctive: checked absent from every log line
_STATUS = "/v1/owner/status"


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", _SHARED)
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(_OWNER))
    deps.reset_owner_failures_for_tests()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    deps.reset_owner_failures_for_tests()


def _headers(
    owner: str | bytes | None = _OWNER, shared: str | None = _SHARED, ip: str | None = None
) -> dict[str, str | bytes]:
    headers: dict[str, str | bytes] = {}
    if shared is not None:
        headers["Authorization"] = f"Bearer {shared}"
    if owner is not None:
        headers[OWNER_HEADER] = owner
    if ip is not None:
        headers["Fly-Client-IP"] = ip
    return headers


async def test_both_keys_open_the_status(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tastytrade_client, "is_configured", lambda: True)
    resp = await client.get(_STATUS, headers=_headers())
    assert resp.status_code == 200
    assert resp.json() == {"tastytrade": True}


async def test_the_owner_key_alone_is_not_enough(client: AsyncClient) -> None:
    resp = await client.get(_STATUS, headers=_headers(shared=None))
    assert resp.status_code == 401


@pytest.mark.parametrize("owner", [None, "", "not-it", _OWNER + "x", "x" + _OWNER])
async def test_a_missing_or_wrong_owner_key_is_refused(client: AsyncClient, owner: str | None) -> None:
    resp = await client.get(_STATUS, headers=_headers(owner=owner))
    assert resp.status_code == 403


async def test_a_key_that_is_not_ascii_is_refused_not_an_error(client: AsyncClient) -> None:
    resp = await client.get(_STATUS, headers=_headers(owner="k\xe9y".encode("latin-1")))
    assert resp.status_code == 403


async def test_with_no_owner_key_configured_the_routes_are_not_there(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(""))
    assert (await client.get(_STATUS, headers=_headers())).status_code == 404
    assert (await client.get(_STATUS, headers=_headers(owner=""))).status_code == 404


async def test_without_a_shared_secret_the_owner_key_is_still_required(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local dev runs with no shared secret; the owner routes stay shut."""
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    assert (await client.get(_STATUS, headers=_headers(shared=None, owner=None))).status_code == 403
    assert (await client.get(_STATUS, headers=_headers(shared=None))).status_code == 200


async def test_repeated_wrong_keys_lock_out_that_address_even_for_the_right_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 3)
    for _ in range(3):
        assert (await client.get(_STATUS, headers=_headers(owner="guess", ip="203.0.113.7"))).status_code == 403
    locked = await client.get(_STATUS, headers=_headers(owner="guess", ip="203.0.113.7"))
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert (await client.get(_STATUS, headers=_headers(ip="203.0.113.7"))).status_code == 429
    assert (await client.get(_STATUS, headers=_headers(ip="198.51.100.2"))).status_code == 200


async def test_the_right_key_uses_up_no_tries(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 2)
    for _ in range(5):
        assert (await client.get(_STATUS, headers=_headers(ip="203.0.113.9"))).status_code == 200
    for _ in range(2):
        assert (await client.get(_STATUS, headers=_headers(owner="guess", ip="203.0.113.9"))).status_code == 403


async def test_no_owner_key_reaches_a_log_line(client: AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await client.get(_STATUS, headers=_headers(owner="wrong-key-55e1b0"))
    await client.get(_STATUS, headers=_headers())
    assert "refused" in caplog.text  # the failure is logged...
    assert _OWNER not in caplog.text and "wrong-key-55e1b0" not in caplog.text  # ...without the key


def _depends_on(route: APIRoute, dependency: object) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is dependency:
            return True
        stack.extend(dep.dependencies)
    return False


# The owner's routes, pinned: a new one is a decision.
_OWNER_PATHS = {"/v1/owner/status"}


def test_every_owner_route_takes_the_owner_key_and_is_exactly_these() -> None:
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/v1/owner")]
    assert {r.path for r in routes} == _OWNER_PATHS
    for route in routes:
        assert _depends_on(route, require_owner), route.path
        assert route.methods == {"GET"}, route.path
