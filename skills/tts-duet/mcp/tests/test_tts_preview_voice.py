"""Unit tests for ``tts_preview_voice``."""

from __future__ import annotations

import base64

import pytest

from gemini_tts_mcp.tools import tts


pytestmark = pytest.mark.asyncio


async def test_preview_voice_returns_chunk_shape(app_context):
    result = await tts.handle(
        "tts_preview_voice",
        {
            "voice": "Charon",
            "text": "the quick brown fox",
            "model": "gemini-2.5-flash-preview-tts",
        },
        app_context,
    )

    assert result["sample_rate_hz"] == 24000
    assert result["bits_per_sample"] == 16
    assert result["channels"] == 1
    assert base64.b64decode(result["pcm_base64"]) == b"\x00" * 48000


async def test_preview_voice_uses_single_speaker_config(app_context):
    await tts.handle(
        "tts_preview_voice",
        {
            "voice": "Aoede",
            "text": "hello",
            "model": "gemini-2.5-flash-preview-tts",
        },
        app_context,
    )

    call = app_context.client.models.generate_content.call_args
    config = call.kwargs["config"]
    assert config.speech_config.multi_speaker_voice_config is None
    assert (
        config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Aoede"
    )


async def test_preview_voice_missing_field_returns_bad_input(app_context):
    result = await tts.handle(
        "tts_preview_voice",
        {"voice": "Charon", "model": "gemini-2.5-flash-preview-tts"},
        app_context,
    )
    assert result["failure_reason"] == "bad_input"
