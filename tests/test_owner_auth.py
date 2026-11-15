"""The owner key (ADR 0009, amended 2026-11-15).

Routes under ``/v1/owner`` hold the owner's own account data. The shared
secret is also a GitHub Actions secret (the IV snapshot cron), so a leak
there must not open them: they take a second key, ``X-Owner-Key``, on top
of the shared secret. With no owner key configured they don't exist (404),
and an address that keeps sending a wrong one is locked out for a while,
the right key included.
"""
from __future__ import annotations

import ast
import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from app.api.v1 import dependencies as deps
from app.api.v1.dependencies import OWNER_HEADER, require_owner
from app.core import settings as settings_module
from app.core.settings import Settings
from app.main import app
from app.services import tastytrade_client

_SHARED = "the-shared-secret"
_OWNER = "owner-key-7f3a9c41d2-5b8e60c4aa19f3d7"  # distinctive: checked absent from every log line
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


async def test_a_burst_of_guesses_gets_no_more_than_the_tries(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each request holds a try while its key is compared, so concurrent
    guesses can't all slip past one check."""
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 3)
    codes = await asyncio.gather(
        *(client.get(_STATUS, headers=_headers(owner=f"guess-{i}", ip="203.0.113.5")) for i in range(40))
    )
    assert sorted(r.status_code for r in codes) == [403] * 3 + [429] * 37


async def test_an_ipv6_caller_is_one_caller_across_its_64(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 2)
    for host in ("2001:db8:0:7::1", "2001:db8:0:7::2"):
        assert (await client.get(_STATUS, headers=_headers(owner="guess", ip=host))).status_code == 403
    assert (await client.get(_STATUS, headers=_headers(owner="guess", ip="2001:db8:0:7::3"))).status_code == 429
    assert (await client.get(_STATUS, headers=_headers(ip="2001:db8:0:8::1"))).status_code == 200


async def test_an_ipv4_address_written_as_ipv6_is_still_its_own_caller(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under the /64 rule every IPv4-mapped address would share one block,
    so ten guesses from anywhere would lock out every IPv4 caller (#126's AI review)."""
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 2)
    for _ in range(2):
        assert (await client.get(_STATUS, headers=_headers(owner="guess", ip="::ffff:203.0.113.7"))).status_code == 403
    assert (await client.get(_STATUS, headers=_headers(ip="203.0.113.7"))).status_code == 429  # the same caller
    assert (await client.get(_STATUS, headers=_headers(ip="::ffff:198.51.100.9"))).status_code == 200


async def test_refusals_and_lockouts_are_logged_by_an_anonymous_caller_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 2)
    caplog.set_level(logging.DEBUG)
    for _ in range(3):
        await client.get(_STATUS, headers=_headers(owner="wrong-key-55e1b0", ip="203.0.113.77"))
    await client.get(_STATUS, headers=_headers())
    refusals = [r.getMessage() for r in caplog.records if "refused" in r.getMessage()]
    assert len(refusals) == 2 and len({m.split("caller ")[1] for m in refusals}) == 1  # one caller, named the same way
    assert any("locked out" in r.getMessage() for r in caplog.records)
    for secret in (_OWNER, "wrong-key-55e1b0", "203.0.113.77"):
        assert secret not in caplog.text  # neither key nor address


def test_the_owner_routes_are_left_out_of_the_public_schema() -> None:
    assert not any(path.startswith("/v1/owner") for path in app.openapi()["paths"])


_APP = Path(__file__).resolve().parents[1] / "app"
_OWNER_SOURCES = {"tastytrade_client", "dxlink"}


def _imported_services(source: Path) -> set[str]:
    """The ``app.services`` modules a file imports, by their short names."""
    found = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.removeprefix("app.services.") for a in node.names if a.name.startswith("app.services.")}
        elif isinstance(node, ast.ImportFrom) and node.module == "app.services":
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.services."):
            found.add(node.module.removeprefix("app.services."))
    return found


def test_only_the_owner_router_reads_tastytrade() -> None:
    """tastytrade's data and the owner's trades are served from behind the
    owner key only (ADR 0009): no other router imports tastytrade, or a
    service that does (the probe aside, which is never imported)."""
    readers = {
        path.stem for path in (_APP / "services").glob("*.py")
        if _imported_services(path) & _OWNER_SOURCES and path.stem != "tastytrade_probe"
    } | _OWNER_SOURCES
    routers = {path.name: _imported_services(path) & readers for path in (_APP / "api" / "v1" / "routers").glob("*.py")}
    assert routers["owner.py"], "the detector found nothing: it's broken"
    assert {name for name, hits in routers.items() if hits} == {"owner.py"}


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"OWNER_KEY": "too-short"}, "32"),
        ({"OWNER_KEY": "k" * 40, "BACKEND_SHARED_SECRET": "k" * 40}, "shared secret"),
        ({"OWNER_KEY_FAILURES_PER_HOUR": 0}, "OWNER_KEY_FAILURES_PER_HOUR"),
        ({"OWNER_KEY_FAILURES_PER_HOUR": 1000}, "OWNER_KEY_FAILURES_PER_HOUR"),
    ],
)
def test_a_weak_owner_setup_refuses_to_start(overrides: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    Settings(_env_file=None, OWNER_KEY="k" * 40)  # a long, separate key is fine
    Settings(_env_file=None)  # and so is none


def _depends_on(route: APIRoute, dependency: object) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is dependency:
            return True
        stack.extend(dep.dependencies)
    return False


# The owner's routes, pinned: a new one is a decision.
_OWNER_PATHS = {"/v1/owner/status", "/v1/owner/positions"}


def test_every_owner_route_takes_the_owner_key_and_is_exactly_these() -> None:
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/v1/owner")]
    assert all(isinstance(r, APIRoute) for r in routes)  # no websocket or mount slips past the pin
    assert {r.path for r in routes} == _OWNER_PATHS
    for route in routes:
        assert isinstance(route, APIRoute)
        assert _depends_on(route, require_owner), route.path
        assert route.methods == {"GET"}, route.path
