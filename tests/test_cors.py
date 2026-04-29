"""
Tests for the CORS middleware that fronts the React frontend.

The frontend lives on a public Vercel URL hitting the public Fly URL —
two different origins, so the browser issues a preflight ``OPTIONS``
before any non-trivial cross-origin request and rejects the response
unless the server returns the right ``Access-Control-Allow-*``
headers.

The middleware is installed via ``configure_cors(app, *, origin=...)``
from ``app.core.cors``. Empty origin = no middleware = same-origin
only. Set origin = exactly that origin allowlisted (never ``*``,
because we ship an Authorization header).

Tests construct a fresh bare FastAPI per case so the global ``app``'s
already-installed middleware doesn't bleed in.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.cors import configure_cors

ALLOWED = "https://market-agent.vercel.app"
DISALLOWED = "https://evil.example.com"


def _build_app(origin: str) -> FastAPI:
    """A throw-away FastAPI app with one GET + one POST route + CORS."""
    test_app = FastAPI()

    @test_app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @test_app.post("/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    configure_cors(test_app, origin=origin)
    return test_app


@pytest.fixture
def app_no_cors() -> FastAPI:
    return _build_app(origin="")


@pytest.fixture
def app_with_cors() -> FastAPI:
    return _build_app(origin=ALLOWED)


# ── No CORS configured ──────────────────────────────────────────────


async def test_no_origin_setting_no_cors_headers(
    app_no_cors: FastAPI,
) -> None:
    """When FRONTEND_ORIGIN is empty, no Access-Control-Allow-* headers."""
    transport = ASGITransport(app=app_no_cors)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/ping",
            headers={"Origin": ALLOWED},
        )

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {
        k.lower() for k in resp.headers
    }


# ── CORS configured ─────────────────────────────────────────────────


async def test_preflight_returns_allow_headers_for_configured_origin(
    app_with_cors: FastAPI,
) -> None:
    """OPTIONS preflight from the allowlisted origin gets the right headers."""
    transport = ASGITransport(app=app_with_cors)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.options(
            "/echo",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED
    # Methods + headers must include what the frontend will actually send.
    allowed_methods = resp.headers["access-control-allow-methods"].lower()
    for m in ("get", "post", "options"):
        assert m in allowed_methods
    allowed_headers = resp.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers


async def test_simple_get_includes_allow_origin_for_configured_origin(
    app_with_cors: FastAPI,
) -> None:
    """A non-preflight GET from the allowed origin gets the ACAO header."""
    transport = ASGITransport(app=app_with_cors)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ping", headers={"Origin": ALLOWED})

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED


async def test_disallowed_origin_does_not_get_acao_header(
    app_with_cors: FastAPI,
) -> None:
    """A request from an unlisted origin must NOT echo back ACAO.

    Without this guard, CORS is effectively `*` — anyone can read the
    response from a JS context. Browsers enforce this on the client
    side; the test confirms the server side cooperates.
    """
    transport = ASGITransport(app=app_with_cors)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ping", headers={"Origin": DISALLOWED})

    assert resp.status_code == 200
    # Either the header is missing entirely OR it is the configured
    # allowed origin (not echoing the requester's origin).
    acao = resp.headers.get("access-control-allow-origin")
    assert acao != DISALLOWED


async def test_no_wildcard_origin(
    app_with_cors: FastAPI,
) -> None:
    """``*`` is never the response value — that would defeat the allowlist."""
    transport = ASGITransport(app=app_with_cors)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.options(
            "/echo",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.headers.get("access-control-allow-origin") != "*"
