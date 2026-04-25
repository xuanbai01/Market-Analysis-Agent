"""
Tests for the LLM client. The real Anthropic API is mocked end-to-end
so the suite stays free, fast, and deterministic. The eval harness
(tests/evals/) is the place that talks to the real API.

Coverage:
  - triage_call routes to claude-haiku-4-5
  - synth_call routes to claude-sonnet-4-6
  - both force tool_use with the schema's JSON schema as input_schema
  - both return a validated Pydantic instance from the tool_use input
  - prompt caching is requested on the system block (cache_control set)
  - log_external_call records token usage + cache hits in output_summary
  - missing API key raises a clear error, not a silent 401
  - model returning no tool_use block raises (forced-tool contract)
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.services import llm


class FakeIntent(BaseModel):
    intent: str
    confidence: float


def _make_response(*, intent: str = "search", confidence: float = 0.9):
    """Build a minimal mock of the SDK's Message response object."""
    tool_use_block = SimpleNamespace(
        type="tool_use",
        name="submit_response",
        input={"intent": intent, "confidence": confidence},
    )
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=18,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=80,
    )
    return SimpleNamespace(
        content=[tool_use_block],
        usage=usage,
        stop_reason="tool_use",
    )


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a fresh module-level client + a stub key."""
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "stub-key")


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Bypass _get_client() and inject a mock messages.create."""
    fake_create = AsyncMock(return_value=_make_response())
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)
    return fake_create


# ── Routing & schema enforcement ─────────────────────────────────────


async def test_triage_call_uses_haiku(mock_client: AsyncMock) -> None:
    await llm.triage_call("classify this", FakeIntent)
    kwargs = mock_client.call_args.kwargs
    assert kwargs["model"] == llm.TRIAGE_MODEL
    assert kwargs["model"] == "claude-haiku-4-5"


async def test_synth_call_uses_sonnet(mock_client: AsyncMock) -> None:
    await llm.synth_call("write a paragraph", FakeIntent)
    kwargs = mock_client.call_args.kwargs
    assert kwargs["model"] == llm.SYNTH_MODEL
    assert kwargs["model"] == "claude-sonnet-4-6"


async def test_call_forces_tool_choice(mock_client: AsyncMock) -> None:
    """Forced-tool pattern is the contract; tool_choice must always be set."""
    await llm.triage_call("...", FakeIntent)
    kwargs = mock_client.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_response"}


async def test_call_passes_pydantic_schema_as_input_schema(
    mock_client: AsyncMock,
) -> None:
    await llm.triage_call("...", FakeIntent)
    tool_def = mock_client.call_args.kwargs["tools"][0]
    assert tool_def["name"] == "submit_response"
    assert tool_def["input_schema"] == FakeIntent.model_json_schema()


async def test_call_returns_validated_pydantic_instance(mock_client: AsyncMock) -> None:
    result = await llm.triage_call("...", FakeIntent)
    assert isinstance(result, FakeIntent)
    assert result.intent == "search"
    assert result.confidence == pytest.approx(0.9)


# ── Prompt caching ───────────────────────────────────────────────────


async def test_system_prompt_has_cache_control(mock_client: AsyncMock) -> None:
    """
    cache_control on the system block is what enables the ~10× cost
    discount on repeated calls — losing it silently is the kind of bug
    that costs real money. Lock the contract here.
    """
    await llm.triage_call("...", FakeIntent, system="You are a research agent.")
    system = mock_client.call_args.kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    block = system[0]
    assert block["type"] == "text"
    assert block["text"] == "You are a research agent."
    assert block["cache_control"] == {"type": "ephemeral"}


async def test_no_system_prompt_omits_system_param(mock_client: AsyncMock) -> None:
    """Don't send an empty system list — that wastes tokens on no-op."""
    from anthropic import NotGiven

    await llm.triage_call("...", FakeIntent)
    assert isinstance(mock_client.call_args.kwargs["system"], NotGiven)


# ── Observability ────────────────────────────────────────────────────


async def test_call_logs_token_usage_and_cache_hits(
    mock_client: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.triage_call("hello", FakeIntent)

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "anthropic.triage"
    assert r.outcome == "ok"
    assert r.output_summary["input_tokens"] == 120
    assert r.output_summary["output_tokens"] == 18
    assert r.output_summary["cache_read_input_tokens"] == 80


async def test_synth_call_uses_distinct_service_id(
    mock_client: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """triage and synth must be separable in the log stream so we can
    chart cost per tier."""
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.synth_call("...", FakeIntent)
    r = next(r for r in caplog.records if r.name == "app.external")
    assert r.service_id == "anthropic.synth"


# ── Failure modes ────────────────────────────────────────────────────


async def test_missing_api_key_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm, "_client", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await llm.triage_call("...", FakeIntent)


async def test_no_tool_use_block_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    With forced tool_choice the model MUST emit a tool_use. If the SDK
    response somehow has none — version drift, model bug, refusal — we
    surface it loudly rather than papering over with empty Pydantic.
    """
    bad = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I refuse.")],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        stop_reason="end_turn",
    )
    fake_create = AsyncMock(return_value=bad)
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="no tool_use block"):
        await llm.triage_call("...", FakeIntent)
