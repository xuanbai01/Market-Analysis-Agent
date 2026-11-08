"""
DeepSeek adapter for ``app.services.llm`` (ADR 0006).

Speaks DeepSeek's OpenAI-format chat-completions API through the
official ``openai`` SDK pointed at ``settings.DEEPSEEK_BASE_URL``. Same
contract as the Anthropic path in ``llm``: force one function call whose
parameters are the Pydantic schema, validate the returned arguments,
and turn every provider failure into ``RuntimeError`` (→ 503 at the
research router).

Three DeepSeek specifics, all from api-docs.deepseek.com:
  - Thinking mode is on by default and rejects a named ``tool_choice``
    with HTTP 400, so every call sends ``thinking: {"type": "disabled"}``
    (via ``extra_body`` — it isn't part of the OpenAI SDK's signature).
  - The docs only show a non-standard ``$def`` spelling for schema
    references, so Pydantic's ``$defs`` / ``$ref`` are inlined first.
  - Prefix caching is automatic; hits come back in the extra usage
    field ``prompt_cache_hit_tokens``.

Strict function calling (beta endpoint) is deliberately not used: it
requires every property to be required with ``additionalProperties:
false``, which our schemas with defaulted fields don't satisfy. Pydantic
validation of the returned arguments is the safety net instead, exactly
as on the Anthropic path.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.observability import log_external_call
from app.core.settings import settings

T = TypeVar("T", bound=BaseModel)

# Named tool_choice is a 400 in thinking mode, and thinking is the default.
_THINKING_DISABLED: dict[str, Any] = {"thinking": {"type": "disabled"}}

# Lazy-initialized for the same reason as the Anthropic client: the
# module imports cleanly without a key (tests, rubric unit tests), and
# the first real call raises a clear error instead of a generic 401.
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set (LLM_PROVIDER=deepseek). "
                "Add it to .env for local dev, or "
                "`fly secrets set DEEPSEEK_API_KEY=...` for production.",
            )
        _client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )
    return _client


def inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with every ``#/$defs/<Name>`` reference replaced
    by its definition and the ``$defs`` table dropped.

    Our tool schemas are small, non-recursive Pydantic models, so plain
    substitution is enough. A self-referencing model would raise
    ``RecursionError`` here rather than send a broken schema.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
                siblings = {k: resolve(v) for k, v in node.items() if k != "$ref"}
                return {**target, **siblings}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


async def structured_call(
    *,
    model: str,
    schema: type[T],
    prompt: str,
    system: str | None,
    max_tokens: int,
    service_id: str,
    tool_name: str,
    tool_description: str,
) -> T:
    """Force ``tool_name`` with ``schema`` as its parameters; return the
    validated arguments. See module docstring for the DeepSeek specifics."""
    client = _get_client()

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    tool = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_description,
            "parameters": inline_schema_refs(schema.model_json_schema()),
        },
    }

    with log_external_call(
        service_id,
        {
            "model": model,
            "schema": schema.__name__,
            "prompt_chars": len(prompt),
            "system_chars": len(system) if system else 0,
            "max_tokens": max_tokens,
        },
    ) as call:
        try:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                extra_body=_THINKING_DISABLED,
            )
        except openai.APIStatusError as exc:
            raise RuntimeError(
                f"DeepSeek API returned HTTP {exc.status_code}: {exc.message}"
            ) from exc
        except openai.APIError as exc:
            raise RuntimeError(f"DeepSeek API call failed: {exc}") from exc

        choice = response.choices[0]
        usage = response.usage
        call.record_output(
            {
                "input_tokens": getattr(usage, "prompt_tokens", 0),
                "output_tokens": getattr(usage, "completion_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
                "stop_reason": choice.finish_reason,
            }
        )

        tool_call = next(
            (tc for tc in choice.message.tool_calls or [] if tc.function.name == tool_name),
            None,
        )
        if tool_call is None:
            raise RuntimeError(
                f"Model {model} returned no tool call under forced "
                f"tool_choice. finish_reason={choice.finish_reason!r}"
            )
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as exc:
            # Usually truncation (finish_reason="length") — raise max_tokens.
            raise RuntimeError(
                f"Model {model} returned invalid JSON arguments "
                f"(finish_reason={choice.finish_reason!r})"
            ) from exc

        return schema.model_validate(arguments)
