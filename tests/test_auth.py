"""
Tests for the shared-secret auth dependency.

The auth dep is the entry gate for ``/v1/research/*`` once the frontend
goes public. Two operating modes:

1. **Unset** (``BACKEND_SHARED_SECRET=""``) — the dep is a pass-through.
   Local dev and the existing test suite keep working without a token.
2. **Set** — every request must carry ``Authorization: Bearer <secret>``.
   Constant-time compared via ``hmac.compare_digest`` so a timing-attack
   adversary can't probe the secret byte by byte.

The dep is mounted on ``/v1/research/{symbol}`` (POST) by Phase 3.0 PR
A1; ``GET /v1/research`` picks it up in A3. Other routes deliberately
stay open — they're either internal or already cheap.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1 import dependencies as deps_module
from app.api.v1.dependencies import get_session
from app.core import settings as settings_module
from app.main import app
from app.schemas.research import (
    Claim,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from app.services import research_cache as cache_module
from app.services import research_orchestrator as orch_module


def _stub_report() -> ResearchReport:
    src = Source(tool="test.tool", fetched_at=datetime.now(UTC))
    return ResearchReport(
        symbol="AAPL",
        generated_at=datetime.now(UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[
                    Claim(description="P/E", value=28.5, source=src),
                ],
                summary="OK.",
                confidence=Confidence.HIGH,
            ),
        ],
        overall_confidence=Confidence.HIGH,
    )


@pytest_asyncio.fixture
async def auth_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """ASGI client with cache + orchestrator stubbed; rate limiter off.

    Each test sets ``BACKEND_SHARED_SECRET`` to whatever it needs.
    Without a per-test reset the secret would leak between cases.
    """

    async def _no_session() -> AsyncIterator[None]:
        yield None

    async def _miss(*_a: Any, **_kw: Any) -> None:
        return None

    async def _noop(*_a: Any, **_kw: Any) -> None:
        return None

    async def _orch(symbol: str, focus: Any) -> ResearchReport:
        return _stub_report()

    app.dependency_overrides[get_session] = _no_session
    monkeypatch.setattr(cache_module, "lookup_recent", _miss)
    monkeypatch.setattr(cache_module, "upsert", _noop)
    monkeypatch.setattr(orch_module, "compose_research_report", _orch)
    monkeypatch.setattr(
        settings_module.settings, "RESEARCH_RATE_LIMIT_PER_HOUR", 0
    )
    deps_module.reset_research_rate_limit_for_tests()
    # Default secret to empty (dep is a pass-through). Tests that exercise
    # the gate flip this on explicitly.
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)
        deps_module.reset_research_rate_limit_for_tests()


# ── Mode 1: secret unset → dep is a pass-through ─────────────────────


async def test_no_secret_no_auth_required(
    auth_client: AsyncClient,
) -> None:
    """Empty BACKEND_SHARED_SECRET → no header needed, no 401."""
    resp = await auth_client.post("/v1/research/AAPL")
    assert resp.status_code == 200


async def test_no_secret_arbitrary_header_ignored(
    auth_client: AsyncClient,
) -> None:
    """A token sent when auth is off is silently ignored — not a 401."""
    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 200


# ── Mode 2: secret set → header is enforced ──────────────────────────


async def test_missing_authorization_header_returns_401(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post("/v1/research/AAPL")

    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    # WWW-Authenticate is a recommended header on 401 responses (RFC 7235).
    assert resp.headers.get("WWW-Authenticate", "").lower().startswith("bearer")


async def test_wrong_scheme_returns_401(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Authorization: Basic ...`` is not accepted — we only do Bearer."""
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "Basic dGhlLXNlY3JldA=="},
    )

    assert resp.status_code == 401


async def test_wrong_secret_returns_401(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "Bearer not-the-secret"},
    )

    assert resp.status_code == 401


async def test_correct_secret_returns_200(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "Bearer the-secret"},
    )

    assert resp.status_code == 200


async def test_bearer_token_is_case_insensitive_scheme(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RFC 7235 §2.1: scheme tokens are case-insensitive."""
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "bearer the-secret"},
    )

    assert resp.status_code == 200


async def test_secret_with_extra_whitespace_still_compared_strictly(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Bearer  the-secret`` (extra space) does not equal the secret.

    We split on the first space, so token becomes ``" the-secret"`` —
    that fails the constant-time compare. This documents the strictness;
    a future change loosening this should add a test.
    """
    monkeypatch.setattr(
        settings_module.settings, "BACKEND_SHARED_SECRET", "the-secret"
    )

    resp = await auth_client.post(
        "/v1/research/AAPL",
        headers={"Authorization": "Bearer  the-secret"},
    )

    assert resp.status_code == 401
