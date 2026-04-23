"""Unit tests for ``text.transform`` — the generic Gemini text pipe.

Critical AC: the input schema must contain EXACTLY
``{prompt, model, temperature, max_output_tokens}`` — no TTS-domain
fields. The MCP contract is intentionally narrow.
"""

from __future__ import annotations

import pytest

from gemini_tts_mcp.tools import text as text_tool


pytestmark = pytest.mark.asyncio


def _input_schema() -> dict:
    definition = next(t for t in text_tool.DEFINITIONS if t.name == "text.transform")
    return definition.inputSchema  # type: ignore[return-value]


def test_input_schema_has_exactly_four_properties():
    schema = _input_schema()
    assert set(schema["properties"].keys()) == {
        "prompt",
        "model",
        "temperature",
        "max_output_tokens",
    }
    assert set(schema["required"]) == {"prompt", "model"}
    assert schema.get("additionalProperties") is False


def test_input_schema_has_no_tts_domain_fields():
    schema = _input_schema()
    forbidden = {"genre", "voices", "voice_a", "voice_b", "speaker", "style"}
    assert forbidden.isdisjoint(schema["properties"].keys())


async def test_returns_text_and_token_counts(app_context):
    app_context.client.models.generate_content.return_value = (
        app_context.client._build_text_response("Director's Notes: …")  # type: ignore[attr-defined]
    )

    result = await text_tool.handle(
        "text.transform",
        {
            "prompt": "Rewrite the following script in a cinematic tone…",
            "model": "gemini-2.5-flash",
        },
        app_context,
    )

    assert result["text"] == "Director's Notes: …"
    assert result["input_tokens"] == 50
    assert result["output_tokens"] == 75


async def test_default_temperature_and_max_tokens(app_context):
    app_context.client.models.generate_content.return_value = (
        app_context.client._build_text_response("ok")  # type: ignore[attr-defined]
    )

    await text_tool.handle(
        "text.transform",
        {"prompt": "hi", "model": "gemini-2.5-flash"},
        app_context,
    )

    config = app_context.client.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0.2
    assert config.max_output_tokens == 8192


async def test_missing_field_returns_bad_input(app_context):
    result = await text_tool.handle(
        "text.transform",
        {"model": "gemini-2.5-flash"},
        app_context,
    )
    assert result["failure_reason"] == "bad_input"


async def test_deprecated_model_returns_upstream_break(app_context):
    app_context.client.models.generate_content.side_effect = RuntimeError(
        "model deprecated"
    )

    result = await text_tool.handle(
        "text.transform",
        {"prompt": "hi", "model": "gemini-2.5-flash"},
        app_context,
    )
    assert result["failure_reason"] == "upstream_break"


async def test_transient_failure_is_retryable_text_transform(app_context):
    app_context.client.models.generate_content.side_effect = RuntimeError(
        "transient blip"
    )

    result = await text_tool.handle(
        "text.transform",
        {"prompt": "hi", "model": "gemini-2.5-flash"},
        app_context,
    )
    assert result["failure_reason"] == "text_transform_failed"
    assert result["retryable"] is True
