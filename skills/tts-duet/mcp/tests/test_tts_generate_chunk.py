"""Unit tests for ``tts_generate_chunk``."""

from __future__ import annotations

import base64

import pytest

from gemini_tts_mcp.tools import tts


pytestmark = pytest.mark.asyncio


async def test_returns_base64_pcm_with_format_metadata(app_context):
    result = await tts.handle(
        "tts_generate_chunk",
        {
            "model": "gemini-2.5-flash-preview-tts",
            "content": "A: hi\nB: hello",
            "voice_a": "Charon",
            "voice_b": "Aoede",
        },
        app_context,
    )

    assert "failure_reason" not in result
    assert result["sample_rate_hz"] == 24000
    assert result["bits_per_sample"] == 16
    assert result["channels"] == 1
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 24000
    decoded = base64.b64decode(result["pcm_base64"])
    assert len(decoded) == 48000
    assert decoded == b"\x00" * 48000


async def test_single_voice_path_omits_multi_speaker(app_context):
    await tts.handle(
        "tts_generate_chunk",
        {
            "model": "gemini-2.5-flash-preview-tts",
            "content": "solo",
            "voice_a": "Charon",
        },
        app_context,
    )

    call = app_context.client.models.generate_content.call_args
    config = call.kwargs["config"]
    assert config.speech_config.voice_config is not None
    assert config.speech_config.multi_speaker_voice_config is None


async def test_dual_voice_path_uses_multi_speaker(app_context):
    await tts.handle(
        "tts_generate_chunk",
        {
            "model": "gemini-2.5-flash-preview-tts",
            "content": "A: hi\nB: ho",
            "voice_a": "Charon",
            "voice_b": "Aoede",
        },
        app_context,
    )

    call = app_context.client.models.generate_content.call_args
    config = call.kwargs["config"]
    assert config.speech_config.multi_speaker_voice_config is not None
    speakers = config.speech_config.multi_speaker_voice_config.speaker_voice_configs
    assert {s.speaker for s in speakers} == {"A", "B"}
    assert speakers[0].voice_config.prebuilt_voice_config.voice_name == "Charon"
    assert speakers[1].voice_config.prebuilt_voice_config.voice_name == "Aoede"


async def test_missing_required_field_returns_bad_input(app_context):
    result = await tts.handle(
        "tts_generate_chunk",
        {"model": "gemini-2.5-flash-preview-tts", "content": "hi"},
        app_context,
    )
    assert result["failure_reason"] == "bad_input"
    assert result["retryable"] is False


async def test_upstream_deprecation_maps_to_upstream_break(app_context):
    app_context.client.models.generate_content.side_effect = RuntimeError(
        "model deprecated; please migrate"
    )

    result = await tts.handle(
        "tts_generate_chunk",
        {
            "model": "gemini-2.5-flash-preview-tts",
            "content": "hi",
            "voice_a": "Charon",
        },
        app_context,
    )
    assert result["failure_reason"] == "upstream_break"
    assert result["retryable"] is False


async def test_transient_error_is_retryable(app_context):
    app_context.client.models.generate_content.side_effect = RuntimeError("rate limited")

    result = await tts.handle(
        "tts_generate_chunk",
        {
            "model": "gemini-2.5-flash-preview-tts",
            "content": "hi",
            "voice_a": "Charon",
        },
        app_context,
    )
    assert result["failure_reason"] == "tts_chunk_failed"
    assert result["retryable"] is True


async def test_tool_definition_carries_max_result_size_meta():
    chunk_def = next(t for t in tts.DEFINITIONS if t.name == "tts_generate_chunk")
    meta = getattr(chunk_def, "_meta", None) or getattr(chunk_def, "meta", None)
    assert meta == {"anthropic/maxResultSizeChars": 500_000}
