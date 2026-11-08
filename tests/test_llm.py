"""
Tests for the LLM client. Both providers' SDKs are mocked end-to-end
so the suite stays free, fast, and deterministic. The eval harness
(tests/evals/, opt-in via ``-m live_llm``) is what talks to real APIs.

Coverage:
  Provider + model resolution (settings-driven, read at call time)
    - anthropic defaults: triage → claude-haiku-4-5, synth → claude-sonnet-4-6
    - deepseek defaults: both tiers → deepseek-flash
    - LLM_TRIAGE_MODEL / LLM_SYNTH_MODEL override the provider default
    - provider_api_key_configured follows the active provider
    - an unknown LLM_PROVIDER fails settings validation loudly
  Anthropic adapter
    - forces tool_use with the schema's JSON schema as input_schema
    - returns a validated Pydantic instance from the tool_use input
    - prompt caching is requested on the system block
    - logs token usage + cache hits under anthropic.<tier>
    - missing key / no tool_use block / API error → RuntimeError
  DeepSeek adapter
    - forces the named function and disables thinking mode (forced
      tool_choice returns 400 in thinking mode)
    - system + user messages; Pydantic $refs inlined into the parameters
    - returns a validated Pydantic instance from the function arguments
    - logs token usage + cache hits under deepseek.<tier>
    - missing key / no tool call / invalid JSON / API error → RuntimeError
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import httpx2
import openai
import pytest
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings
from app.services import llm, llm_deepseek


class FakeIntent(BaseModel):
    intent: str
    confidence: float


class Inner(BaseModel):
    label: str


class Outer(BaseModel):
    items: list[Inner]


@pytest.fixture(autouse=True)
def _pin_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from Anthropic defaults with stub keys and fresh
    clients, regardless of what the developer's ``.env`` configures."""
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm.settings, "LLM_TRIAGE_MODEL", "")
    monkeypatch.setattr(llm.settings, "LLM_SYNTH_MODEL", "")
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "stub-key")
    monkeypatch.setattr(llm.settings, "DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(llm, "_anthropic_client", None)
    monkeypatch.setattr(llm_deepseek, "_client", None)


# ── Anthropic fakes ──────────────────────────────────────────────────


def _anthropic_response(*, intent: str = "search", confidence: float = 0.9):
    """Minimal mock of the Anthropic SDK's Message response object."""
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
    return SimpleNamespace(content=[tool_use_block], usage=usage, stop_reason="tool_use")


@pytest.fixture
def anthropic_create(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Bypass the Anthropic client factory and inject a mock messages.create."""
    fake_create = AsyncMock(return_value=_anthropic_response())
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: fake_client)
    return fake_create


# ── DeepSeek fakes ───────────────────────────────────────────────────


def _deepseek_response(
    arguments: str = '{"intent": "search", "confidence": 0.9}',
    *,
    tool_calls: list | None = None,
    finish_reason: str = "tool_calls",
):
    """Minimal mock of the openai SDK's ChatCompletion object as DeepSeek
    returns it (cache counters are DeepSeek-specific usage fields)."""
    if tool_calls is None:
        tool_calls = [
            SimpleNamespace(
                id="call_0",
                type="function",
                function=SimpleNamespace(name="submit_response", arguments=arguments),
            )
        ]
    message = SimpleNamespace(role="assistant", content=None, tool_calls=tool_calls)
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=18,
        total_tokens=138,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=40,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, finish_reason=finish_reason, message=message)],
        usage=usage,
    )


@pytest.fixture
def deepseek_create(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Switch the provider to DeepSeek and inject a mock chat.completions.create."""
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "deepseek")
    fake_create = AsyncMock(return_value=_deepseek_response())
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(llm_deepseek, "_get_client", lambda: fake_client)
    return fake_create


# ── Provider + model resolution ──────────────────────────────────────


async def test_anthropic_defaults_triage_to_haiku(anthropic_create: AsyncMock) -> None:
    await llm.triage_call("classify this", FakeIntent)
    assert anthropic_create.call_args.kwargs["model"] == "claude-haiku-4-5"


async def test_anthropic_defaults_synth_to_sonnet(anthropic_create: AsyncMock) -> None:
    await llm.synth_call("write a paragraph", FakeIntent)
    assert anthropic_create.call_args.kwargs["model"] == "claude-sonnet-4-6"


async def test_deepseek_defaults_both_tiers_to_flash(deepseek_create: AsyncMock) -> None:
    await llm.triage_call("classify this", FakeIntent)
    assert deepseek_create.call_args.kwargs["model"] == "deepseek-flash"
    await llm.synth_call("write a paragraph", FakeIntent)
    assert deepseek_create.call_args.kwargs["model"] == "deepseek-flash"


async def test_model_override_applies_to_its_tier_only(
    anthropic_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching synth to Haiku is a one-line .env change."""
    monkeypatch.setattr(llm.settings, "LLM_SYNTH_MODEL", "claude-haiku-4-5")
    await llm.synth_call("...", FakeIntent)
    assert anthropic_create.call_args.kwargs["model"] == "claude-haiku-4-5"
    await llm.triage_call("...", FakeIntent)
    assert anthropic_create.call_args.kwargs["model"] == "claude-haiku-4-5"


async def test_deepseek_model_override(
    deepseek_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm.settings, "LLM_SYNTH_MODEL", "deepseek-v4-pro")
    await llm.synth_call("...", FakeIntent)
    assert deepseek_create.call_args.kwargs["model"] == "deepseek-v4-pro"


def test_resolve_model_reads_settings_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    assert llm.resolve_model("synth") == "claude-sonnet-4-6"
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "deepseek")
    assert llm.resolve_model("synth") == "deepseek-flash"
    assert llm.resolve_model("triage") == "deepseek-flash"


def test_provider_api_key_configured_follows_active_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm.settings, "DEEPSEEK_API_KEY", "sk-test")
    assert llm.provider_api_key_configured() is False
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "deepseek")
    assert llm.provider_api_key_configured() is True


def test_unknown_provider_fails_settings_validation() -> None:
    """A typo in LLM_PROVIDER must fail at boot, not on the first report."""
    with pytest.raises(ValidationError):
        Settings(LLM_PROVIDER="gpt", _env_file=None)


# ── Anthropic adapter ────────────────────────────────────────────────


async def test_anthropic_forces_tool_choice(anthropic_create: AsyncMock) -> None:
    """Forced-tool pattern is the contract; tool_choice must always be set."""
    await llm.triage_call("...", FakeIntent)
    kwargs = anthropic_create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_response"}


async def test_anthropic_passes_pydantic_schema_as_input_schema(
    anthropic_create: AsyncMock,
) -> None:
    await llm.triage_call("...", FakeIntent)
    tool_def = anthropic_create.call_args.kwargs["tools"][0]
    assert tool_def["name"] == "submit_response"
    assert tool_def["input_schema"] == FakeIntent.model_json_schema()


async def test_anthropic_returns_validated_pydantic_instance(
    anthropic_create: AsyncMock,
) -> None:
    result = await llm.triage_call("...", FakeIntent)
    assert isinstance(result, FakeIntent)
    assert result.intent == "search"
    assert result.confidence == pytest.approx(0.9)


async def test_anthropic_system_prompt_has_cache_control(anthropic_create: AsyncMock) -> None:
    """
    cache_control on the system block is what enables the ~10× cost
    discount on repeated calls — losing it silently is the kind of bug
    that costs real money. Lock the contract here.
    """
    await llm.triage_call("...", FakeIntent, system="You are a research agent.")
    system = anthropic_create.call_args.kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    block = system[0]
    assert block["type"] == "text"
    assert block["text"] == "You are a research agent."
    assert block["cache_control"] == {"type": "ephemeral"}


async def test_anthropic_no_system_prompt_omits_system_param(
    anthropic_create: AsyncMock,
) -> None:
    """Don't send an empty system list — that wastes tokens on no-op."""
    await llm.triage_call("...", FakeIntent)
    assert isinstance(anthropic_create.call_args.kwargs["system"], anthropic.NotGiven)


async def test_anthropic_logs_token_usage_and_cache_hits(
    anthropic_create: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.triage_call("hello", FakeIntent)

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "anthropic.triage"
    assert r.outcome == "ok"
    assert r.input_summary["model"] == "claude-haiku-4-5"
    assert r.output_summary["input_tokens"] == 120
    assert r.output_summary["output_tokens"] == 18
    assert r.output_summary["cache_read_input_tokens"] == 80


async def test_anthropic_synth_uses_distinct_service_id(
    anthropic_create: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """triage and synth must be separable in the log stream so we can
    chart cost per tier."""
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.synth_call("...", FakeIntent)
    r = next(r for r in caplog.records if r.name == "app.external")
    assert r.service_id == "anthropic.synth"


async def test_anthropic_missing_api_key_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await llm.triage_call("...", FakeIntent)


async def test_anthropic_no_tool_use_block_raises(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="no tool_use block"):
        await llm.triage_call("...", FakeIntent)


async def test_anthropic_api_error_becomes_runtime_error(
    anthropic_create: AsyncMock,
) -> None:
    """The research router maps RuntimeError → 503. A provider outage
    (529 overloaded, 5xx after SDK retries) is exactly that case."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    anthropic_create.side_effect = anthropic.APIStatusError(
        "Overloaded", response=httpx.Response(529, request=request), body=None
    )
    with pytest.raises(RuntimeError, match="HTTP 529"):
        await llm.synth_call("...", FakeIntent)


# ── DeepSeek adapter ─────────────────────────────────────────────────


async def test_deepseek_forces_named_function(deepseek_create: AsyncMock) -> None:
    await llm.triage_call("...", FakeIntent)
    kwargs = deepseek_create.call_args.kwargs
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_response"},
    }
    tool = kwargs["tools"][0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "submit_response"


async def test_deepseek_disables_thinking_mode(deepseek_create: AsyncMock) -> None:
    """DeepSeek returns 400 for a named tool_choice in thinking mode, and
    thinking is on by default — so every call must turn it off."""
    await llm.synth_call("...", FakeIntent)
    assert deepseek_create.call_args.kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


async def test_deepseek_passes_max_tokens(deepseek_create: AsyncMock) -> None:
    await llm.synth_call("...", FakeIntent, max_tokens=8000)
    assert deepseek_create.call_args.kwargs["max_tokens"] == 8000


async def test_deepseek_sends_system_then_user_message(deepseek_create: AsyncMock) -> None:
    await llm.triage_call("hello", FakeIntent, system="You are a research agent.")
    assert deepseek_create.call_args.kwargs["messages"] == [
        {"role": "system", "content": "You are a research agent."},
        {"role": "user", "content": "hello"},
    ]


async def test_deepseek_omits_empty_system_message(deepseek_create: AsyncMock) -> None:
    await llm.triage_call("hello", FakeIntent)
    assert deepseek_create.call_args.kwargs["messages"] == [
        {"role": "user", "content": "hello"},
    ]


async def test_deepseek_inlines_schema_refs(deepseek_create: AsyncMock) -> None:
    """Pydantic emits nested models as ``$defs`` + ``$ref``; DeepSeek's
    docs only show a non-standard ``$def`` spelling, so send a schema
    with every reference already resolved."""
    deepseek_create.return_value = _deepseek_response('{"items": [{"label": "a"}]}')
    await llm.triage_call("...", Outer)
    params = deepseek_create.call_args.kwargs["tools"][0]["function"]["parameters"]
    dumped = json.dumps(params)
    assert "$ref" not in dumped
    assert "$defs" not in dumped
    assert params["properties"]["items"]["items"]["properties"]["label"]["type"] == "string"


async def test_deepseek_returns_validated_pydantic_instance(
    deepseek_create: AsyncMock,
) -> None:
    result = await llm.triage_call("...", FakeIntent)
    assert isinstance(result, FakeIntent)
    assert result.intent == "search"
    assert result.confidence == pytest.approx(0.9)


async def test_deepseek_logs_token_usage_and_cache_hits(
    deepseek_create: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.triage_call("hello", FakeIntent)

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "deepseek.triage"
    assert r.outcome == "ok"
    assert r.input_summary["model"] == "deepseek-flash"
    assert r.output_summary["input_tokens"] == 120
    assert r.output_summary["output_tokens"] == 18
    assert r.output_summary["cache_read_input_tokens"] == 80
    assert r.output_summary["stop_reason"] == "tool_calls"


async def test_deepseek_synth_uses_distinct_service_id(
    deepseek_create: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.external"):
        await llm.synth_call("...", FakeIntent)
    r = next(r for r in caplog.records if r.name == "app.external")
    assert r.service_id == "deepseek.synth"


async def test_deepseek_missing_api_key_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm.settings, "DEEPSEEK_API_KEY", "")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        await llm.triage_call("...", FakeIntent)


async def test_deepseek_no_tool_call_raises(deepseek_create: AsyncMock) -> None:
    deepseek_create.return_value = _deepseek_response(tool_calls=[], finish_reason="stop")
    with pytest.raises(RuntimeError, match="no tool call"):
        await llm.triage_call("...", FakeIntent)


async def test_deepseek_invalid_json_arguments_raise(deepseek_create: AsyncMock) -> None:
    """Truncated output (finish_reason=length) leaves unparseable JSON —
    surface it as a provider failure, with the finish reason attached."""
    deepseek_create.return_value = _deepseek_response(
        '{"intent": "search", "conf', finish_reason="length"
    )
    with pytest.raises(RuntimeError, match="invalid JSON.*length"):
        await llm.triage_call("...", FakeIntent)


async def test_deepseek_api_error_becomes_runtime_error(deepseek_create: AsyncMock) -> None:
    """402 = out of credit. The router turns RuntimeError into a 503 with
    this message, which is far clearer than a bare 500."""
    request = httpx2.Request("POST", "https://api.deepseek.com/chat/completions")
    deepseek_create.side_effect = openai.APIStatusError(
        "Insufficient Balance", response=httpx2.Response(402, request=request), body=None
    )
    with pytest.raises(RuntimeError, match="HTTP 402"):
        await llm.synth_call("...", FakeIntent)


async def test_deepseek_connection_error_becomes_runtime_error(
    deepseek_create: AsyncMock,
) -> None:
    request = httpx2.Request("POST", "https://api.deepseek.com/chat/completions")
    deepseek_create.side_effect = openai.APIConnectionError(request=request)
    with pytest.raises(RuntimeError, match="DeepSeek API call failed"):
        await llm.synth_call("...", FakeIntent)
