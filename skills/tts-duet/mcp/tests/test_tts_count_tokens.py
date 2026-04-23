"""Unit tests for ``tts.count_tokens``."""

from __future__ import annotations

import pytest

from gemini_tts_mcp.tools import tts


pytestmark = pytest.mark.asyncio


async def test_returns_total_and_model_id(app_context):
    result = await tts.handle(
        "tts.count_tokens",
        {"model": "gemini-2.5-flash-preview-tts", "content": "hello world"},
        app_context,
    )

    assert result == {
        "total_tokens": 123,
        "model_id": "gemini-2.5-flash-preview-tts",
    }


async def test_missing_field_returns_bad_input(app_context):
    result = await tts.handle(
        "tts.count_tokens",
        {"model": "gemini-2.5-flash-preview-tts"},
        app_context,
    )
    assert result["failure_reason"] == "bad_input"


async def test_upstream_failure_is_retryable(app_context):
    app_context.client.models.count_tokens.side_effect = RuntimeError("network error")

    result = await tts.handle(
        "tts.count_tokens",
        {"model": "gemini-2.5-flash-preview-tts", "content": "hi"},
        app_context,
    )
    assert result["failure_reason"] == "tts_chunk_failed"
    assert result["retryable"] is True
